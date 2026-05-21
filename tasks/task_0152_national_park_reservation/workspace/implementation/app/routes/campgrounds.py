"""Campground, reservation, and waitlist routes."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from flask import Blueprint, jsonify

from ..auth import (
    ROLE_PARK_ADMIN,
    ROLE_PARK_RANGER,
    ROLE_VISITOR,
    current_user_id,
    require_auth,
)
from ..clock import now_utc
from ..envelope import parse_pagination, success_array, success_object, empty_success
from ..errors import APIError
from ..serializers import (
    serialize_campground,
    serialize_campground_reservation,
    serialize_waitlist_entry,
)
from ..services.calculations import (
    campground_refund,
    compute_booking_total,
    date_local_at_hm_utc,
    date_local_at_midnight_utc,
)
from ..services.common import stamp_create, stamp_update
from ..services.inventory import campground_has_inventory
from ..services.waitlist import try_promote_one
from ..services.wallet import debit_for_fee, refund as wallet_refund
from ..store import get_store
from ..timeutil import parse_date_local
from ..util import format_iso8601, new_id
from ..validators import (
    get_json_body,
    optional_int,
    require_int,
    require_string,
)
from ._helpers import (
    filter_visitor_owned,
    lookup_campground,
    lookup_park,
    lookup_visitor,
    require_visitor_ownership,
)

bp = Blueprint("campgrounds", __name__)


@bp.post("/parks/<park_id>/campgrounds")
@require_auth([ROLE_PARK_ADMIN])
def create_campground(park_id: str):
    park = lookup_park(park_id)
    body = get_json_body()
    name = require_string(body, "name", min_len=1, max_len=120)
    std_count = require_int(body, "standard_site_count", min_val=0)
    grp_count = require_int(body, "group_site_count", min_val=0)
    std_fee = require_int(body, "nightly_standard_fee_cents", min_val=0)
    grp_fee = require_int(body, "nightly_group_fee_cents", min_val=0)
    max_nights = optional_int(body, "max_consecutive_nights", default=14, min_val=1, max_val=30)
    waitlist_hours = optional_int(body, "waitlist_window_hours", default=24, min_val=1, max_val=168)
    store = get_store()
    key = (park_id, name.lower())
    with store.lock:
        if key in store.campground_names:
            raise APIError("ERR_VALIDATION", "campground name not unique within park", 422)
        cg = {
            "id": new_id(),
            "park_id": park_id,
            "name": name,
            "standard_site_count": std_count,
            "group_site_count": grp_count,
            "nightly_standard_fee_cents": std_fee,
            "nightly_group_fee_cents": grp_fee,
            "max_consecutive_nights": max_nights,
            "waitlist_window_hours": waitlist_hours,
        }
        stamp_create(cg)
        store.campgrounds[cg["id"]] = cg
        store.campground_names[key] = cg["id"]
    return jsonify(success_object(serialize_campground(cg))), 201


@bp.get("/parks/<park_id>/campgrounds")
@require_auth([ROLE_PARK_ADMIN, ROLE_VISITOR, ROLE_PARK_RANGER])
def list_campgrounds(park_id: str):
    lookup_park(park_id)
    limit, offset = parse_pagination()
    store = get_store()
    items = [c for c in store.campgrounds.values() if c["park_id"] == park_id]
    items.sort(key=lambda c: c["created_at"])
    total = len(items)
    page = [serialize_campground(c) for c in items[offset : offset + limit]]
    return jsonify(success_array(page, limit=limit, offset=offset, total_count=total)), 200


def _parse_check_dates(check_in: str, check_out: str) -> int:
    a = parse_date_local(check_in)
    b = parse_date_local(check_out)
    if a is None or b is None:
        raise APIError("ERR_VALIDATION", "check_in/out must be YYYY-MM-DD", 422)
    nights = (b - a).days
    return nights


@bp.post("/campgrounds/<campground_id>/reservations")
@require_auth([ROLE_VISITOR])
def create_campground_reservation(campground_id: str):
    cg = lookup_campground(campground_id)
    park = get_store().parks[cg["park_id"]]
    visitor_id = current_user_id()
    visitor = lookup_visitor(visitor_id)
    body = get_json_body()
    site_kind = require_string(body, "site_kind", min_len=1)
    if site_kind not in ("STANDARD", "GROUP"):
        raise APIError("ERR_VALIDATION", "site_kind must be STANDARD or GROUP", 422)
    # PRD §2.12 priority 9: party_size mismatch with site_kind surfaces as
    # ERR_PARTY_SIZE_INVALID (not ERR_VALIDATION). Accept any integer here
    # and apply the kind-specific bound below.
    party_size = require_int(body, "party_size")
    check_in = require_string(body, "check_in_date_local", min_len=10, max_len=10)
    check_out = require_string(body, "check_out_date_local", min_len=10, max_len=10)

    # Park posture: FROZEN blocks; RESTRICTED still allows campground bookings.
    if park["status"] == "FROZEN":
        raise APIError("ERR_PARK_FROZEN", "Park is FROZEN", 409)

    # Strike-limit gate fires before capacity for GROUP
    if site_kind == "GROUP":
        if visitor.get("lottery_strikes", 0) >= 3:
            raise APIError("ERR_STRIKE_LIMIT_REACHED", "Strike limit reached for GROUP", 422)

    # party_size matches site_kind
    if site_kind == "STANDARD" and not (1 <= party_size <= 6):
        raise APIError("ERR_PARTY_SIZE_INVALID", "STANDARD party_size 1..6", 422)
    if site_kind == "GROUP" and not (7 <= party_size <= 40):
        raise APIError("ERR_PARTY_SIZE_INVALID", "GROUP party_size 7..40", 422)

    nights = _parse_check_dates(check_in, check_out)
    if nights <= 0:
        raise APIError("ERR_STAY_TOO_LONG", "check_out must be after check_in", 422)
    if nights > cg["max_consecutive_nights"]:
        raise APIError("ERR_STAY_TOO_LONG", "Exceeds max_consecutive_nights", 422)

    nightly_rate = (
        cg["nightly_standard_fee_cents"] if site_kind == "STANDARD" else cg["nightly_group_fee_cents"]
    )

    store = get_store()
    with store.lock:
        if not campground_has_inventory(campground_id, site_kind, check_in, check_out):
            raise APIError("ERR_CAMPGROUND_FULL", "No inventory for date range", 409)
        totals = compute_booking_total(nightly_rate, nights)
        now = now_utc()
        held_until = now + timedelta(minutes=15)
        r = {
            "id": new_id(),
            "campground_id": campground_id,
            "visitor_id": visitor_id,
            "site_kind": site_kind,
            "party_size": party_size,
            "check_in_date_local": check_in,
            "check_out_date_local": check_out,
            "nights": totals["nights"],
            "nightly_rate_cents": totals["nightly_rate_cents"],
            "total_fee_cents": totals["total_fee_cents"],
            "status": "HELD",
            "held_until": format_iso8601(held_until),
            "refund_cents": 0,
        }
        stamp_create(r)
        store.campground_reservations[r["id"]] = r
    return jsonify(success_object(serialize_campground_reservation(r))), 201


def _lookup_cg_reservation(campground_id: str, reservation_id: str):
    lookup_campground(campground_id)
    store = get_store()
    r = store.campground_reservations.get(reservation_id)
    if r is None or r["campground_id"] != campground_id:
        raise APIError("ERR_NOT_FOUND", "Reservation not found", 404)
    return r


@bp.post("/campgrounds/<campground_id>/reservations/<reservation_id>/confirm")
@require_auth([ROLE_VISITOR])
def confirm_campground_reservation(campground_id: str, reservation_id: str):
    r = _lookup_cg_reservation(campground_id, reservation_id)
    require_visitor_ownership(r["visitor_id"])
    if r["status"] != "HELD":
        raise APIError("ERR_INVALID_STATE", "Reservation not HELD", 409)
    from ..util import parse_iso8601
    held_until = parse_iso8601(r["held_until"])
    if held_until is None or now_utc() >= held_until:
        raise APIError("ERR_INVALID_STATE", "Hold expired", 409)
    cg = get_store().campgrounds[campground_id]
    park = get_store().parks[cg["park_id"]]
    if park["status"] == "FROZEN":
        raise APIError("ERR_PARK_FROZEN", "Park is FROZEN", 409)
    visitor = get_store().visitors[r["visitor_id"]]
    if r["site_kind"] == "GROUP" and visitor.get("lottery_strikes", 0) >= 3:
        raise APIError("ERR_STRIKE_LIMIT_REACHED", "Strike limit reached for GROUP", 422)
    if visitor["wallet_balance_cents"] < r["total_fee_cents"]:
        raise APIError("ERR_INSUFFICIENT_FUNDS", "Wallet too low", 402)
    store = get_store()
    with store.lock:
        if r["total_fee_cents"] > 0:
            debit_for_fee(
                visitor["id"], r["total_fee_cents"], "FEE_CHARGE", "CampgroundReservation", r["id"]
            )
        r["status"] = "CONFIRMED"
        stamp_update(r)
    return jsonify(success_object(serialize_campground_reservation(r))), 200


@bp.post("/campgrounds/<campground_id>/reservations/<reservation_id>/cancel")
@require_auth([ROLE_VISITOR])
def cancel_campground_reservation(campground_id: str, reservation_id: str):
    r = _lookup_cg_reservation(campground_id, reservation_id)
    require_visitor_ownership(r["visitor_id"])
    if r["status"] not in ("HELD", "CONFIRMED"):
        raise APIError("ERR_INVALID_STATE", "Cannot cancel", 409)
    cg = get_store().campgrounds[campground_id]
    park = get_store().parks[cg["park_id"]]
    if r["status"] == "CONFIRMED":
        # must be strictly before 16:00 park-local on check_in_date_local
        cutoff_utc = date_local_at_hm_utc(
            r["check_in_date_local"], 16, 0, park["timezone"]
        )
        if now_utc() >= cutoff_utc:
            raise APIError("ERR_INVALID_STATE", "Past cancel window", 409)
        ci_utc = date_local_at_midnight_utc(r["check_in_date_local"], park["timezone"])
        hours = (ci_utc - now_utc()).total_seconds() / 3600.0
        refund_cents = campground_refund(
            total_fee_cents=r["total_fee_cents"],
            nightly_rate_cents=r["nightly_rate_cents"],
            hours_to_check_in=hours,
            site_kind=r["site_kind"],
        )
    else:
        refund_cents = 0
    store = get_store()
    with store.lock:
        if refund_cents > 0:
            wallet_refund(r["visitor_id"], refund_cents, "CampgroundReservation", r["id"])
        r["refund_cents"] = refund_cents
        r["status"] = "CANCELLED"
        stamp_update(r)
        # cascade: waitlist promote
        try_promote_one(campground_id, r["site_kind"])
    return jsonify(success_object(serialize_campground_reservation(r))), 200


@bp.post("/campgrounds/<campground_id>/reservations/<reservation_id>/check-in")
@require_auth([ROLE_PARK_RANGER])
def checkin_campground_reservation(campground_id: str, reservation_id: str):
    r = _lookup_cg_reservation(campground_id, reservation_id)
    if r["status"] != "CONFIRMED":
        raise APIError("ERR_INVALID_STATE", "Reservation not CONFIRMED", 409)
    store = get_store()
    with store.lock:
        r["checked_in"] = True
        stamp_update(r)
    return jsonify(success_object(serialize_campground_reservation(r))), 200


@bp.get("/campgrounds/<campground_id>/reservations")
@require_auth([ROLE_PARK_ADMIN, ROLE_PARK_RANGER, ROLE_VISITOR])
def list_campground_reservations(campground_id: str):
    lookup_campground(campground_id)
    limit, offset = parse_pagination()
    store = get_store()
    items = [r for r in store.campground_reservations.values() if r["campground_id"] == campground_id]
    items = filter_visitor_owned(items)
    items.sort(key=lambda r: r["created_at"])
    total = len(items)
    page = [serialize_campground_reservation(r) for r in items[offset : offset + limit]]
    return jsonify(success_array(page, limit=limit, offset=offset, total_count=total)), 200


# ---------------- Waitlist ----------------


@bp.post("/campgrounds/<campground_id>/waitlist")
@require_auth([ROLE_VISITOR])
def create_waitlist_entry(campground_id: str):
    lookup_campground(campground_id)
    visitor_id = current_user_id()
    lookup_visitor(visitor_id)
    body = get_json_body()
    site_kind = require_string(body, "site_kind", min_len=1)
    if site_kind not in ("STANDARD", "GROUP"):
        raise APIError("ERR_VALIDATION", "site_kind must be STANDARD or GROUP", 422)
    check_in = require_string(body, "check_in_date_local", min_len=10, max_len=10)
    if parse_date_local(check_in) is None:
        raise APIError("ERR_VALIDATION", "check_in_date_local must be YYYY-MM-DD", 422)
    nights = require_int(body, "nights", min_val=1, max_val=14)
    now = now_utc()
    # priority_score = floor((created_at - epoch) / 60) seconds
    epoch = datetime(1970, 1, 1, tzinfo=timezone.utc)
    priority_score = int((now - epoch).total_seconds() // 60)
    entry = {
        "id": new_id(),
        "campground_id": campground_id,
        "visitor_id": visitor_id,
        "site_kind": site_kind,
        "check_in_date_local": check_in,
        "nights": nights,
        "priority_score": priority_score,
        "status": "WAITING",
        "promoted_reservation_id": None,
    }
    entry["created_at"] = format_iso8601(now)
    store = get_store()
    with store.lock:
        store.waitlist_entries[entry["id"]] = entry
    return jsonify(success_object(serialize_waitlist_entry(entry))), 201


@bp.get("/campgrounds/<campground_id>/waitlist")
@require_auth([ROLE_PARK_ADMIN, ROLE_PARK_RANGER, ROLE_VISITOR])
def list_waitlist(campground_id: str):
    lookup_campground(campground_id)
    limit, offset = parse_pagination()
    store = get_store()
    items = [w for w in store.waitlist_entries.values() if w["campground_id"] == campground_id]
    items = filter_visitor_owned(items)
    items.sort(key=lambda w: w["created_at"])
    total = len(items)
    page = [serialize_waitlist_entry(w) for w in items[offset : offset + limit]]
    return jsonify(success_array(page, limit=limit, offset=offset, total_count=total)), 200


@bp.delete("/campgrounds/<campground_id>/waitlist/<entry_id>")
@require_auth([ROLE_VISITOR])
def delete_waitlist_entry(campground_id: str, entry_id: str):
    lookup_campground(campground_id)
    store = get_store()
    w = store.waitlist_entries.get(entry_id)
    if w is None or w["campground_id"] != campground_id:
        raise APIError("ERR_NOT_FOUND", "Waitlist entry not found", 404)
    require_visitor_ownership(w["visitor_id"])
    if w["status"] != "WAITING":
        raise APIError("ERR_INVALID_STATE", "Waitlist entry not WAITING", 409)
    with store.lock:
        w["status"] = "CANCELLED"
    return ("", 204)
