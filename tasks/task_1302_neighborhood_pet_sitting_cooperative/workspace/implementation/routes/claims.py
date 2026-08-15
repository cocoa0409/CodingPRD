"""SittingClaim endpoints: create/list/get, accept (OCC-guarded), reject, withdraw."""

from flask import Blueprint, request

import clock
import db
from errors import (
    ApiError,
    ERR_FORBIDDEN,
    ERR_INVALID_REQUEST,
    ERR_INVALID_STATE,
    ERR_MEMBER_NOT_VETTED,
    ERR_NOT_FOUND,
    ERR_RELIABILITY_TOO_LOW,
    ERR_SELF_REFERENCE,
    ERR_SITTER_OVERLAP,
    ERR_STALE_VERSION,
)
from middleware import body, paginate, require_roles
from response import created, ok
from routes.requests import get_request_or_404
from serializers import claim_view
from services.calc import CLAIM_MIN_SCORE, intervals_overlap
from util import base_entity, round2, touch

bp = Blueprint("claims", __name__)


def get_claim_or_404(claim_id):
    claim = db.store["claims"].get(claim_id)
    if claim is None:
        raise ApiError(ERR_NOT_FOUND, 404, f"SittingClaim {claim_id} does not exist")
    return claim


@bp.post("/coop/sitting-requests/<request_id>/claims")
def create_claim(request_id):
    user_id, _ = require_roles("Member")
    req = get_request_or_404(request_id)
    if req["status"] != "OPEN":
        raise ApiError(ERR_INVALID_STATE, 409, "Only an OPEN request can be claimed")
    claimer = db.store["members"].get(user_id)
    if claimer is None:
        raise ApiError(
            ERR_MEMBER_NOT_VETTED, 409, "Claimant must be a VETTED member"
        )
    if claimer["reliability_score"] < CLAIM_MIN_SCORE:
        raise ApiError(
            ERR_RELIABILITY_TOO_LOW,
            409,
            "Claimant's reliability_score must be at least 30",
        )
    if user_id == req["owner_member_id"]:
        raise ApiError(
            ERR_SELF_REFERENCE, 422, "Self-dealing prohibited: claimer == owner"
        )
    data = body()
    message = data.get("message")
    if not isinstance(message, str):
        raise ApiError(ERR_INVALID_REQUEST, 400, "message is required")
    claim = base_entity()
    claim.update(
        {
            "sitting_request_id": req["id"],
            "claimer_member_id": user_id,
            "message": message,
            "status": "PENDING",
            "decided_at": None,
        }
    )
    db.store["claims"][claim["id"]] = claim
    return created(claim_view(claim))


@bp.get("/coop/sitting-requests/<request_id>/claims")
def list_claims(request_id):
    require_roles("CoopAdmin", "Member")
    get_request_or_404(request_id)
    items = [
        c for c in db.store["claims"].values() if c["sitting_request_id"] == request_id
    ]
    status = request.args.get("status")
    if status is not None:
        items = [c for c in items if c["status"] == status]
    return paginate(items, claim_view)


@bp.get("/coop/sitting-claims/<claim_id>")
def get_claim(claim_id):
    require_roles("CoopAdmin", "Member")
    return ok(claim_view(get_claim_or_404(claim_id)))


