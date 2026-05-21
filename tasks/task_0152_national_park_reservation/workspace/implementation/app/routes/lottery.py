"""Lottery permit and application routes."""
from __future__ import annotations

from datetime import datetime, timezone

from flask import Blueprint, jsonify

from ..auth import (
    ROLE_PARK_ADMIN,
    ROLE_PARK_RANGER,
    ROLE_SYSTEM_OPERATOR,
    ROLE_VISITOR,
    current_user_id,
    require_auth,
)
from ..clock import now_utc
from ..envelope import parse_pagination, success_array, success_object
from ..errors import APIError
from ..serializers import serialize_lottery_application, serialize_lottery_permit
from ..services.common import stamp_create, stamp_update
from ..services.lottery import promote_next_waitlisted, run_draw
from ..services.wallet import debit_for_fee
from ..store import get_store
from ..timeutil import parse_date_local
from ..util import new_id, new_rank_seed, parse_iso8601
from ..validators import get_json_body, optional_int, require_int, require_string
from ._helpers import (
    filter_visitor_owned,
    lookup_lottery_permit,
    lookup_park,
    lookup_visitor,
    require_visitor_ownership,
)

bp = Blueprint("lottery", __name__)


@bp.post("/parks/<park_id>/lottery-permits")
@require_auth([ROLE_PARK_ADMIN])
def create_lottery_permit(park_id: str):
    lookup_park(park_id)
    body = get_json_body()
    name = require_string(body, "name", min_len=1, max_len=80)
    lottery_open_at = require_string(body, "lottery_open_at", min_len=1)
    lottery_close_at = require_string(body, "lottery_close_at", min_len=1)
    draw_at = require_string(body, "draw_at", min_len=1)
    hike_date = require_string(body, "hike_date", min_len=1)
    daily_slot_count = require_int(body, "daily_slot_count", min_val=1)
    per_app_max_party = optional_int(body, "per_application_max_party", default=6, min_val=1, max_val=12)
    application_fee_cents = require_int(body, "application_fee_cents", min_val=0)
    permit_fee_cents = require_int(body, "permit_fee_cents", min_val=0)

    # Validate timestamps
    open_dt = parse_iso8601(lottery_open_at)
    close_dt = parse_iso8601(lottery_close_at)
    draw_dt = parse_iso8601(draw_at)
    if open_dt is None or close_dt is None or draw_dt is None:
        raise APIError("ERR_VALIDATION", "lottery dates must be ISO 8601 UTC", 422)
    if not (open_dt < close_dt <= draw_dt):
        raise APIError("ERR_VALIDATION", "open_at < close_at <= draw_at required", 422)

    store = get_store()
    key = (park_id, name.lower())
    with store.lock:
        if key in store.lottery_names:
            raise APIError("ERR_VALIDATION", "lottery name not unique within park", 422)
        permit = {
            "id": new_id(),
            "park_id": park_id,
            "name": name,
            "lottery_open_at": lottery_open_at,
            "lottery_close_at": lottery_close_at,
            "draw_at": draw_at,
            "hike_date": hike_date,
            "daily_slot_count": daily_slot_count,
            "per_application_max_party": per_app_max_party,
            "application_fee_cents": application_fee_cents,
            "permit_fee_cents": permit_fee_cents,
            "status": "OPEN",
        }
        stamp_create(permit)
        store.lottery_permits[permit["id"]] = permit
        store.lottery_names[key] = permit["id"]
    return jsonify(success_object(serialize_lottery_permit(permit))), 201


@bp.get("/parks/<park_id>/lottery-permits")
@require_auth([ROLE_PARK_ADMIN, ROLE_VISITOR, ROLE_PARK_RANGER])
def list_lottery_permits(park_id: str):
    lookup_park(park_id)
    limit, offset = parse_pagination()
    store = get_store()
    items = [lp for lp in store.lottery_permits.values() if lp["park_id"] == park_id]
    items.sort(key=lambda lp: lp["created_at"])
    total = len(items)
    page = [serialize_lottery_permit(lp) for lp in items[offset : offset + limit]]
    return jsonify(success_array(page, limit=limit, offset=offset, total_count=total)), 200


