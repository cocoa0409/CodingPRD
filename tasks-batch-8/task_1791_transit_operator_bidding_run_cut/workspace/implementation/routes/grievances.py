"""Grievance case endpoints: file, uphold (with OT_EQUALIZATION evidence), dismiss, withdraw."""
from flask import request, Blueprint

from db import db, mint, touch, ser
from errors import (
    ApiError,
    forbidden,
    invalid_state,
    validation,
    ERR_GRIEVANCE_PRECONDITION,
)
from helpers import (
    body_json,
    req_str,
    req_enum,
    req_field,
    opt_int,
    get_grievance_or_404,
    ref_operator_or_404,
    ref_period_or_404,
    paginated,
)
from middleware import authenticate, require_roles, READ_SO_OP_UR
from response import ok_obj

bp = Blueprint("grievances", __name__)

UR = ["UnionRep"]
CATEGORIES = ("OT_EQUALIZATION", "SENIORITY_BYPASS", "WORK_RULE_SPREAD", "PAY_VALIDATION")


@bp.post("/api/grievance-cases")
def file_grievance():
    auth = authenticate()
    require_roles(auth, ["Operator", "UnionRep"])
    body = body_json()
    filed_by = req_field(body, "filed_by_operator_id")
    period_id = req_field(body, "sign_up_period_id")
    if not isinstance(filed_by, str) or not isinstance(period_id, str):
        raise validation("filed_by_operator_id and sign_up_period_id must be strings")
    category = req_enum(body, "category", CATEGORIES)
    detail = req_str(body, "detail")
    ref_operator_or_404(filed_by)
    ref_period_or_404(period_id)
    g = mint()
    g.update(
        {
            "filed_by_operator_id": filed_by,
            "sign_up_period_id": period_id,
            "category": category,
            "detail": detail,
            "status": "FILED",
            "remedy_minutes": 0,
        }
    )
    db.grievance_cases[g["id"]] = g
    return ok_obj(ser(g), 201)


@bp.get("/api/grievance-cases")
def list_grievances():
    auth = authenticate()
    require_roles(auth, READ_SO_OP_UR)
    items = list(db.grievance_cases.values())
    for param in ("status", "category", "sign_up_period_id", "filed_by_operator_id"):
        raw = request.args.get(param)
        if raw is not None:
            items = [g for g in items if g[param] == raw]
    return paginated(items)


@bp.get("/api/grievance-cases/<gid>")
def get_grievance(gid):
    auth = authenticate()
    require_roles(auth, READ_SO_OP_UR)
    return ok_obj(ser(get_grievance_or_404(gid)))


def _ot_equalization_evidence(period_id):
    """Evidence: among operators who received an OVERTIME_OFFER assignment in
    this period, at least one has some other ACTIVE operator whose
    weekly_ot_minutes_accum is strictly lower."""
    ot_operator_ids = {
        a["operator_id"]
        for a in db.daily_assignments.values()
        if a["sign_up_period_id"] == period_id and a["source"] == "OVERTIME_OFFER"
    }
    for ot_oid in ot_operator_ids:
        ot_op = db.operators.get(ot_oid)
        if ot_op is None:
            continue
        for o in db.operators.values():
            if (
                o["status"] == "ACTIVE"
                and o["id"] != ot_oid
                and o["weekly_ot_minutes_accum"] < ot_op["weekly_ot_minutes_accum"]
            ):
                return True
    return False


@bp.post("/api/grievance-cases/<gid>/uphold")
def uphold_grievance(gid):
    auth = authenticate()
    require_roles(auth, UR)
    g = get_grievance_or_404(gid)
    body = body_json(required=False)
    remedy = opt_int(body, "remedy_minutes", 0)
    if g["status"] != "FILED":
        raise invalid_state("Only a FILED grievance may be upheld")
    if g["category"] == "OT_EQUALIZATION" and not _ot_equalization_evidence(
        g["sign_up_period_id"]
    ):
        raise ApiError(
            ERR_GRIEVANCE_PRECONDITION,
            "OT_EQUALIZATION uphold requires an ACTIVE operator with a strictly lower "
            "weekly overtime accumulator than the operator who received the overtime",
            422,
        )
    g["status"] = "UPHELD"
    g["remedy_minutes"] = remedy
    touch(g)
    if remedy:
        op = db.operators.get(g["filed_by_operator_id"])
        if op is not None:
            op["weekly_ot_minutes_accum"] += remedy
            touch(op)
    return ok_obj(ser(g))


@bp.post("/api/grievance-cases/<gid>/dismiss")
def dismiss_grievance(gid):
    auth = authenticate()
    require_roles(auth, UR)
    g = get_grievance_or_404(gid)
    if g["status"] != "FILED":
        raise invalid_state("Only a FILED grievance may be dismissed")
    g["status"] = "DISMISSED"
    touch(g)
    return ok_obj(ser(g))


@bp.post("/api/grievance-cases/<gid>/withdraw")
def withdraw_grievance(gid):
    auth = authenticate()
    require_roles(auth, ["Operator"])
    g = get_grievance_or_404(gid)
    if g["filed_by_operator_id"] != auth["user_id"]:
        raise forbidden("Only the filing operator may withdraw this grievance")
    if g["status"] != "FILED":
        raise invalid_state("Only a FILED grievance may be withdrawn")
    g["status"] = "WITHDRAWN"
    touch(g)
    return ok_obj(ser(g))
