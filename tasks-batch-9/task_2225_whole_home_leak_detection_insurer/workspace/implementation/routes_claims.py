"""Reimbursement claims: filing and adjudication."""
from datetime import timedelta

from flask import Blueprint, request

import auth
import clock
import db
import serializers as ser
import services
from config import (
    CLAIM_DECISIONS,
    CLAIM_DENIAL_REASONS,
    CLAIM_STATUSES,
    CLAIM_SUBMISSION_WINDOW_DAYS,
    CLAIM_TYPES,
    ROLE_ADJUSTER,
    ROLE_ADMIN,
    ROLE_ANALYST,
    ROLE_HOMEOWNER,
)
from errors import ApiError
from response import created, enum_filter, listing, ok, page_params, str_filter
from util import get_body, opt_string, req_enum, req_int, req_string

bp = Blueprint("claims", __name__)

DECISION_ROLE = {
    "BEGIN_REVIEW": ROLE_ADJUSTER,
    "REQUEST_INFO": ROLE_ADJUSTER,
    "SUPPLY_INFO": ROLE_HOMEOWNER,
    "APPROVE": ROLE_ADJUSTER,
    "DENY": ROLE_ADJUSTER,
    "PAY": ROLE_ANALYST,
}

DECISION_FROM = {
    "BEGIN_REVIEW": "SUBMITTED",
    "REQUEST_INFO": "UNDER_REVIEW",
    "SUPPLY_INFO": "INFO_REQUESTED",
    "APPROVE": "UNDER_REVIEW",
    "DENY": "UNDER_REVIEW",
    "PAY": "APPROVED",
}


def _claim(cid):
    row = db.claims.get(cid)
    if row is None:
        raise ApiError("ERR_CLAIM_NOT_FOUND", "No reimbursement claim exists with id %s." % cid)
    return row


# ---------------------------------------------------------------- reads
@bp.get("/claims/<cid>")
def get_claim(cid):
    actor = auth.guard(ROLE_HOMEOWNER, ROLE_ADJUSTER, ROLE_ANALYST, ROLE_ADMIN)
    row = _claim(cid)
    auth.own_claim(actor, row)
    return ok(ser.claim(row))


@bp.get("/claims")
def list_claims():
    actor = auth.guard(ROLE_HOMEOWNER, ROLE_ADJUSTER, ROLE_ANALYST, ROLE_ADMIN)
    limit, offset = page_params()
    policy_id = str_filter("policy_id")
    device_id = str_filter("device_id")
    event_id = str_filter("anomaly_event_id")
    status = enum_filter("status", CLAIM_STATUSES)
    rows = list(db.claims.values())
    if actor.is_homeowner:
        rows = [c for c in rows if db.owner_of_claim(c) == actor.user_id]
    if policy_id is not None:
        rows = [c for c in rows if c["policy_id"] == policy_id]
    if device_id is not None:
        rows = [c for c in rows if c["device_id"] == device_id]
    if event_id is not None:
        rows = [c for c in rows if c.get("anomaly_event_id") == event_id]
    if status is not None:
        rows = [c for c in rows if c["status"] == status]
    rows = db.sort_rows(rows, lambda c: c["created_at"])
    return listing(rows, ser.claim, limit, offset)


# ---------------------------------------------------------------- writes
@bp.post("/claims")
def file_claim():
    actor = auth.guard(ROLE_HOMEOWNER, ROLE_ADMIN)
    body = get_body(request)
    policy_id = req_string(body, "policy_id")
    device_id = req_string(body, "device_id")
    claim_type = req_enum(body, "claim_type", CLAIM_TYPES)
    loss = req_int(body, "documented_loss_cents", minimum=1)
    event_id = opt_string(body, "anomaly_event_id")

    device_row = db.devices.get(device_id)
    if device_row is None:
        raise ApiError("ERR_DEVICE_NOT_FOUND", "No device exists with id %s." % device_id)
    event = None
    if event_id is not None:
        event = db.anomaly_events.get(event_id)
        if event is None:
            raise ApiError(
                "ERR_ANOMALY_EVENT_NOT_FOUND", "No anomaly event exists with id %s." % event_id
            )
    policy_row = db.policies.get(policy_id)
    if policy_row is None:
        raise ApiError("ERR_POLICY_NOT_FOUND", "No policy exists with id %s." % policy_id)

    auth.own_device(actor, device_row)
    owner_id = db.owner_of_device(device_row)
    auth.alive_id(owner_id)

    if policy_row["credit_state"] == "TERMINATED":
        raise ApiError("ERR_POLICY_TERMINATED", "This policy has been terminated.")

    if claim_type == "WATER_DAMAGE":
        if event is None:
            raise ApiError(
                "ERR_NO_QUALIFYING_EVENT", "A water-damage claim must name a qualifying event."
            )
    if event is not None:
        if event["device_id"] != device_id:
            raise ApiError(
                "ERR_NO_QUALIFYING_EVENT", "The named event does not belong to the named device."
            )
        if device_row["property_id"] != policy_row["property_id"]:
            raise ApiError(
                "ERR_NO_QUALIFYING_EVENT",
                "The named device is not insured by the named policy.",
            )
    elif device_row["property_id"] != policy_row["property_id"]:
        raise ApiError(
            "ERR_NO_QUALIFYING_EVENT", "The named device is not insured by the named policy."
        )

    if event is not None:
        deadline = event["detected_at"] + timedelta(days=CLAIM_SUBMISSION_WINDOW_DAYS)
        if clock.now() > deadline:
            raise ApiError(
                "ERR_CLAIM_WINDOW_EXPIRED", "The filing window for this event has closed."
            )
        for existing in db.claims.values():
            if (
                existing.get("anomaly_event_id") == event_id
                and existing["claim_type"] == claim_type
                and existing["status"] != "DENIED"
            ):
                raise ApiError(
                    "ERR_DUPLICATE_CLAIM",
                    "A live claim of this type already exists for the named event.",
                )

    row = {
        "policy_id": policy_id,
        "device_id": device_id,
        "anomaly_event_id": event_id,
        "claim_type": claim_type,
        "documented_loss_cents": loss,
        "submitted_by_user_id": owner_id,
        "status": "SUBMITTED",
        "payout_variant": None,
        "approved_payout_cents": 0,
        "deductible_applied_cents": 0,
        "info_request_count": 0,
        "decided_by_user_id": None,
        "decided_at": None,
        "denial_reason": None,
        "paid_at": None,
    }
    db.insert(db.claims, row)
    return created(ser.claim(row))


