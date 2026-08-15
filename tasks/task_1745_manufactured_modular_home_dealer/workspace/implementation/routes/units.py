"""HomeUnit inventory (PRD 3.2) and factory completion."""

from flask import Blueprint, request

from db import bump, create_record, store
from errors import fail
from middleware import ALL_ROLES, require
from response import ok, ok_list
from services import get_or_404, lead_time_elapsed, ser
from validate import Shape, get_body, pagination_params

bp = Blueprint("units", __name__)

UNIT_KINDS = ["STOCK", "FACTORY_ORDER", "TRADE_IN"]
CONDITION_GRADES = ["NEW", "A", "B", "C"]


@bp.post("/home-units")
@require("DealershipAdmin")
def create_home_unit(actor_id, actor_role):
    shape = Shape(get_body())
    shape.req_str("model_id")
    shape.req_str("serial_number")
    shape.req_enum("unit_kind", UNIT_KINDS)
    shape.req_enum("condition_grade", CONDITION_GRADES)
    # (5) body FK existence
    model = None
    if shape.ok("model_id"):
        model = store.home_models.get(shape.value("model_id"))
        if model is None:
            fail("ERR_HOME_MODEL_NOT_FOUND", "Home model not found")
    # state rule: DISCONTINUED models cannot back new units
    if model is not None and model["status"] == "DISCONTINUED":
        fail("ERR_INVALID_STATE", "Model is DISCONTINUED")
    # (18) uniqueness: serial_number across all units
    if shape.ok("serial_number"):
        sn = shape.value("serial_number")
        if any(u["serial_number"] == sn for u in store.home_units.values()):
            fail("ERR_DUPLICATE_RESOURCE", "serial_number already registered")
    # TRADE_IN units are system-created via appraisal acceptance only
    if shape.ok("unit_kind") and shape.value("unit_kind") == "TRADE_IN":
        shape._err("unit_kind", "TRADE_IN units are created by trade-in appraisal acceptance")
    shape.raise_if_errors()
    unit_kind = shape.value("unit_kind")
    rec = create_record(store.home_units, {
        "model_id": shape.value("model_id"),
        "serial_number": shape.value("serial_number"),
        "unit_kind": unit_kind,
        "condition_grade": shape.value("condition_grade"),
        "status": "AT_FACTORY" if unit_kind == "FACTORY_ORDER" else "AT_DEALER",
        "lot_id": None,
        "sales_order_id": None,
        "delivered_at": None,
        "set_completed_at": None,
    })
    return ok(ser(rec), 201)


@bp.get("/home-units")
@require(*ALL_ROLES)
def list_home_units(actor_id, actor_role):
    filters = {}
    for k in ("model_id", "lot_id", "sales_order_id", "unit_kind", "status"):
        if request.args.get(k) is not None:
            filters[k] = request.args.get(k)
    limit, offset = pagination_params()
    rows = [u for u in store.home_units.values()
            if all(u.get(k) == v for k, v in filters.items())]
    rows.sort(key=lambda r: (r["created_at"], r["_seq"]))
    total = len(rows)
    return ok_list([ser(r) for r in rows[offset:offset + limit]], total, limit, offset)


@bp.get("/home-units/<rid>")
@require(*ALL_ROLES)
def get_home_unit(rid, actor_id, actor_role):
    return ok(ser(get_or_404(store.home_units, rid, "ERR_HOME_UNIT_NOT_FOUND", "Home unit")))


@bp.post("/home-units/<rid>/mark-ready")
@require("DealershipAdmin")
def mark_ready(rid, actor_id, actor_role):
    unit = get_or_404(store.home_units, rid, "ERR_HOME_UNIT_NOT_FOUND", "Home unit")
    # (7) state precondition: AT_FACTORY -> AT_DEALER for FACTORY_ORDER units
    if unit["unit_kind"] != "FACTORY_ORDER" or unit["status"] != "AT_FACTORY":
        fail("ERR_INVALID_STATE", "Unit is not a FACTORY_ORDER unit awaiting completion")
    # (23) production lead time
    model = store.home_models.get(unit["model_id"])
    if model is not None and not lead_time_elapsed(unit, model):
        fail("ERR_PRODUCTION_INCOMPLETE", "Factory lead time has not elapsed")
    unit["status"] = "AT_DEALER"
    bump(unit)
    return ok(ser(unit))
