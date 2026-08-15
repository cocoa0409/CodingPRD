"""SittingRequest endpoints: post/list/get/cancel."""

from datetime import timedelta
from decimal import Decimal

from flask import Blueprint, request

import clock
import db
from errors import (
    ApiError,
    ERR_FORBIDDEN,
    ERR_INSUFFICIENT_CREDIT,
    ERR_INVALID_REQUEST,
    ERR_INVALID_STATE,
    ERR_NOT_FOUND,
    ERR_PET_PROFILE_INVALID,
)
from middleware import body, paginate, require_roles
from response import created, ok
from serializers import request_view
from services.calc import (
    LATE_CANCEL_PENALTY_FRACTION,
    LATE_CANCEL_WINDOW_HOURS,
    MAX_DURATION_HOURS,
    MAX_OVERDRAFT_HOURS,
    MIN_DURATION_HOURS,
    SCORE_LATE_CANCEL,
    adjust_reliability,
    append_ledger,
    assignment_for_request,
    cancel_assignment,
    compute_offer,
)
from util import base_entity, parse_dt, round2, td_hours, touch

bp = Blueprint("sitting_requests", __name__)


def get_request_or_404(request_id):
    req = db.store["requests"].get(request_id)
    if req is None:
        raise ApiError(ERR_NOT_FOUND, 404, f"SittingRequest {request_id} does not exist")
    return req


@bp.post("/coop/sitting-requests")
def create_request():
    user_id, _ = require_roles("Member")
    data = body()
    pet_profile_id = data.get("pet_profile_id")
    if not isinstance(pet_profile_id, str) or not pet_profile_id.strip():
        raise ApiError(ERR_INVALID_REQUEST, 400, "pet_profile_id is required")
    pet = db.store["pets"].get(pet_profile_id)
    if pet is None:
        raise ApiError(
            ERR_NOT_FOUND, 404, f"PetProfile {pet_profile_id} does not exist"
        )
    try:
        start_at = parse_dt(data.get("start_at"))
        end_at = parse_dt(data.get("end_at"))
    except (TypeError, ValueError):
        raise ApiError(
            ERR_INVALID_REQUEST,
            400,
            "start_at and end_at must be valid ISO 8601 datetimes",
        )
    # Priority 14: owner credit sufficiency at posting.
    offered, multiplier = compute_offer(start_at, end_at)
    owner = db.store["members"].get(user_id)
    owner_balance = (
        owner["credit_balance_hours"] if owner is not None else round2(0)
    )
    if owner_balance - offered < -MAX_OVERDRAFT_HOURS:
        raise ApiError(
            ERR_INSUFFICIENT_CREDIT,
            402,
            "Posting would push the owner's credit balance below the -5.0 hour overdraft floor",
        )
    # Priority 15: pet profile validity (active, owned by caller, waiver accepted).
    if (
        pet["owner_member_id"] != user_id
        or not pet["active"]
        or pet["liability_waiver_accepted"] is not True
    ):
        raise ApiError(
            ERR_PET_PROFILE_INVALID,
            409,
            "Pet profile must be active, owned by the caller, and carry an accepted liability waiver",
        )
    # Priority 17: basic field validation — future start, positive duration
    # within [1, 72] hours.
    now = clock.now()
    if start_at <= now:
        raise ApiError(ERR_INVALID_REQUEST, 400, "start_at must be in the future")
    if end_at <= start_at:
        raise ApiError(ERR_INVALID_REQUEST, 400, "end_at must be after start_at")
    duration_hours = td_hours(end_at - start_at)
    if duration_hours < MIN_DURATION_HOURS or duration_hours > MAX_DURATION_HOURS:
        raise ApiError(
            ERR_INVALID_REQUEST, 400, "Request duration must be within [1, 72] hours"
        )
    instructions = data.get("instructions")
    if not isinstance(instructions, str):
        raise ApiError(ERR_INVALID_REQUEST, 400, "instructions is required")

    req = base_entity()
    req.update(
        {
            "owner_member_id": user_id,
            "pet_profile_id": pet_profile_id,
            "start_at": start_at,
            "end_at": end_at,
            "instructions": instructions,
            "credit_hours_offered": offered,
            "status": "OPEN",
            "cancelled_reason": None,
            "expires_at": start_at - timedelta(hours=4),
            "_demand_multiplier": multiplier,
        }
    )
    db.store["requests"][req["id"]] = req
    return created(request_view(req))


