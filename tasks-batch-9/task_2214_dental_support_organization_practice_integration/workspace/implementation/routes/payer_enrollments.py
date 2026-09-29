"""Credentialing enrollments: half-open participation intervals (PRD 3.6)."""

from flask import Blueprint

import clock
import config
import db
import middleware
import payload
import support
from errors import ApiError, invalid
from services import derive, uow

bp = Blueprint("payer_enrollments", __name__)

READ_ROLES = (
    config.ROLE_INTEGRATION_LEAD,
    config.ROLE_FINANCE_CONTROLLER,
    config.ROLE_DEAL_COUNSEL,
    config.ROLE_CLINICAL_DIRECTOR,
)


def _interval(enrollment):
    start = enrollment["effective_date"]
    end = enrollment["term_date"] or clock.OPEN_ENDED
    return start, end


@bp.post("/payer-enrollments")
@support.transactional
def create_enrollment():
    middleware.authorize([config.ROLE_INTEGRATION_LEAD])
    data = payload.body()
    contract = support.load_fk(data, "payer_contract_id", "payer_contracts")
    employment = support.load_fk(data, "doctor_employment_id", "doctor_employments")
    payload.string(data, "payer_contract_id")
    payload.string(data, "doctor_employment_id")
    effective_date = payload.timestamp(data, "effective_date")
    term_date = payload.timestamp(data, "term_date", required=False)
    if term_date is not None and term_date <= effective_date:
        raise invalid("'term_date' must be strictly after 'effective_date'.")

    if employment["employment_status"] != "ACTIVE":
        raise ApiError(
            "ERR_INVALID_EMPLOYMENT_STATE",
            "Only an ACTIVE employment can be enrolled with a payer.",
        )

    new_start = effective_date
    new_end = term_date or clock.OPEN_ENDED
    for existing in derive.enrollments_of_contract(contract["id"]):
        if existing["doctor_employment_id"] != employment["id"]:
            continue
        if existing["status"] not in ("SUBMITTED", "APPROVED"):
            continue
        old_start, old_end = _interval(existing)
        if new_start < old_end and old_start < new_end:
            raise ApiError(
                "ERR_ENROLLMENT_PERIOD_OVERLAP",
                "The requested participation interval overlaps an occupied one.",
            )

    row = db.insert(
        "payer_enrollments",
        {
            "payer_contract_id": contract["id"],
            "doctor_employment_id": employment["id"],
            "status": "NOT_STARTED",
            "effective_date": effective_date,
            "term_date": term_date,
            "submitted_at": None,
            "decided_at": None,
            "denial_reason": None,
            "submission_round": 0,
        },
    )
    # The contract's open-enrollment ledger moves, which may open credentialing.
    uow.touch(contract)
    return "payer_enrollments", row, 201


@bp.get("/payer-enrollments/<payer_enrollment_id>")
def get_enrollment(payer_enrollment_id):
    middleware.authorize(READ_ROLES)
    row = support.load("payer_enrollments", payer_enrollment_id)
    return support.read_one("payer_enrollments", row)


@bp.get("/payer-enrollments")
def list_enrollments():
    middleware.authorize(READ_ROLES)
    rows = db.all_rows("payer_enrollments")
    rows = support.filter_rows(
        rows, "payer_contract_id", payload.filter_value("payer_contract_id")
    )
    rows = support.filter_rows(
        rows, "doctor_employment_id", payload.filter_value("doctor_employment_id")
    )
    rows = support.filter_rows(rows, "status", payload.filter_value("status"))
    return support.read_many("payer_enrollments", rows)


@bp.post("/payer-enrollments/<payer_enrollment_id>/submit")
@support.transactional
def submit_enrollment(payer_enrollment_id):
    middleware.authorize([config.ROLE_INTEGRATION_LEAD])
    enrollment = support.load("payer_enrollments", payer_enrollment_id)
    payload.body()
    employment = db.get("doctor_employments", enrollment["doctor_employment_id"])
    if employment["employment_status"] != "ACTIVE":
        raise ApiError(
            "ERR_INVALID_EMPLOYMENT_STATE",
            "Only an ACTIVE employment can be submitted for credentialing.",
        )
    if enrollment["status"] not in ("NOT_STARTED", "DENIED"):
        raise ApiError(
            "ERR_INVALID_ENROLLMENT_STATE",
            "Only a not-started or denied enrollment can be submitted.",
        )
    contract = db.get("payer_contracts", enrollment["payer_contract_id"])
    practice = db.get("practices", contract["practice_id"])
    support.require_affiliated(practice)
    if derive.integration_posture(practice) == "FROZEN":
        raise ApiError(
            "ERR_PRACTICE_POSTURE_BLOCKED",
            "A frozen practice cannot submit credentialing.",
        )
    enrollment["status"] = "SUBMITTED"
    enrollment["submitted_at"] = clock.now()
    enrollment["submission_round"] += 1
    enrollment["denial_reason"] = None
    uow.touch(enrollment)
    return "payer_enrollments", enrollment, 200


@bp.post("/payer-enrollments/<payer_enrollment_id>/decide")
@support.transactional
def decide_enrollment(payer_enrollment_id):
    middleware.authorize([config.ROLE_INTEGRATION_LEAD])
    enrollment = support.load("payer_enrollments", payer_enrollment_id)
    data = payload.body()
    decision = payload.enum(data, "decision", config.DECISIONS)
    denial_reason = payload.string(data, "denial_reason", required=False)
    if decision == "DENY" and not denial_reason:
        raise invalid("'denial_reason' is required when the decision is DENY.")
    if enrollment["status"] != "SUBMITTED":
        raise ApiError(
            "ERR_INVALID_ENROLLMENT_STATE",
            "Only a submitted enrollment can be decided.",
        )
    enrollment["decided_at"] = clock.now()
    if decision == "APPROVE":
        enrollment["status"] = "APPROVED"
    else:
        enrollment["status"] = "DENIED"
        enrollment["denial_reason"] = denial_reason
    uow.touch(enrollment)
    return "payer_enrollments", enrollment, 200
