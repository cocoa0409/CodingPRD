"""Margin-call liquidation (PRD §3.9).

Liquidation force-creates closing SELL fills against the account's open positions
until maintenance_excess returns to >= 0, cascading into disposals, position
updates, realized P/L, and settled cash."""
from decimal import Decimal

from db import db, created_ts, new_id
from models import touch
from money import round_half_up, shares_str
from services.account import (recompute_account, positions_for_account,
                              recompute_position_market_value)
from services.position import dispose_shares
from timeutil import add_business_days, iso


def liquidate_call(acct, mc):
    """Force closing SELL fills until excess >= 0, then mark call LIQUIDATED."""
    recompute_account(acct)
    # iterate over positions with quantity, selling shares at last_price to raise
    # equity/lower maintenance until the deficiency is cured.
    guard = 0
    while acct["maintenance_excess_cents"] < 0 and guard < 10000:
        guard += 1
        positions = [p for p in positions_for_account(acct["id"]) if p["quantity"] > 0]
        if not positions:
            break
        progressed = False
        for p in positions:
            if p["quantity"] <= 0:
                continue
            sec = db.securities.get(p["security_id"])
            price = sec["last_price_cents"] if sec else 0
            if price <= 0:
                continue
            sell_qty = p["quantity"]  # liquidate the whole position
            _force_sell_fill(acct, p, sec, sell_qty, price)
            recompute_account(acct)
            progressed = True
            if acct["maintenance_excess_cents"] >= 0:
                break
        if not progressed:
            break

    mc["status"] = "LIQUIDATED"
    touch(mc)
    recompute_account(acct)
    touch(acct)


def _force_sell_fill(acct, position, sec, sell_qty, price):
    """Create a synthetic closing SELL Fill + Settlement + Disposals."""
    gross_value = round_half_up(Decimal(str(sell_qty)) * Decimal(price))

    fill = {
        "id": new_id(),
        "created_at": created_ts(),
        "_seq": db.next_seq(),
        "order_id": None,
        "account_id": acct["id"],
        "fill_quantity": shares_str(sell_qty),
        "fill_price_cents": price,
        "gross_value_cents": gross_value,
        "pfof_rebate_cents": 0,
        "settlement_id": None,
    }
    db.fills[fill["id"]] = fill

    dispose_shares(position, fill, sell_qty, price)

    # Settlement leg (CREDIT) — cash arrives at T+1
    from models import _base_full
    s = _base_full()
    s.update({
        "account_id": acct["id"],
        "fill_id": fill["id"],
        "direction": "CREDIT",
        "amount_cents": gross_value,
        "settles_on": iso(add_business_days(db.clock, 1)),
        "status": "UNSETTLED",
        "_pfof_rebate_cents": 0,
    })
    db.settlements[s["id"]] = s
    fill["settlement_id"] = s["id"]

    # provisional unsettled cash credit (SELL)
    acct["unsettled_cash_cents"] += gross_value
