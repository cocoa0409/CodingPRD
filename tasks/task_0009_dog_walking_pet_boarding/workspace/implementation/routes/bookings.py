"""Booking routes."""
from __future__ import annotations

from datetime import timedelta

from flask import Blueprint, request

import db
import response
from errors import (
    ApiError,
    ERR_INVALID_REQUEST,
    ERR_INVALID_STATE,
    ERR_MEET_AND_GREET_REQUIRED,
    ERR_PET_OWNER_MISMATCH,
    ERR_PET_TIME_CONFLICT,
    ERR_SITTER_NOT_CLEARED,
    ERR_SITTER_TIME_CONFLICT,
    ERR_STALE_VERSION,
    ERR_WALLET_INSUFFICIENT,
)
from middleware import require_auth
from services.calculations import (
    compute_booking_quote,
    compute_sitter_payout_final,
    compute_sitter_payout_provisional,
)
from services.common import (
    bump,
    get_json_body,
    new_common_fields,
    optional_enum,
    optional_int,
    optional_non_negative_int,
    paginate,
    parse_pagination,
    require_enum,
    require_iso8601,
    require_str,
    sorted_by_created_at,
)
from services.lookup import (
    bg_check_for_sitter,
    fk_owner,
    fk_pet,
    fk_sitter,
    get_booking_or_404,
    key_handoff_for_booking,
)
from services.sitter_logic import recompute_sitter_tier

bp = Blueprint("bookings", __name__)


_SERVICE_TYPES = {"WALK_30MIN", "WALK_60MIN", "BOARDING_OVERNIGHT", "DAYCARE"}
_TIME_OF_DAY = {"STANDARD", "PEAK", "OVERNIGHT"}
_RECURRING = {"NONE", "WEEKLY", "BIWEEKLY"}

_BOOKING_STATUSES = {
    "REQUESTED",
    "CONFIRMED",
    "KEY_RECEIVED",
    "IN_PROGRESS",
    "COMPLETED",
    "CANCELLED",
    "REJECTED",
    "EMERGENCY_TERMINATED",
}


def booking_to_dict(b: dict) -> dict:
    return {
        "id": b["id"],
        "owner_id": b["owner_id"],
        "sitter_id": b["sitter_id"],
        "pet_id": b["pet_id"],
        "service_type": b["service_type"],
        "time_of_day": b["time_of_day"],
        "recurring_cadence": b["recurring_cadence"],
        "start_at": b["start_at"],
        "end_at": b["end_at"],
        "status": b["status"],
        "emergency_surcharge_cents": b["emergency_surcharge_cents"],
        "booking_quote_cents": b["booking_quote_cents"],
        "provisional_sitter_payout_cents": b["provisional_sitter_payout_cents"],
        "final_sitter_payout_cents": b["final_sitter_payout_cents"],
        "tip_cents": b["tip_cents"],
        "incident_deduction_cents": b["incident_deduction_cents"],
        "owner_rating": b["owner_rating"],
        "wallet_credit_applied_cents": b["wallet_credit_applied_cents"],
        "cancellation_reason": b["cancellation_reason"],
        "created_at": b["created_at"],
        "updated_at": b["updated_at"],
        "version": b["version"],
    }


def _has_completed_approved_mg(owner_id: str, sitter_id: str, pet_id: str) -> bool:
    for m in db.meet_and_greets.values():
        if (
            m["owner_id"] == owner_id
            and m["sitter_id"] == sitter_id
            and m["pet_id"] == pet_id
            and m["status"] == "COMPLETED_APPROVED"
        ):
            return True
    return False


_NON_TERMINAL_OPEN = {"REQUESTED", "CONFIRMED", "KEY_RECEIVED", "IN_PROGRESS"}


