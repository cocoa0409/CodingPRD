"""QuarantineCase reads and reviews (EXTEND / RESUME / CLEAR / FAIL)."""

from datetime import timedelta

from flask import Blueprint

import db
import middleware as M
import response
import serializers as S
import validators as V
from errors import ApiError
from services import engine

bp = Blueprint("quarantine", __name__)

OUTCOMES = ("EXTEND", "RESUME", "CLEAR", "FAIL")
CASE_COMPUTED = (
    "specimen_id", "protocol_days", "started_at", "projected_release_at", "status",
    "extension_count", "total_extension_days", "clearance_exam_count", "cleared_by_user_id",
    "cleared_at", "failure_reason",
)

LEGAL_OUTCOMES = {
    "ACTIVE": ("EXTEND", "CLEAR", "FAIL"),
    "EXTENDED": ("RESUME", "FAIL"),
}


@bp.route("/aquarium/quarantine-cases/<row_id>", methods=["GET"])
def get_case(row_id):
    M.authenticate(M.NON_LIAISON)
    row = M.fetch("quarantine_cases", row_id)
    return response.object_response(S.quarantine_case(row))


@bp.route("/aquarium/quarantine-cases/<row_id>/reviews", methods=["POST"])
def review_case(row_id):
    user_id, _role = M.authenticate({M.VET})
    case = M.fetch("quarantine_cases", row_id)
    body = M.json_body()
    V.reject_computed(body, CASE_COMPUTED)
    outcome = V.as_enum(body, "outcome", OUTCOMES, required=True)
    extension_days = V.as_int(body, "extension_days", minimum=1, maximum=30)
    reason = V.as_str(body, "reason")
    if outcome == "EXTEND" and extension_days is None:
        V.bad("Field 'extension_days' is required for an EXTEND review")

    if case["status"] in ("CLEARED", "FAILED"):
        raise ApiError("ERR_ENTITY_TERMINAL")
    if outcome not in LEGAL_OUTCOMES.get(case["status"], ()):
        raise ApiError("ERR_INVALID_ACTION")

    specimen = db.db.specimens.get(case["specimen_id"])

    if outcome == "CLEAR":
        if specimen is not None and specimen["health_status"] != "HEALTHY":
            raise ApiError("ERR_SPECIMEN_NOT_HEALTHY")
        if db.db.clock < case["projected_release_at"]:
            raise ApiError("ERR_QUARANTINE_NOT_COMPLETE")
        if engine.clearance_exam_count(case) < engine.QUARANTINE_MIN_CLEAR_EXAMS:
            raise ApiError("ERR_CLEARANCE_EXAMS_INSUFFICIENT")
        case["status"] = "CLEARED"
        case["cleared_by_user_id"] = user_id
        case["cleared_at"] = db.db.clock
        db.touch(case)
        if specimen is not None and specimen["disposition_status"] == "QUARANTINE":
            specimen["disposition_status"] = "CLEARED"
            db.touch(specimen)
    elif outcome == "EXTEND":
        if int(case["extension_count"]) + 1 > engine.QUARANTINE_MAX_EXTENSIONS:
            raise ApiError("ERR_ROUND_LIMIT_EXCEEDED")
        case["extension_count"] = int(case["extension_count"]) + 1
        case["total_extension_days"] = int(case["total_extension_days"]) + int(extension_days)
        case["projected_release_at"] = case["started_at"] + timedelta(
            days=int(case["protocol_days"]) + int(case["total_extension_days"]))
        case["status"] = "EXTENDED"
        db.touch(case)
    elif outcome == "RESUME":
        case["status"] = "ACTIVE"
        db.touch(case)
    else:
        case["status"] = "FAILED"
        case["failure_reason"] = reason
        db.touch(case)

    return response.object_response(S.quarantine_case(case))
