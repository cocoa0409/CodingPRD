"""Claims experience endpoints (PRD 3.3)."""
from flask import Blueprint

from db import store, new_record, touch
from errors import (
    ApiError, not_found, invalid_request,
    ERR_CLAIMS_NOT_PENDING, ERR_CLAIMS_NOT_SUBMITTED,
    ERR_INVALID_EXPERIENCE_PERIOD, ERR_INSUFFICIENT_EXPERIENCE_MONTHS,
    ERR_SAME_REVIEWER_AS_SUBMITTER, ERR_INVALID_STATE_TRANSITION,
)
from middleware import auth
from response import ok, created, paginated, sorted_items
from serializers import claims_json
from services import calcs
from services.workflow import on_claims_reviewed, parse_dt
from validators import body, req_str, req_int

bp = Blueprint("claims", __name__)

READ_ROLES = ["Underwriter", "SeniorUnderwriter", "Broker", "ComplianceOfficer"]


def get_claims_or_404(claims_id):
    claims = store.claims.get(claims_id)
    if claims is None:
        raise not_found("Claims experience does not exist")
    return claims


@bp.post("/underwriting-cases/<caseId>/claims-experiences")
def create_claims(caseId):
    auth(["Underwriter"])
    if caseId not in store.cases:
        raise not_found("Underwriting case does not exist")
    data = body()
    rec = new_record()
    rec.update({
        "case_id": caseId,
        "experience_period_start": req_str(data, "experience_period_start"),
        "experience_period_end": req_str(data, "experience_period_end"),
        "months_of_experience": 0,
        "total_paid_claims_cents": req_int(data, "total_paid_claims_cents"),
        "total_enrollment_months": req_int(data, "total_enrollment_months"),
        "large_claim_count": req_int(data, "large_claim_count"),
        "pooling_threshold_cents": req_int(data, "pooling_threshold_cents"),
        "pooled_claims_cents": 0,
        "experience_claim_cost_cents": 0,
        "completion_ratio": 0,
        "status": "PENDING",
        "_submitted_by": None,
    })
    store.claims[rec["id"]] = rec
    return created(claims_json(rec))


@bp.get("/underwriting-cases/<caseId>/claims-experiences")
def list_claims(caseId):
    auth(READ_ROLES)
    if caseId not in store.cases:
        raise not_found("Underwriting case does not exist")
    items = [c for c in store.claims.values() if c["case_id"] == caseId]
    return paginated([claims_json(c) for c in sorted_items(items)])


@bp.get("/claims-experiences/<claimsId>")
def get_claims(claimsId):
    auth(READ_ROLES)
    return ok(claims_json(get_claims_or_404(claimsId)))


@bp.post("/claims-experiences/<claimsId>/submit")
def submit_claims(claimsId):
    uid, _ = auth(["Underwriter"])
    claims = get_claims_or_404(claimsId)
    if claims["status"] != "PENDING":
        raise ApiError(ERR_CLAIMS_NOT_PENDING,
                       "Claims experience must be in PENDING status", 409)
    start = parse_dt(claims["experience_period_start"])
    end = parse_dt(claims["experience_period_end"])
    if start is None or end is None:
        raise invalid_request("Experience period dates must be valid ISO 8601")
    if end <= start:
        raise ApiError(ERR_INVALID_EXPERIENCE_PERIOD,
                       "experience_period_end must be after experience_period_start", 400)
    months = calcs.whole_months_inclusive(start, end)
    if months < 12:
        raise ApiError(ERR_INSUFFICIENT_EXPERIENCE_MONTHS,
                       "Claims experience must cover at least 12 months", 409)
    claims["months_of_experience"] = months
    pooled = calcs.pooled_claims(
        claims["total_paid_claims_cents"],
        claims["large_claim_count"],
        claims["pooling_threshold_cents"],
    )
    claims["pooled_claims_cents"] = pooled
    claims["experience_claim_cost_cents"] = claims["total_paid_claims_cents"] - pooled
    claims["status"] = "SUBMITTED"
    claims["_submitted_by"] = uid
    touch(claims)
    return ok(claims_json(claims))


@bp.post("/claims-experiences/<claimsId>/review")
def review_claims(claimsId):
    uid, _ = auth(["SeniorUnderwriter"])
    claims = get_claims_or_404(claimsId)
    if claims["status"] != "SUBMITTED":
        raise ApiError(ERR_CLAIMS_NOT_SUBMITTED,
                       "Claims experience must be in SUBMITTED status", 409)
    if claims["_submitted_by"] is not None and claims["_submitted_by"] == uid:
        raise ApiError(ERR_SAME_REVIEWER_AS_SUBMITTER,
                       "Claims reviewer must not be the same user who submitted "
                       "(segregation of duties)", 403)
    claims["completion_ratio"] = float(calcs.completion_ratio(claims["months_of_experience"]))
    claims["status"] = "REVIEWED"
    touch(claims)
    on_claims_reviewed(claims)
    return ok(claims_json(claims))


@bp.post("/claims-experiences/<claimsId>/reject")
def reject_claims(claimsId):
    auth(["SeniorUnderwriter"])
    claims = get_claims_or_404(claimsId)
    if claims["status"] not in ("PENDING", "SUBMITTED"):
        raise ApiError(ERR_INVALID_STATE_TRANSITION,
                       "The requested state transition is not valid from the current state", 409)
    claims["status"] = "REJECTED"
    touch(claims)
    return ok(claims_json(claims))
