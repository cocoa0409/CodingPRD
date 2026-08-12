"""StageSlot routes (PRD 3.7) — buffered changeover on the single shared stage."""

from flask import Blueprint

from db import store
from errors import (ERR_INVALID_STATE, ERR_STAGE_CONFLICT, ERR_TIME_RANGE,
                    ApiError, conflict)
from middleware import require_roles
from response import ok_object
from routes.common import get_or_404, list_response
from services import stage_conflict
from util import json_body, new_record, parse_dt, req_enum, req_str, to_public, touch

bp = Blueprint("stage_slots", __name__)

SLOT_TYPES = ("LOAD_IN", "LOAD_OUT", "TECH", "PERFORMANCE_SLOT", "DRESS_ON_STAGE")
TARGET_STATES = ("LOCKED", "DONE", "CANCELLED")


@bp.post("/opera/stage-slots")
def create_slot():
    require_roles("TechnicalDirector")
    body = json_body()
    production_id = req_str(body, "production_id")
    slot_type = req_enum(body, "slot_type", SLOT_TYPES)
    starts_at = parse_dt(body.get("starts_at"), "starts_at")
    ends_at = parse_dt(body.get("ends_at"), "ends_at")
    if ends_at <= starts_at:
        raise ApiError(ERR_TIME_RANGE, 400, "ends_at must be strictly after starts_at")
    prod = get_or_404(store.productions, production_id, "Production")
    if stage_conflict(prod["id"], starts_at, ends_at):
        raise conflict(ERR_STAGE_CONFLICT,
                       "Slot violates the stage changeover buffer")
    rec = new_record(
        production_id=prod["id"],
        slot_type=slot_type,
        starts_at=starts_at,
        ends_at=ends_at,
        status="PLANNED",
    )
    store.stage_slots[rec["id"]] = rec
    return ok_object(to_public(rec), 201)


@bp.get("/opera/stage-slots")
def list_slots():
    require_roles("Any")
    return list_response(
        store.stage_slots.values(),
        [("production_id", "production_id"), ("slot_type", "slot_type"),
         ("status", "status")],
    )


@bp.get("/opera/stage-slots/<sid>")
def get_slot(sid):
    require_roles("Any")
    return ok_object(to_public(get_or_404(store.stage_slots, sid, "StageSlot")))


@bp.post("/opera/stage-slots/<sid>/transition")
def transition_slot(sid):
    require_roles("TechnicalDirector")
    body = json_body()
    to_state = req_enum(body, "to_state", TARGET_STATES)
    slot = get_or_404(store.stage_slots, sid, "StageSlot")
    cur = slot["status"]
    allowed = (cur == "PLANNED" and to_state in ("LOCKED", "CANCELLED")) or \
              (cur == "LOCKED" and to_state in ("DONE", "CANCELLED"))
    if not allowed:
        raise conflict(ERR_INVALID_STATE,
                       f"StageSlot cannot transition {cur} -> {to_state}")
    slot["status"] = to_state
    touch(slot)
    return ok_object(to_public(slot))