@bp.post("/lottery-permits/<permit_id>/applications")
@require_auth([ROLE_VISITOR])
def submit_application(permit_id: str):
    permit = lookup_lottery_permit(permit_id)
    park = get_store().parks[permit["park_id"]]
    visitor_id = current_user_id()
    visitor = lookup_visitor(visitor_id)
    body = get_json_body()
    party_size = require_int(body, "party_size", min_val=1, max_val=12)

    if park["status"] == "FROZEN":
        raise APIError("ERR_PARK_FROZEN", "Park is FROZEN", 409)

    if visitor.get("lottery_strikes", 0) >= 3:
        raise APIError("ERR_STRIKE_LIMIT_REACHED", "Strike limit reached", 422)

    if party_size > permit["per_application_max_party"]:
        raise APIError("ERR_PARTY_SIZE_INVALID", "party_size exceeds max", 422)

    open_dt = parse_iso8601(permit["lottery_open_at"])
    close_dt = parse_iso8601(permit["lottery_close_at"])
    now = now_utc()
    if open_dt is None or close_dt is None:
        raise APIError("ERR_LOTTERY_CLOSED", "lottery dates invalid", 422)
    if now < open_dt or now >= close_dt:
        raise APIError("ERR_LOTTERY_CLOSED", "Outside [open, close)", 422)

    # Snapshot fee
    fee = permit["application_fee_cents"]
    if visitor["wallet_balance_cents"] < fee:
        raise APIError("ERR_INSUFFICIENT_FUNDS", "Wallet too low for application fee", 402)

    store = get_store()
    with store.lock:
        app = {
            "id": new_id(),
            "lottery_permit_id": permit_id,
            "visitor_id": visitor_id,
            "party_size": party_size,
            "rank_seed": new_rank_seed(),
            "application_fee_cents": fee,
            "status": "SUBMITTED",
            "award_expires_at": None,
        }
        stamp_create(app)
        store.lottery_applications[app["id"]] = app
        if fee > 0:
            debit_for_fee(visitor_id, fee, "LOTTERY_FEE", "LotteryApplication", app["id"])
    return jsonify(success_object(serialize_lottery_application(app))), 201


@bp.post("/lottery-permits/<permit_id>/draw")
@require_auth([ROLE_PARK_ADMIN, ROLE_SYSTEM_OPERATOR])
def trigger_draw(permit_id: str):
    permit = lookup_lottery_permit(permit_id)
    park = get_store().parks[permit["park_id"]]
    # Transition OPEN -> CLOSED if window passed
    if permit["status"] == "OPEN":
        close_dt = parse_iso8601(permit["lottery_close_at"])
        if close_dt is not None and now_utc() >= close_dt:
            permit["status"] = "CLOSED"
            stamp_update(permit)
    if permit["status"] == "DRAWN":
        raise APIError("ERR_LOTTERY_ALREADY_DRAWN", "Lottery already drawn", 409)
    if permit["status"] != "CLOSED":
        raise APIError("ERR_INVALID_STATE", "Lottery not in CLOSED state", 409)
    if park["status"] == "FROZEN":
        raise APIError("ERR_PARK_FROZEN", "Park is FROZEN", 409)
    store = get_store()
    with store.lock:
        run_draw(permit_id)
    return jsonify(success_object(serialize_lottery_permit(permit))), 200


@bp.get("/lottery-permits/<permit_id>/applications")
@require_auth([ROLE_PARK_ADMIN, ROLE_VISITOR])
def list_applications(permit_id: str):
    lookup_lottery_permit(permit_id)
    limit, offset = parse_pagination()
    store = get_store()
    items = [a for a in store.lottery_applications.values() if a["lottery_permit_id"] == permit_id]
    items = filter_visitor_owned(items)
    items.sort(key=lambda a: a["created_at"])
    total = len(items)
    page = [serialize_lottery_application(a) for a in items[offset : offset + limit]]
    return jsonify(success_array(page, limit=limit, offset=offset, total_count=total)), 200


