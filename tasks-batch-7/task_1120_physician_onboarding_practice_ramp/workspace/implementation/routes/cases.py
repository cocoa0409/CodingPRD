"""Onboarding case endpoints (PRD 3.1)."""

from flask import Blueprint, request

import domain as D
from db import store, new_record, bump
from errors import (
    ApiError, ERR_PHYSICIAN_NOT_FOUND, ERR_CASE_NOT_FOUND,
    ERR_DUPLICATE_CASE, ERR_INVALID_STATE,
)
from middleware import get_context, require_role
from response import success_object, paginate

bp = Blueprint("cases", __name__)


@bp.route("/onboarding/onboarding-cases", methods=["POST"])
def create_case():
    _uid, role = get_context()
    require_role(role, ["Recruiter"])
    body = D.get_body()
    physician_id = D.req_str(body, "physician_id")
    target_start_date = D.req_str(body, "target_start_date")
    D.parse_date(target_start_date, "target_start_date")
    physician = store.physicians.get(physician_id)
    if physician is None:
        raise ApiError(ERR_PHYSICIAN_NOT_FOUND, 404, "Physician not found")
    if D.case_for_physician(physician_id) is not None:
        raise ApiError(ERR_DUPLICATE_CASE, 409, "An OnboardingCase already exists for the physician")
    if physician["status"] != "PROSPECT":
        raise ApiError(ERR_INVALID_STATE, 409, "Physician must be PROSPECT to open a case")
    rec = new_record()
    rec.update({
        "physician_id": physician_id,
        "target_start_date": target_start_date,
        "actual_start_date": None,
        "case_status": "IN_PROGRESS",
        "credential_status": "NOT_STARTED",
        "training_status": "NOT_STARTED",
        "practice_status": "PLANNING",
        "posture": "PRE_CONTRACT",
        "weekly_active_minutes": 0,
        "attained_milestone_count": 0,
        "missed_milestone_count": 0,
        "latest_risk_score": None,
        "latest_risk_band": None,
        "at_risk": False,
    })
    store.cases[rec["id"]] = rec
    physician["status"] = "ONBOARDING"
    bump(physician)
    return success_object(D.serialize_case(rec), status=201)


@bp.route("/onboarding/onboarding-cases/<cid>", methods=["GET"])
def get_case(cid):
    get_context()
    case = store.cases.get(cid)
    if case is None:
        raise ApiError(ERR_CASE_NOT_FOUND, 404, "OnboardingCase not found")
    return success_object(D.serialize_case(case))


@bp.route("/onboarding/onboarding-cases", methods=["GET"])
def list_cases():
    get_context()
    physician_id = request.args.get("physician_id")
    posture = request.args.get("posture")
    case_status = request.args.get("case_status")
    records = sorted(store.cases.values(), key=lambda r: r["_seq"])
    if physician_id is not None:
        records = [r for r in records if r["physician_id"] == physician_id]
    if posture is not None:
        records = [r for r in records if r["posture"] == posture]
    if case_status is not None:
        records = [r for r in records if r["case_status"] == case_status]
    return paginate([D.serialize_case(r) for r in records], request.args)