def _check_sitter_time_conflict(sitter_id: str, start_dt, end_dt) -> None:
    """Half-open semantics + 30 minute trailing buffer on existing bookings.

    Existing booking's effective window: [start_at, end_at + 30min).
    Proposed window: [start_at, end_at).
    Overlap when proposed.start < existing.end+30 AND existing.start < proposed.end.
    """
    buffer = timedelta(minutes=30)
    for b in db.bookings.values():
        if b["sitter_id"] != sitter_id:
            continue
        if b["status"] not in _NON_TERMINAL_OPEN:
            continue
        b_start = db.parse_ts(b["start_at"])
        b_end = db.parse_ts(b["end_at"])
        if start_dt < b_end + buffer and b_start < end_dt:
            raise ApiError(
                ERR_SITTER_TIME_CONFLICT,
                "Sitter has a conflicting booking (half-open + 30min buffer).",
            )


def _check_pet_time_conflict(pet_id: str, start_dt, end_dt) -> None:
    """Closed-inclusive on both sides; no buffer.

    Existing closed [start_at, end_at] intersects proposed closed [start_at, end_at]
    when proposed.start <= existing.end AND existing.start <= proposed.end.
    """
    for b in db.bookings.values():
        if b["pet_id"] != pet_id:
            continue
        if b["status"] not in _NON_TERMINAL_OPEN:
            continue
        b_start = db.parse_ts(b["start_at"])
        b_end = db.parse_ts(b["end_at"])
        if start_dt <= b_end and b_start <= end_dt:
            raise ApiError(
                ERR_PET_TIME_CONFLICT,
                "Pet has a conflicting booking (closed-inclusive intersection).",
            )


@bp.post("/api/v1/bookings")
@require_auth(roles=["Owner"])
def create_booking():
    body = get_json_body()
    owner_id = require_str(body, "owner_id")
    sitter_id = require_str(body, "sitter_id")
    pet_id = require_str(body, "pet_id")
    service_type = require_enum(body, "service_type", _SERVICE_TYPES)
    time_of_day = require_enum(body, "time_of_day", _TIME_OF_DAY)
    recurring_cadence = optional_enum(body, "recurring_cadence", _RECURRING, "NONE")
    start_dt = require_iso8601(body, "start_at")
    end_dt = require_iso8601(body, "end_at")
    emergency_surcharge_cents = optional_non_negative_int(body, "emergency_surcharge_cents", 0)
    wallet_credit_applied_cents = optional_non_negative_int(body, "wallet_credit_applied_cents", 0)

    if end_dt <= start_dt:
        raise ApiError(ERR_INVALID_REQUEST, "end_at must be strictly after start_at.")

    # FK existence
    owner = fk_owner(owner_id)
    sitter = fk_sitter(sitter_id)
    pet = fk_pet(pet_id)

    # Validation #8 MeetAndGreet + Sitter.status==ACTIVE
    if sitter["status"] != "ACTIVE" or not _has_completed_approved_mg(owner_id, sitter_id, pet_id):
        raise ApiError(
            ERR_MEET_AND_GREET_REQUIRED,
            "Booking requires a COMPLETED_APPROVED MeetAndGreet and an ACTIVE Sitter.",
        )

    # Validation #9 Pet.owner_id == owner_id
    if pet["owner_id"] != owner_id:
        raise ApiError(ERR_PET_OWNER_MISMATCH, "pet does not belong to owner.")

    # Validation #10 Sitter time conflict
    _check_sitter_time_conflict(sitter_id, start_dt, end_dt)

    # Validation #11 Pet time conflict
    _check_pet_time_conflict(pet_id, start_dt, end_dt)

    # Compute booking quote
    quote_cents = compute_booking_quote(
        service_type=service_type,
        sitter_tier=sitter["tier"],
        time_of_day=time_of_day,
        recurring_cadence=recurring_cadence,
        emergency_surcharge_cents=emergency_surcharge_cents,
    )

    # Validation #15 wallet sufficiency
    if wallet_credit_applied_cents > owner["wallet_credit_cents"]:
        raise ApiError(
            ERR_WALLET_INSUFFICIENT,
            "wallet_credit_applied_cents exceeds Owner.wallet_credit_cents.",
        )
    if wallet_credit_applied_cents > quote_cents:
        raise ApiError(
            ERR_WALLET_INSUFFICIENT,
            "wallet_credit_applied_cents exceeds booking_quote_cents.",
        )

    with db.lock:
        b = {
            **new_common_fields(),
            "owner_id": owner_id,
            "sitter_id": sitter_id,
            "pet_id": pet_id,
            "service_type": service_type,
            "time_of_day": time_of_day,
            "recurring_cadence": recurring_cadence,
            "start_at": db.fmt_ts(start_dt),
            "end_at": db.fmt_ts(end_dt),
            "status": "REQUESTED",
            "emergency_surcharge_cents": emergency_surcharge_cents,
            "booking_quote_cents": quote_cents,
            "provisional_sitter_payout_cents": 0,
            "final_sitter_payout_cents": 0,
            "tip_cents": 0,
            "incident_deduction_cents": 0,
            "owner_rating": None,
            "wallet_credit_applied_cents": wallet_credit_applied_cents,
            "cancellation_reason": None,
        }
        db.bookings[b["id"]] = b
        if wallet_credit_applied_cents > 0:
            owner["wallet_credit_cents"] -= wallet_credit_applied_cents
            bump(owner)
    return response.ok(booking_to_dict(b), status=201)


