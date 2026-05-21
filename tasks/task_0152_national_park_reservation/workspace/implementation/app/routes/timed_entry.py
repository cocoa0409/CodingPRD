"""Timed-entry reservation routes."""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

from flask import Blueprint, jsonify

from ..auth import (
    ROLE_PARK_ADMIN,
    ROLE_PARK_RANGER,
    ROLE_VISITOR,
    current_user_id,
    require_auth,
)
from ..clock import now_utc
from ..envelope import parse_pagination, success_array, success_object
from ..errors import APIError
from ..serializers import serialize_timed_entry
from ..services.calculations import (
    add_minutes_to_hhmm,
    date_local_at_hm_utc,
    hhmm_to_minutes,
    hours_between_now_and_utc,
    timed_entry_refund,
)
from ..services.common import stamp_create, stamp_update
from ..services.inventory import timed_entry_remaining
from ..services.wallet import debit_for_fee, refund as wallet_refund
from ..store import get_store
from ..timeutil import parse_date_local, park_local_date_at, parse_hhmm
from ..util import format_iso8601, new_id, parse_iso8601
from ..validators import get_json_body, optional_string, require_string
from ._helpers import (
    filter_visitor_owned,
    lookup_park,
    lookup_visitor,
    require_visitor_ownership,
)

bp = Blueprint("timed_entry", __name__)


DEFAULT_TIMED_ENTRY_FEE_CENTS = 3500  # $35.00 fee when no pass


def _check_pass_valid(pass_id: str, visitor_id: str, entry_date_local: str) -> None:
    store = get_store()
    p = store.passes.get(pass_id)
    if p is None or p["visitor_id"] != visitor_id:
        raise APIError("ERR_PASS_INVALID", "Pass does not belong to visitor", 422)
    if p["status"] != "ACTIVE":
        raise APIError("ERR_PASS_INVALID", "Pass not ACTIVE", 422)
    # Check valid window: pass valid at entry_date_local
    vf = parse_iso8601(p["valid_from"])
    vu = parse_iso8601(p["valid_until"])
    d = parse_date_local(entry_date_local)
    if d is None or vf is None or vu is None:
        raise APIError("ERR_PASS_INVALID", "Pass dates invalid", 422)
    # Entry date midnight UTC reference
    entry_ref = datetime(d.year, d.month, d.day, tzinfo=timezone.utc)
    if not (vf <= entry_ref <= vu):
        raise APIError("ERR_PASS_INVALID", "Pass not valid at entry_date_local", 422)


@bp.post("/parks/<park_id>/timed-entry")
@require_auth([ROLE_VISITOR])
def create_timed_entry(park_id: str):
    park = lookup_park(park_id)
    visitor_id = current_user_id()
    lookup_visitor(visitor_id)
    body = get_json_body()
    vehicle_plate = require_string(body, "vehicle_plate", min_len=1, max_len=10).upper()
    entry_date_local = require_string(body, "entry_date_local", min_len=10, max_len=10)
    window_start_local = require_string(body, "window_start_local", min_len=5, max_len=5)
    pass_id = optional_string(body, "pass_id")

    # validate state
    if park["status"] == "FROZEN":
        raise APIError("ERR_PARK_FROZEN", "Park is FROZEN", 409)
    if park["status"] == "RESTRICTED":
        raise APIError("ERR_PARK_RESTRICTED", "Park is RESTRICTED", 409)

    # business_temporal — date format
    edate = parse_date_local(entry_date_local)
    if edate is None:
        raise APIError("ERR_VALIDATION", "entry_date_local must be YYYY-MM-DD", 422)
    # window alignment
    if parse_hhmm(window_start_local) is None:
        raise APIError("ERR_WINDOW_MISALIGNED", "window_start_local must be HH:MM", 422)
    window_minutes = park["timed_entry_window_minutes"]
    start_min = hhmm_to_minutes(window_start_local)
    if start_min % window_minutes != 0:
        raise APIError("ERR_WINDOW_MISALIGNED", "window_start_local not aligned", 422)

    # 30-day rolling window in park-local
    park_local_today = park_local_date_at(now_utc(), park["timezone"])
    if edate < park_local_today:
        raise APIError("ERR_OUT_OF_BOOKING_WINDOW", "entry_date_local in the past", 422)
    if (edate - park_local_today).days > 30:
        raise APIError("ERR_OUT_OF_BOOKING_WINDOW", "entry_date_local >30 days ahead", 422)

    # pass referential check (when supplied)
    if pass_id is not None:
        _check_pass_valid(pass_id, visitor_id, entry_date_local)

    store = get_store()
    with store.lock:
        # capacity
        if timed_entry_remaining(park_id, entry_date_local, window_start_local) <= 0:
            raise APIError("ERR_TIMED_ENTRY_FULL", "No capacity", 409)
        # compute fee
        entry_fee = 0 if pass_id else DEFAULT_TIMED_ENTRY_FEE_CENTS
        now = now_utc()
        held_until = now + timedelta(minutes=15)
        window_end_local = add_minutes_to_hhmm(window_start_local, window_minutes)
        reservation = {
            "id": new_id(),
            "park_id": park_id,
            "visitor_id": visitor_id,
            "vehicle_plate": vehicle_plate,
            "entry_date_local": entry_date_local,
            "window_start_local": window_start_local,
            "window_end_local": window_end_local,
            "pass_id": pass_id,
            "entry_fee_cents": entry_fee,
            "status": "HELD",
            "held_until": format_iso8601(held_until),
        }
        stamp_create(reservation)
        store.timed_entry_reservations[reservation["id"]] = reservation
    return jsonify(success_object(serialize_timed_entry(reservation))), 201


