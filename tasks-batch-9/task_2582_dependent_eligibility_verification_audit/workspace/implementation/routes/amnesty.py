"""POST /amnesty-removals - voluntary removal without penalty (section 3.4)."""

from flask import Blueprint

import auth
import calc
import clock
import constants as K
import db
import derive
import emit
import response
import serialize
import validate
from auth import endpoint
from errors import ApiError

bp = Blueprint("amnesty", __name__)


@bp.route("/amnesty-removals", methods=["POST"])
@endpoint("Employee", "ProgramAdmin")
def record_amnesty_removal():
    raw = validate.body()
    auth.soft_owner_check_dependent(raw.get("dependent_id"))
    auth.soft_owner_check_case(raw.get("case_id"))

    dependent_id = validate.req_id(raw, "dependent_id")
    case_id = validate.req_id(raw, "case_id")
    reason_code = validate.req_enum(raw, "reason_code", K.AMNESTY_REASON_CODES)
    attestation_signed = raw.get("attestation_signed")
    if attestation_signed is not True:
        validate.bad("attestation_signed must be exactly true.")

    dependent = db.get("dependents", dependent_id)
    if dependent is None:
        raise ApiError("ERR_DEPENDENT_NOT_FOUND")
    case = db.get("cases", case_id)
    if case is None:
        raise ApiError("ERR_CASE_NOT_FOUND")

    program = db.get("programs", case["program_id"])
    if program is None or program["status"] != "AMNESTY_OPEN":
        raise ApiError("ERR_PROGRAM_PHASE_INVALID")
    if case["status"] not in ("NOTIFIED", "IN_PROGRESS"):
        raise ApiError("ERR_CASE_STATE_INVALID")
    if dependent["coverage_status"] not in (
        "PENDING_VERIFICATION",
        "AMNESTY_REMOVED",
    ) or dependent["id"] not in (case.get("in_scope_dependent_ids") or []):
        raise ApiError("ERR_DEPENDENT_STATE_INVALID")

    now = clock.now()
    amnesty_end = program.get("amnesty_end_at")
    if amnesty_end is not None and now > amnesty_end:
        raise ApiError("ERR_AMNESTY_WINDOW_CLOSED")

    for existing in db.collection("amnesty_removals").values():
        if existing["dependent_id"] == dependent["id"]:
            raise ApiError("ERR_AMNESTY_ALREADY_RECORDED")

    coverage_end_date = calc.amnesty_coverage_end(now)
    removal = db.insert(
        "amnesty_removals",
        {
            "dependent_id": dependent["id"],
            "case_id": case["id"],
            "reason_code": reason_code,
            "attestation_signed": True,
            "recorded_at": now,
            "coverage_end_date": coverage_end_date,
            "penalty_waived": True,
            "claims_recovery_waived": True,
            "audited_savings_contribution_cents": calc.amnesty_savings_contribution(
                dependent, coverage_end_date
            ),
        },
    )

    db.set_fields(
        dependent,
        coverage_status="AMNESTY_REMOVED",
        coverage_end_date=coverage_end_date,
    )
    emit.communication(case, "AMNESTY_CONFIRMATION")
    derive.first_response(case)
    derive.recompute_case(case)
    derive.maybe_complete_case(case)
    derive.refresh_all()
    return response.obj_out(serialize.amnesty_removal, removal, 201)
