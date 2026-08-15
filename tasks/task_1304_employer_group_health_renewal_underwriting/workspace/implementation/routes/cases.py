"""Underwriting case endpoints (PRD 3.1)."""
from flask import Blueprint

from db import store, new_record, touch
from errors import (
    ApiError, not_found,
    ERR_CASE_NOT_IN_INTAKE, ERR_CASE_NOT_IN_CENSUS_RECEIVED,
    ERR_CASE_NOT_DECLINABLE, ERR_BROKER_NOT_ACTIVE,
    ERR_NOT_BROKER_OF_RECORD, ERR_GROUP_TOO_SMALL_EXPERIENCE,
    ERR_INVALID_STATE_TRANSITION,
)
from middleware import auth
from response import ok, created, paginated, sorted_items
from serializers import case_json
from validators import body, req_str, req_int, req_enum

bp = Blueprint("cases", __name__)

FUNDING_TYPES = ["FULLY_INSURED", "LEVEL_FUNDED", "SELF_FUNDED"]
READ_ROLES = ["Underwriter", "SeniorUnderwriter", "Broker", "ComplianceOfficer"]
# States from which a case may be withdrawn (PRD 3.1)
WITHDRAWABLE = [
    "INTAKE", "CENSUS_PENDING", "CENSUS_RECEIVED", "CLAIMS_PENDING",
    "RATING_IN_PROGRESS", "QUOTED", "NEGOTIATING",
]


def get_case_or_404(case_id):
    case = store.cases.get(case_id)
    if case is None:
        raise not_found("Underwriting case does not exist")
    return case


@bp.post("/underwriting-cases")
def create_case():
    uid, _ = auth(["Underwriter"])
    data = body()
    group_name = req_str(data, "group_name")
    group_size = req_int(data, "group_size")
    sic_code = req_str(data, "sic_code")
    state_code = req_str(data, "state_code")
    effective_date = req_str(data, "effective_date")
    current_premium_annual = req_int(data, "current_premium_annual")
    current_renewal_date = req_str(data, "current_renewal_date")
    funding_type = req_enum(data, "funding_type", FUNDING_TYPES)
    broker_id = req_str(data, "broker_id")
    if broker_id not in store.brokers:
        raise not_found("Broker does not exist")

    rec = new_record()
    rec.update({
        "group_name": group_name,
        "group_size": group_size,
        "sic_code": sic_code,
        "state_code": state_code,
        "effective_date": effective_date,
        "current_premium_annual": current_premium_annual,
        "current_renewal_date": current_renewal_date,
        "funding_type": funding_type,
        "status": "INTAKE",
        "assigned_underwriter_id": uid,
        "broker_id": broker_id,
        "credibility_factor": 0,
        "blended_rate_cents": 0,
        "manual_rate_cents": 0,
        "experience_rate_cents": 0,
        "rate_cap_pct": 0,
        "is_rate_cap_applied": False,
    })
    store.cases[rec["id"]] = rec
    return created(case_json(rec))


@bp.get("/underwriting-cases")
def list_cases():
    auth(READ_ROLES)
    items = list(store.cases.values())
    status = request_arg("status")
    funding = request_arg("funding_type")
    broker = request_arg("broker_id")
    if status is not None:
        items = [c for c in items if c["status"] == status]
    if funding is not None:
        items = [c for c in items if c["funding_type"] == funding]
    if broker is not None:
        items = [c for c in items if c["broker_id"] == broker]
    return paginated([case_json(c) for c in sorted_items(items)])


def request_arg(name):
    from flask import request
    return request.args.get(name)


@bp.get("/underwriting-cases/<caseId>")
def get_case(caseId):
    auth(READ_ROLES)
    return ok(case_json(get_case_or_404(caseId)))


@bp.post("/underwriting-cases/<caseId>/submit-for-census")
def submit_for_census(caseId):
    auth(["Underwriter"])
    case = get_case_or_404(caseId)
    if case["status"] != "INTAKE":
        raise ApiError(ERR_CASE_NOT_IN_INTAKE,
                       "Case must be in INTAKE to submit for census", 409)
    broker = store.brokers.get(case["broker_id"])
    if broker is None or broker["status"] != "ACTIVE":
        raise ApiError(ERR_BROKER_NOT_ACTIVE, "Broker must be in ACTIVE status", 409)
    case["status"] = "CENSUS_PENDING"
    touch(case)
    return ok(case_json(case))


@bp.post("/underwriting-cases/<caseId>/request-claims")
def request_claims(caseId):
    auth(["Underwriter"])
    case = get_case_or_404(caseId)
    if case["status"] != "CENSUS_RECEIVED":
        raise ApiError(ERR_CASE_NOT_IN_CENSUS_RECEIVED,
                       "Case must be in CENSUS_RECEIVED to request claims", 409)
    if case["group_size"] < 25:
        raise ApiError(ERR_GROUP_TOO_SMALL_EXPERIENCE,
                       "Group size must be >= 25 for experience rating", 409)
    case["status"] = "CLAIMS_PENDING"
    touch(case)
    return ok(case_json(case))


@bp.post("/underwriting-cases/<caseId>/decline")
def decline_case(caseId):
    auth(["Underwriter", "SeniorUnderwriter"])
    case = get_case_or_404(caseId)
    if case["status"] not in ("QUOTED", "NEGOTIATING"):
        raise ApiError(ERR_CASE_NOT_DECLINABLE,
                       "Case must be in QUOTED or NEGOTIATING to decline", 409)
    case["status"] = "DECLINED"
    touch(case)
    return ok(case_json(case))


@bp.post("/underwriting-cases/<caseId>/withdraw")
def withdraw_case(caseId):
    uid, role = auth(["Underwriter", "Broker"])
    case = get_case_or_404(caseId)
    if role == "Broker" and case["broker_id"] != uid:
        raise ApiError(ERR_NOT_BROKER_OF_RECORD,
                       "Acting broker is not the broker of record on this case", 403)
    if case["status"] not in WITHDRAWABLE:
        raise ApiError(ERR_INVALID_STATE_TRANSITION,
                       "The requested state transition is not valid from the current state", 409)
    case["status"] = "WITHDRAWN"
    touch(case)
    return ok(case_json(case))
