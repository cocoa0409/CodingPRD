"""Refund state machine endpoints: submit / approve / deny / settle."""

from decimal import Decimal

from flask import Blueprint

from httpkit import (
    ApiError, authenticate, ensure_empty_body, err_invalid_state,
    err_not_found, get_body, require_member_ownership, require_roles,
    respond_object,
)
from serializers import refund_json
from services import (
    card_escrow, card_trips, insert_ledger_entry, touch,
)
from store import db
from util import D, add_months, round_hours, round_money

bp = Blueprint("refunds", __name__)

OPEN_TRIP_STATUSES = ("CONFIRMED", "DISPATCHED", "IN_FLIGHT")


def _get_refund_or_404(refund_id):
    r = db.refunds.get(refund_id)
    if r is None:
        raise err_not_found(f"Refund {refund_id} does not exist")
    return r


@bp.post("/refunds/<refundId>/submit")
def submit_refund(refundId):
    ensure_empty_body()
    authenticate()
    require_roles("Member")
    refund = _get_refund_or_404(refundId)
    card = db.cards.get(refund["card_id"])
    if card is not None:
        require_member_ownership(card["member_id"])
    # Priority 5: card must be ACTIVE.
    if card is None or card["card_status"] != "ACTIVE":
        raise ApiError("ERR_CARD_NOT_ACTIVE", 409,
                       "Refund submit requires JetCard.card_status == ACTIVE")
    # Priority 7: from-state.
    if refund["refund_status"] != "DRAFT":
        raise err_invalid_state("Refund is not in DRAFT")
    # Priority 8: no open trips on the card.
    if any(t["trip_status"] in OPEN_TRIP_STATUSES
           for t in card_trips(card["id"])):
        raise ApiError("ERR_OPEN_TRIPS_EXIST", 409,
                       "Refund submit blocked by an open trip on the card")

    # Snapshot and compute gross / penalty / net (calc refund_net_amount).
    program = db.programs.get(card["program_id"])
    escrow = card_escrow(card["id"])
    principal = escrow["principal_cents"] if escrow is not None else 0
    hours_at_request = card["hours_remaining"]
    gross = round_money(
        (hours_at_request / D(card["hours_total"])) * D(principal))
    # Priority 18: refuse to refund an empty card.
    if gross <= 0:
        raise ApiError("ERR_NOTHING_TO_REFUND", 422,
                       "Refund submit on a card with zero refundable value")
    now = db.now()
    if card["purchased_at"] is not None and now < add_months(card["purchased_at"], 12):
        penalty = round_money(
            D(gross) * D(program["early_termination_penalty_pct"]))
    else:
        penalty = 0
    net = max(0, gross - penalty)

    refund["hours_at_request"] = hours_at_request
    refund["gross_refund_cents"] = gross
    refund["penalty_cents"] = penalty
    refund["net_refund_cents"] = net
    refund["requested_at"] = now
    refund["refund_status"] = "SUBMITTED"
    touch(refund)
    return respond_object(refund_json(refund))


@bp.post("/refunds/<refundId>/approve")
def approve_refund(refundId):
    ensure_empty_body()
    authenticate()
    require_roles("Ops")
    refund = _get_refund_or_404(refundId)
    if refund["refund_status"] != "SUBMITTED":
        raise err_invalid_state("Refund is not in SUBMITTED")
    refund["refund_status"] = "APPROVED"
    touch(refund)
    return respond_object(refund_json(refund))


@bp.post("/refunds/<refundId>/deny")
def deny_refund(refundId):
    data = get_body([
        {"name": "denial_reason", "type": "string", "required": True},
    ])
    authenticate()
    require_roles("Ops")
    refund = _get_refund_or_404(refundId)
    if refund["refund_status"] != "SUBMITTED":
        raise err_invalid_state("Refund is not in SUBMITTED")
    refund["denial_reason"] = data["denial_reason"]
    refund["refund_status"] = "DENIED"
    touch(refund)
    return respond_object(refund_json(refund))


@bp.post("/refunds/<refundId>/settle")
def settle_refund(refundId):
    ensure_empty_body()
    authenticate()
    require_roles("Ops")
    refund = _get_refund_or_404(refundId)
    if refund["refund_status"] != "APPROVED":
        raise err_invalid_state("Refund is not in APPROVED")

    # Settlement cascade: money moves, card -> REFUNDED.
    card = db.cards.get(refund["card_id"])
    refund["refund_status"] = "SETTLED"
    touch(refund)
    if card is not None:
        hours_at_request = refund["hours_at_request"] or Decimal("0")
        insert_ledger_entry(card["id"], "REFUND_DEBIT", -hours_at_request)
        escrow = card_escrow(card["id"])
        if escrow is not None:
            net = refund["net_refund_cents"] or 0
            escrow["available_cents"] -= net
            escrow["released_cents"] += net
            card["escrow_balance_cents"] = escrow["available_cents"]
            touch(escrow)
        card["hours_remaining"] = round_hours(
            card["hours_remaining"] - hours_at_request)
        card["card_status"] = "REFUNDED"
        touch(card)
    return respond_object(refund_json(refund))
