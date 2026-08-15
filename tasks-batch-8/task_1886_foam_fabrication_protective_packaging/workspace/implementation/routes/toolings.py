"""Die tooling (PRD §3.3)."""
from flask import Blueprint

import db
import errors
from errors import ApiError
from middleware import get_auth_context, require_role
from response import success_object
from services.common import (
    body, get_or_404, get_single, list_many, owner_of_tooling, pub, req_int,
    req_str, stamp_new, touch,
)

bp = Blueprint("toolings", __name__)


@bp.route("/toolings", methods=["POST"])
def create_tooling():
    user_id, role = get_auth_context()
    require_role(role, ("DesignEngineer",))
    data = body()
    cut_program_id = req_str(data, "cut_program_id")
    die_cost = req_int(data, "die_cost_cents", minimum=0)
    amort_qty = req_int(data, "amortization_qty", minimum=1)
    lead_time = req_int(data, "lead_time_days", minimum=0)
    program = get_or_404(db.cut_programs, cut_program_id, "CutProgram")
    if program["method"] != "DIE_CUT":
        raise ApiError(
            errors.ERR_METHOD_MISMATCH,
            "Tooling may be ordered only for DIE_CUT cut programs",
            422,
        )
    rec = stamp_new({
        "cut_program_id": cut_program_id,
        "die_cost_cents": die_cost,
        "amortization_qty": amort_qty,
        "lead_time_days": lead_time,
        "amortized_cents": 0,
        "status": "ORDERED",
    })
    db.toolings[rec["id"]] = rec
    return success_object(pub(rec), 201)


@bp.route("/toolings", methods=["GET"])
def list_toolings():
    return list_many(db.toolings, owner_of_tooling, ("cut_program_id", "status"))


@bp.route("/toolings/<rid>", methods=["GET"])
def get_tooling(rid):
    return get_single(db.toolings, rid, owner_of_tooling, "Tooling")


@bp.route("/toolings/<rid>/commission", methods=["POST"])
def commission_tooling(rid):
    user_id, role = get_auth_context()
    require_role(role, ("DesignEngineer",))
    rec = get_or_404(db.toolings, rid, "Tooling")
    if rec["status"] != "ORDERED":
        raise ApiError(errors.ERR_INVALID_STATE, f"Cannot commission tooling in {rec['status']}", 409)
    rec["status"] = "IN_SERVICE"
    touch(rec)
    return success_object(pub(rec))


@bp.route("/toolings/<rid>/retire", methods=["POST"])
def retire_tooling(rid):
    user_id, role = get_auth_context()
    require_role(role, ("DesignEngineer",))
    rec = get_or_404(db.toolings, rid, "Tooling")
    if rec["status"] not in ("ORDERED", "IN_SERVICE"):
        raise ApiError(errors.ERR_INVALID_STATE, f"Cannot retire tooling in {rec['status']}", 409)
    rec["status"] = "RETIRED"
    touch(rec)
    return success_object(pub(rec))
