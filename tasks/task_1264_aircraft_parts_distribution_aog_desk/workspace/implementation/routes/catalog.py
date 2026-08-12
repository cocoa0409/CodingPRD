"""PartMaster and InventoryUnit endpoints."""

from flask import Blueprint, request

from auth import require_roles, ALL_BUSINESS
from calc import TRACE_RANK
from db import store
from errors import (ApiError, ERR_INVALID_REQUEST, ERR_PART_NOT_FOUND,
                    ERR_UNIT_NOT_FOUND, ERR_DUPLICATE_SERIAL)
from helpers import (new_record, touch, get_or_404, ser_part, ser_unit,
                     sort_asc)
from util import (success, get_body, page_params, paged, req_present, as_str,
                  as_int, as_bool, as_enum, bad)

bp = Blueprint("catalog", __name__)

HAZMAT_CLASSES = {"NONE", "CLASS_2", "CLASS_3", "CLASS_9"}
EXPORT_CODES = {"EAR99", "EAR9X610", "ITAR"}
CONDITIONS = {"NEW", "OVERHAULED", "SERVICEABLE", "AS_REMOVED"}
TRACE_LEVELS = set(TRACE_RANK.keys())


@bp.post("/aog/parts")
def create_part():
    require_roles("WarehouseOperator")
    body = get_body()
    part_number = as_str(req_present(body, "part_number"), "part_number")
    description = as_str(req_present(body, "description"), "description")
    rotable = as_bool(req_present(body, "rotable"), "rotable")
    list_price = as_int(req_present(body, "list_price_cents"),
                        "list_price_cents")
    if list_price <= 0:
        bad("list_price_cents must be > 0")
    hazmat = as_enum(body.get("hazmat_class", "NONE"), "hazmat_class",
                     HAZMAT_CLASSES)
    export_code = as_enum(body.get("export_control_code", "EAR99"),
                          "export_control_code", EXPORT_CODES)
    core_value = body.get("core_value_cents", 0)
    core_value = as_int(core_value, "core_value_cents")
    if rotable and core_value <= 0:
        bad("core_value_cents must be > 0 for rotable parts")
    if not rotable and core_value != 0:
        bad("core_value_cents must be 0 for non-rotable parts")
    warranty_months = as_int(body.get("warranty_months", 12),
                             "warranty_months")
    if warranty_months <= 0:
        bad("warranty_months must be > 0")
    for p in store["parts"].values():
        if p["part_number"] == part_number:
            raise ApiError(ERR_INVALID_REQUEST, 400,
                           "part_number must be unique")
    rec = new_record("parts", {
        "part_number": part_number,
        "description": description,
        "rotable": rotable,
        "hazmat_class": hazmat,
        "export_control_code": export_code,
        "list_price_cents": list_price,
        "core_value_cents": core_value,
        "warranty_months": warranty_months,
    })
    return success(ser_part(rec), 201)


@bp.get("/aog/parts")
def list_parts():
    require_roles(*ALL_BUSINESS)
    limit, offset = page_params()
    recs = list(store["parts"].values())
    q = request.args
    if q.get("part_number") is not None:
        recs = [p for p in recs if p["part_number"] == q.get("part_number")]
    return paged([ser_part(p) for p in sort_asc(recs)], limit, offset)


@bp.get("/aog/parts/<pid>")
def get_part(pid):
    require_roles(*ALL_BUSINESS)
    rec = get_or_404("parts", pid, ERR_PART_NOT_FOUND, "PartMaster")
    return success(ser_part(rec))


@bp.post("/aog/inventory-units")
def create_unit():
    require_roles("WarehouseOperator")
    body = get_body()
    part_id = as_str(req_present(body, "part_id"), "part_id")
    serial = as_str(req_present(body, "serial_number"), "serial_number")
    condition = as_enum(req_present(body, "condition"), "condition",
                        CONDITIONS)
    trace = as_enum(req_present(body, "trace_doc_level"), "trace_doc_level",
                    TRACE_LEVELS)
    warehouse = as_str(req_present(body, "warehouse_code"), "warehouse_code")
    get_or_404("parts", part_id, ERR_PART_NOT_FOUND, "PartMaster")
    for u in store["units"].values():
        if u["part_id"] == part_id and u["serial_number"] == serial:
            raise ApiError(ERR_DUPLICATE_SERIAL, 409,
                           "serial_number already exists for this part")
    rec = new_record("units", {
        "part_id": part_id,
        "serial_number": serial,
        "condition": condition,
        "trace_doc_level": trace,
        "warehouse_code": warehouse,
        "status": "AVAILABLE",
        "reserved_by_request_id": None,
    })
    return success(ser_unit(rec), 201)


@bp.get("/aog/inventory-units")
def list_units():
    require_roles(*ALL_BUSINESS)
    limit, offset = page_params()
    recs = list(store["units"].values())
    q = request.args
    if q.get("part_id") is not None:
        recs = [u for u in recs if u["part_id"] == q.get("part_id")]
    if q.get("status") is not None:
        recs = [u for u in recs if u["status"] == q.get("status")]
    if q.get("condition") is not None:
        recs = [u for u in recs if u["condition"] == q.get("condition")]
    if q.get("reserved_by_request_id") is not None:
        recs = [u for u in recs
                if u["reserved_by_request_id"] == q.get("reserved_by_request_id")]
    return paged([ser_unit(u) for u in sort_asc(recs)], limit, offset)


@bp.get("/aog/inventory-units/<uid>")
def get_unit(uid):
    require_roles(*ALL_BUSINESS)
    rec = get_or_404("units", uid, ERR_UNIT_NOT_FOUND, "InventoryUnit")
    return success(ser_unit(rec))


@bp.post("/aog/inventory-units/<uid>/certify-trace")
def certify_trace(uid):
    require_roles("ComplianceOfficer")
    unit = get_or_404("units", uid, ERR_UNIT_NOT_FOUND, "InventoryUnit")
    body = get_body()
    level = as_enum(req_present(body, "trace_doc_level"), "trace_doc_level",
                    TRACE_LEVELS)
    if TRACE_RANK[level] < TRACE_RANK[unit["trace_doc_level"]]:
        raise ApiError(ERR_INVALID_REQUEST, 400,
                       "trace_doc_level downgrade is not allowed")
    unit["trace_doc_level"] = level
    touch(unit)
    return success(ser_unit(unit))
