"""Payout opening (the most heavily gated write) and lifecycle transitions."""

from flask import Blueprint, request

import db
import domain
from core import (ApiError, auth, body, err_invalid_request, err_invalid_state,
                  err_not_found, err_ownership, ok_obj, opt_str, paginate,
                  pagination, req_enum, require_role)

bp = Blueprint("payouts", __name__)

ACTIONS = ("PROCESS", "SETTLE_SUCCESS", "SETTLE_FAILURE", "RETRY", "CANCEL")
ADMIN_ACTIONS = ("PROCESS", "SETTLE_SUCCESS", "SETTLE_FAILURE")
CREATOR_ACTIONS = ("RETRY", "CANCEL")


@bp.post("/api/channels/<channel_id>/payouts")
def open_payout(channel_id):
    uid, role = auth()
    body()  # no inputs; a malformed body still fails well-formedness
    require_role(role, ("Creator",))
    ch = domain.get_channel(channel_id)
    if ch is None:
        raise err_not_found("Channel not found")
    if uid != ch["id"]:
        raise err_ownership()
    # Gate chain in §2.9 order: suspension(7) -> in-flight(18) -> tax(24)
    # -> non-empty sweep(25) -> threshold(26, inclusive).
    if domain.monetization_posture(ch) == "SUSPENDED":
        raise ApiError("ERR_CHANNEL_SUSPENDED", 409,
                       "Channel monetization_posture is SUSPENDED")
    if any(p["payout_status"] in domain.IN_FLIGHT_PAYOUT
           for p in domain.channel_payouts(channel_id)):
        raise ApiError("ERR_PAYOUT_IN_FLIGHT", 409,
                       "Another payout of this channel is already in flight")
    form = domain.current_tax_form(ch)
    if form is None or form["tax_status"] != "VERIFIED":
        raise ApiError("ERR_TAX_FORM_NOT_VERIFIED", 402,
                       "The channel's current tax form is missing or not VERIFIED")
    if not domain.unswept_cleared_events(channel_id):
        raise ApiError("ERR_NO_ELIGIBLE_REVENUE", 422,
                       "No eligible CLEARED revenue event exists to sweep")
    if domain.balance_payable_cents(channel_id) < ch["payout_threshold_cents"]:
        raise ApiError("ERR_BELOW_PAYOUT_THRESHOLD", 422,
                       "balance_payable_cents is strictly below payout_threshold_cents")
    payout = domain.open_payout(ch)
    return ok_obj(domain.payout_json(payout), status=201)


@bp.get("/api/channels/<channel_id>/payouts")
def list_payouts(channel_id):
    uid, role = auth()
    limit, offset = pagination()
    require_role(role, ("PlatformAdmin", "Creator"))
    ch = domain.get_channel(channel_id)
    if ch is None:
        raise err_not_found("Channel not found")
    payouts = domain.channel_payouts(channel_id)
    status = request.args.get("payout_status")
    if status is not None:
        payouts = [p for p in payouts if p["payout_status"] == status]
    return paginate(payouts, limit, offset, domain.payout_json)


@bp.post("/api/payouts/<payout_id>/transition")
def transition_payout(payout_id):
    uid, role = auth()
    b = body()
    action = req_enum(b, "action", ACTIONS)
    failure_reason = opt_str(b, "failure_reason")
    if action == "SETTLE_FAILURE" and not failure_reason:
        raise err_invalid_request("Field 'failure_reason' is required for SETTLE_FAILURE")
    # Per-action role map (priority 3).
    if action in ADMIN_ACTIONS:
        require_role(role, ("PlatformAdmin",))
    else:
        require_role(role, ("Creator",))
    p = db.store.payouts.get(payout_id)
    if p is None:
        raise err_not_found("Payout not found")
    if role == "Creator" and uid != p["channel_id"]:
        raise err_ownership()

    if action == "PROCESS":
        if p["payout_status"] != "SCHEDULED":
            raise err_invalid_state("Only a SCHEDULED payout can move to PROCESSING")
        p["payout_status"] = "PROCESSING"

    elif action == "SETTLE_SUCCESS":
        if p["payout_status"] != "PROCESSING":
            raise err_invalid_state("Only a PROCESSING payout can settle PAID")
        p["payout_status"] = "PAID"  # lifetime_paid_cents derives from PAID payouts

    elif action == "SETTLE_FAILURE":
        if p["payout_status"] != "PROCESSING":
            raise err_invalid_state("Only a PROCESSING payout can settle FAILED")
        p["payout_status"] = "FAILED"
        p["failure_reason"] = failure_reason

    elif action == "RETRY":
        if p["payout_status"] != "FAILED":
            raise err_invalid_state("Only a FAILED payout can be retried")
        # State-level retry cap fires before any fiscal gate.
        if p["retry_count"] >= 3:
            raise ApiError("ERR_RETRY_LIMIT_REACHED", 409,
                           "Payout retry_count has reached the cap of 3")
        ch = domain.get_channel(p["channel_id"])
        if domain.monetization_posture(ch) == "SUSPENDED":
            raise ApiError("ERR_CHANNEL_SUSPENDED", 409,
                           "Channel monetization_posture is SUSPENDED")
        form = domain.current_tax_form(ch)
        if form is None or form["tax_status"] != "VERIFIED":
            raise ApiError("ERR_TAX_FORM_NOT_VERIFIED", 402,
                           "The channel's current tax form is missing or not VERIFIED")
        p["payout_status"] = "SCHEDULED"
        p["retry_count"] += 1
        p["failure_reason"] = None

    elif action == "CANCEL":
        if p["payout_status"] not in ("SCHEDULED", "HELD"):
            raise err_invalid_state("Only a SCHEDULED or HELD payout can be cancelled")
        # Compensating restore: balance_payable_cents rises by amount_cents via
        # the ledger derivation once the payout leaves the in-flight set, and
        # the swept events are released back to the eligible pool.
        p["payout_status"] = "CANCELLED"
        p["hold_reason"] = "NONE"
        domain.unsweep_payout(p)

    db.touch(p)
    return ok_obj(domain.payout_json(p))
