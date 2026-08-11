"""Visit endpoints: recording, verification, rejection, voiding."""
from datetime import timedelta

from flask import Blueprint, request, g

from db import STORE
from errors import (err, ERR_VISIT_NOT_FOUND, ERR_ENROLLMENT_NOT_FOUND,
                    ERR_MEMBER_NOT_FOUND, ERR_MEMBER_TERMINATED,
                    ERR_PROVIDER_NOT_ACTIVE, ERR_PROVIDER_TERMINATED,
                    ERR_INVALID_REQUEST, ERR_INVALID_DATE_RANGE,
                    ERR_SERVICE_OUTSIDE_CONTRACT, ERR_VISIT_TIME_OVERLAP,
                    ERR_FREQUENCY_CAP_EXCEEDED, ERR_FRAUD_HOLD,
                    ERR_VISIT_IN_USE)
from middleware import require_roles, is_member, is_provider_operator, member_owns, provider_owns
from response import success, paginate
from services.core import (new_entity, touch, serialize, sort_created,
                           tier_for, fraud_score, create_fraud_flag,
                           reject_visit_cascade, FRAUD_BLOCK_THRESHOLD,
                           FRAUD_FLAG_THRESHOLD)
from util import body_json, req, as_str, check_enum, parse_dt

bp = Blueprint("visits", __name__)

VERIFICATION_METHODS = ("GEO_FENCE", "POS_SWIPE", "MANUAL_REVIEW")
READ_ROLES = ("BenefitsAdmin", "Auditor", "ClaimsReviewer", "Member", "ProviderOperator")
FREQUENCY_WINDOW_DAYS = 30


def get_visit(vid):
    v = STORE.visits.get(vid)
    if v is None:
        raise err(ERR_VISIT_NOT_FOUND, 404, "visit id does not resolve")
    return v


