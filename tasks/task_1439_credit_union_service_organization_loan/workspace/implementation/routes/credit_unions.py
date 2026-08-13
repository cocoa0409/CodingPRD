"""Credit unions & CUSOs (PRD 3.1)."""
from flask import Blueprint, request

import db
import serialize as ser
from errors import not_found, invalid_state, raise_err, ERR_INVALID_REQUEST
from middleware import (
    auth_context, require_role, body, req_str, req_int, opt_num, req_enum,
    touch, ALL_ROLES,
)
from response import success

bp = Blueprint("credit_unions", __name__)

CU_TYPES = {"ORIGINATOR", "BUYER", "DUAL"}
SERVICE_LINES = {"LENDING", "PAYMENTS", "COMPLIANCE", "TECHNOLOGY"}


@bp.post("/network/credit-unions")
def create_credit_union():
    uid, role = auth_context()
    require_role(role, {"NetworkAdmin"})
    b = body()
    charter = req_str(b, "charter_number")
    legal_name = req_str(b, "legal_name")
    cu_type = req_enum(b, "cu_type", CU_TYPES)
    total_assets = req_int(b, "total_assets_cents", minimum=1)
    net_worth = req_int(b, "net_worth_cents", minimum=1)
    cap = opt_num(b, "concentration_cap_pct", 0.25)
    if cap <= 0:
        raise_err(ERR_INVALID_REQUEST, "concentration_cap_pct must be positive")
    # charter_number is unique across the network
    for cu in db.credit_unions.values():
        if cu["charter_number"] == charter:
            raise_err(ERR_INVALID_REQUEST, "charter_number must be unique across the network")
    cu = db.insert("credit_union", {
        "charter_number": charter,
        "legal_name": legal_name,
        "cu_type": cu_type,
        "total_assets_cents": total_assets,
        "net_worth_cents": net_worth,
        "concentration_cap_pct": cap,
        "status": "ACTIVE",
    })
    return success(ser.credit_union(cu), 201)


@bp.get("/network/credit-unions/<cid>")
def get_credit_union(cid):
    auth_context()
    require_role(request.headers.get("X-User-Role"), set(ALL_ROLES))
    cu = db.credit_unions.get(cid)
    if cu is None:
        not_found("CreditUnion")
    return success(ser.credit_union(cu))


@bp.post("/network/credit-unions/<cid>/suspend")
def suspend_credit_union(cid):
    uid, role = auth_context()
    require_role(role, {"NetworkAdmin"})
    cu = db.credit_unions.get(cid)
    if cu is None:
        not_found("CreditUnion")
    if cu["status"] != "ACTIVE":
        invalid_state("CreditUnion must be ACTIVE to suspend")
    cu["status"] = "SUSPENDED"
    touch("credit_union", cu)
    return success(ser.credit_union(cu))


@bp.post("/network/credit-unions/<cid>/reinstate")
def reinstate_credit_union(cid):
    uid, role = auth_context()
    require_role(role, {"NetworkAdmin"})
    cu = db.credit_unions.get(cid)
    if cu is None:
        not_found("CreditUnion")
    if cu["status"] != "SUSPENDED":
        invalid_state("CreditUnion must be SUSPENDED to reinstate")
    cu["status"] = "ACTIVE"
    touch("credit_union", cu)
    return success(ser.credit_union(cu))


@bp.post("/network/cusos")
def create_cuso():
    uid, role = auth_context()
    require_role(role, {"NetworkAdmin"})
    b = body()
    legal_name = req_str(b, "legal_name")
    service_line = req_enum(b, "service_line", SERVICE_LINES)
    cuso = db.insert("cuso", {
        "legal_name": legal_name,
        "service_line": service_line,
        "status": "ACTIVE",
    })
    return success(ser.cuso(cuso), 201)


@bp.get("/network/cusos/<cid>")
def get_cuso(cid):
    auth_context()
    require_role(request.headers.get("X-User-Role"), set(ALL_ROLES))
    cuso = db.cusos.get(cid)
    if cuso is None:
        not_found("CUSO")
    return success(ser.cuso(cuso))
