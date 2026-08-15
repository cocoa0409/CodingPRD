"""Operator routes: create/list/get (PRD 3.1)."""
from flask import Blueprint, request

import db
from envelope import success
from errors import ApiError, ERR_NOT_FOUND, ERR_DUPLICATE_EMPLOYEE_CODE
from helpers import (
    body, bad, req_str, opt_bool, paginate, EMPLOYEE_CODE_RE, CERTS,
)
from middleware import require_roles
from serializers import ser_operator

bp = Blueprint("operators", __name__)

OPERATOR_READ_ROLES = (
    "UtilityAdmin", "OperationsSupervisor", "OnCallOperator", "MaintenancePlanner",
)


@bp.post("/operators")
def create_operator():
    require_roles("UtilityAdmin")
    b = body()
    # business constraint (priority 14): format + uniqueness
    code = b.get("employee_code")
    if code is not None:
        if not isinstance(code, str) or not EMPLOYEE_CODE_RE.match(code):
            raise ApiError(
                ERR_DUPLICATE_EMPLOYEE_CODE, 422,
                "employee_code must match ^OP-[0-9]{4}$",
            )
        for o in db.operators.values():
            if o["employee_code"] == code:
                raise ApiError(
                    ERR_DUPLICATE_EMPLOYEE_CODE, 422,
                    "employee_code %s already exists" % code,
                )
    # shape (priority 30)
    if code is None:
        bad("employee_code is required")
    name = req_str(b, "full_name")
    certs = b.get("certifications")
    if not isinstance(certs, list):
        bad("certifications must be an array")
    for c in certs:
        if not isinstance(c, str) or c not in CERTS:
            bad("certifications entries must be one of %s" % ", ".join(CERTS))
    zone = req_str(b, "home_zone")
    active = opt_bool(b, "is_active", True)
    op = {
        "id": db.new_id(),
        "employee_code": code,
        "full_name": name,
        "certifications": list(certs),
        "home_zone": zone,
        "is_active": active,
        "_dispatch_times": [],
    }
    db.stamp(op)
    db.operators[op["id"]] = op
    return success(ser_operator(op), 201)


@bp.get("/operators")
def list_operators():
    require_roles(*OPERATOR_READ_ROLES)
    items = list(db.operators.values())
    active = request.args.get("is_active")
    if active is not None:
        if active.lower() in ("true", "1"):
            items = [o for o in items if o["is_active"]]
        elif active.lower() in ("false", "0"):
            items = [o for o in items if not o["is_active"]]
        else:
            bad("is_active must be true or false")
    zone = request.args.get("home_zone")
    if zone is not None:
        items = [o for o in items if o["home_zone"] == zone]
    page, meta = paginate(items)
    return success([ser_operator(o) for o in page], 200, meta)


@bp.get("/operators/<oid>")
def get_operator(oid):
    require_roles(*OPERATOR_READ_ROLES)
    op = db.operators.get(oid)
    if op is None:
        raise ApiError(ERR_NOT_FOUND, 404, "Operator not found")
    return success(ser_operator(op))
