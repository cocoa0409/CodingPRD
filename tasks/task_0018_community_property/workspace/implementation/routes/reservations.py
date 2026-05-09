"""Facility reservations: book, check-in, cancel, close (manager).
Settlement waterfall per PRD §3.7."""
from __future__ import annotations

from datetime import timedelta
from decimal import Decimal

from flask import Blueprint, g

import db
from errors import (
    APIError,
    ERR_FACILITY_SLOT_FULL,
    ERR_FORBIDDEN,
    ERR_INVALID_STATE,
    ERR_NOT_FOUND,
    ERR_OWNER_DELINQUENT,
    ERR_REFERENCE_NOT_FOUND,
    ERR_SLOT_IN_PAST,
    ERR_SLOT_MISALIGNED,
)
from middleware import require_roles
from response import success
from services.common import bump, stamp_create
from services.fees import issue_damage_spillover_bill
from utils import (
    get_body,
    parse_iso,
    require_field,
    round2,
    round2_dec,
    to_decimal,
)
from routes.residents import _owner_is_delinquent

bp = Blueprint("reservations", __name__)


def _get_or_404(rid):
    r = db.reservations.get(rid)
    if r is None:
        raise APIError(ERR_NOT_FOUND, f"Reservation {rid} not found.", 404)
    return r


def _slot_aligned(start_dt, slot_minutes: int) -> bool:
    """Slot grid is rooted at 00:00 UTC of the start date. We require the start
    minute-of-day to be a multiple of slot_minutes and seconds/microseconds zero."""
    if start_dt.second != 0 or start_dt.microsecond != 0:
        return False
    minutes_of_day = start_dt.hour * 60 + start_dt.minute
    return minutes_of_day % slot_minutes == 0


@bp.post("/reservations")
@require_roles("Owner")
def book():
    body = get_body()
    facility_id = require_field(body, "facility_id")
    slot_start_at = require_field(body, "slot_start_at")
    slot_end_at = require_field(body, "slot_end_at")

    facility = db.facilities.get(facility_id)
    if facility is None:
        raise APIError(ERR_REFERENCE_NOT_FOUND, f"Facility {facility_id} not found.", 404)

    start_dt = parse_iso(slot_start_at, field="slot_start_at")
    end_dt = parse_iso(slot_end_at, field="slot_end_at")

    # Validation order — see PRD §2.6.
    # business_temporal: misaligned slot
    slot_minutes = int(facility["slot_minutes"])
    expected_delta = timedelta(minutes=slot_minutes)
    if (end_dt - start_dt) != expected_delta or not _slot_aligned(start_dt, slot_minutes):
        raise APIError(ERR_SLOT_MISALIGNED, "Slot length or alignment invalid.", 422)
    if start_dt <= db.now():
        raise APIError(ERR_SLOT_IN_PAST, "slot_start_at must be in the future.", 422)

    # Capacity check, serialized
    with db.mutation_lock:
        existing = [
            r for r in db.reservations.values()
            if r.get("facility_id") == facility_id
            and r.get("slot_start_at") and parse_iso(r["slot_start_at"], field="slot_start_at") == start_dt
            and r.get("status") in ("BOOKED", "CHECKED_IN")
        ]
        if len(existing) >= int(facility.get("capacity_per_slot", 1)):
            raise APIError(ERR_FACILITY_SLOT_FULL, "Facility slot is full.", 409)

        # business_safety: owner delinquent
        if _owner_is_delinquent(g.user_id):
            raise APIError(ERR_OWNER_DELINQUENT, "Owner has overdue bills.", 403)

        deposit = float(round2_dec(to_decimal(facility.get("damage_deposit", 0))))
        from utils import iso_format
        reservation = {
            "facility_id": facility_id,
            "owner_id": g.user_id,
            "slot_start_at": iso_format(start_dt),
            "slot_end_at": iso_format(end_dt),
            "status": "BOOKED",
            "deposit_held": deposit,
            "damage_amount": 0.0,
            "cancellation_at": None,
        }
        stamp_create(reservation)
        db.reservations[reservation["id"]] = reservation
    return success(reservation, status=201)


