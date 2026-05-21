"""/foia/fee-assessments — estimate, accept, waive."""

from __future__ import annotations

from flask import Blueprint, g

from ..auth import require_auth
from ..envelope import ok_object
from ..errors import (
    ApiError,
    ERR_FEE_ASSESSMENT_EXISTS,
    ERR_FK_NOT_FOUND,
    ERR_FORBIDDEN,
    ERR_INVALID_STATE,
    ERR_NOT_FOUND,
    ERR_WAIVER_NOT_ELIGIBLE,
)
from ..serializers import serialize_fee_assessment
from ..services.fees import calc_fee_estimate
from ..store import append_audit, store
from ..util import require_int, require_json_body, require_number, require_str


fee_assessments_bp = Blueprint("fee_assessments", __name__)


def _get_assessment(fid: str) -> dict:
    fa = store.fee_assessments.get(fid)
    if fa is None:
        raise ApiError(ERR_NOT_FOUND, 404, "Fee assessment not found.")
    return fa


@fee_assessments_bp.post("/foia/fee-assessments")
@require_auth({"Officer"})
def create_fee_assessment():
    payload = require_json_body()
    request_id = require_str(payload, "request_id", max_len=200)
    estimated_pages = require_int(payload, "estimated_pages", minimum=0)
    estimated_search_hours = require_number(payload, "estimated_search_hours", minimum=0)
    estimated_review_hours = require_number(payload, "estimated_review_hours", minimum=0)

    req = store.requests.get(request_id)
    if req is None:
        raise ApiError(ERR_FK_NOT_FOUND, 404, "Referenced request does not exist.")
    with store.lock:
        for existing in store.fee_assessments.values():
            if existing["request_id"] == request_id:
                raise ApiError(
                    ERR_FEE_ASSESSMENT_EXISTS,
                    409,
                    "A fee assessment already exists for this request.",
                )

        entity = {
            "request_id": request_id,
            "tier_at_assessment": None,
            "estimated_pages": estimated_pages,
            "estimated_search_hours": estimated_search_hours,
            "estimated_review_hours": estimated_review_hours,
            "estimate_total_cents": 0,
            "final_total_cents": 0,
            "status": "DRAFT",
        }
        store.stamp_create(entity)
        store.fee_assessments[entity["id"]] = entity
    return ok_object(serialize_fee_assessment(entity), status=201)


@fee_assessments_bp.post("/foia/fee-assessments/<fid>/estimate")
@require_auth({"Officer"})
def estimate(fid: str):
    fa = _get_assessment(fid)
    with store.lock:
        if fa["status"] != "DRAFT":
            raise ApiError(ERR_INVALID_STATE, 409, "Assessment must be DRAFT.")
        req = store.requests.get(fa["request_id"])
        if req is None or req["status"] != "ACKNOWLEDGED":
            raise ApiError(
                ERR_INVALID_STATE,
                409,
                "Linked request must be ACKNOWLEDGED to estimate.",
            )
        requester = store.requesters.get(req["requester_id"])
        if requester is None:
            raise ApiError(ERR_INVALID_STATE, 409, "Linked requester missing.")
        tier = requester["requester_tier"]
        fa["tier_at_assessment"] = tier
        fa["estimate_total_cents"] = calc_fee_estimate(
            tier=tier,
            estimated_pages=int(fa["estimated_pages"]),
            estimated_search_hours=float(fa["estimated_search_hours"]),
            estimated_review_hours=float(fa["estimated_review_hours"]),
        )
        fa["status"] = "ESTIMATED"
        store.bump(fa)
        append_audit(
            subject_type="FEE_ASSESSMENT",
            subject_id=fa["id"],
            event_code="FEE_ESTIMATED",
            actor_role=g.user_role,
            actor_id=g.user_id,
            payload={
                "tier": tier,
                "estimate_total_cents": fa["estimate_total_cents"],
            },
        )
    return ok_object(serialize_fee_assessment(fa))


@fee_assessments_bp.post("/foia/fee-assessments/<fid>/accept")
@require_auth({"Requester"})
def accept(fid: str):
    fa = _get_assessment(fid)
    with store.lock:
        if fa["status"] != "ESTIMATED":
            raise ApiError(ERR_INVALID_STATE, 409, "Assessment must be ESTIMATED.")
        req = store.requests.get(fa["request_id"])
        if req is None:
            raise ApiError(ERR_INVALID_STATE, 409, "Linked request missing.")
        if g.user_id != req["requester_id"]:
            raise ApiError(ERR_FORBIDDEN, 403, "Only the owning requester may accept.")
        fa["status"] = "ACCEPTED"
        store.bump(fa)
        req["fee_estimate_accepted"] = True
        store.bump(req)
        append_audit(
            subject_type="FEE_ASSESSMENT",
            subject_id=fa["id"],
            event_code="FEE_ACCEPTED",
            actor_role=g.user_role,
            actor_id=g.user_id,
            payload={"request_id": req["id"]},
        )
    return ok_object(serialize_fee_assessment(fa))


@fee_assessments_bp.post("/foia/fee-assessments/<fid>/waive")
@require_auth({"Officer"})
def waive(fid: str):
    fa = _get_assessment(fid)
    with store.lock:
        if fa["status"] != "ESTIMATED":
            raise ApiError(ERR_INVALID_STATE, 409, "Assessment must be ESTIMATED.")
        req = store.requests.get(fa["request_id"])
        if req is None:
            raise ApiError(ERR_INVALID_STATE, 409, "Linked request missing.")
        if not req.get("fee_waiver_requested"):
            raise ApiError(
                ERR_WAIVER_NOT_ELIGIBLE,
                422,
                "Request did not ask for a fee waiver.",
            )
        requester = store.requesters.get(req["requester_id"])
        if requester is None or requester["requester_tier"] not in (
            "EDUCATIONAL_NONCOMMERCIAL",
            "PUBLIC_INTEREST",
        ):
            raise ApiError(
                ERR_WAIVER_NOT_ELIGIBLE,
                422,
                "Fee waiver requires a non-commercial tier.",
            )
        fa["status"] = "WAIVED"
        fa["estimate_total_cents"] = 0
        store.bump(fa)
        req["fee_waiver_granted"] = True
        store.bump(req)
        append_audit(
            subject_type="FEE_ASSESSMENT",
            subject_id=fa["id"],
            event_code="FEE_ESTIMATED",
            actor_role=g.user_role,
            actor_id=g.user_id,
            payload={"outcome": "WAIVED"},
        )
    return ok_object(serialize_fee_assessment(fa))


@fee_assessments_bp.get("/foia/fee-assessments/<fid>")
@require_auth({"Officer", "Requester"})
def get_assessment(fid: str):
    fa = _get_assessment(fid)
    if g.user_role == "Requester":
        # Owner-only read.
        req = store.requests.get(fa["request_id"])
        if req is None or req["requester_id"] != g.user_id:
            raise ApiError(ERR_FORBIDDEN, 403, "Requester may only read own assessments.")
    return ok_object(serialize_fee_assessment(fa))
