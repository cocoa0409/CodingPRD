"""Packer slots (PRD §3.5)."""

from flask import Blueprint, request

from db import store
from errors import (
    conflict, malformed,
    ERR_INVALID_STATE_TRANSITION,
    ERR_DUPLICATE_SLOT,
    ERR_SLOT_HAS_ACTIVE_LOADS,
)
from middleware import (
    require_roles, ROLE_INTEGRATOR_ADMIN, ROLE_FIELD_TECH, ROLE_TRANSPORT_COORDINATOR,
)
from response import success_object, paginate
from services.core import new_record, touch, ser_packer_slot
from util import get_body, req, as_str, as_int, as_date, as_enum, load_or_404

bp = Blueprint("packer_slots", __name__)

ROLES_READ = [ROLE_INTEGRATOR_ADMIN, ROLE_FIELD_TECH, ROLE_TRANSPORT_COORDINATOR]
SHIFTS = {"AM", "PM"}


@bp.route("/packer-slots", methods=["POST"])
def create_packer_slot():
    require_roles([ROLE_INTEGRATOR_ADMIN])
    body = get_body()
    plant_code = as_str(req(body, "plant_code"), "plant_code")
    slot_date = as_date(req(body, "slot_date"), "slot_date")
    shift = as_enum(req(body, "shift"), "shift", SHIFTS)
    capacity_head = as_int(req(body, "capacity_head"), "capacity_head", 1)
    min_weight = as_int(req(body, "min_weight_lbs"), "min_weight_lbs", 0)
    max_weight = as_int(req(body, "max_weight_lbs"), "max_weight_lbs", 0)
    if max_weight < min_weight:
        raise malformed("max_weight_lbs must be >= min_weight_lbs")
    # (plant_code, slot_date, shift) must be unique (priority 11)
    for s in store.packer_slots.values():
        if (s["plant_code"] == plant_code and s["slot_date"] == slot_date
                and s["shift"] == shift):
            raise conflict(ERR_DUPLICATE_SLOT,
                           "A slot with this plant_code, slot_date, shift exists")
    rec = new_record()
    rec.update({
        "plant_code": plant_code, "slot_date": slot_date, "shift": shift,
        "capacity_head": capacity_head, "min_weight_lbs": min_weight,
        "max_weight_lbs": max_weight, "reserved_head": 0, "slot_status": "OPEN",
    })
    store.packer_slots[rec["id"]] = rec
    return success_object(ser_packer_slot(rec), 201)


@bp.route("/packer-slots", methods=["GET"])
def list_packer_slots():
    require_roles(ROLES_READ)
    plant_code = request.args.get("plant_code")
    slot_date = request.args.get("slot_date")
    status = request.args.get("slot_status")
    items = list(store.packer_slots.values())
    if plant_code is not None:
        items = [s for s in items if s["plant_code"] == plant_code]
    if slot_date is not None:
        items = [s for s in items if s["slot_date"].isoformat() == slot_date]
    if status is not None:
        items = [s for s in items if s["slot_status"] == status]
    return paginate(items, request.args, ser_packer_slot)


@bp.route("/packer-slots/<sid>", methods=["GET"])
def get_packer_slot(sid):
    require_roles(ROLES_READ)
    return success_object(ser_packer_slot(load_or_404(store.packer_slots, sid, "PackerSlot")))


@bp.route("/packer-slots/<sid>/close", methods=["POST"])
def close_packer_slot(sid):
    require_roles([ROLE_INTEGRATOR_ADMIN])
    slot = load_or_404(store.packer_slots, sid, "PackerSlot")
    if slot["slot_status"] not in ("OPEN", "FULL"):
        raise conflict(ERR_INVALID_STATE_TRANSITION,
                       f"Cannot close a slot in {slot['slot_status']}")
    for l in store.market_loads.values():
        if l["slot_id"] == sid and l["load_status"] in ("SCHEDULED", "DISPATCHED"):
            raise conflict(ERR_SLOT_HAS_ACTIVE_LOADS,
                           "Slot still has SCHEDULED or DISPATCHED loads")
    slot["slot_status"] = "CLOSED"
    touch(slot)
    return success_object(ser_packer_slot(slot))