@bp.post("/api/visits")
def create_visit():
    require_roles("ProviderOperator")
    provider = STORE.providers[g.user_id]  # guaranteed by auth
    body = body_json()
    enrollment_id = as_str(req(body, "enrollment_id"), "enrollment_id")
    member_id = as_str(req(body, "member_id"), "member_id")
    ci_raw = req(body, "check_in_at")
    co_raw = req(body, "check_out_at")
    method = check_enum(req(body, "verification_method"), VERIFICATION_METHODS,
                        "verification_method")
    # existence: body FKs
    enr = STORE.enrollments.get(enrollment_id)
    if enr is None:
        raise err(ERR_ENROLLMENT_NOT_FOUND, 404, "enrollment id does not resolve")
    member = STORE.members.get(member_id)
    if member is None:
        raise err(ERR_MEMBER_NOT_FOUND, 404, "member id does not resolve")
    # shape: datetime range
    ci, co = parse_dt(ci_raw), parse_dt(co_raw)
    if co <= ci:
        raise err(ERR_INVALID_DATE_RANGE, 400, "check_out_at must be strictly after check_in_at")
    # state: member / provider
    if member["eligibility_status"] == "TERMINATED":
        raise err(ERR_MEMBER_TERMINATED, 409, "member TERMINATED")
    if provider["status"] == "TERMINATED":
        raise err(ERR_PROVIDER_TERMINATED, 409, "terminated provider accepts no new visits")
    if provider["status"] != "ACTIVE":
        raise err(ERR_PROVIDER_NOT_ACTIVE, 409, "provider not ACTIVE")
    # temporal: check_in inside provider contract window (closed both ends)
    if not (provider["_cs"] <= ci <= provider["_ce"]):
        raise err(ERR_SERVICE_OUTSIDE_CONTRACT, 422,
                  "visit check_in_at outside provider contract window")
    # business: no overlapping visit (half-open intervals; adjacency allowed)
    member_visits = [v for v in STORE.visits.values()
                     if v["member_id"] == member_id and v["status"] in ("RECORDED", "VERIFIED")]
    for v in member_visits:
        if ci < v["_check_out_dt"] and v["_check_in_dt"] < co:
            raise err(ERR_VISIT_TIME_OVERLAP, 409,
                      "member has a non-terminal visit intersecting the new interval")
    # business: rolling 30-day frequency cap (strict lower bound)
    tier = tier_for(enr["plan_id"], enr["tier_code"]) or enr["_tier_snapshot"]
    window_start = ci - timedelta(days=FREQUENCY_WINDOW_DAYS)
    count = sum(1 for v in member_visits
                if window_start < v["_check_in_dt"] <= ci)
    if count >= tier["visit_frequency_cap"]:
        raise err(ERR_FREQUENCY_CAP_EXCEEDED, 422,
                  "rolling 30-day visit count already at tier visit_frequency_cap")
    v = new_entity()
    v.update({
        "enrollment_id": enrollment_id,
        "member_id": member_id,
        "provider_id": provider["id"],
        "check_in_at": ci_raw,
        "check_out_at": co_raw,
        "verification_method": method,
        "duration_minutes": int((co - ci).total_seconds() // 60),
        "fraud_score": 0,
        "status": "RECORDED",
        "_check_in_dt": ci, "_check_out_dt": co,
    })
    score, _contrib = fraud_score(v, final=False)
    v["fraud_score"] = score
    STORE.visits[v["id"]] = v
    return success(serialize(v), 201)


@bp.get("/api/visits/<vid>")
def read_visit(vid):
    require_roles(*READ_ROLES)
    v = get_visit(vid)
    member_owns(v["member_id"])
    provider_owns(v["provider_id"])
    return success(serialize(v))


@bp.get("/api/visits")
def list_visits():
    require_roles(*READ_ROLES)
    items = sort_created(STORE.visits.values())
    member_id = request.args.get("member_id")
    provider_id = request.args.get("provider_id")
    enrollment_id = request.args.get("enrollment_id")
    status = request.args.get("status")
    if is_member():
        if member_id is not None and member_id != g.user_id:
            member_owns(member_id)
        items = [v for v in items if v["member_id"] == g.user_id]
    elif member_id is not None:
        items = [v for v in items if v["member_id"] == member_id]
    if is_provider_operator():
        if provider_id is not None and provider_id != g.user_id:
            provider_owns(provider_id)
        items = [v for v in items if v["provider_id"] == g.user_id]
    elif provider_id is not None:
        items = [v for v in items if v["provider_id"] == provider_id]
    if enrollment_id is not None:
        items = [v for v in items if v["enrollment_id"] == enrollment_id]
    if status is not None:
        items = [v for v in items if v["status"] == status]
    return paginate([serialize(v) for v in items])


def _visit_wrong_state():
    return err(ERR_INVALID_REQUEST, 409, "visit is not in the required state for this transition")


@bp.post("/api/visits/<vid>/verify")
def verify_visit(vid):
    require_roles("ClaimsReviewer")
    v = get_visit(vid)
    if v["status"] != "RECORDED":
        raise _visit_wrong_state()
    provider = STORE.providers.get(v["provider_id"])
    if provider is not None:
        if provider["status"] == "TERMINATED":
            raise err(ERR_PROVIDER_TERMINATED, 409, "provider TERMINATED")
        if provider["status"] != "ACTIVE":
            raise err(ERR_PROVIDER_NOT_ACTIVE, 409,
                      "verify requires recording provider ACTIVE")
    # fraud gate: provisional score at or above the block threshold refuses verification
    if v["fraud_score"] >= FRAUD_BLOCK_THRESHOLD:
        raise err(ERR_FRAUD_HOLD, 422, "visit provisional fraud score blocks verification")
    score, contributions = fraud_score(v, final=True)
    v["fraud_score"] = score
    v["status"] = "VERIFIED"
    touch(v)
    if score >= FRAUD_FLAG_THRESHOLD:
        create_fraud_flag(v, score, contributions)
    return success(serialize(v))


@bp.post("/api/visits/<vid>/reject")
def reject_visit(vid):
    require_roles("ClaimsReviewer")
    v = get_visit(vid)
    if v["status"] != "RECORDED":
        raise _visit_wrong_state()
    v["status"] = "REJECTED"
    touch(v)
    reject_visit_cascade(v)
    return success(serialize(v))


@bp.post("/api/visits/<vid>/void")
def void_visit(vid):
    require_roles("ClaimsReviewer")
    v = get_visit(vid)
    if v["status"] != "VERIFIED":
        raise _visit_wrong_state()
    # referential guard: blocked while referenced by an open claim
    for c in STORE.claims.values():
        if vid in c.get("visit_ids", []) and c["review_status"] in (
                "SUBMITTED", "UNDER_REVIEW", "NEEDS_INFO", "APPROVED"):
            raise err(ERR_VISIT_IN_USE, 409,
                      "void blocked: visit referenced by an open claim")
    v["status"] = "VOIDED"
    touch(v)
    return success(serialize(v))
