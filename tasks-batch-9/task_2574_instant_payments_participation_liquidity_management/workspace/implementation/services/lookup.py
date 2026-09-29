"""Existence resolution (rung 4 of the rejection ladder) and joins."""

from db import db, order_key
from errors import ApiError


def _get(collection, entity_id, error_id):
    if not isinstance(entity_id, str):
        raise ApiError(error_id)
    row = getattr(db, collection).get(entity_id)
    if row is None:
        raise ApiError(error_id)
    return row


def participant(entity_id):
    return _get("participants", entity_id, "ERR_PARTICIPANT_NOT_FOUND")


def position_account(entity_id):
    return _get("position_accounts", entity_id, "ERR_POSITION_ACCOUNT_NOT_FOUND")


def liquidity_alert(entity_id):
    return _get("liquidity_alerts", entity_id, "ERR_LIQUIDITY_ALERT_NOT_FOUND")


def customer_account(entity_id):
    return _get("customer_accounts", entity_id, "ERR_CUSTOMER_ACCOUNT_NOT_FOUND")


def credit_transfer(entity_id):
    return _get("credit_transfers", entity_id, "ERR_CREDIT_TRANSFER_NOT_FOUND")


def request_for_payment(entity_id):
    return _get("request_for_payments", entity_id, "ERR_RFP_NOT_FOUND")


def fraud_review(entity_id):
    return _get("fraud_reviews", entity_id, "ERR_FRAUD_REVIEW_NOT_FOUND")


def return_request(entity_id):
    return _get("return_requests", entity_id, "ERR_RETURN_REQUEST_NOT_FOUND")


def settlement_cycle(entity_id):
    return _get("settlement_cycles", entity_id, "ERR_SETTLEMENT_CYCLE_NOT_FOUND")


def reconciliation_run(entity_id):
    return _get("reconciliation_runs", entity_id, "ERR_RECONCILIATION_RUN_NOT_FOUND")


def outage_event(entity_id):
    return _get("outage_events", entity_id, "ERR_OUTAGE_EVENT_NOT_FOUND")


# --- joins -----------------------------------------------------------------


def account_of_participant(participant_id):
    for row in db.position_accounts.values():
        if row["participant_id"] == participant_id:
            return row
    return None


def account_of_participant_or_fail(participant_id):
    account = account_of_participant(participant_id)
    if account is None:
        raise ApiError("ERR_POSITION_ACCOUNT_NOT_FOUND")
    return account


def entries_of_account(account_id):
    return sorted(
        [e for e in db.ledger_entries.values() if e["account_id"] == account_id],
        key=lambda e: e["sequence_no"],
    )


def alerts_of_account(account_id):
    return sorted(
        [a for a in db.liquidity_alerts.values() if a["account_id"] == account_id],
        key=order_key,
    )


def transfers_of_participant(participant_id, statuses=None, direction="OUTBOUND"):
    out = []
    for row in db.credit_transfers.values():
        if row["originator_participant_id"] != participant_id:
            continue
        if direction is not None and row["direction"] != direction:
            continue
        if statuses is not None and row["clearing_status"] not in statuses:
            continue
        out.append(row)
    return sorted(out, key=order_key)


def transfers_of_customer_account(customer_account_id, statuses=None, direction="OUTBOUND"):
    out = []
    for row in db.credit_transfers.values():
        if row["customer_account_id"] != customer_account_id:
            continue
        if direction is not None and row["direction"] != direction:
            continue
        if statuses is not None and row["clearing_status"] not in statuses:
            continue
        out.append(row)
    return sorted(out, key=order_key)


def reviews_of_transfer(credit_transfer_id):
    return sorted(
        [r for r in db.fraud_reviews.values() if r["credit_transfer_id"] == credit_transfer_id],
        key=order_key,
    )


def cycle_for_business_date(business_date):
    for row in db.settlement_cycles.values():
        if row["business_date"] == business_date:
            return row
    return None


def live_participants():
    return sorted(
        [p for p in db.participants.values() if p["enrollment_status"] == "LIVE"],
        key=order_key,
    )
