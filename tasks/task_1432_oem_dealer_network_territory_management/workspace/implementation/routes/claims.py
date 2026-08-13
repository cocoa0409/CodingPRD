"""WarrantyClaim endpoints: submit, decide, pay, flag-audit, chargeback (with
the suspension cascade), dispute, resolve-dispute."""

from __future__ import annotations

from datetime import timedelta
from flask import Blueprint

import db
from errors import (
    raise_err,
    ERR_INVALID_REQUEST,
    ERR_DEALER_NOT_FOUND,
    ERR_CLAIM_NOT_FOUND,
    ERR_DEALER_IDENTITY_MISMATCH,
    ERR_CLAIM_INVALID_STATE,
    ERR_AUDIT_WINDOW_CLOSED,
)
from middleware import require_roles
from response import success_object, success_list
from services.calculations import claim_amount_cents
from services.cascades import requeue_leads_for_dealer
from services.serializers import serialize, serialize_list
from util import (
    apply_filters,
    get_json_body,
    paginate,
    parse_iso8601,
    parse_pagination,
    require_enum,
    require_int,
    require_number,
    require_string,
    sort_by_created_at,
)

bp = Blueprint("claims", __name__)

AUDIT_WINDOW_DAYS = 365
CHARGEBACK_SUSPEND_THRESHOLD = 50000


def get_claim_or_404(claim_id: str) -> dict:
    claim = db.claims.get(claim_id)
    if claim is None:
        raise_err(ERR_CLAIM_NOT_FOUND, "Warranty claim id does not exist")
    return claim


@bp.route("/warranty-claims", methods=["POST"])
@require_roles("DealerUser")
def create_claim(_user_id: str, _role: str):
    body = get_json_body()
    dealer_id = require_string(body, "dealer_id")
    unit_serial = require_string(body, "unit_serial")
    parts_cost_cents = require_int(body, "parts_cost_cents")
    if parts_cost_cents < 0:
        raise_err(ERR_INVALID_REQUEST, "parts_cost_cents must be >= 0")
    labor_hours = require_number(body, "labor_hours")
    if labor_hours < 0:
        raise_err(ERR_INVALID_REQUEST, "labor_hours must be >= 0")
    failure_description = require_string(body, "failure_description")

    # Priority 4 existence.
    dealer = db.dealers.get(dealer_id)
    if dealer is None:
        raise_err(ERR_DEALER_NOT_FOUND, "Dealer id does not exist")

    # Priority 5 ownership.
    if dealer_id != _user_id:
        raise_err(ERR_DEALER_IDENTITY_MISMATCH, "DealerUser body dealer_id != X-User-ID")

    claim = {
        "dealer_id": dealer_id,
        "unit_serial": unit_serial,
        "parts_cost_cents": parts_cost_cents,
        "labor_hours": labor_hours,
        "failure_description": failure_description,
        "claim_amount_cents": claim_amount_cents(parts_cost_cents, labor_hours, dealer["tier"]),
        "paid_amount_cents": None,
        "paid_at": None,
        "chargeback_amount_cents": None,
        "status": "SUBMITTED",
    }
    db.stamp_new(claim)
    db.claims[claim["id"]] = claim
    return success_object(serialize(claim), 201)


@bp.route("/warranty-claims", methods=["GET"])
@require_roles("Any")
def list_claims(_user_id: str, _role: str):
    limit, offset = parse_pagination()
    items = sort_by_created_at(list(db.claims.values()))
    items = apply_filters(items, ["dealer_id", "status"])
    page, total = paginate(items, limit, offset)
    return success_list(serialize_list(page), limit, offset, total)


@bp.route("/warranty-claims/<claim_id>", methods=["GET"])
@require_roles("Any")
def get_claim(claim_id: str, _user_id: str, _role: str):
    claim = get_claim_or_404(claim_id)
    return success_object(serialize(claim))


@bp.route("/warranty-claims/<claim_id>/decide", methods=["POST"])
@require_roles("OemAuditor")
def decide_claim(claim_id: str, _user_id: str, _role: str):
    body = get_json_body()
    decision = require_enum(body, "decision", {"APPROVE", "REJECT"})
    claim = get_claim_or_404(claim_id)
    if claim["status"] != "SUBMITTED":
        raise_err(ERR_CLAIM_INVALID_STATE, "decide requires claim SUBMITTED")
    claim["status"] = "APPROVED" if decision == "APPROVE" else "REJECTED"
    db.touch(claim)
    return success_object(serialize(claim))


