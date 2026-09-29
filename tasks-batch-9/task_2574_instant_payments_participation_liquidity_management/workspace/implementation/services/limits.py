"""Segment policy selection, velocity windows and daily exposure."""

from db import db, now
from timeutils import date_str, plus_minutes
from services.constants import IN_FLIGHT_STATUSES, VELOCITY_STATUSES


def governing_policy(participant_id, segment):
    """Resolve the policy that governs a send, once, at origination."""
    clock = now()
    candidates = []
    for policy in db.segment_policies.values():
        if policy["participant_id"] != participant_id:
            continue
        if policy["segment"] != segment:
            continue
        if policy["superseded_at"] is not None:
            continue
        if policy["effective_from"] > clock:
            continue
        if policy["effective_to"] is not None and policy["effective_to"] <= clock:
            continue
        candidates.append(policy)
    if not candidates:
        return None
    candidates.sort(key=lambda p: (p["effective_from"], p["created_at"], p["_seq"]), reverse=True)
    return candidates[0]


def velocity_rows(customer_account_id, window_minutes, exclude_transfer_id=None):
    """The countable rows of the half-open window ending at the clock."""
    clock = now()
    window_start = plus_minutes(clock, -window_minutes)
    rows = []
    for row in db.credit_transfers.values():
        if row["customer_account_id"] != customer_account_id:
            continue
        if row["direction"] != "OUTBOUND":
            continue
        if row["clearing_status"] not in VELOCITY_STATUSES:
            continue
        if exclude_transfer_id is not None and row["id"] == exclude_transfer_id:
            continue
        if not (window_start <= row["created_at"] < clock):
            continue
        rows.append(row)
    return rows


def daily_sent_amount(customer_account_id, business_date=None):
    """The conserved part of the daily exposure, mirrored on the account."""
    business_date = business_date or date_str(now())
    total = 0
    for row in db.credit_transfers.values():
        if row["customer_account_id"] != customer_account_id:
            continue
        if row["direction"] != "OUTBOUND":
            continue
        if row["clearing_status"] != "SETTLED":
            continue
        if row["settlement_business_date"] != business_date:
            continue
        if row["exception_status"] == "RETURN_HONORED":
            continue
        total += row["amount_cents"]
    return total


def daily_exposure(customer_account_id):
    business_date = date_str(now())
    total = daily_sent_amount(customer_account_id, business_date)
    for row in db.credit_transfers.values():
        if row["customer_account_id"] != customer_account_id:
            continue
        if row["direction"] != "OUTBOUND":
            continue
        if row["clearing_status"] not in IN_FLIGHT_STATUSES:
            continue
        if date_str(row["created_at"]) != business_date:
            continue
        total += row["amount_cents"]
    return total


def has_settled_beneficiary(customer_account_id, receiver_routing_number, exclude_transfer_id=None):
    for row in db.credit_transfers.values():
        if row["customer_account_id"] != customer_account_id:
            continue
        if row["direction"] != "OUTBOUND":
            continue
        if row["clearing_status"] != "SETTLED":
            continue
        if row["receiver_routing_number"] != receiver_routing_number:
            continue
        if exclude_transfer_id is not None and row["id"] == exclude_transfer_id:
            continue
        return True
    return False
