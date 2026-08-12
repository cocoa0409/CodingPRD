"""Flush records: medicated carryover control under segregation of duties (PRD 3.7)."""
from flask import Blueprint, request

from db import STORE, make_record, bump, clock_now
from envelope import success
from errors import ApiError
from middleware import authenticate, authorize
from services import ser_flush, sorted_items, MIN_FLUSH_TONS
from validation import get_body, req_str, req_num, paginate

bp = Blueprint("flushes", __name__)

READ_ROLES = {"MillManager", "Operator", "QualityTech"}


def _get_flush(fid):
    f = STORE["flushes"].get(fid)
    if f is None:
        raise ApiError("ERR_NOT_FOUND", 404, f"FlushRecord {fid} not found")
    return f


@bp.post("/api/flush-records")
def create_flush():
    uid, role = authenticate()
    data = get_body()
    line_id = req_str(data, "line_id")
    material_id = req_str(data, "flush_material_ingredient_id")
    quantity = req_num(data, "quantity_tons", gt=__import__("decimal").Decimal("0"))
    authorize(role, uid, {"Operator"})
    if line_id not in STORE["lines"]:
        raise ApiError("ERR_NOT_FOUND", 404, f"ProductionLine {line_id} not found")
    material = STORE["ingredients"].get(material_id)
    if material is None:
        raise ApiError("ERR_NOT_FOUND", 404, f"Ingredient {material_id} not found")
    # Layer 9 in listed order: flush-material flag, then the quantity minimum.
    if not material["is_flush_material"]:
        raise ApiError("ERR_FLUSH_MATERIAL_INVALID", 422,
                       "Ingredient is not approved as flush material")
    if quantity < MIN_FLUSH_TONS:
        raise ApiError("ERR_FLUSH_QUANTITY_BELOW_MIN", 422,
                       "Flush quantity must be at least 0.5 tons")
    rec = make_record()
    rec.update(line_id=line_id, flush_material_ingredient_id=material_id,
               quantity_tons=quantity, recorded_by_employee_id=uid,
               verified_by_employee_id=None, verified_at=None, status="RECORDED")
    STORE["flushes"][rec["id"]] = rec
    return success(ser_flush(rec), 201)


@bp.get("/api/flush-records")
def list_flushes():
    uid, role = authenticate()
    authorize(role, uid, READ_ROLES)
    items = sorted_items(STORE["flushes"])
    line_id = request.args.get("line_id")
    material_id = request.args.get("flush_material_ingredient_id")
    status = request.args.get("status")
    if line_id is not None:
        items = [f for f in items if f["line_id"] == line_id]
    if material_id is not None:
        items = [f for f in items if f["flush_material_ingredient_id"] == material_id]
    if status is not None:
        items = [f for f in items if f["status"] == status]
    page, meta = paginate(items)
    return success([ser_flush(f) for f in page], 200, meta)


@bp.get("/api/flush-records/<fid>")
def get_flush(fid):
    uid, role = authenticate()
    authorize(role, uid, READ_ROLES)
    return success(ser_flush(_get_flush(fid)), 200)


@bp.post("/api/flush-records/<fid>/verify")
def verify_flush(fid):
    uid, role = authenticate()
    get_body()
    authorize(role, uid, {"Operator"})
    f = _get_flush(fid)
    if f["status"] != "RECORDED":
        raise ApiError("ERR_INVALID_STATE", 409, "Only a RECORDED flush can be verified")
    if uid == f["recorded_by_employee_id"]:
        raise ApiError("ERR_SOD_VIOLATION", 422,
                       "The recorder of a flush may not verify it")
    f["verified_by_employee_id"] = uid
    f["verified_at"] = clock_now()
    f["status"] = "VERIFIED"
    bump(f)
    return success(ser_flush(f), 200)


@bp.post("/api/flush-records/<fid>/reject")
def reject_flush(fid):
    uid, role = authenticate()
    get_body()
    authorize(role, uid, {"QualityTech"})
    f = _get_flush(fid)
    if f["status"] != "RECORDED":
        raise ApiError("ERR_INVALID_STATE", 409, "Only a RECORDED flush can be rejected")
    f["status"] = "REJECTED"
    bump(f)
    return success(ser_flush(f), 200)