@bp.route("/warranty-claims/<claim_id>/pay", methods=["POST"])
@require_roles("OemAuditor")
def pay_claim(claim_id: str, _user_id: str, _role: str):
    claim = get_claim_or_404(claim_id)
    if claim["status"] != "APPROVED":
        raise_err(ERR_CLAIM_INVALID_STATE, "pay requires claim APPROVED")
    claim["status"] = "PAID"
    claim["paid_amount_cents"] = claim["claim_amount_cents"]
    claim["paid_at"] = db.get_current_utc()
    db.touch(claim)
    return success_object(serialize(claim))


@bp.route("/warranty-claims/<claim_id>/flag-audit", methods=["POST"])
@require_roles("OemAuditor")
def flag_audit(claim_id: str, _user_id: str, _role: str):
    claim = get_claim_or_404(claim_id)
    # Priority 6 state.
    if claim["status"] != "PAID":
        raise_err(ERR_CLAIM_INVALID_STATE, "flag-audit requires claim PAID")
    # Priority 9 temporal: within 365 days of payment.
    paid_at = parse_iso8601(claim["paid_at"], "paid_at")
    if db.clock_datetime() > paid_at + timedelta(days=AUDIT_WINDOW_DAYS):
        raise_err(ERR_AUDIT_WINDOW_CLOSED, "flag-audit requires current logical datetime <= paid_at + 365 days")
    claim["status"] = "AUDIT_FLAGGED"
    db.touch(claim)
    return success_object(serialize(claim))


@bp.route("/warranty-claims/<claim_id>/chargeback", methods=["POST"])
@require_roles("OemAuditor")
def chargeback_claim(claim_id: str, _user_id: str, _role: str):
    body = get_json_body()
    finding = require_enum(body, "finding", {"FULL", "PARTIAL"})
    claim = get_claim_or_404(claim_id)
    if claim["status"] != "AUDIT_FLAGGED":
        raise_err(ERR_CLAIM_INVALID_STATE, "chargeback requires claim AUDIT_FLAGGED")

    if finding == "FULL":
        amount = claim["claim_amount_cents"]
    else:  # PARTIAL claws back only the labor portion
        amount = claim["claim_amount_cents"] - claim["parts_cost_cents"]

    claim["chargeback_amount_cents"] = amount
    claim["status"] = "CHARGED_BACK"
    db.touch(claim)

    # Link 1: balance accrues; link 2: threshold suspension; link 3: leads.
    dealer = db.dealers.get(claim["dealer_id"])
    if dealer is not None:
        dealer["chargeback_balance_cents"] += amount
        suspended = False
        if (
            dealer["chargeback_balance_cents"] >= CHARGEBACK_SUSPEND_THRESHOLD
            and dealer["status"] == "ACTIVE"
        ):
            dealer["status"] = "SUSPENDED"
            suspended = True
        db.touch(dealer)
        if suspended:
            requeue_leads_for_dealer(dealer["id"])
    return success_object(serialize(claim))


@bp.route("/warranty-claims/<claim_id>/dispute", methods=["POST"])
@require_roles("DealerUser")
def dispute_claim(claim_id: str, _user_id: str, _role: str):
    claim = get_claim_or_404(claim_id)
    # Priority 5 ownership (before state per PRD 2.8 ordering).
    if claim["dealer_id"] != _user_id:
        raise_err(ERR_DEALER_IDENTITY_MISMATCH, "Disputing DealerUser is not the claim's dealer")
    # Priority 6 state.
    if claim["status"] != "CHARGED_BACK":
        raise_err(ERR_CLAIM_INVALID_STATE, "dispute requires claim CHARGED_BACK")
    claim["status"] = "DISPUTED"
    db.touch(claim)
    return success_object(serialize(claim))


@bp.route("/warranty-claims/<claim_id>/resolve-dispute", methods=["POST"])
@require_roles("OemAuditor")
def resolve_dispute(claim_id: str, _user_id: str, _role: str):
    body = get_json_body()
    outcome = require_enum(body, "outcome", {"UPHELD", "DENIED"})
    claim = get_claim_or_404(claim_id)
    if claim["status"] != "DISPUTED":
        raise_err(ERR_CLAIM_INVALID_STATE, "resolve-dispute requires claim DISPUTED")

    if outcome == "UPHELD":
        # Dealer wins: balance reversed, chargeback amount cleared, back to PAID.
        dealer = db.dealers.get(claim["dealer_id"])
        if dealer is not None:
            dealer["chargeback_balance_cents"] -= claim["chargeback_amount_cents"] or 0
            db.touch(dealer)
        claim["chargeback_amount_cents"] = None
        claim["status"] = "PAID"
    else:
        # DENIED: chargeback stands, no balance change.
        claim["status"] = "CHARGED_BACK"
    db.touch(claim)
    return success_object(serialize(claim))