def _lookup_application(app_id: str):
    store = get_store()
    a = store.lottery_applications.get(app_id)
    if a is None:
        raise APIError("ERR_NOT_FOUND", "Application not found", 404)
    return a


@bp.post("/lottery-applications/<app_id>/accept")
@require_auth([ROLE_VISITOR])
def accept_application(app_id: str):
    app = _lookup_application(app_id)
    require_visitor_ownership(app["visitor_id"])
    if app["status"] != "AWARDED":
        raise APIError("ERR_INVALID_STATE", "Application not AWARDED", 409)
    expires = parse_iso8601(app.get("award_expires_at") or "")
    if expires is None or now_utc() >= expires:
        raise APIError("ERR_AWARD_EXPIRED", "Award expired", 409)
    store = get_store()
    permit = store.lottery_permits[app["lottery_permit_id"]]
    visitor = store.visitors[app["visitor_id"]]
    fee = permit["permit_fee_cents"] * app["party_size"]
    if visitor["wallet_balance_cents"] < fee:
        raise APIError("ERR_INSUFFICIENT_FUNDS", "Wallet too low for permit fee", 402)
    with store.lock:
        if fee > 0:
            debit_for_fee(visitor["id"], fee, "PERMIT_FEE", "LotteryApplication", app["id"])
        app["status"] = "ACCEPTED"
        stamp_update(app)
    return jsonify(success_object(serialize_lottery_application(app))), 200


@bp.post("/lottery-applications/<app_id>/decline")
@require_auth([ROLE_VISITOR])
def decline_application(app_id: str):
    app = _lookup_application(app_id)
    require_visitor_ownership(app["visitor_id"])
    if app["status"] != "AWARDED":
        raise APIError("ERR_INVALID_STATE", "Application not AWARDED", 409)
    store = get_store()
    with store.lock:
        app["status"] = "DECLINED"
        stamp_update(app)
        # Promote next waitlisted
        promote_next_waitlisted(app["lottery_permit_id"])
    return jsonify(success_object(serialize_lottery_application(app))), 200


@bp.post("/lottery-applications/<app_id>/no-show")
@require_auth([ROLE_PARK_RANGER])
def no_show_application(app_id: str):
    app = _lookup_application(app_id)
    if app["status"] != "ACCEPTED":
        raise APIError("ERR_INVALID_STATE", "Application not ACCEPTED", 409)
    store = get_store()
    permit = store.lottery_permits[app["lottery_permit_id"]]
    park = store.parks[permit["park_id"]]
    # park-local now must be after 23:59 on hike_date
    hike_date_str = permit["hike_date"]
    if isinstance(hike_date_str, str) and "T" not in hike_date_str:
        hike_date = parse_date_local(hike_date_str[:10])
    else:
        dt_hike = parse_iso8601(hike_date_str)
        hike_date = dt_hike.date() if dt_hike else None
    if hike_date is None:
        raise APIError("ERR_VALIDATION", "Invalid hike_date", 422)
    from ..services.calculations import date_local_at_hm_utc
    end_utc = date_local_at_hm_utc(
        hike_date.strftime("%Y-%m-%d"), 23, 59, park["timezone"]
    )
    if now_utc() <= end_utc:
        raise APIError("ERR_INVALID_STATE", "Cannot record no-show before hike_date ends", 409)
    with store.lock:
        app["status"] = "FORFEITED"
        stamp_update(app)
        visitor = store.visitors.get(app["visitor_id"])
        if visitor is not None:
            visitor["lottery_strikes"] = min(3, visitor.get("lottery_strikes", 0) + 1)
            stamp_update(visitor)
    return jsonify(success_object(serialize_lottery_application(app))), 200
