"""The proceeds waterfall (PRD 3.10) and the challenge-forfeiture posting
(PRD 3.4).  Both post ProceedsAllocation event rows and credit funds.
"""

from decimal import Decimal

import clockmod
import db
from services.money import round_half_up


def funds_by_rank():
    rows = db.all_rows("funds")
    rows.sort(key=lambda f: f["priority_rank"])
    return rows


def allocation_pct_sum():
    total = Decimal(0)
    for fund in db.all_rows("funds"):
        total += Decimal(str(fund["allocation_pct"]))
    return total


def _post_row(conveyance_id, fund, amount_cents, basis):
    return db.insert_event("proceeds_allocations", {
        "conveyance_id": conveyance_id,
        "fund_id": fund["id"],
        "amount_cents": amount_cents,
        "allocation_basis": basis,
        "residual_included_cents": 0,
        "status": "POSTED",
        "reversed_at": None,
    })


def _credit(fund, amount_cents):
    fund["balance_cents"] += amount_cents
    fund["lifetime_credits_cents"] += amount_cents
    db.touch(fund)


def run_waterfall(conveyance):
    """Distribute net_proceeds_cents across the funds in three passes."""
    funds = funds_by_rank()
    remaining = conveyance["net_proceeds_cents"]
    posted = []

    # Pass one: statutory fixed reserves off the top, in priority_rank order.
    for fund in funds:
        take = min(fund["fixed_reserve_cents"], remaining)
        if take > 0:
            posted.append((_post_row(conveyance["id"], fund, take, "FIXED_RESERVE"), fund))
            remaining -= take

    # Pass two: percentage shares against one captured base.
    base = remaining
    percentage_rows = []
    for fund in funds:
        pct = Decimal(str(fund["allocation_pct"]))
        if pct > 0:
            amount = round_half_up(Decimal(base) * pct)
            row = _post_row(conveyance["id"], fund, amount, "PERCENTAGE")
            posted.append((row, fund))
            percentage_rows.append((row, fund))
            remaining -= amount

    # Pass three: the signed rounding residual folds into the last percentage row.
    if remaining != 0 and percentage_rows:
        row, _fund = percentage_rows[-1]
        row["amount_cents"] += remaining
        row["residual_included_cents"] = remaining
        remaining = 0

    for row, fund in posted:
        _credit(fund, row["amount_cents"])
    return [row for row, _fund in posted]


def post_challenge_forfeiture(challenge, amount_cents):
    """Credit a forfeited challenge deposit to the lowest-priority_rank fund."""
    funds = funds_by_rank()
    if not funds:
        return None
    fund = funds[0]
    row = _post_row(None, fund, amount_cents, "CHALLENGE_FORFEITURE")
    _credit(fund, amount_cents)
    return row


def reverse_conveyance_allocations(conveyance):
    """Reverse every POSTED row on the conveyance, debiting the credited funds."""
    now = clockmod.now()
    for row in db.all_rows("proceeds_allocations"):
        if row.get("conveyance_id") != conveyance["id"]:
            continue
        if row["status"] != "POSTED":
            continue
        row["status"] = "REVERSED"
        row["reversed_at"] = now
        fund = db.get("funds", row["fund_id"])
        if fund is not None:
            fund["balance_cents"] -= row["amount_cents"]
            fund["lifetime_debits_cents"] += row["amount_cents"]
            db.touch(fund)
