"""The carrier data set and complaint-ratio surveillance (PRD §3.1)."""

from flask import Blueprint

import validation as v
from db import db, new_record, touch
from errors import ApiError
from middleware import (
    ROLE_EXAMINER_IN_CHARGE,
    ROLE_INSURER_RESPONDENT,
    ROLE_MARKET_ANALYST,
    ROLE_MULTISTATE_COORDINATOR,
    ROLE_SUPERVISING_EXAMINER,
    authorize,
)
from response import paginated, success
from routes.common import bool_query, filter_equals, str_query
from services import calculations as calc
from services import derive, serialize
from services.guards import get_insurer

bp = Blueprint("insurers", __name__)

LICENSE_STATUSES = ("LICENSED", "SUSPENDED", "WITHDRAWN")
RISK_TIERS = ("HIGH", "ELEVATED", "MODERATE", "LOW", "UNRATED")


def _rederive(insurer):
    ratio, tier = calc.complaint_ratio_and_tier(
        insurer["policy_count_in_force"], insurer["confirmed_complaints_12mo"]
    )
    insurer["complaint_ratio_per_1k"] = ratio
    insurer["risk_tier"] = tier


@bp.post("/insurers")
@authorize(ROLE_MARKET_ANALYST)
def create_insurer():
    payload = v.body()
    name = v.get_str(payload, "name", min_len=1, max_len=120)
    naic_code = v.require_naic(payload, "naic_code")
    premium = v.get_int(payload, "annual_premium_written_cents", minimum=0)
    policies = v.get_int(payload, "policy_count_in_force", minimum=0)
    complaints = v.get_int(payload, "confirmed_complaints_12mo", minimum=0)
    financial = v.get_int(payload, "financial_stress_score", minimum=0, maximum=100)
    trend = v.get_int(payload, "consumer_trend_score", minimum=0, maximum=100)
    license_status = v.get_enum(
        payload, "license_status", LICENSE_STATUSES, required=False, default="LICENSED"
    )

    if any(row["naic_code"] == naic_code for row in db.insurers.values()):
        raise ApiError(
            "ERR_DUPLICATE_IDENTIFIER", "That naic_code already exists on another carrier."
        )

    insurer = new_record(
        {
            "name": name,
            "naic_code": naic_code,
            "license_status": license_status,
            "annual_premium_written_cents": premium,
            "policy_count_in_force": policies,
            "confirmed_complaints_12mo": complaints,
            "financial_stress_score": financial,
            "consumer_trend_score": trend,
            "complaint_ratio_per_1k": None,
            "risk_tier": None,
        }
    )
    _rederive(insurer)
    db.insurers[insurer["id"]] = insurer
    return success(serialize.insurer(insurer), 201)


@bp.get("/insurers")
@authorize(
    ROLE_MARKET_ANALYST,
    ROLE_EXAMINER_IN_CHARGE,
    ROLE_SUPERVISING_EXAMINER,
    ROLE_MULTISTATE_COORDINATOR,
)
def list_insurers():
    rows = derive.by_creation_insurers()
    rows = filter_equals(rows, "license_status", str_query("license_status"))
    rows = filter_equals(rows, "risk_tier", str_query("risk_tier"))
    return paginated(rows, serialize.insurer)


@bp.get("/insurers/<insurer_id>")
@authorize(
    ROLE_MARKET_ANALYST,
    ROLE_EXAMINER_IN_CHARGE,
    ROLE_SUPERVISING_EXAMINER,
    ROLE_MULTISTATE_COORDINATOR,
    ROLE_INSURER_RESPONDENT,
)
def read_insurer(insurer_id):
    return success(serialize.insurer(get_insurer(insurer_id)))


@bp.patch("/insurers/<insurer_id>/market-data")
@authorize(ROLE_MARKET_ANALYST)
def patch_market_data(insurer_id):
    insurer = get_insurer(insurer_id)
    payload = v.body()
    policies = v.get_int(payload, "policy_count_in_force", required=False, minimum=0)
    complaints = v.get_int(payload, "confirmed_complaints_12mo", required=False, minimum=0)
    financial = v.get_int(
        payload, "financial_stress_score", required=False, minimum=0, maximum=100
    )
    trend = v.get_int(
        payload, "consumer_trend_score", required=False, minimum=0, maximum=100
    )
    premium = v.get_int(
        payload, "annual_premium_written_cents", required=False, minimum=0
    )
    license_status = v.get_enum(
        payload, "license_status", LICENSE_STATUSES, required=False
    )

    if policies is not None:
        insurer["policy_count_in_force"] = policies
    if complaints is not None:
        insurer["confirmed_complaints_12mo"] = complaints
    if financial is not None:
        insurer["financial_stress_score"] = financial
    if trend is not None:
        insurer["consumer_trend_score"] = trend
    if premium is not None:
        insurer["annual_premium_written_cents"] = premium
    if license_status is not None:
        insurer["license_status"] = license_status

    _rederive(insurer)
    touch(insurer)
    return success(serialize.insurer(insurer))


@bp.get("/insurers/<insurer_id>/analysis-scores")
@authorize(ROLE_MARKET_ANALYST, ROLE_SUPERVISING_EXAMINER)
def list_insurer_scores(insurer_id):
    get_insurer(insurer_id)
    rows = derive.scores_of_insurer(insurer_id)
    rows = filter_equals(rows, "cycle_id", str_query("cycle_id"))
    selected = bool_query("selected")
    if selected is not None:
        rows = [row for row in rows if row["selected"] is selected]
    return paginated(rows, serialize.analysis_score)
