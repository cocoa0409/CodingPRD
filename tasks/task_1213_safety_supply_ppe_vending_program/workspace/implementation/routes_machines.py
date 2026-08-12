"""Machine estate routes: vending machines, planogram slots, serialized units."""
from datetime import timedelta

from flask import Blueprint, g

import db
from auth import require_roles
from envelope import ok, ok_list
from errors import err
from helpers import (body, get_or_404, opt_int, opt_str, paged,
                     pagination_params, qparam, req_date, req_enum, req_int,
                     req_str, req_version_token)
from util import new_record, parse_date, touch

bp = Blueprint("machines", __name__)

MACHINE_STATUSES = {"COMMISSIONING", "ACTIVE", "OFFLINE", "IN_SERVICE", "DECOMMISSIONED"}


# --- VendingMachine --------------------------------------------------------

@bp.post("/machines")
def create_machine():
    require_roles("VendingTechnician")
    b = body()
    location = req_str(b, "location_code")
    site = req_str(b, "site_name")
    model = req_str(b, "model")
    if any(m["location_code"] == location for m in db.machines.values()):
        err("ERR_DUPLICATE_MACHINE_LOCATION", "location_code already exists")
    rec = new_record({
        "location_code": location,
        "site_name": site,
        "model": model,
        "status": "COMMISSIONING",
    })
    db.machines[rec["id"]] = rec
    return ok(rec, 201)


@bp.get("/machines")
def list_machines():
    require_roles("Any")
    limit, offset = pagination_params()
    rows = list(db.machines.values())
    st = qparam("status")
    if st is not None:
        rows = [m for m in rows if m["status"] == st]
    page, total = paged(rows, limit, offset)
    return ok_list(page, limit, offset, total)


@bp.get("/machines/<machineId>")
def get_machine(machineId):
    require_roles("Any")
    return ok(get_or_404(db.machines, machineId, "ERR_MACHINE_NOT_FOUND"))


@bp.put("/machines/<machineId>")
def update_machine(machineId):
    require_roles("VendingTechnician")
    b = body()
    status = req_enum(b, "status", MACHINE_STATUSES)
    machine = get_or_404(db.machines, machineId, "ERR_MACHINE_NOT_FOUND")
    cur = machine["status"]
    if status == "ACTIVE":
        if cur == "COMMISSIONING":
            if not any(s["machine_id"] == machineId for s in db.slots.values()):
                err("ERR_MACHINE_NO_PLANOGRAM",
                    "commission requires at least one planogram slot")
        elif cur == "OFFLINE":
            pass
        else:
            err("ERR_INVALID_STATE", "machine transition %s -> ACTIVE not allowed" % cur)
    elif status == "OFFLINE":
        if cur != "ACTIVE":
            err("ERR_INVALID_STATE", "machine transition %s -> OFFLINE not allowed" % cur)
    elif status == "DECOMMISSIONED":
        if cur not in ("ACTIVE", "OFFLINE"):
            err("ERR_INVALID_STATE",
                "machine transition %s -> DECOMMISSIONED not allowed" % cur)
        if any(o["machine_id"] == machineId and o["status"] in ("SUGGESTED", "PICKED")
               for o in db.restock_orders.values()):
            err("ERR_OPEN_RESTOCK_ORDERS_EXIST",
                "decommission blocked by open restock orders")
        if any(t["machine_id"] == machineId and t["status"] in ("OPEN", "IN_PROGRESS")
               for t in db.service_tickets.values()):
            err("ERR_OPEN_SERVICE_TICKETS_EXIST",
                "decommission blocked by open service tickets")
    else:
        err("ERR_INVALID_STATE", "unsupported machine status target %s" % status)
    machine["status"] = status
    touch(machine)
    return ok(machine)


# --- MachineSlot -----------------------------------------------------------

