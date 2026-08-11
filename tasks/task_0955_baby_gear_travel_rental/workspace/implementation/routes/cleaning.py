from flask import Blueprint

from db import bump, create_rec, store
from errors import ApiError
from middleware import body, require_roles
from response import ok_obj
from serialize import ser_ticket
from validate import opt_str, req_enum

bp = Blueprint("cleaning", __name__)

TICKET_TYPES = ("STANDARD", "DEEP", "RECALL_DECONTAMINATION")


def _get_ticket(tid):
    t = store.tickets.get(tid)
    if t is None:
        raise ApiError("ERR_TICKET_NOT_FOUND", 404, "Cleaning ticket not found")
    return t


@bp.post("/cleaning-tickets")
def create_ticket():
    require_roles("Inspector", "OperationsAdmin")
    b = body()
    unit_id = b.get("unit_id")
    if not isinstance(unit_id, str) or not unit_id.strip():
        raise ApiError("ERR_INVALID_REQUEST", 400, "unit_id is required")
    unit = store.units.get(unit_id)
    if unit is None:
        raise ApiError("ERR_UNIT_NOT_FOUND", 404, "Inventory unit not found")
    ticket_type = req_enum(b, "ticket_type", TICKET_TYPES)
    # State preconditions (priority 6)
    if unit["status"] not in ("AWAITING_CLEANING", "QUARANTINED"):
        raise ApiError("ERR_INVALID_STATE", 409,
                       "Unit must be AWAITING_CLEANING or QUARANTINED")
    if any(t["unit_id"] == unit["id"] and t["status"] == "OPEN"
           for t in store.tickets.values()):
        raise ApiError("ERR_INVALID_STATE", 409,
                       "An OPEN cleaning ticket already exists for this unit")
    if ticket_type == "RECALL_DECONTAMINATION" and unit["status"] != "QUARANTINED":
        raise ApiError("ERR_INVALID_STATE", 409,
                       "RECALL_DECONTAMINATION is reserved for QUARANTINED units")
    # Structural (priority 10): a STANDARD clean may not skip a due deep clean
    if ticket_type == "STANDARD":
        item = store.catalog_items[unit["catalog_item_id"]]
        if unit["cleans_since_deep"] >= item["deep_clean_every_cycles"]:
            raise ApiError("ERR_DEEP_CLEAN_REQUIRED", 409,
                           "A DEEP clean is due for this unit")
    rec = create_rec(store.tickets, {
        "unit_id": unit["id"], "ticket_type": ticket_type, "status": "OPEN",
        "inspector_user_id": None, "resolution_note": None})
    if unit["status"] == "AWAITING_CLEANING":
        unit["status"] = "IN_CLEANING"
        bump(unit)
    return ok_obj(ser_ticket(rec), 201)


@bp.get("/cleaning-tickets/<tid>")
def get_ticket(tid):
    require_roles("Inspector", "OperationsAdmin")
    return ok_obj(ser_ticket(_get_ticket(tid)))


def _resolve(t, uid, passed):
    if t["status"] != "OPEN":
        raise ApiError("ERR_INVALID_STATE", 409, "Ticket is not OPEN")
    unit = store.units[t["unit_id"]]
    if t["ticket_type"] == "RECALL_DECONTAMINATION":
        if unit["status"] != "QUARANTINED":
            raise ApiError("ERR_INVALID_STATE", 409, "Unit is not QUARANTINED")
        if passed:
            unit["status"] = "AVAILABLE"
            unit["cleans_since_deep"] = 0
            unit["blocked_until"] = None
            bump(unit)
        # failed decontamination: unit stays QUARANTINED, no unit mutation
    else:
        if unit["status"] != "IN_CLEANING":
            raise ApiError("ERR_INVALID_STATE", 409, "Unit is not IN_CLEANING")
        if passed:
            unit["status"] = "AVAILABLE"
            if t["ticket_type"] == "STANDARD":
                unit["cleans_since_deep"] += 1
            else:  # DEEP
                unit["cleans_since_deep"] = 0
        else:
            unit["status"] = "AWAITING_CLEANING"  # cleans_since_deep unchanged
        bump(unit)
    b = body()
    note = opt_str(b, "resolution_note")
    t["status"] = "PASSED" if passed else "FAILED"
    t["inspector_user_id"] = uid
    if note is not None:
        t["resolution_note"] = note
    bump(t)
    return t


@bp.post("/cleaning-tickets/<tid>/pass")
def pass_ticket(tid):
    uid, _ = require_roles("Inspector")
    t = _get_ticket(tid)
    return ok_obj(ser_ticket(_resolve(t, uid, True)))


@bp.post("/cleaning-tickets/<tid>/fail")
def fail_ticket(tid):
    uid, _ = require_roles("Inspector")
    t = _get_ticket(tid)
    return ok_obj(ser_ticket(_resolve(t, uid, False)))