@bp.get("/parks/<park_id>/timed-entry")
@require_auth([ROLE_PARK_ADMIN, ROLE_PARK_RANGER, ROLE_VISITOR])
def list_timed_entry(park_id: str):
    lookup_park(park_id)
    limit, offset = parse_pagination()
    store = get_store()
    items = [r for r in store.timed_entry_reservations.values() if r["park_id"] == park_id]
    items = filter_visitor_owned(items)
    items.sort(key=lambda r: r["created_at"])
    total = len(items)
    page = [serialize_timed_entry(r) for r in items[offset : offset + limit]]
    return jsonify(success_array(page, limit=limit, offset=offset, total_count=total)), 200


def _lookup_te(park_id: str, te_id: str):
    lookup_park(park_id)
    store = get_store()
    r = store.timed_entry_reservations.get(te_id)
    if r is None or r["park_id"] != park_id:
        raise APIError("ERR_NOT_FOUND", "Reservation not found", 404)
    return r


@bp.post("/parks/<park_id>/timed-entry/<te_id>/confirm")
@require_auth([ROLE_VISITOR])
def confirm_timed_entry(park_id: str, te_id: str):
    r = _lookup_te(park_id, te_id)
    require_visitor_ownership(r["visitor_id"])
    park = get_store().parks[park_id]
    if r["status"] != "HELD":
        raise APIError("ERR_INVALID_STATE", "Reservation not in HELD", 409)
    held_until = parse_iso8601(r["held_until"])
    if held_until is None or now_utc() >= held_until:
        # Held expired — mark as cancelled by the sweep next, but report here
        raise APIError("ERR_INVALID_STATE", "Hold expired", 409)
    if park["status"] != "OPEN":
        if park["status"] == "FROZEN":
            raise APIError("ERR_PARK_FROZEN", "Park is FROZEN", 409)
        raise APIError("ERR_PARK_RESTRICTED", "Park is RESTRICTED", 409)
    visitor = get_store().visitors[r["visitor_id"]]
    fee = r["entry_fee_cents"]
    if visitor["wallet_balance_cents"] < fee:
        raise APIError("ERR_INSUFFICIENT_FUNDS", "Wallet too low", 402)
    store = get_store()
    with store.lock:
        if fee > 0:
            debit_for_fee(visitor["id"], fee, "FEE_CHARGE", "TimedEntryReservation", r["id"])
        r["status"] = "CONFIRMED"
        stamp_update(r)
    return jsonify(success_object(serialize_timed_entry(r))), 200


@bp.post("/parks/<park_id>/timed-entry/<te_id>/cancel")
@require_auth([ROLE_VISITOR])
def cancel_timed_entry(park_id: str, te_id: str):
    r = _lookup_te(park_id, te_id)
    require_visitor_ownership(r["visitor_id"])
    if r["status"] not in ("HELD", "CONFIRMED"):
        raise APIError("ERR_INVALID_STATE", "Reservation cannot be cancelled", 409)
    park = get_store().parks[park_id]
    if r["status"] == "CONFIRMED":
        # must be strictly before entry-window start (park-local)
        start_hm = parse_hhmm(r["window_start_local"])
        if start_hm is None:
            raise APIError("ERR_INVALID_STATE", "Internal time error", 409)
        start_utc = date_local_at_hm_utc(
            r["entry_date_local"], start_hm[0], start_hm[1], park["timezone"]
        )
        if now_utc() >= start_utc:
            raise APIError("ERR_INVALID_STATE", "Past entry window start", 409)
        hours = (start_utc - now_utc()).total_seconds() / 3600.0
        refund_cents = timed_entry_refund(r["entry_fee_cents"], hours)
    else:
        refund_cents = 0
    store = get_store()
    with store.lock:
        if refund_cents > 0:
            wallet_refund(r["visitor_id"], refund_cents, "TimedEntryReservation", r["id"])
        r["status"] = "CANCELLED"
        stamp_update(r)
    return jsonify(success_object(serialize_timed_entry(r))), 200


@bp.post("/parks/<park_id>/timed-entry/<te_id>/check-in")
@require_auth([ROLE_PARK_RANGER])
def checkin_timed_entry(park_id: str, te_id: str):
    r = _lookup_te(park_id, te_id)
    if r["status"] != "CONFIRMED":
        raise APIError("ERR_INVALID_STATE", "Reservation not CONFIRMED", 409)
    park = get_store().parks[park_id]
    start_hm = parse_hhmm(r["window_start_local"])
    end_hm = parse_hhmm(r["window_end_local"])
    if start_hm is None or end_hm is None:
        raise APIError("ERR_INVALID_STATE", "Bad window times", 409)
    start_utc = date_local_at_hm_utc(
        r["entry_date_local"], start_hm[0], start_hm[1], park["timezone"]
    )
    end_utc = date_local_at_hm_utc(
        r["entry_date_local"], end_hm[0], end_hm[1], park["timezone"]
    )
    now = now_utc()
    if not (start_utc <= now <= end_utc):
        raise APIError("ERR_INVALID_STATE", "Outside check-in window", 409)
    store = get_store()
    with store.lock:
        r["status"] = "USED"
        stamp_update(r)
    return jsonify(success_object(serialize_timed_entry(r))), 200
