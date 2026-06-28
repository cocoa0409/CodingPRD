"""RecurringSeries routes: create draft, list, get, activate (waterfall), cancel.

PRD §3.9, calc series_materialization.
"""
from datetime import timedelta

from flask import Blueprint, request

from db import store
from errors import (
    err, ERR_NOT_FOUND, ERR_FORBIDDEN, ERR_LOCATION_MISMATCH, ERR_INVALID_STATE,
    ERR_MEMBER_SUSPENDED, ERR_SERIES_OCCURRENCE_LIMIT,
)
from middleware import authenticate, require_role, forbid
from response import success, success_list
from util import (
    get_json_body, require_str, require_int, require_enum,
    parse_pagination, paginate, parse_iso, now_clock,
)
from services.common import make_full, bump
from services.wallet import wallet_available, reconcile_creditpack_status
from services.booking import (
    _resolve_wallet, _overlapping_table_bookings, _flexologist_conflict,
    build_booking, cascade_cancel_release,
)
from services import serialize

bp = Blueprint("series", __name__)

MEMBER_ROLES = ["StudioManager", "FrontDesk", "Member"]


@bp.route("/recurring-series", methods=["POST"])
def create_series():
    p = authenticate()
    require_role(p, MEMBER_ROLES)
    body = get_json_body()
    member_id = require_str(body, "member_id")
    location_id = require_str(body, "location_id")
    service_id = require_str(body, "service_id")
    flexologist_id = require_str(body, "flexologist_id")
    table_id = require_str(body, "table_id")
    funding_source = require_enum(body, "funding_source", {"MEMBERSHIP", "CREDIT_PACK"})
    funding_id = require_str(body, "funding_id")
    first_start = require_str(body, "first_start_utc")
    parse_iso(first_start)
    interval_days = require_int(body, "interval_days")
    occurrence_count = require_int(body, "occurrence_count")

    if p.is_member and p.user_id != member_id:
        forbid()

    # occurrence_count 1..26 and interval_days > 0 (ERR_SERIES_OCCURRENCE_LIMIT, 422).
    if interval_days <= 0 or not (1 <= occurrence_count <= 26):
        raise err(ERR_SERIES_OCCURRENCE_LIMIT,
                  "occurrence_count must be 1..26 and interval_days > 0.")

    member = store.members.get(member_id)
    if member is None:
        raise err(ERR_NOT_FOUND, "Member not found.")
    location = store.locations.get(location_id)
    if location is None:
        raise err(ERR_NOT_FOUND, "Location not found.")
    service = store.services.get(service_id)
    if service is None:
        raise err(ERR_NOT_FOUND, "Service not found.")
    flexologist = store.flexologists.get(flexologist_id)
    if flexologist is None:
        raise err(ERR_NOT_FOUND, "Flexologist not found.")
    table = store.tables.get(table_id)
    if table is None:
        raise err(ERR_NOT_FOUND, "Table not found.")
    wallet = _resolve_wallet(funding_source, funding_id)
    if wallet is None:
        raise err(ERR_NOT_FOUND, "Funding wallet not found.")

    # cross-location integrity (applies at series creation, PRD §3.9).
    if (service["location_id"] != location_id
            or flexologist["location_id"] != location_id
            or table["location_id"] != location_id
            or wallet["location_id"] != location_id):
        raise err(ERR_LOCATION_MISMATCH, "Referenced resource belongs to a different location.")

    rec = make_full({
        "member_id": member_id,
        "location_id": location_id,
        "service_id": service_id,
        "flexologist_id": flexologist_id,
        "table_id": table_id,
        "funding_source": funding_source,
        "funding_id": funding_id,
        "first_start_utc": first_start,
        "interval_days": interval_days,
        "occurrence_count": occurrence_count,
        "generated_count": 0,
        "skipped_count": 0,
        "status": "DRAFT",
    })
    store.recurring_series[rec["id"]] = rec
    return success(serialize.series_view(rec), 201)


@bp.route("/recurring-series", methods=["GET"])
def list_series():
    p = authenticate()
    require_role(p, MEMBER_ROLES)
    limit, offset = parse_pagination()
    filters = {
        "member_id": _qs("member_id"),
        "location_id": _qs("location_id"),
        "service_id": _qs("service_id"),
        "flexologist_id": _qs("flexologist_id"),
        "table_id": _qs("table_id"),
        "funding_id": _qs("funding_id"),
        "status": _qs("status"),
    }
    items = [r for r in store.recurring_series.values()
             if all(v is None or r.get(k) == v for k, v in filters.items())]
    if p.is_member:
        items = [r for r in items if r["member_id"] == p.user_id]
    window, total = paginate(items, limit, offset)
    return success_list([serialize.series_view(r) for r in window], limit, offset, total)