@bp.post("/reservations/<rid>/check-in")
@require_roles("Owner")
def check_in(rid):
    r = _get_or_404(rid)
    if r.get("owner_id") != g.user_id:
        raise APIError(ERR_FORBIDDEN, "Only the booking owner may check in.", 403)
    if r["status"] != "BOOKED":
        raise APIError(ERR_INVALID_STATE, "Reservation is not BOOKED.", 409)
    start_dt = parse_iso(r["slot_start_at"], field="slot_start_at")
    end_dt = parse_iso(r["slot_end_at"], field="slot_end_at")
    now = db.now()
    if not (start_dt <= now < end_dt):
        raise APIError(ERR_INVALID_STATE, "Outside check-in window.", 409)
    r["status"] = "CHECKED_IN"
    bump(r)
    return success(r)


@bp.post("/reservations/<rid>/cancel")
@require_roles("Owner")
def cancel(rid):
    r = _get_or_404(rid)
    if r.get("owner_id") != g.user_id:
        raise APIError(ERR_FORBIDDEN, "Only the booking owner may cancel.", 403)
    if r["status"] != "BOOKED":
        raise APIError(ERR_INVALID_STATE, "Reservation is not BOOKED.", 409)

    facility = db.facilities.get(r["facility_id"])
    cancel_window_hours = int(facility.get("cancellation_window_hours", 24)) if facility else 24

    start_dt = parse_iso(r["slot_start_at"], field="slot_start_at")
    cutoff = start_dt - timedelta(hours=cancel_window_hours)
    now = db.now()
    held = to_decimal(r.get("deposit_held", 0))

    if now <= cutoff:
        # Free-window cancel: PRD §3.7 says "the full deposit_held is refunded
        # and nothing is forfeited." The held amount drops to zero (parallel to
        # late-cancel's explicit "deposit_held is replaced by round(deposit_held * 0.5, 2)"
        # — the field tracks the residual hold, not the original).
        r["deposit_held"] = 0.0
    else:
        refund = round2_dec(held * Decimal("0.5"))
        r["deposit_held"] = float(refund)

    from utils import iso_format
    r["cancellation_at"] = iso_format(now)
    r["status"] = "CANCELLED"
    bump(r)
    return success(r)


@bp.post("/reservations/<rid>/close")
@require_roles("PropertyManager")
def close(rid):
    r = _get_or_404(rid)
    if r["status"] != "CHECKED_IN":
        raise APIError(ERR_INVALID_STATE, "Reservation is not CHECKED_IN.", 409)
    end_dt = parse_iso(r["slot_end_at"], field="slot_end_at")
    if db.now() < end_dt:
        raise APIError(ERR_INVALID_STATE, "Cannot close before slot_end_at.", 409)

    body = get_body()
    damage_amount = body.get("damage_amount", 0)
    damage_d = to_decimal(damage_amount)
    if damage_d < 0:
        raise APIError(__import__("errors").ERR_VALIDATION, "damage_amount must be >= 0.", 422)

    held = to_decimal(r.get("deposit_held", 0))

    if damage_d == 0:
        # Full refund; deposit_held unchanged (refund equals deposit_held).
        r["damage_amount"] = 0.0
        r["status"] = "COMPLETED"
    else:
        absorb = min(held, damage_d)
        refund = round2_dec(held - absorb)
        r["deposit_held"] = float(refund)
        r["damage_amount"] = float(round2_dec(damage_d))
        r["status"] = "DAMAGED"
        if damage_d > held:
            spillover = round2_dec(damage_d - held)
            facility = db.facilities.get(r["facility_id"])
            # The damaged spillover bill is owed by the booking owner — bind it
            # to one of their properties. We pick the first property they own.
            owner_id = r.get("owner_id")
            owner_props = [p for p in db.properties.values() if p.get("owner_id") == owner_id]
            if owner_props:
                issue_damage_spillover_bill(
                    property_id=owner_props[0]["id"],
                    spillover_amount=float(spillover),
                )
    bump(r)
    return success(r)
