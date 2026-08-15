"""Technician endpoints."""
from flask import Blueprint

import store
from auth import authenticate, authorize, ALL_ROLES
from errors import raise_err, ERR_INVALID_REQUEST, ERR_NOT_FOUND, ERR_INVALID_STATE
from util import (
    body_json, req_str, new_record, bump, success_object, get_or_404,
)
import services

bp = Blueprint("technicians", __name__)


@bp.post("/fleet/technicians")
def create_technician():
    _, role = authenticate()
    authorize(role, ["ServiceDispatcher"])
    body = body_json()
    full_name = req_str(body, "full_name")
    home_branch = req_str(body, "home_branch")
    van_stock_raw = body.get("van_stock", [])
    if van_stock_raw is None:
        van_stock_raw = []
    if not isinstance(van_stock_raw, list):
        raise_err(ERR_INVALID_REQUEST, "van_stock must be a list")
    van_stock = []
    for entry in van_stock_raw:
        if not isinstance(entry, dict):
            raise_err(ERR_INVALID_REQUEST, "each van_stock entry must be an object")
        pn = entry.get("part_number")
        qty = entry.get("qty")
        if not isinstance(pn, str):
            raise_err(ERR_INVALID_REQUEST, "part_number must be a string")
        if not isinstance(qty, int) or isinstance(qty, bool) or qty < 0:
            raise_err(ERR_INVALID_REQUEST, "qty must be an integer >= 0")
        van_stock.append({"part_number": pn, "qty": qty})
    rec = new_record()
    rec.update({
        "full_name": full_name,
        "home_branch": home_branch,
        "van_stock": van_stock,
        "status": "ACTIVE",
    })
    store.technicians[rec["id"]] = rec
    return success_object(services.serialize_technician(rec), 201)


@bp.get("/fleet/technicians/<tid>")
def get_technician(tid):
    _, role = authenticate()
    authorize(role, ALL_ROLES)
    t = get_or_404(store.technicians, tid, "Technician")
    return success_object(services.serialize_technician(t), 200)


@bp.post("/fleet/technicians/<tid>/van-stock")
def restock_van(tid):
    _, role = authenticate()
    authorize(role, ["ServiceDispatcher"])
    body = body_json()
    part_number = req_str(body, "part_number")
    qty = body.get("qty")
    if not isinstance(qty, int) or isinstance(qty, bool):
        raise_err(ERR_INVALID_REQUEST, "qty must be an integer")
    if qty < 0:
        raise_err(ERR_INVALID_REQUEST, "qty must be >= 0")
    t = get_or_404(store.technicians, tid, "Technician")
    found = False
    for entry in t["van_stock"]:
        if entry["part_number"] == part_number:
            entry["qty"] += qty
            found = True
            break
    if not found:
        t["van_stock"].append({"part_number": part_number, "qty": qty})
    bump(t)
    return success_object(services.serialize_technician(t), 200)


@bp.post("/fleet/technicians/<tid>/deactivate")
def deactivate_technician(tid):
    _, role = authenticate()
    authorize(role, ["ServiceDispatcher"])
    t = get_or_404(store.technicians, tid, "Technician")
    if t["status"] != "ACTIVE":
        raise_err(ERR_INVALID_STATE, "Technician must be ACTIVE to deactivate")
    t["status"] = "INACTIVE"
    bump(t)
    return success_object(services.serialize_technician(t), 200)
