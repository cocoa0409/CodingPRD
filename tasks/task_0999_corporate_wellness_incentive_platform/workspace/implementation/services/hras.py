"""HealthAssessment endpoint (PRD §3.4)."""
from flask import Blueprint

from db import DB
from errors import ApiError
from middleware import require_roles
from response import success
from services import serializers
from services.common import (
    check_employee_scope, get_enrollment_or_404, parse_body, require_fields,
    stamp_new, touch,
)

bp = Blueprint("hras", __name__)


@bp.post("/wellness/hras")
@require_roles("Employee")
def create_hra():
    body = parse_body()
    vals = require_fields(body, [
        ("enrollment_id", "string", True),
        ("answers", "answers", True),
    ])
    enr = get_enrollment_or_404(vals["enrollment_id"])
    check_employee_scope(enr)
    if enr["participation_status"] != "ACTIVE":
        raise ApiError(
            "ERR_ENROLLMENT_NOT_ACTIVE",
            "HRA submission requires an ACTIVE enrollment",
        )
    if any(h["enrollment_id"] == enr["id"] for h in DB.hras.values()):
        raise ApiError(
            "ERR_HRA_ALREADY_COMPLETED",
            "An HRA already exists for this enrollment",
        )
    answers = vals["answers"]
    risk_score = sum(answers)
    if risk_score < 30:
        risk_band = "LOW"
    elif risk_score < 60:
        risk_band = "MODERATE"
    else:
        risk_band = "HIGH"
    rec = stamp_new(
        {
            "enrollment_id": enr["id"],
            "answers": answers,
            "risk_score": risk_score,
            "risk_band": risk_band,
        },
        common=False,  # HealthAssessment carries only id + created_at (PRD §2.4)
    )
    DB.hras[rec["id"]] = rec
    # verification axis: PENDING -> VERIFIED (independent of participation axis)
    if enr["verification_status"] == "PENDING":
        enr["verification_status"] = "VERIFIED"
        touch(enr)
    # HIGH band: auto-create AUTO_RISK coaching referral
    if risk_band == "HIGH":
        referral = stamp_new({
            "enrollment_id": enr["id"],
            "reason": "HIGH_RISK",
            "source": "AUTO_RISK",
            "assigned_coach_id": None,
            "sessions_completed": 0,
            "session_dates": [],
            "referral_round": 1,
            "outcome": None,
            "status": "REFERRED",
        })
        DB.referrals[referral["id"]] = referral
        enr["auto_referral_count"] += 1
        touch(enr)
    return success(serializers.hra(rec), status=201)