@bp.get("/coop/sitting-requests")
def list_requests():
    require_roles("CoopAdmin", "Member")
    items = list(db.store["requests"].values())
    status = request.args.get("status")
    if status is not None:
        items = [r for r in items if r["status"] == status]
    owner_member_id = request.args.get("owner_member_id")
    if owner_member_id is not None:
        items = [r for r in items if r["owner_member_id"] == owner_member_id]
    return paginate(items, request_view)


@bp.get("/coop/sitting-requests/<request_id>")
def get_request(request_id):
    require_roles("CoopAdmin", "Member")
    return ok(request_view(get_request_or_404(request_id)))


@bp.post("/coop/sitting-requests/<request_id>/cancel")
def cancel_request(request_id):
    user_id, _ = require_roles("Member")
    req = get_request_or_404(request_id)
    # Priority 5: state gate — only OPEN / CLAIMED / ASSIGNED can cancel.
    if req["status"] not in ("OPEN", "CLAIMED", "ASSIGNED"):
        raise ApiError(
            ERR_INVALID_STATE,
            409,
            f"Request in {req['status']} cannot be cancelled",
        )
    assignment = assignment_for_request(req["id"])
    is_owner = req["owner_member_id"] == user_id
    is_sitter = assignment is not None and assignment["sitter_member_id"] == user_id
    # Priority 6: ownership — OPEN/CLAIMED is the owner's prerogative alone;
    # once ASSIGNED either the owner or the sitter may cancel.
    if req["status"] in ("OPEN", "CLAIMED"):
        if not is_owner:
            raise ApiError(
                ERR_FORBIDDEN, 403, "Only the request owner may cancel at this stage"
            )
    else:
        if not (is_owner or is_sitter):
            raise ApiError(
                ERR_FORBIDDEN,
                403,
                "Only the request owner or the assigned sitter may cancel",
            )
    data = body()
    reason = data.get("cancelled_reason")
    if not isinstance(reason, str) or not reason.strip():
        raise ApiError(ERR_INVALID_REQUEST, 400, "cancelled_reason is required")

    # Side effects: pending claims rejected; accepted claim's assignment
    # cancelled per cancelling party with provisional reversal.
    for c in db.store["claims"].values():
        if c["sitting_request_id"] == req["id"] and c["status"] == "PENDING":
            c["status"] = "REJECTED"
            c["decided_at"] = clock.now()
            touch(c)
    if assignment is not None and assignment["status"] in (
        "CONFIRMED",
        "IN_PROGRESS",
        "COMPLETED_PENDING_REVIEW",
        "DISPUTED",
    ):
        by = "OWNER" if is_owner else "SITTER"
        cancel_assignment(assignment, by)
        # Late sitter-cancel penalty: fewer than 24h before scheduled start
        # (exactly 24h is not late).
        if by == "SITTER":
            sitter = db.store["members"][assignment["sitter_member_id"]]
            hours_until_start = td_hours(
                assignment["scheduled_start_at"] - clock.now()
            )
            if hours_until_start < LATE_CANCEL_WINDOW_HOURS:
                penalty = round2(
                    req["credit_hours_offered"] * LATE_CANCEL_PENALTY_FRACTION
                )
                append_ledger(
                    sitter,
                    "CANCELLATION_PENALTY",
                    -penalty,
                    assignment_id=assignment["id"],
                    memo="Late cancellation penalty (within 24h of scheduled start)",
                )
                adjust_reliability(sitter, SCORE_LATE_CANCEL)
    req["status"] = "CANCELLED"
    req["cancelled_reason"] = reason
    touch(req)
    return ok(request_view(req))
