"""The trust fund ledger (PRD 3.10 / calculations.trust_fund_ledger).

Money entering the fund: every cent actually paid on an in-lieu fee, whatever
state that assessment now sits in, plus city recapture from CLOSED resales only.
Money leaving: REQUESTED encumbrances and DISBURSED payments. A VOIDED
disbursement contributes nothing to either side.
"""

import db
from services import calc


def ledger():
    total_paid_fees = 0
    for fee in db.all_rows(db.in_lieu_fees):
        total_paid_fees += int(fee.get("paid_amount_cents") or 0)

    total_recapture = 0
    for txn in db.all_rows(db.resale_transactions):
        if txn.get("state") == "CLOSED":
            total_recapture += int(txn.get("city_recapture_cents") or 0)

    total_inflow = total_paid_fees + total_recapture

    encumbered = 0
    disbursed = 0
    admin_committed = 0
    for row in db.all_rows(db.disbursements):
        state = row.get("state")
        amount = int(row.get("amount_cents") or 0)
        if state == "REQUESTED":
            encumbered += amount
        elif state == "DISBURSED":
            disbursed += amount
        if state in ("REQUESTED", "DISBURSED") and row.get("eligible_use") == "ADMIN":
            admin_committed += amount

    unencumbered = total_inflow - encumbered - disbursed
    admin_cap = calc.round_half_up(total_inflow * calc.ADMIN_USE_CAP_BPS, calc.BPS)

    return {
        "total_paid_fees_cents": total_paid_fees,
        "total_recapture_cents": total_recapture,
        "total_inflow_cents": total_inflow,
        "encumbered_cents": encumbered,
        "disbursed_cents": disbursed,
        "unencumbered_balance_cents": unencumbered,
        "admin_cap_cents": admin_cap,
        "admin_committed_cents": admin_committed,
    }
