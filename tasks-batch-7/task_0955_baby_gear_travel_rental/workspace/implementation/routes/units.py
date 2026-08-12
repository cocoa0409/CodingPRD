from flask import Blueprint, request

from db import bump, create_rec, sorted_ords, store
from errors import ApiError
from middleware import body, require_roles
from response import ok_obj, paginate
from serialize import ser_ticket, ser_unit
from validate import req_enum, req_str

bp = Blueprint("units", __name__)

GRADES = ("A", "B", "C")


def _get_unit(uid):
    u = store.units.get(uid)
    if u is None:
        raise ApiError("ERR_UNIT_NOT_FOUND", 404, "Inventory unit not found")
    return u


@bp.post("/inventory-units")
def create_unit():
    require_roles("OperationsAdmin")
    b = body()
    item_id = b.get("catalog_item_id")
    if not isinstance(item_id, str) or not item_id.strip():
        raise ApiError("ERR_INVALID_REQUEST", 400, "catalog_item_id is required")
    if item_id not in store.catalog_items:
        raise ApiError("ERR_CATALOG_ITEM_NOT_FOUND", 404, "Catalog item not found")
    serial = req_str(b, "serial_number")
    grade = req_enum(b, "condition_grade", GRADES)
    if any(u["serial_number"] == serial for u in store.units.values()):
        raise ApiError("ERR_INVALID_REQUEST", 400, "serial_number must be unique across units")
    rec = create_rec(store.units, {
        "catalog_item_id": item_id, "serial_number": serial,
        "condition_grade": grade, "status": "AVAILABLE",
        "cleans_since_deep": 0, "blocked_until": None})
    return ok_obj(ser_unit(rec), 201)


@bp.get("/inventory-units/<uid>")
def get_unit(uid):
    require_roles("Inspector", "OperationsAdmin")
    return ok_obj(ser_unit(_get_unit(uid)))


@bp.get("/inventory-units")
def list_units():
    require_roles("Inspector", "OperationsAdmin")
    recs = sorted_ords(list(store.units.values()))
    item_id = request.args.get("catalog_item_id")
    if item_id is not None:
        recs = [u for u in recs if u["catalog_item_id"] == item_id]
    status = request.args.get("status")
    if status is not None:
        recs = [u for u in recs if u["status"] == status]
    return paginate(recs, ser_unit)


@bp.post("/inventory-units/<uid>/retire")
def retire_unit(uid):
    require_roles("OperationsAdmin")
    u = _get_unit(uid)
    if u["status"] not in ("AVAILABLE", "QUARANTINED"):
        raise ApiError("ERR_INVALID_STATE", 409,
                       "Only AVAILABLE or QUARANTINED units may be retired")
    u["status"] = "RETIRED"
    bump(u)
    return ok_obj(ser_unit(u))


@bp.get("/inventory-units/<uid>/cleaning-tickets")
def unit_tickets(uid):
    require_roles("Inspector", "OperationsAdmin")
    u = _get_unit(uid)
    recs = sorted_ords([t for t in store.tickets.values() if t["unit_id"] == u["id"]])
    status = request.args.get("status")
    if status is not None:
        recs = [t for t in recs if t["status"] == status]
    return paginate(recs, ser_ticket)
