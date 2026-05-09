"""POST /payments — record a payment and reconcile against the bill."""
from __future__ import annotations

from flask import Blueprint, g

import db
from errors import (
    APIError,
    ERR_FORBIDDEN,
    ERR_REFERENCE_NOT_FOUND,
    ERR_VALIDATION,
)
from middleware import require_roles
from response import success
from services.payments import record_payment
from utils import get_body, require_field

bp = Blueprint("payments", __name__)

VALID_CHANNELS = {"WECHAT", "ALIPAY", "BANK_TRANSFER", "CASH"}


@bp.post("/payments")
@require_roles("PropertyManager", "Owner")
def create_payment():
    body = get_body()
    bill_id = require_field(body, "bill_id")
    channel = require_field(body, "channel")
    external_txn_id = require_field(body, "external_txn_id")
    amount = require_field(body, "amount")
    paid_at = require_field(body, "paid_at")

    if channel not in VALID_CHANNELS:
        raise APIError(ERR_VALIDATION, "Invalid channel.", 422)

    bill = db.fee_bills.get(bill_id)
    if bill is None:
        raise APIError(ERR_REFERENCE_NOT_FOUND, f"FeeBill {bill_id} not found.", 404)

    # Ownership for Owner role
    if g.user_role == "Owner":
        prop = db.properties.get(bill.get("property_id"))
        if prop is None or prop.get("owner_id") != g.user_id:
            raise APIError(ERR_FORBIDDEN, "Owner cannot pay another owner's bill.", 403)

    record = record_payment(
        bill_id=bill_id,
        channel=channel,
        external_txn_id=external_txn_id,
        amount=amount,
        paid_at_str=paid_at,
    )
    return success(record, status=201)
