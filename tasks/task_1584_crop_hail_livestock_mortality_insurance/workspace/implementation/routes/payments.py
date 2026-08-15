"""Indemnity payment endpoints (PRD 3.8): issue, clear, void."""

from __future__ import annotations

from datetime import timedelta

from flask import Blueprint

import db
from errors import (
    raise_err, ERR_INVALID_STATE, ERR_CLAIM_NOT_IN_APPROVED,
    ERR_PAYMENT_ALREADY_ISSUED, ERR_VOID_WINDOW_EXPIRED,
)
from middleware import require_roles
from response import success_object, success_list
from routes.common import (
    resolve_carrier, resolve_policy, resolve_claim, resolve_payment,
)
from serializers import indemnity_payment_view
from services import core
from util import (
    get_json_body, reject_unknown_fields, require_enum,
    parse_pagination, paginate, sort_created, dt,
)

bp = Blueprint("payments", __name__)

LIST_ROLES = ("PlatformAdmin", "Underwriter", "ClaimsApprover")

CREATE_FIELDS = {"payment_method"}


@bp.route("/carriers/<carrierId>/policies/<policyId>/claims/<claimId>/indemnity-payments",
          methods=["POST"])
@require_roles("ClaimsApprover")
def create_indemnity_payment(carrierId: str, policyId: str, claimId: str,
                             _user_id: str, _role: str):
    carrier = resolve_carrier(carrierId)
    policy = resolve_policy(carrier["id"], policyId)
    claim = resolve_claim(policy["id"], claimId)
    body = get_json_body()
    reject_unknown_fields(body, CREATE_FIELDS)
    payment_method = require_enum(body, "payment_method", {"ACH", "CHECK", "WIRE"})

    # A live (non-VOID) payment implies the claim already moved to PAID, so
    # the double-issue guard must run first to stay reachable (PRD 3.8).
    for existing in db.indemnity_payments.values():
        if existing["claim_id"] == claim["id"] and existing["status"] != "VOID":
            raise_err(ERR_PAYMENT_ALREADY_ISSUED,
                      "A non-VOID IndemnityPayment already exists for this claim")
    if claim["claim_state"] != "APPROVED":
        raise_err(ERR_CLAIM_NOT_IN_APPROVED,
                  "indemnity-payments require claim_state APPROVED")

    now = carrier["current_utc"]
    payment = db.stamp_new({
        "claim_id": claim["id"],
        "amount_cents": claim["final_indemnity_cents"],
        "issued_at": now,
        "payment_method": payment_method,
        "status": "ISSUED",
    }, now)
    db.indemnity_payments[payment["id"]] = payment

    claim["claim_state"] = "PAID"
    db.touch(claim, now)
    return success_object(indemnity_payment_view(payment), 201)


@bp.route("/carriers/<carrierId>/policies/<policyId>/claims/<claimId>/indemnity-payments",
          methods=["GET"])
@require_roles(*LIST_ROLES)
def list_indemnity_payments(carrierId: str, policyId: str, claimId: str,
                            _user_id: str, _role: str):
    carrier = resolve_carrier(carrierId)
    policy = resolve_policy(carrier["id"], policyId)
    claim = resolve_claim(policy["id"], claimId)
    items = [p for p in db.indemnity_payments.values() if p["claim_id"] == claim["id"]]
    items = sort_created(items)
    limit, offset = parse_pagination()
    page, total = paginate(items, limit, offset)
    return success_list([indemnity_payment_view(p) for p in page], limit, offset, total)


@bp.route("/carriers/<carrierId>/policies/<policyId>/claims/<claimId>/indemnity-payments/<paymentId>/clear",
          methods=["POST"])
@require_roles("ClaimsApprover")
def clear_indemnity_payment(carrierId: str, policyId: str, claimId: str,
                            paymentId: str, _user_id: str, _role: str):
    carrier = resolve_carrier(carrierId)
    policy = resolve_policy(carrier["id"], policyId)
    claim = resolve_claim(policy["id"], claimId)
    payment = resolve_payment(claim["id"], paymentId)
    body = get_json_body()
    reject_unknown_fields(body, set())

    if payment["status"] != "ISSUED":
        raise_err(ERR_INVALID_STATE, "Only an ISSUED payment can be cleared")
    payment["status"] = "CLEARED"
    db.touch(payment, carrier["current_utc"])
    return success_object(indemnity_payment_view(payment))


@bp.route("/carriers/<carrierId>/policies/<policyId>/claims/<claimId>/indemnity-payments/<paymentId>/void",
          methods=["POST"])
@require_roles("ClaimsApprover")
def void_indemnity_payment(carrierId: str, policyId: str, claimId: str,
                           paymentId: str, _user_id: str, _role: str):
    carrier = resolve_carrier(carrierId)
    policy = resolve_policy(carrier["id"], policyId)
    claim = resolve_claim(policy["id"], claimId)
    payment = resolve_payment(claim["id"], paymentId)
    body = get_json_body()
    reject_unknown_fields(body, set())

    if payment["status"] != "ISSUED":
        raise_err(ERR_INVALID_STATE, "Only an ISSUED payment can be voided")

    now = carrier["current_utc"]
    if dt(now) > dt(payment["issued_at"]) + timedelta(hours=24):
        raise_err(ERR_VOID_WINDOW_EXPIRED,
                  "Void attempted after the 24-hour void window")

    payment["status"] = "VOID"
    db.touch(payment, now)

    # Re-open the claim for a corrected re-issue (PRD 3.8).
    if claim["claim_state"] == "PAID":
        claim["claim_state"] = "APPROVED"
        db.touch(claim, now)
    core.recompute_reserve(policy)
    return success_object(indemnity_payment_view(payment))