@bp.get("/api/v1/bookings/<bid>")
@require_auth(roles=["Owner", "Sitter", "PlatformAdmin", "ClaimsAdjuster"])
def get_booking(bid: str):
    b = get_booking_or_404(bid)
    return response.ok(booking_to_dict(b))


@bp.get("/api/v1/bookings")
@require_auth(roles=["Owner", "Sitter", "PlatformAdmin", "ClaimsAdjuster"])
def list_bookings():
    limit, offset = parse_pagination()
    owner_id = request.args.get("owner_id")
    sitter_id = request.args.get("sitter_id")
    pet_id = request.args.get("pet_id")
    status_filter = request.args.get("status")

    items = list(db.bookings.values())
    if owner_id is not None:
        items = [b for b in items if b["owner_id"] == owner_id]
    if sitter_id is not None:
        items = [b for b in items if b["sitter_id"] == sitter_id]
    if pet_id is not None:
        items = [b for b in items if b["pet_id"] == pet_id]
    if status_filter is not None:
        if status_filter not in _BOOKING_STATUSES:
            raise ApiError(ERR_INVALID_REQUEST, f"Invalid status filter: {status_filter}")
        items = [b for b in items if b["status"] == status_filter]
    items = sorted_by_created_at(items)
    page, total = paginate(items, limit, offset)
    return response.list_ok([booking_to_dict(b) for b in page], limit, offset, total)


@bp.post("/api/v1/bookings/<bid>/confirm")
@require_auth(roles=["Sitter"])
def confirm_booking(bid: str):
    b = get_booking_or_404(bid)
    if b["status"] != "REQUESTED":
        raise ApiError(ERR_INVALID_STATE, "Booking must be REQUESTED.")
    if db.utcnow() >= db.parse_ts(b["start_at"]):
        raise ApiError(ERR_INVALID_STATE, "Booking.start_at must be in the future.")

    # Validation: sitter cleared
    bc = bg_check_for_sitter(b["sitter_id"])
    if bc is None or bc["status"] != "CLEARED":
        raise ApiError(ERR_SITTER_NOT_CLEARED, "Sitter not cleared.")

    # Validation: MeetAndGreet + sitter active
    sitter = db.sitters.get(b["sitter_id"])
    if sitter is None or sitter["status"] != "ACTIVE":
        raise ApiError(ERR_MEET_AND_GREET_REQUIRED, "Sitter is not ACTIVE.")
    if not _has_completed_approved_mg(b["owner_id"], b["sitter_id"], b["pet_id"]):
        raise ApiError(
            ERR_MEET_AND_GREET_REQUIRED,
            "Booking requires a COMPLETED_APPROVED MeetAndGreet.",
        )

    with db.lock:
        b["status"] = "CONFIRMED"
        provisional = compute_sitter_payout_provisional(b["booking_quote_cents"])
        b["provisional_sitter_payout_cents"] = provisional
        bump(b)
        sitter["pending_payout_cents"] += provisional
        bump(sitter)
    return response.ok(booking_to_dict(b))