@bp.route("/recurring-series/<sid>", methods=["GET"])
def get_series(sid):
    p = authenticate()
    require_role(p, MEMBER_ROLES)
    rec = store.recurring_series.get(sid)
    if rec is None:
        raise err(ERR_NOT_FOUND, "Recurring series not found.")
    if p.is_member and p.user_id != rec["member_id"]:
        forbid()
    return success(serialize.series_view(rec), 200)


@bp.route("/recurring-series/<sid>/activate", methods=["POST"])
def activate_series(sid):
    p = authenticate()
    require_role(p, MEMBER_ROLES)
    rec = store.recurring_series.get(sid)
    if rec is None:
        raise err(ERR_NOT_FOUND, "Recurring series not found.")
    if p.is_member and p.user_id != rec["member_id"]:
        forbid()

    member = store.members.get(rec["member_id"])
    location = store.locations.get(rec["location_id"])
    service = store.services.get(rec["service_id"])
    flexologist = store.flexologists.get(rec["flexologist_id"])
    table = store.tables.get(rec["table_id"])
    wallet = _resolve_wallet(rec["funding_source"], rec["funding_id"])
    if wallet is None:
        raise err(ERR_NOT_FOUND, "Funding wallet not found.")

    # cross-location integrity at activation (PRD §3.9).
    if (service["location_id"] != rec["location_id"]
            or flexologist["location_id"] != rec["location_id"]
            or table["location_id"] != rec["location_id"]
            or wallet["location_id"] != rec["location_id"]):
        raise err(ERR_LOCATION_MISMATCH, "Referenced resource belongs to a different location.")

    # state precondition: must be DRAFT.
    if rec["status"] != "DRAFT":
        raise err(ERR_INVALID_STATE, "Series is not DRAFT.")

    # member standing.
    if member["status"] == "SUSPENDED":
        raise err(ERR_MEMBER_SUSPENDED, "Member is suspended.")

    # funding wallet must be usable (ACTIVE membership / non-EXPIRED pack).
    if rec["funding_source"] == "MEMBERSHIP":
        if wallet["status"] != "ACTIVE":
            raise err(ERR_INVALID_STATE, "Funding membership is not ACTIVE.")
    else:
        if wallet["status"] == "EXPIRED":
            raise err(ERR_INVALID_STATE, "Funding credit pack is EXPIRED.")

    # Waterfall over occurrences in ascending k (chronological).
    generated = 0
    skipped = 0
    first_start = parse_iso(rec["first_start_utc"])
    for k in range(rec["occurrence_count"]):
        start = first_start + timedelta(days=k * rec["interval_days"])
        end = start + timedelta(minutes=service["duration_minutes"])
        table_conflict = _overlapping_table_bookings(table["id"], start, end)
        flex_conflict = _flexologist_conflict(
            flexologist["id"], start, end, location["flexologist_buffer_minutes"])
        available = wallet_available(rec["funding_source"], wallet)
        if table_conflict or flex_conflict or available < service["credit_cost"]:
            skipped += 1
            continue
        build_booking(member, location, service, flexologist, table,
                      rec["funding_source"], wallet, start, series_id=rec["id"])
        generated += 1

    rec["generated_count"] = generated
    rec["skipped_count"] = skipped
    rec["status"] = "ACTIVE"
    bump(rec)
    return success(serialize.series_view(rec), 200)


@bp.route("/recurring-series/<sid>/cancel", methods=["POST"])
def cancel_series(sid):
    p = authenticate()
    require_role(p, MEMBER_ROLES)
    rec = store.recurring_series.get(sid)
    if rec is None:
        raise err(ERR_NOT_FOUND, "Recurring series not found.")
    if p.is_member and p.user_id != rec["member_id"]:
        forbid()
    if rec["status"] != "ACTIVE":
        raise err(ERR_INVALID_STATE, "Series is not ACTIVE.")
    rec["status"] = "ENDED"
    # Cascade: future (session_start_utc > clock) HELD series bookings -> CANCELLED.
    clock = now_clock()
    for b in list(store.bookings.values()):
        if b.get("series_id") != sid:
            continue
        if b["credit_status"] != "HELD":
            continue
        if parse_iso(b["session_start_utc"]) > clock:
            cascade_cancel_release(b)
    bump(rec)
    return success(serialize.series_view(rec), 200)


def _qs(name):
    v = request.args.get(name)
    if v is None or v == "":
        return None
    return v
