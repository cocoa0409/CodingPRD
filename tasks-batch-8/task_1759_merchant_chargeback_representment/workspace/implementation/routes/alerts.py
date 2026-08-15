"""PreventionAlert endpoints (PRD 3.4) — ingest, 72h window, REFUND deflection."""

from datetime import timedelta

from flask import Blueprint, g, request

from clock import CLOCK
from db import db
from errors import ApiError
from middleware import is_merchant_user
from records import new_prevention_alert, touch
from response import ok_object
from routes.common import ALL_ROLES, authenticate, get_or_404, hide_if_cross_merchant, json_body, list_response
from serializers import serialize_prevention_alert
from util import ALERT_ACTIONS, ALERT_RESPONSE_HOURS, ALERT_STATUSES, ALERT_TYPES, Body, filter_enum

bp = Blueprint("alerts", __name__)


@bp.post("/acquirer/prevention-alerts")
def create_alert():
    authenticate(("AcquirerOps",))
    b = Body(json_body())
    transaction_id = b.req_str("transaction_id")
    alert_type = b.req_enum("alert_type", ALERT_TYPES)

    txn = None
    if transaction_id is not None:
        txn = get_or_404(db.transactions, transaction_id, "Transaction")
    b.raise_pending()

    now = CLOCK.now()
    alert = new_prevention_alert(txn["id"], txn["merchant_id"], alert_type,
                                 now, now + timedelta(hours=ALERT_RESPONSE_HOURS))
    db.prevention_alerts[alert["id"]] = alert
    return ok_object(serialize_prevention_alert(alert), status=201)


@bp.get("/acquirer/prevention-alerts")
def list_alerts():
    authenticate(ALL_ROLES)
    merchant_id = request.args.get("merchant_id")
    transaction_id = request.args.get("transaction_id")
    status = filter_enum(request.args, "status", ALERT_STATUSES)
    records = list(db.prevention_alerts.values())
    if is_merchant_user():
        records = [a for a in records if a["merchant_id"] == g.uid]
    elif merchant_id is not None:
        records = [a for a in records if a["merchant_id"] == merchant_id]
    if transaction_id is not None:
        records = [a for a in records if a["transaction_id"] == transaction_id]
    if status is not None:
        records = [a for a in records if a["status"] == status]
    return list_response(records, serialize_prevention_alert)


@bp.get("/acquirer/prevention-alerts/<aid>")
def get_alert(aid):
    authenticate(ALL_ROLES)
    alert = get_or_404(db.prevention_alerts, aid, "PreventionAlert")
    hide_if_cross_merchant(alert["merchant_id"])
    return ok_object(serialize_prevention_alert(alert))


@bp.post("/acquirer/prevention-alerts/<aid>/action")
def action_alert(aid):
    authenticate(("MerchantUser",))
    alert = get_or_404(db.prevention_alerts, aid, "PreventionAlert")
    hide_if_cross_merchant(alert["merchant_id"])
    # Priority 5: the alert must be OPEN (a past-due alert has already been flipped
    # to EXPIRED by the clock-set sweep, so a late action surfaces as this error).
    if alert["status"] != "OPEN":
        raise ApiError(409, "ERR_ALERT_NOT_OPEN", "The prevention alert is not OPEN")
    b = Body(json_body())
    action_raw = b.d.get("action")
    txn = db.transactions.get(alert["transaction_id"])
    # Priority 5 (cont.): REFUND requires the sale still SETTLED.
    if action_raw == "REFUND" and txn is not None and txn["status"] != "SETTLED":
        raise ApiError(409, "ERR_TRANSACTION_NOT_REFUNDABLE", "Transaction is not refundable")
    # Priority 6: suspension gate.
    merchant = db.merchants[alert["merchant_id"]]
    if merchant["status"] != "ACTIVE":
        raise ApiError(409, "ERR_MERCHANT_SUSPENDED", "Merchant is SUSPENDED")
    # Priority 11: payload shape.
    action = b.req_enum("action", ALERT_ACTIONS)
    b.raise_pending()

    if action == "REFUND":
        # Deflection: refund funds from clearing; a refunded sale can no longer be charged back.
        txn["status"] = "REFUNDED"
        touch(txn)
        merchant["clearing_balance_cents"] -= txn["amount_cents"]
        touch(merchant)
        alert["status"] = "ACTIONED_REFUND"
    else:  # DISMISS
        alert["status"] = "DISMISSED"
    touch(alert)
    return ok_object(serialize_prevention_alert(alert))