@bp.post("/api/v1/bookings/<bid>/reject")
@require_auth(roles=["Sitter"])
def reject_booking(bid: str):
    b = get_booking_or_404(bid)
    if b["status"] != "REQUESTED":
        raise ApiError(ERR_INVALID_STATE, "Booking must be REQUESTED to reject.")
    body = get_json_body()
    reason = require_str(body, "reason")

    with db.lock:
        b["status"] = "REJECTED"
        b["cancellation_reason"] = reason
        bump(b)
        # Restore applied credit
        owner = db.owners.get(b["owner_id"])
        if owner is not None and b["wallet_credit_applied_cents"] > 0:
            owner["wallet_credit_cents"] += b["wallet_credit_applied_cents"]
            bump(owner)
    return response.ok(booking_to_dict(b))


@bp.post("/api/v1/bookings/<bid>/cancel")
@require_auth(roles=["Owner"])
def cancel_booking(bid: str):
    b = get_booking_or_404(bid)

    if b["status"] not in ("REQUESTED", "CONFIRMED"):
        raise ApiError(ERR_INVALID_STATE, "Booking must be REQUESTED or CONFIRMED to cancel.")

    body = get_json_body()

    # OCC check for CONFIRMED-source cancel (required); not required for REQUESTED.
    if b["status"] == "CONFIRMED":
        if "expected_booking_version" not in body or body["expected_booking_version"] is None:
            raise ApiError(
                ERR_STALE_VERSION,
                "expected_booking_version required to cancel a CONFIRMED Booking.",
            )
        v = body["expected_booking_version"]
        if isinstance(v, bool) or not isinstance(v, int):
            raise ApiError(ERR_INVALID_REQUEST, "expected_booking_version must be an integer.")
        if v != b["version"]:
            raise ApiError(ERR_STALE_VERSION, "expected_booking_version does not match.")
    else:
        # REQUESTED — if expected_booking_version provided, ignore (no OCC required).
        # PRD §2.6: "REQUESTED" cancel does not require the field; we don't validate it.
        pass

    reason = require_str(body, "reason")

    with db.lock:
        original_status = b["status"]
        b["status"] = "CANCELLED"
        b["cancellation_reason"] = reason
        bump(b)
        owner = db.owners.get(b["owner_id"])
        sitter = db.sitters.get(b["sitter_id"])

        if original_status == "CONFIRMED":
            if sitter is not None:
                sitter["pending_payout_cents"] = max(
                    0, sitter["pending_payout_cents"] - b["provisional_sitter_payout_cents"]
                )
                bump(sitter)
            # Full refund as wallet credit (net: += booking_quote_cents)
            if owner is not None:
                owner["wallet_credit_cents"] += b["booking_quote_cents"]
                bump(owner)
        else:
            # REQUESTED-source cancel: restore applied credit only
            if owner is not None and b["wallet_credit_applied_cents"] > 0:
                owner["wallet_credit_cents"] += b["wallet_credit_applied_cents"]
                bump(owner)
    return response.ok(booking_to_dict(b))


