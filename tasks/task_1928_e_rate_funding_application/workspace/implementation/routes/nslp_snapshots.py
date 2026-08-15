"""NSLPSnapshot endpoints (PRD 3.2). Snapshots are append-only: no updated_at/version."""
from flask import Blueprint, request

from errors import raise_error, ERR_INVALID_REQUEST
from middleware import get_caller, check_role
from response import success_object
from routes.helpers import public, list_collection, get_one
from services.core import new_record
from services.calcs import compute_effective_share
from validate import (
    get_body, check_allowed, req_str, req_int, req_bool, opt_number,
    require_ref,
)

bp = Blueprint("nslp_snapshots", __name__, url_prefix="/erate")


@bp.post("/nslp-snapshots")
def create_snapshot():
    caller = get_caller()
    check_role(caller, ["ProgramAdmin"])
    body = get_body()
    check_allowed(body, {"applicant_id", "funding_cycle_id", "total_students",
                         "free_lunch_eligible_students", "cep_participating",
                         "cep_identified_student_pct"})
    applicant_id = req_str(body, "applicant_id")
    funding_cycle_id = req_str(body, "funding_cycle_id")
    total_students = req_int(body, "total_students", positive=True)
    free_lunch = req_int(body, "free_lunch_eligible_students", non_negative=True)
    cep_participating = req_bool(body, "cep_participating")
    if free_lunch > total_students:
        raise_error(ERR_INVALID_REQUEST,
                    "free_lunch_eligible_students exceeds total_students")
    cep_pct = opt_number(body, "cep_identified_student_pct", minimum=0, maximum=100)
    if cep_participating and cep_pct is None:
        raise_error(ERR_INVALID_REQUEST,
                    "cep_identified_student_pct is required when cep_participating is true")
    require_ref("applicants", applicant_id, "applicant_id")
    require_ref("funding_cycles", funding_cycle_id, "funding_cycle_id")
    share = compute_effective_share(total_students, free_lunch,
                                    cep_participating, cep_pct)
    rec = new_record("nslp_snapshots", {
        "applicant_id": applicant_id,
        "funding_cycle_id": funding_cycle_id,
        "total_students": total_students,
        "free_lunch_eligible_students": free_lunch,
        "cep_participating": cep_participating,
        "cep_identified_student_pct": cep_pct,
        "effective_share_pct": share,
    }, with_version=False)
    return success_object(public(rec), 201)


@bp.get("/nslp-snapshots")
def list_snapshots():
    return list_collection("nslp_snapshots", {
        "applicant_id": request.args.get("applicant_id"),
        "funding_cycle_id": request.args.get("funding_cycle_id"),
    })


@bp.get("/nslp-snapshots/<rid>")
def get_snapshot(rid):
    return get_one("nslp_snapshots", rid)
