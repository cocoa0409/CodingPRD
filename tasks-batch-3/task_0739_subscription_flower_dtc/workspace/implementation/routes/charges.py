"""Charge routes: simulate-payment, refund."""
from flask import Blueprint, request

from common import touch
from errors import (
    ApiError, invalid_state,
    ERR_CHARGE_NOT_FOUND, ERR_REFUND_EXCEEDS_CAPTURED,
)
from middleware import auth_required
import db
from response import ok
from services import validators as v
from services import subscription as svc
from services.views import charge_view

bp = Blueprint("charges", __name__)


def _get_charge_or_404(cid):
    c = db.charges.get(cid)
    if c is None:
        raise ApiError(ERR_CHARGE_NOT_FOUND, "charge not found", 404)
    return c


@bp.route("/charges/<cid>/simulate-payment", methods=["POST"])
@auth_required("BillingAdmin")
def simulate_payment(cid):
    charge = _get_charge_or_404(cid)
    body = request.get_json(silent=True) or {}
    v.require_dict(body)
    outcome = v.require_enum(body, "outcome", v.PAYMENT_OUTCOME_ENUM)

    if charge["status"] != "PENDING":
        raise invalid_state("charge is not PENDING")

    sub = db.subscriptions[charge["subscription_id"]]

    if outcome == "SUCCEEDED":
        charge["status"] = "CAPTURED"
        touch(charge)
        # If this capture clears PAST_DUE, flip billing status back.
        if sub.get("billing_status") == "PAST_DUE":
            sub["billing_status"] = "CURRENT"
            touch(sub)
    else:
        # FAILED
        charge["status"] = "FAILED"
        touch(charge)
        # Cascade: billing PAST_DUE + cancel current-cycle SCHEDULED shipments.
        svc.apply_billing_past_due(sub)
        touch(sub)

    return ok(charge_view(charge))


@bp.route("/charges/<cid>/refund", methods=["POST"])
@auth_required("BillingAdmin")
def refund_charge(cid):
    charge = _get_charge_or_404(cid)
    body = request.get_json(silent=True) or {}
    v.require_dict(body)
    amount_cents = v.require_int(body, "amount_cents", min_value=1)

    if charge["status"] != "CAPTURED":
        raise invalid_state("charge is not CAPTURED")

    already = int(charge.get("refunded_cents", 0))
    if already + amount_cents > int(charge["amount_cents"]):
        raise ApiError(ERR_REFUND_EXCEEDS_CAPTURED,
                       "refund exceeds captured", 422)

    charge["refunded_cents"] = already + amount_cents
    if charge["refunded_cents"] == int(charge["amount_cents"]):
        charge["status"] = "REFUNDED"
    touch(charge)

    # Wallet entry.
    sub = db.subscriptions[charge["subscription_id"]]
    svc.create_wallet_entry(
        customer_id=sub["customer_id"],
        amount_cents=amount_cents,
        reason="REFUND",
        related_charge_id=charge["id"],
    )
    return ok(charge_view(charge))
