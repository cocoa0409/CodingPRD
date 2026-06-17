"""Convention, TicketType, and lottery endpoints (PRD §3.1, §3.8)."""
from flask import Blueprint

import common
import db
import errors
from middleware import authenticate, authorize
from services import calc, lookup
import response

bp = Blueprint("conventions", __name__)

ALL_ROLES = {"ConventionAdmin", "RegistrationAgent", "Attendee", "Exhibitor"}
READ_ROLES = {"ConventionAdmin", "RegistrationAgent", "Attendee"}

TICKET_TIERS = {"GENERAL", "THREE_DAY", "VIP", "EXHIBITOR"}


# --------------------------------------------------------------------------- #
# Convention
# --------------------------------------------------------------------------- #
@bp.route("/conventions", methods=["POST"])
def create_convention():
    _, role = authenticate()
    authorize(role, {"ConventionAdmin"})
    body = common.get_body()

    name = common.require_str(body, "name")
    event_start = common.require_datetime(body, "event_start_utc")
    event_end = common.require_datetime(body, "event_end_utc")
    if event_end <= event_start:
        raise errors.err(errors.ERR_INVALID_REQUEST, "event_end_utc must be strictly after event_start_utc")
    total_capacity = common.require_int(body, "total_badge_capacity", minimum=1)
    lottery_open = common.require_datetime(body, "lottery_open_utc")

    row = common.common_fields()
    row.update({
        "name": name,
        "event_start_utc": body["event_start_utc"],
        "event_end_utc": body["event_end_utc"],
        "total_badge_capacity": total_capacity,
        "badges_issued_count": 0,
        "lottery_open_utc": body["lottery_open_utc"],
        "posture": "OPEN",
    })
    db.conventions[row["id"]] = row
    return response.success(common.serialize(row), 201)


@bp.route("/conventions/<cid>", methods=["GET"])
def get_convention(cid):
    _, role = authenticate()
    authorize(role, ALL_ROLES)
    conv = lookup.convention(cid)
    return response.success(common.serialize(conv), 200)


@bp.route("/conventions", methods=["GET"])
def list_conventions():
    _, role = authenticate()
    authorize(role, ALL_ROLES)
    items, limit, offset, total = common.paginate(list(db.conventions.values()))
    return response.success_list(items, limit, offset, total)


@bp.route("/conventions/<cid>/close", methods=["POST"])
def close_convention(cid):
    _, role = authenticate()
    authorize(role, {"ConventionAdmin"})
    conv = lookup.convention(cid)
    body = common.get_body()
    expected = common.require_int(body, "expected_convention_version")
    if expected != conv["version"]:
        raise errors.err(errors.ERR_STALE_CONVENTION_VERSION, "Stale convention version")
    conv["posture"] = "CLOSED"
    common.touch(conv)
    return response.success(common.serialize(conv), 200)


@bp.route("/conventions/<cid>/run-lottery", methods=["POST"])
def run_lottery(cid):
    _, role = authenticate()
    authorize(role, {"ConventionAdmin"})
    conv = lookup.convention(cid)
    body = common.get_body()
    expected = common.require_int(body, "expected_convention_version")
    if expected != conv["version"]:
        raise errors.err(errors.ERR_STALE_CONVENTION_VERSION, "Stale convention version")

    remaining = conv["total_badge_capacity"] - conv["badges_issued_count"]
    candidates = [
        e for e in db.waitlist_entries.values()
        if e["convention_id"] == cid and e["status"] == "ENTERED"
    ]
    # priority_score DESC, then created_at ASC (creation sequence), never id.
    candidates.sort(key=lambda e: (-e["priority_score"], e["_seq"]))
    for entry in candidates:
        if entry["requested_quantity"] <= remaining:
            entry["status"] = "WON"
            remaining -= entry["requested_quantity"]
        else:
            entry["status"] = "LOST"
        common.touch(entry)

    common.touch(conv)
    return response.success(common.serialize(conv), 200)


# --------------------------------------------------------------------------- #
# TicketType
# --------------------------------------------------------------------------- #
@bp.route("/conventions/<cid>/ticket-types", methods=["POST"])
def create_ticket_type(cid):
    _, role = authenticate()
    authorize(role, {"ConventionAdmin"})
    conv = lookup.convention(cid)
    body = common.get_body()

    tier = common.require_enum(body, "tier", TICKET_TIERS)
    base_price = common.require_int(body, "base_price_cents", minimum=0)
    tier_capacity = common.require_int(body, "tier_capacity", minimum=1)
    is_day_pass = common.optional_bool(body, "is_day_pass", False)

    row = common.common_fields()
    row.update({
        "convention_id": conv["id"],
        "tier": tier,
        "base_price_cents": base_price,
        "tier_capacity": tier_capacity,
        "tier_issued_count": 0,
        "is_day_pass": is_day_pass,
    })
    db.ticket_types[row["id"]] = row
    return response.success(common.serialize(row), 201)


@bp.route("/conventions/<cid>/ticket-types", methods=["GET"])
def list_ticket_types(cid):
    _, role = authenticate()
    authorize(role, ALL_ROLES)
    conv = lookup.convention(cid)
    rows = [t for t in db.ticket_types.values() if t["convention_id"] == conv["id"]]
    items, limit, offset, total = common.paginate(rows)
    return response.success_list(items, limit, offset, total)


@bp.route("/ticket-types/<tid>", methods=["GET"])
def get_ticket_type(tid):
    _, role = authenticate()
    authorize(role, ALL_ROLES)
    tt = lookup.ticket_type(tid)
    return response.success(common.serialize(tt), 200)