@bp.post("/api/v1/bookings/<bid>/start")
@require_auth(roles=["Sitter"])
def start_booking(bid: str):
    b = get_booking_or_404(bid)
    if b["status"] != "KEY_RECEIVED":
        raise ApiError(ERR_INVALID_STATE, "Booking must be KEY_RECEIVED to start.")
    if db.utcnow() < db.parse_ts(b["start_at"]):
        raise ApiError(ERR_INVALID_STATE, "Cannot start before start_at.")
    with db.lock:
        b["status"] = "IN_PROGRESS"
        bump(b)
    return response.ok(booking_to_dict(b))


@bp.post("/api/v1/bookings/<bid>/complete")
@require_auth(roles=["Sitter"])
def complete_booking(bid: str):
    b = get_booking_or_404(bid)
    body = get_json_body()

    if b["status"] != "IN_PROGRESS":
        raise ApiError(ERR_INVALID_STATE, "Booking must be IN_PROGRESS to complete.")
    if db.utcnow() < db.parse_ts(b["end_at"]):
        raise ApiError(ERR_INVALID_STATE, "Cannot complete before end_at.")
    kh = key_handoff_for_booking(b["id"])
    if kh is None or kh["status"] != "RECEIVED":
        raise ApiError(
            ERR_INVALID_STATE,
            "KeyHandoff must exist and be RECEIVED to complete.",
        )

    tip_cents = optional_non_negative_int(body, "tip_cents", 0)
    incident_deduction_cents = optional_non_negative_int(body, "incident_deduction_cents", 0)

    # owner_rating optional, 1..5 or null
    owner_rating = None
    if "owner_rating" in body and body["owner_rating"] is not None:
        v = body["owner_rating"]
        if isinstance(v, bool) or not isinstance(v, int):
            raise ApiError(ERR_INVALID_REQUEST, "owner_rating must be an integer.")
        if v < 1 or v > 5:
            raise ApiError(ERR_INVALID_REQUEST, "owner_rating must be in [1, 5].")
        owner_rating = v

    with db.lock:
        # Flip KeyHandoff to RETURNED
        kh["status"] = "RETURNED"
        bump(kh)

        b["tip_cents"] = tip_cents
        b["incident_deduction_cents"] = incident_deduction_cents
        b["owner_rating"] = owner_rating
        final_payout = compute_sitter_payout_final(
            b["booking_quote_cents"], tip_cents, incident_deduction_cents
        )
        b["final_sitter_payout_cents"] = final_payout

        sitter = db.sitters.get(b["sitter_id"])
        if sitter is not None:
            sitter["pending_payout_cents"] = max(
                0, sitter["pending_payout_cents"] - b["provisional_sitter_payout_cents"]
            )
            sitter["pending_payout_cents"] += final_payout
            sitter["total_completed_bookings"] += 1
            if owner_rating is not None:
                sitter["total_rating_sum"] += owner_rating
                sitter["total_rating_count"] += 1
            # Trigger tier recompute (will bump or no-op depending on change)
            recompute_sitter_tier(sitter, force_bump=True)

        b["status"] = "COMPLETED"
        bump(b)
    return response.ok(booking_to_dict(b))


@bp.post("/api/v1/bookings/<bid>/emergency-terminate")
@require_auth(roles=["Sitter"])
def emergency_terminate_booking(bid: str):
    b = get_booking_or_404(bid)
    if b["status"] != "IN_PROGRESS":
        raise ApiError(ERR_INVALID_STATE, "Booking must be IN_PROGRESS to emergency-terminate.")
    body = get_json_body()
    reason = require_str(body, "reason")
    with db.lock:
        b["status"] = "EMERGENCY_TERMINATED"
        b["cancellation_reason"] = reason
        b["final_sitter_payout_cents"] = 0
        bump(b)
        sitter = db.sitters.get(b["sitter_id"])
        if sitter is not None:
            sitter["pending_payout_cents"] = max(
                0, sitter["pending_payout_cents"] - b["provisional_sitter_payout_cents"]
            )
            bump(sitter)
    return response.ok(booking_to_dict(b))
