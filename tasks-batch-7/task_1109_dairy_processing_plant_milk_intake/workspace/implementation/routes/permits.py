"""Grade A permits and inspection cadence (PRD 3.9)."""
from flask import Blueprint

from db import STORE, base_record, touch
from errors import (
    ApiError,
    ERR_INSPECTION_PASSED,
    ERR_INSUFFICIENT_VIOLATIONS,
    ERR_VIOLATIONS_BELOW_REVOCATION,
    ERR_VIOLATIONS_OUTSTANDING,
    bad_input,
    invalid_state,
    not_found,
)
from helpers import body, req_dt, req_int, req_str
from middleware import require_roles
from response import success_object
from services import ser_permit

bp = Blueprint("permits", __name__)

_SI = "StateInspector"


def _get_permit(pid):
    permit = STORE["permits"].get(pid)
    if permit is None:
        raise not_found("GradeAPermit not found")
    return permit


@bp.route("/dairy/grade-a-permits", methods=["POST"])
def create_permit():
    require_roles(_SI)
    data = body()
    permit_number = req_str(data, "permit_number")
    issued_at = req_dt(data, "issued_at")
    expires_at = req_dt(data, "expires_at")
    rec = base_record()
    rec.update({
        "permit_number": permit_number,
        "issued_at": issued_at,
        "expires_at": expires_at,
        "inspection_score": None,
        "violation_count_12mo": 0,
        "status": "ACTIVE",
    })
    STORE["permits"][rec["id"]] = rec
    return success_object(ser_permit(rec), 201)


@bp.route("/dairy/grade-a-permits/<pid>", methods=["GET"])
def get_permit(pid):
    require_roles(_SI, "PlantController", "QualityAssuranceManager")
    return success_object(ser_permit(_get_permit(pid)))


@bp.route("/dairy/grade-a-permits/<pid>/record-inspection", methods=["POST"])
def record_inspection(pid):
    require_roles(_SI)
    permit = _get_permit(pid)
    if permit["status"] != "ACTIVE":
        raise invalid_state("GradeAPermit is not in ACTIVE")
    data = body()
    score = req_int(data, "inspection_score")
    violations_found = req_int(data, "violations_found")
    if score < 0 or score > 100:
        raise bad_input("inspection_score must be in [0, 100]")
    if violations_found < 0:
        raise bad_input("violations_found must be non-negative")
    passed = score >= 90 \
        and (permit["violation_count_12mo"] + violations_found) < 3
    if passed:
        raise ApiError(
            ERR_INSPECTION_PASSED, 422,
            "Inspection passed; moving the permit to UNDER_REVIEW is "
            "inappropriate",
        )
    permit["inspection_score"] = score
    permit["violation_count_12mo"] += violations_found
    permit["status"] = "UNDER_REVIEW"
    touch(permit)
    return success_object(ser_permit(permit), 200)


@bp.route("/dairy/grade-a-permits/<pid>/suspend", methods=["POST"])
def suspend_permit(pid):
    require_roles(_SI)
    permit = _get_permit(pid)
    if permit["status"] != "UNDER_REVIEW":
        raise invalid_state("GradeAPermit is not UNDER_REVIEW")
    if permit["violation_count_12mo"] < 3:
        raise ApiError(ERR_INSUFFICIENT_VIOLATIONS, 422,
                       "violation_count_12mo < 3")
    permit["status"] = "SUSPENDED"
    touch(permit)
    for run in STORE["runs"].values():
        if run["status"] == "SCHEDULED":
            run["status"] = "CANCELLED"
            touch(run)
    return success_object(ser_permit(permit), 200)


@bp.route("/dairy/grade-a-permits/<pid>/reinstate", methods=["POST"])
def reinstate_permit(pid):
    require_roles(_SI)
    permit = _get_permit(pid)
    if permit["status"] != "UNDER_REVIEW":
        raise invalid_state("GradeAPermit is not UNDER_REVIEW")
    if permit["violation_count_12mo"] >= 3:
        raise ApiError(ERR_VIOLATIONS_OUTSTANDING, 422,
                       "violation_count_12mo >= 3")
    permit["status"] = "REINSTATED"
    touch(permit)
    return success_object(ser_permit(permit), 200)


@bp.route("/dairy/grade-a-permits/<pid>/revoke", methods=["POST"])
def revoke_permit(pid):
    require_roles(_SI)
    permit = _get_permit(pid)
    if permit["status"] != "UNDER_REVIEW":
        raise invalid_state("GradeAPermit is not UNDER_REVIEW")
    if permit["violation_count_12mo"] < 5:
        raise ApiError(ERR_VIOLATIONS_BELOW_REVOCATION, 422,
                       "violation_count_12mo < 5")
    permit["status"] = "REVOKED"
    touch(permit)
    for receipt in STORE["receipts"].values():
        if receipt["disposition"] == "QUARANTINE":
            receipt["disposition"] = "DIVERTED"
            touch(receipt)
    return success_object(ser_permit(permit), 200)