@bp.post("/machines/<machineId>/slots")
def create_slot(machineId):
    require_roles("VendingTechnician")
    b = body()
    slot_code = req_str(b, "slot_code")
    item_id = req_str(b, "item_id")
    capacity = req_int(b, "capacity", minimum=1)
    par_level = req_int(b, "par_level", minimum=0)
    if par_level >= capacity:
        err("ERR_VALIDATION_FAILED", "par_level must be < capacity")
    expected = req_version_token(b, "expected_machine_version")
    machine = get_or_404(db.machines, machineId, "ERR_MACHINE_NOT_FOUND")
    item = get_or_404(db.items, item_id, "ERR_ITEM_NOT_FOUND")
    if expected != machine["version"]:
        err("ERR_STALE_VERSION", "expected_machine_version does not match")
    if machine["status"] not in ("COMMISSIONING", "ACTIVE", "IN_SERVICE"):
        err("ERR_MACHINE_NOT_ACTIVE",
            "slot create requires machine COMMISSIONING, ACTIVE or IN_SERVICE")
    if item["status"] != "ACTIVE":
        err("ERR_ITEM_DISCONTINUED", "item is DISCONTINUED")
    if any(s["machine_id"] == machineId and s["slot_code"] == slot_code
           for s in db.slots.values()):
        err("ERR_DUPLICATE_SLOT_CODE", "slot_code already exists on this machine")
    rec = new_record({
        "machine_id": machineId,
        "slot_code": slot_code,
        "item_id": item_id,
        "capacity": capacity,
        "par_level": par_level,
        "on_hand_qty": 0,
    })
    db.slots[rec["id"]] = rec
    touch(machine)  # slot creation advances the parent machine version
    return ok(rec, 201)


@bp.get("/machines/<machineId>/slots")
def list_machine_slots(machineId):
    require_roles("Any")
    get_or_404(db.machines, machineId, "ERR_MACHINE_NOT_FOUND")
    limit, offset = pagination_params()
    rows = [s for s in db.slots.values() if s["machine_id"] == machineId]
    page, total = paged(rows, limit, offset)
    return ok_list(page, limit, offset, total)


@bp.get("/slots")
def list_slots():
    require_roles("Any")
    limit, offset = pagination_params()
    rows = list(db.slots.values())
    it = qparam("item_id")
    mc = qparam("machine_id")
    if it is not None:
        rows = [s for s in rows if s["item_id"] == it]
    if mc is not None:
        rows = [s for s in rows if s["machine_id"] == mc]
    page, total = paged(rows, limit, offset)
    return ok_list(page, limit, offset, total)


@bp.get("/slots/<slotId>")
def get_slot(slotId):
    require_roles("Any")
    return ok(get_or_404(db.slots, slotId, "ERR_SLOT_NOT_FOUND"))


@bp.put("/slots/<slotId>")
def update_slot(slotId):
    require_roles("VendingTechnician")
    b = body()
    item_id = opt_str(b, "item_id")
    capacity = opt_int(b, "capacity", minimum=1)
    par_level = opt_int(b, "par_level", minimum=0)
    expected = req_version_token(b, "expected_slot_version")
    slot = get_or_404(db.slots, slotId, "ERR_SLOT_NOT_FOUND")
    if item_id is not None:
        get_or_404(db.items, item_id, "ERR_ITEM_NOT_FOUND")
    # merged-range shape check on the resulting slot
    new_capacity = capacity if capacity is not None else slot["capacity"]
    new_par = par_level if par_level is not None else slot["par_level"]
    if new_par >= new_capacity:
        err("ERR_VALIDATION_FAILED", "par_level must be < capacity")
    if expected != slot["version"]:
        err("ERR_STALE_VERSION", "expected_slot_version does not match")
    machine = db.machines.get(slot["machine_id"])
    if machine is None or machine["status"] not in ("COMMISSIONING", "IN_SERVICE"):
        err("ERR_MACHINE_NOT_ACTIVE",
            "slot edits require machine COMMISSIONING or IN_SERVICE")
    if new_capacity < slot["on_hand_qty"]:
        err("ERR_CAPACITY_EXCEEDED", "capacity may not shrink below on_hand_qty")
    if item_id is not None:
        slot["item_id"] = item_id
    if capacity is not None:
        slot["capacity"] = capacity
    if par_level is not None:
        slot["par_level"] = par_level
    touch(slot)
    return ok(slot)


# --- SerializedUnit --------------------------------------------------------

