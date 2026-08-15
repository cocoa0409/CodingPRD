"""Track rights agreements: create/get/events(ACTIVATE|TERMINATE)/list slots."""
from flask import Blueprint

import db
from auth import ALL_ROLES, require_event_role, require_roles
from db import new_entity, public, touch
from envelope import success_list, success_obj
from errors import ApiError, ERR_INVALID_STATE, ERR_NOT_FOUND, ERR_VALIDATION
from services.core import terminate_agreement
from validators import body, paginate, pagination, req_date, req_int, req_str

bp = Blueprint("agreements", __name__)

EVENT_ROLES = {"ACTIVATE": ("Scheduler",), "TERMINATE": ("OperationsManager",)}


def get_agreement_or_404(agreement_id):
    agreement = db.agreements.get(agreement_id)
    if agreement is None:
        raise ApiError(ERR_NOT_FOUND, "Agreement not found", 404)
    return agreement


@bp.post("/railroad/agreements")
def create_agreement():
    require_roles("Scheduler")
    data = body()
    host = req_str(data, "host_railroad_name")
    subdivision = req_str(data, "subdivision_code")
    valid_from = req_date(data, "valid_from")
    valid_until = req_date(data, "valid_until")
    max_trains = req_int(data, "max_trains_per_day")
    min_slot = req_int(data, "min_slot_minutes")
    if valid_until < valid_from:
        raise ApiError(
            ERR_VALIDATION, "valid_until must be on or after valid_from", 400
        )
    if max_trains < 1:
        raise ApiError(ERR_VALIDATION, "max_trains_per_day must be at least 1", 400)
    if min_slot < 30:
        raise ApiError(ERR_VALIDATION, "min_slot_minutes must be at least 30", 400)
    agreement = new_entity(
        {
            "host_railroad_name": host,
            "subdivision_code": subdivision,
            "valid_from": valid_from,
            "valid_until": valid_until,
            "max_trains_per_day": max_trains,
            "min_slot_minutes": min_slot,
            "status": "DRAFT",
        }
    )
    db.agreements[agreement["id"]] = agreement
    return success_obj(public(agreement), 201)


@bp.get("/railroad/agreements/<aid>")
def get_agreement(aid):
    require_roles(*ALL_ROLES)
    return success_obj(public(get_agreement_or_404(aid)), 200)


@bp.get("/railroad/agreements/<aid>/slots")
def list_agreement_slots(aid):
    require_roles(*ALL_ROLES)
    agreement = get_agreement_or_404(aid)
    items = [s for s in db.slots.values() if s["agreement_id"] == agreement["id"]]
    limit, offset = pagination()
    page, total = paginate(items, limit, offset)
    return success_list([public(s) for s in page], limit, offset, total)


@bp.post("/railroad/agreements/<aid>/events")
def agreement_event(aid):
    data = body()
    require_event_role(data, EVENT_ROLES, ("Scheduler", "OperationsManager"))
    agreement = get_agreement_or_404(aid)
    event_type = data.get("event_type")
    if event_type == "ACTIVATE":
        if agreement["status"] != "DRAFT":
            raise ApiError(
                ERR_INVALID_STATE,
                "Only a DRAFT agreement can be activated",
                409,
            )
        agreement["status"] = "ACTIVE"
        touch(agreement)
    elif event_type == "TERMINATE":
        if agreement["status"] not in ("DRAFT", "ACTIVE"):
            raise ApiError(
                ERR_INVALID_STATE, "Agreement is already terminated", 409
            )
        terminate_agreement(agreement)
    else:
        raise ApiError(
            ERR_VALIDATION, "Unknown event_type: %r" % event_type, 400
        )
    return success_obj(public(agreement), 200)
