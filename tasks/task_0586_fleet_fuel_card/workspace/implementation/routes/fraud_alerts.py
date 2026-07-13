"""Fraud alerts and the review axis (PRD §3.6)."""
from flask import Blueprint, g, request

import response
from db import db, touch
from errors import err
from middleware import (body, check_fleet, is_fleet_manager, opt_str, paginate, query_enum,
                        require_roles)
from services import serialize
from services.cascade import suspend_card
from services.store import ALERT_STATUSES, account_of_alert, get_alert, get_card, get_transaction

bp = Blueprint("fraud_alerts", __name__)


def _note(alert):
    note = opt_str(body(), "resolution_note")
    if note is not None:
        alert["resolution_note"] = note


@bp.get("/fraud-alerts/<alert_id>")
@require_roles("FraudAnalyst", "FleetManager", "ProgramAdmin")
def fetch_alert(alert_id):
    alert = get_alert(alert_id)
    check_fleet(account_of_alert(alert))
    return response.ok(serialize.fraud_alert(alert))


@bp.get("/fraud-alerts")
@require_roles("FraudAnalyst", "FleetManager", "ProgramAdmin")
def list_alerts():
    card_filter = request.args.get("card_id")
    transaction_filter = request.args.get("transaction_id")
    status_filter = query_enum("status", ALERT_STATUSES)

    records = list(db.fraud_alerts.values())
    if is_fleet_manager():
        records = [a for a in records if account_of_alert(a) == g.user_id]
    if card_filter is not None:
        records = [a for a in records if a["card_id"] == card_filter]
    if transaction_filter is not None:
        records = [a for a in records if a["transaction_id"] == transaction_filter]
    if status_filter is not None:
        records = [a for a in records if a["status"] == status_filter]

    page, total, limit, offset = paginate(records)
    return response.listing([serialize.fraud_alert(a) for a in page], limit, offset, total)


@bp.post("/fraud-alerts/<alert_id>/investigate")
@require_roles("FraudAnalyst")
def investigate(alert_id):
    alert = get_alert(alert_id)
    if alert["status"] != "OPEN":
        raise err("ERR_INVALID_ALERT_STATE", "Only an OPEN alert can move to INVESTIGATING.")
    alert["status"] = "INVESTIGATING"
    touch(alert)
    return response.ok(serialize.fraud_alert(alert))


@bp.post("/fraud-alerts/<alert_id>/confirm")
@require_roles("FraudAnalyst")
def confirm(alert_id):
    alert = get_alert(alert_id)
    if alert["status"] != "INVESTIGATING":
        raise err("ERR_INVALID_ALERT_STATE", "Only an INVESTIGATING alert can be confirmed.")

    card = get_card(alert["card_id"])
    if card["status"] == "CANCELLED":
        raise err("ERR_INVALID_CARD_STATE",
                  "The alert's card is CANCELLED; it cannot be suspended.")

    alert["status"] = "CONFIRMED"
    _note(alert)
    touch(alert)

    # CASCADE ROOT: suspend the card, which voids its open transactions, which in
    # turn release their holds and reverse their accrued rebate.
    if card["status"] == "ACTIVE":
        suspend_card(card)

    return response.ok(serialize.fraud_alert(alert))


@bp.post("/fraud-alerts/<alert_id>/dismiss")
@require_roles("FraudAnalyst")
def dismiss(alert_id):
    alert = get_alert(alert_id)
    if alert["status"] != "INVESTIGATING":
        raise err("ERR_INVALID_ALERT_STATE", "Only an INVESTIGATING alert can be dismissed.")

    alert["status"] = "DISMISSED"
    _note(alert)
    touch(alert)

    # Review axis only — posting_status is untouched.
    txn = get_transaction(alert["transaction_id"])
    if txn["review_status"] == "FLAGGED":
        txn["review_status"] = "CLEARED"
        touch(txn)

    return response.ok(serialize.fraud_alert(alert))


@bp.post("/fraud-alerts/<alert_id>/reopen")
@require_roles("FraudAnalyst")
def reopen(alert_id):
    alert = get_alert(alert_id)
    if alert["status"] != "CONFIRMED":
        raise err("ERR_INVALID_ALERT_STATE", "Only a CONFIRMED alert can be reopened.")
    alert["status"] = "INVESTIGATING"
    _note(alert)
    touch(alert)
    # Reopening does not un-suspend the card.
    return response.ok(serialize.fraud_alert(alert))
