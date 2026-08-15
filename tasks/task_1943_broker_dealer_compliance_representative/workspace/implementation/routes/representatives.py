"""RegisteredRepresentative endpoints (PRD 3.1)."""
from flask import Blueprint, request

from db import db
from errors import raise_error, ERR_INVALID_STATE, ERR_VALIDATION
from middleware import authorized
from response import success_object
from routes.helpers import get_one, list_response
from services.cascade import terminate_rep_cascade
from services.core import new_record, public, touch
from validate import get_body, req_date, req_str, require_path_resource, require_ref

bp = Blueprint("representatives", __name__)


@bp.post("/representatives")
def create_representative():
    authorized(["FirmAdmin"])
    body = get_body()
    # Priority 3: FK existence
    branch = require_ref("branches", body.get("branch_id"), "branch_id")
    # Priority 8: schema
    crd_number = req_str(body, "crd_number")
    full_name = req_str(body, "full_name")
    hire_date = req_date(body, "hire_date")
    if branch is None:
        raise_error(ERR_VALIDATION, "missing or invalid field: branch_id")
    # crd_number is unique across the firm
    for r in db["representatives"].values():
        if r["crd_number"] == crd_number:
            raise_error(ERR_VALIDATION, f"crd_number already registered: {crd_number}")
    rec = new_record("representatives", {
        "branch_id": branch["id"],
        "crd_number": crd_number,
        "full_name": full_name,
        "hire_date": hire_date,
        "status": "ACTIVE",
        "is_statutorily_disqualified": False,
        "supervision_tier": "STANDARD",
        "compliance_flag_count": 0,
        "active_approved_activity_count": 0,
        "pst_fee_total_cents": 0,
    })
    return success_object(public(rec), status=201)


@bp.get("/representatives")
def list_representatives():
    return list_response("representatives", filters={
        "branch_id": request.args.get("branch_id"),
        "status": request.args.get("status"),
        "supervision_tier": request.args.get("supervision_tier"),
    })


@bp.get("/representatives/<rid>")
def get_representative(rid):
    return get_one("representatives", rid)


@bp.post("/representatives/<rid>/terminate")
def terminate_representative(rid):
    authorized(["CompliancePrincipal"])
    rep = require_path_resource("representatives", rid)
    if rep["status"] != "ACTIVE":
        raise_error(ERR_INVALID_STATE, "only an ACTIVE representative can be terminated")
    rep["status"] = "TERMINATED"
    touch(rep)
    terminate_rep_cascade(rep)
    return success_object(public(rep))