@bp.post("/claims/<cid>/decision")
def decide(cid):
    actor = auth.guard(ROLE_ADJUSTER, ROLE_HOMEOWNER, ROLE_ANALYST)
    claim_row = _claim(cid)
    body = get_body(request)
    decision = req_enum(body, "decision", CLAIM_DECISIONS)
    reason = None
    if decision == "DENY":
        reason = req_enum(body, "denial_reason", CLAIM_DENIAL_REASONS)

    if actor.role != DECISION_ROLE[decision]:
        raise ApiError(
            "ERR_UNAUTHORIZED",
            "The %s verb is reserved to %s." % (decision, DECISION_ROLE[decision]),
        )

    if decision == "SUPPLY_INFO":
        if actor.user_id != claim_row["submitted_by_user_id"]:
            raise ApiError(
                "ERR_NOT_RESOURCE_OWNER",
                "Only the homeowner who filed this claim may supply information.",
            )
    policy_row = db.policies[claim_row["policy_id"]]
    auth.alive_id(db.owner_of_claim(claim_row))

    if claim_row["status"] != DECISION_FROM[decision]:
        raise ApiError(
            "ERR_CLAIM_NOT_REVIEWABLE",
            "%s is not legal from status %s." % (decision, claim_row["status"]),
        )
    if decision in ("BEGIN_REVIEW", "APPROVE") and policy_row["credit_state"] == "TERMINATED":
        raise ApiError("ERR_POLICY_TERMINATED", "This policy has been terminated.")

    now = clock.now()
    if decision == "BEGIN_REVIEW":
        claim_row["status"] = "UNDER_REVIEW"
    elif decision == "REQUEST_INFO":
        claim_row["status"] = "INFO_REQUESTED"
        claim_row["info_request_count"] = claim_row["info_request_count"] + 1
    elif decision == "SUPPLY_INFO":
        claim_row["status"] = "UNDER_REVIEW"
    elif decision == "DENY":
        claim_row["status"] = "DENIED"
        claim_row["denial_reason"] = reason
        claim_row["decided_by_user_id"] = actor.user_id
        claim_row["decided_at"] = now
        claim_row["approved_payout_cents"] = 0
    elif decision == "APPROVE":
        device_row = db.devices[claim_row["device_id"]]
        if (
            claim_row["claim_type"] == "WARRANTY_DEVICE"
            and device_row.get("install_verified_by_user_id") == actor.user_id
        ):
            raise ApiError(
                "ERR_SEGREGATION_OF_DUTIES",
                "The technician who verified the install may not approve its warranty claim.",
            )
        variant, applied, payout = services.payout_for(claim_row, policy_row)
        if services.cap_exceeded(policy_row, payout):
            raise ApiError(
                "ERR_ANNUAL_PAYOUT_CAP_EXCEEDED",
                "This payout would breach the policy's annual payout cap.",
            )
        claim_row["status"] = "APPROVED"
        claim_row["payout_variant"] = variant
        claim_row["deductible_applied_cents"] = applied
        claim_row["approved_payout_cents"] = payout
        claim_row["decided_by_user_id"] = actor.user_id
        claim_row["decided_at"] = now
    else:  # PAY
        if claim_row.get("decided_by_user_id") == actor.user_id:
            raise ApiError(
                "ERR_SEGREGATION_OF_DUTIES",
                "The adjuster who approved this payout may not disburse it.",
            )
        if services.cap_exceeded(policy_row, claim_row["approved_payout_cents"]):
            raise ApiError(
                "ERR_ANNUAL_PAYOUT_CAP_EXCEEDED",
                "This payment would breach the policy's annual payout cap.",
            )
        claim_row["status"] = "PAID"
        claim_row["paid_at"] = now
        policy_row["paid_payout_cents_total"] = (
            policy_row["paid_payout_cents_total"] + claim_row["approved_payout_cents"]
        )
        db.touch(policy_row)
    db.touch(claim_row)
    return ok(ser.claim(claim_row))
