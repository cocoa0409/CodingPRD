from flask import Blueprint

from auth import authenticate, require_role
from db import store
from envelope import success_object
from errors import raise_err, ERR_SCHEDULE_SLOT_NOT_FOUND, \
    ERR_INVALID_STATE, ERR_ALREADY_TERMINAL
from services import touch, ser_schedule_slot
from validate import get_body, check_fields

bp = Blueprint("schedule_slots", __name__)

READ_ROLES = ["PlantAdmin", "ProcessEngineer", "ProductionScheduler"]


@bp.get("/schedule-slots/<sid>")
def get_slot(sid):
    _, role = authenticate()
    require_role(role, READ_ROLES)
    slot = store.schedule_slots.get(sid)
    if slot is None:
        raise_err(ERR_SCHEDULE_SLOT_NOT_FOUND,
                  "ScheduleSlot id does not resolve")
    return success_object(ser_schedule_slot(slot))


@bp.post("/schedule-slots/<sid>/cancel")
def cancel_slot(sid):
    _, role = authenticate()
    require_role(role, ["ProductionScheduler"])
    check_fields(get_body(), {})
    slot = store.schedule_slots.get(sid)
    if slot is None:
        raise_err(ERR_SCHEDULE_SLOT_NOT_FOUND,
                  "ScheduleSlot id does not resolve")
    if slot["status"] in ("COMPLETED", "CANCELLED"):
        raise_err(ERR_ALREADY_TERMINAL, "Slot is in a terminal state")
    if slot["status"] != "CONFIRMED":
        # IN_PROGRESS slots are cancelled by system cascades only
        raise_err(ERR_INVALID_STATE,
                  "Only a CONFIRMED slot can be cancelled directly")
    slot["status"] = "CANCELLED"
    touch(slot)
    return success_object(ser_schedule_slot(slot))
