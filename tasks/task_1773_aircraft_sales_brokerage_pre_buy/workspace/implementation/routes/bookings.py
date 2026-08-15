"""Inspection booking endpoints (PRD 3.7).

Create order: existence -> schema (incl. ERR_BOOKING_WINDOW_INVALID 422) ->
transaction ESCROW_FUNDED gate -> facility buffer conflict -> aircraft
overlap conflict.
"""
from flask import Blueprint

import db as dbmod
from errors import (
    ERR_AIRCRAFT_SLOT_CONFLICT,
    ERR_BOOKING_WINDOW_INVALID,
    ERR_FACILITY_SLOT_CONFLICT,
    ERR_INSPECTION_BOOKING_NOT_FOUND,
    ERR_INSPECTION_FACILITY_NOT_FOUND,
    ERR_INVALID_STATE,
    ERR_TRANSACTION_NOT_FOUND,
    ERR_TRANSACTION_NOT_FUNDED,
    raise_error,
)
from middleware import ALL_ROLES, require_roles
from response import success_object
from services.core import list_page, new_record, serialize, touch
from services.scheduling import (
    aircraft_slot_conflict,
    facility_slot_conflict,
    has_other_active_booking,
)
from validate import body, req_datetime, req_str

bp = Blueprint("bookings", __name__)


def _get_booking(booking_id):
    rec = dbmod.db["bookings"].get(booking_id)
    if rec is None:
        raise_error(ERR_INSPECTION_BOOKING_NOT_FOUND,
                    "inspection booking id does not exist")
    return rec


@bp.post("/api/inspection-bookings")
@require_roles(["FacilityScheduler"])
def create_booking():
    b = body()
    # Priority 3: body-referenced ids that are present must exist.
    if isinstance(b.get("transaction_id"), str):
        if b["transaction_id"] not in dbmod.db["transactions"]:
            raise_error(ERR_TRANSACTION_NOT_FOUND,
                        "transaction id does not exist")
    if isinstance(b.get("facility_id"), str):
        if b["facility_id"] not in dbmod.db["facilities"]:
            raise_error(ERR_INSPECTION_FACILITY_NOT_FOUND,
                        "inspection facility id does not exist")
    # Priority 4: schema, then window well-formedness.
    tx_id = req_str(b, "transaction_id")
    facility_id = req_str(b, "facility_id")
    start_raw, start = req_datetime(b, "start_at")
    end_raw, end = req_datetime(b, "end_at")
    if not end > start:
        raise_error(
            ERR_BOOKING_WINDOW_INVALID,
            "booking end_at must be strictly after start_at",
        )
    tx = dbmod.db["transactions"].get(tx_id)
    facility = dbmod.db["facilities"].get(facility_id)
    if tx is None:
        raise_error(ERR_TRANSACTION_NOT_FOUND, "transaction id does not exist")
    if facility is None:
        raise_error(ERR_INSPECTION_FACILITY_NOT_FOUND,
                    "inspection facility id does not exist")
    # Priority 5(b): only an escrow-funded aircraft may be scheduled.
    if tx["status"] != "ESCROW_FUNDED":
        raise_error(
            ERR_TRANSACTION_NOT_FUNDED,
            "inspection booking requires the transaction to be ESCROW_FUNDED",
        )
    # Priority 7: facility buffer rule first, aircraft rule second.
    if facility_slot_conflict(facility, start, end):
        raise_error(
            ERR_FACILITY_SLOT_CONFLICT,
            "booking window conflicts with the facility turnaround buffer",
        )
    if aircraft_slot_conflict(tx["listing_id"], start, end):
        raise_error(
            ERR_AIRCRAFT_SLOT_CONFLICT,
            "booking window overlaps another booking for the same aircraft",
        )
    rec = new_record(
        "bookings",
        {
            "transaction_id": tx_id,
            "facility_id": facility_id,
            "start_at": start_raw,
            "end_at": end_raw,
            "status": "REQUESTED",
        },
    )
    rec["_start_dt"] = start
    rec["_end_dt"] = end
    return success_object(serialize("bookings", rec), 201)


@bp.get("/api/inspection-bookings")
@require_roles(ALL_ROLES)
def list_bookings():
    return list_page(
        "bookings", ["transaction_id", "facility_id", "status"]
    )


@bp.get("/api/inspection-bookings/<booking_id>")
@require_roles(ALL_ROLES)
def get_booking(booking_id):
    return success_object(serialize("bookings", _get_booking(booking_id)))


@bp.post("/api/inspection-bookings/<booking_id>/confirm")
@require_roles(["FacilityScheduler"])
def confirm_booking(booking_id):
    bk = _get_booking(booking_id)
    if bk["status"] != "REQUESTED":
        raise_error(
            ERR_INVALID_STATE, "only a REQUESTED booking can be confirmed"
        )
    tx = dbmod.db["transactions"].get(bk["transaction_id"])
    if tx is None or tx["status"] not in ("ESCROW_FUNDED", "INSPECTION_SCHEDULED"):
        raise_error(
            ERR_TRANSACTION_NOT_FUNDED,
            "confirmation requires the transaction to be ESCROW_FUNDED or "
            "INSPECTION_SCHEDULED",
        )
    bk["status"] = "CONFIRMED"
    touch(bk)
    if tx["status"] == "ESCROW_FUNDED":
        tx["status"] = "INSPECTION_SCHEDULED"
        touch(tx)
    return success_object(serialize("bookings", bk))


@bp.post("/api/inspection-bookings/<booking_id>/complete")
@require_roles(["FacilityScheduler"])
def complete_booking(booking_id):
    bk = _get_booking(booking_id)
    if bk["status"] != "CONFIRMED":
        raise_error(
            ERR_INVALID_STATE, "only a CONFIRMED booking can be completed"
        )
    tx = dbmod.db["transactions"].get(bk["transaction_id"])
    if tx is None or tx["status"] != "INSPECTION_SCHEDULED":
        raise_error(
            ERR_TRANSACTION_NOT_FUNDED,
            "completion requires the transaction to be INSPECTION_SCHEDULED",
        )
    bk["status"] = "COMPLETED"
    touch(bk)
    if not has_other_active_booking(tx["id"], bk["id"]):
        tx["status"] = "INSPECTION_COMPLETE"
        touch(tx)
    return success_object(serialize("bookings", bk))


@bp.post("/api/inspection-bookings/<booking_id>/cancel")
@require_roles(["FacilityScheduler"])
def cancel_booking(booking_id):
    bk = _get_booking(booking_id)
    if bk["status"] not in ("REQUESTED", "CONFIRMED"):
        raise_error(
            ERR_INVALID_STATE,
            "only a REQUESTED or CONFIRMED booking can be cancelled",
        )
    tx = dbmod.db["transactions"].get(bk["transaction_id"])
    bk["status"] = "CANCELLED"
    touch(bk)
    if (
        tx is not None
        and tx["status"] == "INSPECTION_SCHEDULED"
        and not has_other_active_booking(tx["id"], bk["id"])
    ):
        tx["status"] = "ESCROW_FUNDED"
        touch(tx)
    return success_object(serialize("bookings", bk))
