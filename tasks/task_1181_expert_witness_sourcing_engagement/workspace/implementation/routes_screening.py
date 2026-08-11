"""Engagement requests, conflict checks, credential reviews."""
from flask import Blueprint, g

import db
from lib import (
    ApiError,
    body_dict,
    forbidden,
    get_or_404,
    invalid_state,
    list_ok,
    ok,
    opt_str,
    pagination_params,
    req_enum,
    req_str,
    req_str_list,
    require_role,
)
from services import (
    check_view,
    maybe_promote_request,
    request_view,
    review_view,
)

bp = Blueprint("screening", __name__)


@bp.post("/litigation/engagement-requests")
def create_request():
    b = body_dict()
    case_id = req_str(b, "case_id")
    specialty = req_str(b, "specialty_area")
    notes = opt_str(b, "notes", "")
    require_role("CaseManager")
    case = get_or_404(db.cases, case_id, "case")
    rec = db.base_record()
    rec.update(
        case_id=case_id,
        specialty_area=specialty,
        notes=notes,
        status="OPEN",
    )
    db.engagement_requests[rec["id"]] = rec
    if case["status"] == "INTAKE":
        case["status"] = "SOURCING"
        db.touch(case)
    return ok(request_view(rec), 201)


@bp.get("/litigation/engagement-requests/<rid>")
def get_request(rid):
    require_role("PlatformAdmin", "CaseManager", "ConflictAnalyst", "CredentialAnalyst")
    req = get_or_404(db.engagement_requests, rid, "engagement request")
    return ok(request_view(req))


@bp.post("/litigation/engagement-requests/<rid>/conflict-checks")
def create_conflict_check(rid):
    b = body_dict()
    expert_id = req_str(b, "expert_id")
    adverse = req_str_list(b, "adverse_parties")
    require_role("ConflictAnalyst")
    req = get_or_404(db.engagement_requests, rid, "engagement request")
    get_or_404(db.experts, expert_id, "expert")
    if any(
        c["engagement_request_id"] == rid and c["expert_id"] == expert_id
        for c in db.conflict_checks.values()
    ):
        raise ApiError(
            "ERR_DUPLICATE_SCREENING",
            409,
            "a conflict check already exists for this (request, expert) pair",
        )
    rec = db.base_record()
    rec.update(
        engagement_request_id=rid,
        expert_id=expert_id,
        adverse_parties=adverse,
        status="PENDING",
        resolution_rationale="",
    )
    db.conflict_checks[rec["id"]] = rec
    if req["status"] == "OPEN":
        req["status"] = "SCREENING"
        db.touch(req)
    return ok(check_view(rec), 201)


@bp.get("/litigation/engagement-requests/<rid>/conflict-checks")
def list_conflict_checks(rid):
    limit, offset = pagination_params()
    require_role("PlatformAdmin", "CaseManager", "ConflictAnalyst")
    get_or_404(db.engagement_requests, rid, "engagement request")
    recs = [
        c for c in db.conflict_checks.values() if c["engagement_request_id"] == rid
    ]
    return list_ok([check_view(c) for c in recs], limit, offset)


@bp.post("/litigation/conflict-checks/<cid>/resolve")
def resolve_conflict_check(cid):
    b = body_dict()
    outcome = req_enum(b, "outcome", ("CLEARED", "FLAGGED", "WAIVED"))
    rationale = req_str(b, "rationale")
    require_role("ConflictAnalyst", "PlatformAdmin")
    if outcome == "WAIVED" and g.user_role != "PlatformAdmin":
        forbidden("waiving a flagged conflict check is reserved to PlatformAdmin")
    cc = get_or_404(db.conflict_checks, cid, "conflict check")
    if outcome == "WAIVED":
        if cc["status"] != "FLAGGED":
            invalid_state("only a FLAGGED conflict check can be waived")
    else:
        if cc["status"] != "PENDING":
            invalid_state("only a PENDING conflict check can be resolved")
    cc["status"] = outcome
    cc["resolution_rationale"] = rationale
    db.touch(cc)
    if outcome in ("CLEARED", "WAIVED"):
        maybe_promote_request(cc["engagement_request_id"])
    return ok(check_view(cc))


@bp.post("/litigation/engagement-requests/<rid>/credential-reviews")
def create_credential_review(rid):
    b = body_dict()
    expert_id = req_str(b, "expert_id")
    require_role("CredentialAnalyst")
    req = get_or_404(db.engagement_requests, rid, "engagement request")
    get_or_404(db.experts, expert_id, "expert")
    if any(
        r["engagement_request_id"] == rid and r["expert_id"] == expert_id
        for r in db.credential_reviews.values()
    ):
        raise ApiError(
            "ERR_DUPLICATE_SCREENING",
            409,
            "a credential review already exists for this (request, expert) pair",
        )
    rec = db.base_record()
    rec.update(
        engagement_request_id=rid,
        expert_id=expert_id,
        status="PENDING",
        daubert_notes="",
    )
    db.credential_reviews[rec["id"]] = rec
    if req["status"] == "OPEN":
        req["status"] = "SCREENING"
        db.touch(req)
    return ok(review_view(rec), 201)


@bp.get("/litigation/engagement-requests/<rid>/credential-reviews")
def list_credential_reviews(rid):
    limit, offset = pagination_params()
    require_role("PlatformAdmin", "CaseManager", "CredentialAnalyst")
    get_or_404(db.engagement_requests, rid, "engagement request")
    recs = [
        r for r in db.credential_reviews.values() if r["engagement_request_id"] == rid
    ]
    return list_ok([review_view(r) for r in recs], limit, offset)


@bp.post("/litigation/credential-reviews/<cid>/resolve")
def resolve_credential_review(cid):
    b = body_dict()
    outcome = req_enum(b, "outcome", ("PASSED", "FAILED", "PASSED_WITH_CONDITIONS"))
    notes = opt_str(b, "daubert_notes", None)
    require_role("CredentialAnalyst")
    cr = get_or_404(db.credential_reviews, cid, "credential review")
    if cr["status"] != "PENDING":
        invalid_state("only a PENDING credential review can be resolved")
    cr["status"] = outcome
    if notes is not None:
        cr["daubert_notes"] = notes
    db.touch(cr)
    if outcome in ("PASSED", "PASSED_WITH_CONDITIONS"):
        maybe_promote_request(cr["engagement_request_id"])
    return ok(review_view(cr))
