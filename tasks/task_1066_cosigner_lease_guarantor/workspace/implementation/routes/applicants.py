"""Applicant intake and underwriting (PRD 3.1)."""
from flask import Blueprint

import db
from auth import require, body
from constants import EMPLOYMENT_TYPES, CREDIT_FLOOR
from validation import get_or_404, req_str, req_int, req_enum
from responses import success
from serializers import serialize
from errors import ApiError
from calculations import debt_to_income, assign_risk_tier

bp = Blueprint("applicants", __name__)


@bp.post("/applicants")
@require("Underwriter", "PlatformAdmin")
def create_applicant():
    b = body()
    full_name = req_str(b, "full_name")
    email = req_str(b, "email")
    annual_income = req_int(b, "annual_income_cents", positive=True)
    credit_score = req_int(b, "credit_score", lo=300, hi=850)
    monthly_obligations = req_int(b, "monthly_obligations_cents", nonneg=True)
    employment_type = req_enum(b, "employment_type", EMPLOYMENT_TYPES)
    a = {
        "full_name": full_name,
        "email": email,
        "annual_income_cents": annual_income,
        "credit_score": credit_score,
        "monthly_obligations_cents": monthly_obligations,
        "employment_type": employment_type,
        "risk_tier": None,
        "debt_to_income": None,
        "default_count": 0,
        "open_recovery_count": 0,
        "status": "DRAFT",
    }
    db.stamp_common(a)
    db.applicants[a["id"]] = a
    return success(serialize(a), 201)


@bp.get("/applicants/<aid>")
@require("Underwriter", "PlatformAdmin", "ComplianceOfficer")
def get_applicant(aid):
    a = get_or_404(db.applicants, aid)
    return success(serialize(a), 200)


@bp.post("/applicants/<aid>/verify")
@require("Underwriter")
def verify_applicant(aid):
    a = get_or_404(db.applicants, aid)
    if a["status"] != "DRAFT":
        raise ApiError("ERR_INVALID_STATE")

    if a["credit_score"] < CREDIT_FLOOR or a["employment_type"] == "UNEMPLOYED":
        a["status"] = "DECLINED"
        # risk_tier and debt_to_income stay null
    else:
        dti = debt_to_income(a["monthly_obligations_cents"], a["annual_income_cents"])
        a["debt_to_income"] = float(dti)
        a["risk_tier"] = assign_risk_tier(a["credit_score"], dti)
        a["status"] = "VERIFIED"
    db.touch(a)
    return success(serialize(a), 200)
