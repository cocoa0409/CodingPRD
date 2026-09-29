"""The intraday liquidity access fee assessed at cutoff."""

from decimal import Decimal, ROUND_FLOOR

from db import db, order_key
from services import liquidity, lookup
from services.constants import FEE_RATE_BPS, FEE_REBATE_MIN_COUNT, FEE_REBATE_PCT
from services.fraud import round_half_up


def per_transfer_fee(amount_cents):
    """Ten basis points of the amount, rounded half up for that transfer."""
    return round_half_up(Decimal(amount_cents * FEE_RATE_BPS) / Decimal(10000))


def settled_rows_for(participant_id, business_date):
    rows = []
    for row in db.credit_transfers.values():
        if row["originator_participant_id"] != participant_id:
            continue
        if row["direction"] != "OUTBOUND":
            continue
        if row["clearing_status"] != "SETTLED":
            continue
        if row["settlement_business_date"] != business_date:
            continue
        rows.append(row)
    return sorted(rows, key=order_key)


def assess_participant_fee(participant, business_date):
    """Return the net fee for one participant and post it when positive."""
    rows = settled_rows_for(participant["id"], business_date)
    gross = 0
    for row in rows:
        gross += per_transfer_fee(row["amount_cents"])
    settled_count = len(rows)
    if settled_count >= FEE_REBATE_MIN_COUNT:
        rebate = int((Decimal(gross) * FEE_REBATE_PCT).to_integral_value(rounding=ROUND_FLOOR))
    else:
        rebate = 0
    net = gross - rebate
    if net > 0:
        account = lookup.account_of_participant(participant["id"])
        if account is not None:
            liquidity.post_ledger_entry(account, "FEE_DEBIT", net)
            liquidity.rederive_posture(participant)
    return net


def assess_cycle(cycle):
    total = 0
    for participant in lookup.live_participants():
        total += assess_participant_fee(participant, cycle["business_date"])
    return total