@bp.post("/serialized-units")
def create_unit():
    require_roles("EHSAdministrator")
    b = body()
    item_id = req_str(b, "item_id")
    serial = req_str(b, "serial_number")
    slot_id = req_str(b, "slot_id")
    slot = get_or_404(db.slots, slot_id, "ERR_SLOT_NOT_FOUND")
    item = get_or_404(db.items, item_id, "ERR_ITEM_NOT_FOUND")
    machine = db.machines.get(slot["machine_id"])
    if machine is None or machine["status"] not in ("COMMISSIONING", "ACTIVE"):
        err("ERR_MACHINE_NOT_ACTIVE",
            "unit registration requires machine COMMISSIONING or ACTIVE")
    if item["status"] != "ACTIVE":
        err("ERR_ITEM_DISCONTINUED", "item is DISCONTINUED")
    if item["category"] != "FALL_PROTECTION":
        err("ERR_ITEM_NOT_SERIALIZED_CATEGORY",
            "serialized units require a FALL_PROTECTION item")
    if slot["item_id"] != item_id:
        err("ERR_SLOT_ITEM_MISMATCH", "slot holds a different item")
    if slot["on_hand_qty"] + 1 > slot["capacity"]:
        err("ERR_CAPACITY_EXCEEDED", "registration would exceed slot capacity")
    if any(u["serial_number"] == serial for u in db.units.values()):
        err("ERR_DUPLICATE_SERIAL_NUMBER", "serial_number already exists")
    rec = new_record({
        "item_id": item_id,
        "serial_number": serial,
        "slot_id": slot_id,
        "issued_to_employee_id": None,
        "last_inspected_on": None,
        "next_inspection_due_on": None,
        "inspection_log": [],
        "status": "IN_STOCK",
    })
    db.units[rec["id"]] = rec
    slot["on_hand_qty"] += 1
    touch(slot)
    return ok(rec, 201)


@bp.get("/serialized-units")
def list_units():
    require_roles("Any")
    limit, offset = pagination_params()
    rows = list(db.units.values())
    it = qparam("item_id")
    sl = qparam("slot_id")
    holder = qparam("issued_to_employee_id")
    st = qparam("status")
    if it is not None:
        rows = [u for u in rows if u["item_id"] == it]
    if sl is not None:
        rows = [u for u in rows if u["slot_id"] == sl]
    if holder is not None:
        rows = [u for u in rows if u.get("issued_to_employee_id") == holder]
    if st is not None:
        rows = [u for u in rows if u["status"] == st]
    page, total = paged(rows, limit, offset)
    return ok_list(page, limit, offset, total)


@bp.get("/serialized-units/<unitId>")
def get_unit(unitId):
    require_roles("Any")
    return ok(get_or_404(db.units, unitId, "ERR_SERIALIZED_UNIT_NOT_FOUND"))


@bp.post("/serialized-units/<unitId>/inspect")
def inspect_unit(unitId):
    require_roles("SafetyOfficer")
    b = body()
    result = req_enum(b, "result", {"PASS", "FAIL"})
    inspected_on = req_date(b, "inspected_on")
    unit = get_or_404(db.units, unitId, "ERR_SERIALIZED_UNIT_NOT_FOUND")
    cur = unit["status"]
    if result == "PASS":
        if cur not in ("ISSUED", "INSPECTION_DUE"):
            err("ERR_SERIALIZED_UNIT_NOT_ISSUABLE",
                "PASS inspection requires ISSUED or INSPECTION_DUE")
        item = db.items.get(unit["item_id"])
        unit["last_inspected_on"] = inspected_on
        due = parse_date(inspected_on) + timedelta(days=item["inspection_interval_days"])
        unit["next_inspection_due_on"] = due.isoformat()
        unit["status"] = "ISSUED"
    else:  # FAIL
        if cur not in ("ISSUED", "INSPECTION_DUE", "IN_STOCK"):
            err("ERR_SERIALIZED_UNIT_NOT_ISSUABLE",
                "FAIL inspection not allowed from %s" % cur)
        if cur == "IN_STOCK":
            # incoming inspection rejection: unit leaves sellable stock
            slot = db.slots.get(unit["slot_id"])
            if slot is not None:
                slot["on_hand_qty"] -= 1
                touch(slot)
        unit["status"] = "QUARANTINED"  # issued_to retained for audit traceability
    unit["inspection_log"].append({
        "inspected_on": inspected_on,
        "result": result,
        "inspector_user_id": g.user_id,
    })
    touch(unit)
    return ok(unit)
