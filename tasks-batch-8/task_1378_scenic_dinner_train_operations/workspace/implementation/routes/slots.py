"""Operating slots: half-open minute-of-day windows under an ACTIVE agreement.
Temporal tier order: validity window -> overlap (adjacency allowed) -> daily cap."""
from flask import Blueprint

import db
from auth import ALL_ROLES, require_roles
from db import new_entity, public
from envelope import success_obj
from errors import (
    ApiError,
    ERR_AGREEMENT_NOT_ACTIVE,
    ERR_DAILY_TRAIN_CAP_REACHED,
    ERR_INVALID_REFERENCE,
    ERR_NOT_FOUND,
    ERR_SLOT_DURATION_TOO_SHORT,
    ERR_SLOT_OUTSIDE_AGREEMENT_WINDOW,
    ERR_SLOT_OVERLAP,
    ERR_VALIDATION,
)
from validators import body, req_date, req_int, req_str

bp = Blueprint("slots", __name__)


def get_slot_or_404(slot_id):
    slot = db.slots.get(slot_id)
    if slot is None:
        raise ApiError(ERR_NOT_FOUND, "Slot not found", 404)
    return slot


@bp.post("/railroad/slots")
def create_slot():
    require_roles("Scheduler")
    data = body()
    agreement_id = req_str(data, "agreement_id")
    # Referenced parent-state gate (tier 5): agreement must be ACTIVE.
    agreement = db.agreements.get(agreement_id)
    if agreement is not None and agreement["status"] != "ACTIVE":
        raise ApiError(
            ERR_AGREEMENT_NOT_ACTIVE,
            "Operating slots can only be created under an ACTIVE agreement",
            409,
        )
    service_date = req_date(data, "service_date")
    start_minute = req_int(data, "start_minute")
    end_minute = req_int(data, "end_minute")
    if not (0 <= start_minute <= 1439):
        raise ApiError(
            ERR_VALIDATION, "start_minute must be in 0..1439", 400
        )
    if not (1 <= end_minute <= 1440):
        raise ApiError(ERR_VALIDATION, "end_minute must be in 1..1440", 400)
    # Body FK existence (tier 7).
    if agreement is None:
        raise ApiError(ERR_INVALID_REFERENCE, "agreement_id does not exist", 422)
    # Shape tier (8h): duration floor.
    if end_minute - start_minute < agreement["min_slot_minutes"]:
        raise ApiError(
            ERR_SLOT_DURATION_TOO_SHORT,
            "Slot duration is shorter than the agreement's min_slot_minutes",
            422,
        )
    # Temporal tier: (a) validity window, (b) half-open overlap, (c) daily cap.
    if not (agreement["valid_from"] <= service_date <= agreement["valid_until"]):
        raise ApiError(
            ERR_SLOT_OUTSIDE_AGREEMENT_WINDOW,
            "service_date is outside the agreement validity window",
            422,
        )
    siblings = [
        s
        for s in db.slots.values()
        if s["agreement_id"] == agreement["id"]
        and s["service_date"] == service_date
        and s["status"] != "RELEASED"
    ]
    for s in siblings:
        if start_minute < s["end_minute"] and s["start_minute"] < end_minute:
            raise ApiError(
                ERR_SLOT_OVERLAP,
                "Slot overlaps another slot on the same agreement and date",
                409,
            )
    counted = [s for s in siblings if s["status"] in ("OPEN", "RESERVED", "CONSUMED")]
    if len(counted) >= agreement["max_trains_per_day"]:
        raise ApiError(
            ERR_DAILY_TRAIN_CAP_REACHED,
            "Daily train cap reached for this agreement and date",
            409,
        )
    slot = new_entity(
        {
            "agreement_id": agreement["id"],
            "service_date": service_date,
            "start_minute": start_minute,
            "end_minute": end_minute,
            "status": "OPEN",
        }
    )
    db.slots[slot["id"]] = slot
    return success_obj(public(slot), 201)


@bp.get("/railroad/slots/<sid>")
def get_slot(sid):
    require_roles(*ALL_ROLES)
    return success_obj(public(get_slot_or_404(sid)), 200)