@bp.post("/coop/sitting-requests/<request_id>/claims/<claim_id>/accept")
def accept_claim(request_id, claim_id):
    user_id, _ = require_roles("Member")
    # Priority 3: path existence, left to right, with parent scoping.
    req = get_request_or_404(request_id)
    claim = get_claim_or_404(claim_id)
    if claim["sitting_request_id"] != req["id"]:
        raise ApiError(
            ERR_NOT_FOUND,
            404,
            f"SittingClaim {claim_id} does not belong to request {request_id}",
        )
    # Priority 4: OCC — expected_sitting_request_version, when present, must
    # match the request's current version.
    data = body()
    expected = data.get("expected_sitting_request_version")
    if expected is not None and expected != req["version"]:
        raise ApiError(
            ERR_STALE_VERSION,
            412,
            "expected_sitting_request_version does not match the request's current version",
        )
    # Priority 5: state gates.
    if req["status"] != "OPEN":
        raise ApiError(ERR_INVALID_STATE, 409, "Request must be OPEN to accept a claim")
    if claim["status"] != "PENDING":
        raise ApiError(ERR_INVALID_STATE, 409, "Claim must be PENDING to accept")
    # Priority 6: caller must be the request owner.
    if user_id != req["owner_member_id"]:
        raise ApiError(ERR_FORBIDDEN, 403, "Only the request owner may accept claims")
    # Priority 7: claimant must currently be VETTED.
    claimer = db.store["members"].get(claim["claimer_member_id"])
    if claimer is None or claimer["vetting_status"] != "VETTED":
        raise ApiError(ERR_MEMBER_NOT_VETTED, 409, "Claimant must be VETTED")
    # Priority 8: reliability floor, re-verified at acceptance.
    if claimer["reliability_score"] < CLAIM_MIN_SCORE:
        raise ApiError(
            ERR_RELIABILITY_TOO_LOW,
            409,
            "Claimant's reliability_score must be at least 30",
        )
    # Priority 10: no overlapping CONFIRMED / IN_PROGRESS assignment
    # (half-open intervals — adjacent sits do not conflict).
    for a in db.store["assignments"].values():
        if a["sitter_member_id"] != claimer["id"]:
            continue
        if a["status"] not in ("CONFIRMED", "IN_PROGRESS"):
            continue
        if intervals_overlap(
            a["scheduled_start_at"],
            a["scheduled_end_at"],
            req["start_at"],
            req["end_at"],
        ):
            raise ApiError(
                ERR_SITTER_OVERLAP,
                409,
                "Claimant has an overlapping CONFIRMED or IN_PROGRESS assignment",
            )
    # Acceptance cascade, in one motion.
    now = clock.now()
    claim["status"] = "ACCEPTED"
    claim["decided_at"] = now
    touch(claim)
    for other in db.store["claims"].values():
        if (
            other["sitting_request_id"] == req["id"]
            and other["id"] != claim["id"]
            and other["status"] == "PENDING"
        ):
            other["status"] = "REJECTED"
            other["decided_at"] = now
            touch(other)
    req["status"] = "ASSIGNED"  # OPEN -> CLAIMED -> ASSIGNED
    touch(req)  # request.version += 1
    assignment = base_entity()
    assignment.update(
        {
            "sitting_request_id": req["id"],
            "owner_member_id": req["owner_member_id"],
            "sitter_member_id": claimer["id"],
            "scheduled_start_at": req["start_at"],
            "scheduled_end_at": req["end_at"],
            "actual_start_at": None,
            "actual_end_at": None,
            "credit_hours_settled": None,
            "status": "CONFIRMED",
        }
    )
    db.store["assignments"][assignment["id"]] = assignment
    handoff = base_entity()
    handoff.update(
        {
            "sitting_assignment_id": assignment["id"],
            "handoff_method": None,
            "access_code_ciphertext": None,
            "handed_off_at": None,
            "returned_at": None,
            "status": "PENDING",
        }
    )
    db.store["handoffs"][handoff["id"]] = handoff
    claimer["provisional_credit_hours"] = round2(
        claimer["provisional_credit_hours"] + req["credit_hours_offered"]
    )
    touch(claimer)
    return ok(claim_view(claim))


@bp.post("/coop/sitting-requests/<request_id>/claims/<claim_id>/reject")
def reject_claim(request_id, claim_id):
    user_id, _ = require_roles("Member")
    req = get_request_or_404(request_id)
    claim = get_claim_or_404(claim_id)
    if claim["sitting_request_id"] != req["id"]:
        raise ApiError(
            ERR_NOT_FOUND,
            404,
            f"SittingClaim {claim_id} does not belong to request {request_id}",
        )
    if claim["status"] != "PENDING":
        raise ApiError(ERR_INVALID_STATE, 409, "Claim must be PENDING to reject")
    if user_id != req["owner_member_id"]:
        raise ApiError(ERR_FORBIDDEN, 403, "Only the request owner may reject claims")
    claim["status"] = "REJECTED"
    claim["decided_at"] = clock.now()
    touch(claim)
    return ok(claim_view(claim))


@bp.post("/coop/sitting-requests/<request_id>/claims/<claim_id>/withdraw")
def withdraw_claim(request_id, claim_id):
    user_id, _ = require_roles("Member")
    req = get_request_or_404(request_id)
    claim = get_claim_or_404(claim_id)
    if claim["sitting_request_id"] != req["id"]:
        raise ApiError(
            ERR_NOT_FOUND,
            404,
            f"SittingClaim {claim_id} does not belong to request {request_id}",
        )
    if claim["status"] != "PENDING":
        raise ApiError(ERR_INVALID_STATE, 409, "Claim must be PENDING to withdraw")
    if user_id != claim["claimer_member_id"]:
        raise ApiError(ERR_FORBIDDEN, 403, "Only the claimer may withdraw their claim")
    claim["status"] = "WITHDRAWN"
    touch(claim)
    return ok(claim_view(claim))
