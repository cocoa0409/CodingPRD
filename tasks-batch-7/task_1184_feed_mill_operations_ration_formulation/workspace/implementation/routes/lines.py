"""Production lines (PRD 3.6-3.7)."""
from flask import Blueprint

from db import STORE, make_record, bump
from envelope import success
from errors import ApiError
from middleware import authenticate, authorize
from services import ser_line
from validation import get_body, req_str, req_enum

bp = Blueprint("lines", __name__)

READ_ROLES = {"MillManager", "Nutritionist", "Operator", "QualityTech"}


def _get_line(lid):
    l = STORE["lines"].get(lid)
    if l is None:
        raise ApiError("ERR_NOT_FOUND", 404, f"ProductionLine {lid} not found")
    return l


@bp.post("/api/lines")
def create_line():
    uid, role = authenticate()
    data = get_body()
    code = req_str(data, "code")
    authorize(role, uid, {"MillManager"})
    if any(l["code"] == code for l in STORE["lines"].values()):
        raise ApiError("ERR_DUPLICATE_CODE", 409, f"Line code {code!r} already exists")
    rec = make_record()
    rec.update(code=code, status="ACTIVE")
    STORE["lines"][rec["id"]] = rec
    return success(ser_line(rec), 201)


@bp.get("/api/lines/<lid>")
def get_line(lid):
    uid, role = authenticate()
    authorize(role, uid, READ_ROLES)
    return success(ser_line(_get_line(lid)), 200)


@bp.post("/api/lines/<lid>/set-status")
def set_line_status(lid):
    uid, role = authenticate()
    data = get_body()
    status = req_enum(data, "status", ("ACTIVE", "DOWN"))
    authorize(role, uid, {"MillManager"})
    l = _get_line(lid)
    if l["status"] == status:
        raise ApiError("ERR_INVALID_STATE", 409, f"Line is already {status}")
    l["status"] = status
    bump(l)
    return success(ser_line(l), 200)
