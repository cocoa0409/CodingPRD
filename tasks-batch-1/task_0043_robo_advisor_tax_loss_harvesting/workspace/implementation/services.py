"""Cross-aggregate business logic: drift bubble-up, harvest execute/reverse
cascade, and rebalance execute. Kept separate from the thin route layer in
app.py so the multi-step ledger mutations live in one place."""

from decimal import Decimal

from clock import clock
from db import db, new_common, touch
from calculations import (
    compute_drift, market_value_cents, wash_sale_disallowed, round_half_up,
    WASH_SALE_DAYS,
)
from response import iso_ms


# ----------------------------------------------------------------------------
# Account recompute / drift bubble-up (PRD §2.7)
# ----------------------------------------------------------------------------
def open_lots_for_account(account_id):
    return [l for l in db.tax_lots.values()
            if l["account_id"] == account_id and l["status"] == "OPEN"]


def recompute_account_aggregates(account):
    """Refresh invested_value_cents, max_drift_pct, total_value_cents, and the
    two ytd ledgers from the current ledger. Does NOT change status or version."""
    model = db.model_portfolios.get(account.get("model_portfolio_id"))
    open_lots = open_lots_for_account(account["id"])
    invested, max_drift = compute_drift(open_lots, db.securities, model)
    account["invested_value_cents"] = invested
    account["max_drift_pct"] = max_drift
    account["total_value_cents"] = account["cash_balance_cents"] + invested
    _recompute_ytd_ledgers(account)


def _current_tax_year():
    return clock.now().year


def _recompute_ytd_ledgers(account):
    """realized_gain_cents_ytd: signed sum of realized_gain over CLOSED lots whose
    disposed_at year == current tax year, net of any wash-sale disallowance — the
    loss net of any disallowance per PRD §3.4, i.e. the realized loss plus the
    positive disallowed amount (PRD §3.5). wash_sale_disallowed_cents_ytd: running
    sum of disallowed loss in the current tax year (PRD §2.8)."""
    year = _current_tax_year()
    realized = 0
    disallowed = 0
    for lot in db.tax_lots.values():
        if lot["account_id"] != account["id"]:
            continue
        if lot["status"] != "CLOSED":
            continue
        d = lot.get("_disposed_dt")
        if d is None or d.year != year:
            continue
        rg = lot.get("realized_gain_cents")
        lot_disallowed = lot.get("wash_sale_disallowed_cents", 0) or 0
        if rg is not None:
            # Net of disallowance: adding the positive disallowance moves a
            # negative realized loss back toward zero (PRD §3.4/§3.5).
            realized += rg + lot_disallowed
        disallowed += lot_disallowed
    account["realized_gain_cents_ytd"] = realized
    account["wash_sale_disallowed_cents_ytd"] = disallowed


def apply_drift_status(account):
    """Auto-transition ACTIVE <-> REBALANCE_DUE per the drift boundary (>=).
    Only applies while the account is ACTIVE or REBALANCE_DUE."""
    if account["status"] not in ("ACTIVE", "REBALANCE_DUE"):
        return
    model = db.model_portfolios.get(account.get("model_portfolio_id"))
    if model is None:
        return
    threshold = model["drift_threshold_pct"]
    if account["max_drift_pct"] >= threshold:
        account["status"] = "REBALANCE_DUE"
    else:
        account["status"] = "ACTIVE"


def bubble_up(account):
    """Recompute aggregates, apply the drift boundary, and bump the account
    version+timestamp. Used after a lot opens/closes or a price update changes
    holdings (PRD §2.7, §3.3)."""
    recompute_account_aggregates(account)
    apply_drift_status(account)
    touch(account)


# ----------------------------------------------------------------------------
# Wash-sale scan (PRD §3.5) — run when a lot closes at a loss
# ----------------------------------------------------------------------------
def wash_sale_scan(closing_lot, account):
    """If the closing lot realized a LOSS and an OTHER OPEN lot in the SAME
    security was acquired within +/- WASH_SALE_DAYS of disposed_at, disallow the
    prorated portion of the loss, bump that survivor lot's cost basis, and return
    (disallowed_cents, survivor_lot_id_or_None, basis_bump). Gains never disallowed."""
    realized = closing_lot.get("realized_gain_cents")
    if realized is None or realized >= 0:
        return 0, None, 0

    disposed = closing_lot["_disposed_dt"]
    from datetime import timedelta
    lo = disposed - timedelta(days=WASH_SALE_DAYS)
    hi = disposed + timedelta(days=WASH_SALE_DAYS)

    closing_shares = Decimal(str(closing_lot["quantity"]))
    in_window_lots = []
    repl_shares = Decimal(0)
    for lot in db.tax_lots.values():
        if lot["id"] == closing_lot["id"]:
            continue
        if lot["account_id"] != account["id"]:
            continue
        if lot["security_id"] != closing_lot["security_id"]:
            continue
        if lot["status"] != "OPEN":
            continue
        acq = lot.get("_acquired_dt")
        if acq is None:
            continue
        if lo <= acq <= hi:
            in_window_lots.append(lot)
            repl_shares += Decimal(str(lot["quantity"]))

    if not in_window_lots or repl_shares <= 0:
        return 0, None, 0

    # cap in-window replacement shares at the closing lot's share count
    capped = repl_shares
    if capped > closing_shares:
        capped = closing_shares

    disallowed = wash_sale_disallowed(
        abs(realized), float(closing_shares), float(capped)
    )
    if disallowed <= 0:
        return 0, None, 0

    # Carry the disallowed basis onto the (first, earliest-acquired) survivor lot.
    survivor = sorted(
        in_window_lots,
        key=lambda l: (l["_acquired_dt"], l["_created_seq"]),
    )[0]
    survivor["cost_basis_cents"] += disallowed
    touch(survivor)
    return disallowed, survivor["id"], disallowed


# ----------------------------------------------------------------------------
# Harvest execute cascade (PRD §3.4 L1->L2->L3 + replacement + reinvest)
# ----------------------------------------------------------------------------
def execute_harvest(event, account, source_lot, replacement_security):
    now = clock.now()

    # Snapshot pre-harvest cash so a later reverse can restore it exactly
    # (PRD §3.7: total_value_cents returns to precisely its pre-harvest value).
    event["_pre_harvest_cash"] = account["cash_balance_cents"]

    # L1: close the source lot at its current market value.
    proceeds = market_value_cents(source_lot["quantity"],
                                  db.securities[source_lot["security_id"]]["price_cents"])
    source_lot["status"] = "CLOSED"
    source_lot["_disposed_dt"] = now
    source_lot["disposed_at"] = iso_ms(now)
    source_lot["proceeds_cents"] = proceeds
    source_lot["realized_gain_cents"] = proceeds - source_lot["cost_basis_cents"]
    source_lot["closed_by_harvest_id"] = event["id"]
    realized_loss = source_lot["cost_basis_cents"] - proceeds  # positive magnitude
    event["realized_loss_cents"] = realized_loss
    touch(source_lot)

    # L2: wash-sale scan on the close.
    disallowed, survivor_id, basis_bump = wash_sale_scan(source_lot, account)
    source_lot["wash_sale_disallowed_cents"] = disallowed
    event["disallowed_loss_cents"] = disallowed
    event["_wash_survivor_lot_id"] = survivor_id
    event["_wash_basis_bump"] = basis_bump

    # Replacement lot: buy whole shares with the proceeds, remainder to cash.
    repl_price = replacement_security["price_cents"]
    repl_qty = proceeds // repl_price  # whole-number floor
    repl_cost = repl_qty * repl_price
    remainder = proceeds - repl_cost

    new_lot = new_common(with_version=True)
    new_lot.update({
        "account_id": account["id"],
        "security_id": replacement_security["id"],
        "quantity": repl_qty,
        "cost_basis_cents": repl_cost,
        "_acquired_dt": now,
        "acquired_at": iso_ms(now),
        "status": "OPEN",
        "_disposed_dt": None,
        "disposed_at": None,
        "proceeds_cents": None,
        "realized_gain_cents": None,
        "wash_sale_disallowed_cents": 0,
        "closed_by_harvest_id": None,
    })
    db.tax_lots[new_lot["id"]] = new_lot
    event["replacement_lot_id"] = new_lot["id"]
    event["_cash_remainder"] = remainder

    account["cash_balance_cents"] += remainder

    # L3 + drift: recompute aggregates (ytd ledgers, invested, drift), apply
    # boundary, bump version. Status stays REBALANCE_DUE if still drifted.
    event["status"] = "EXECUTED"
    recompute_account_aggregates(account)
    apply_drift_status(account)
    touch(account)
    return event


# ----------------------------------------------------------------------------
# Harvest reverse (PRD §3.7) — compensating undo, restores pre-harvest value
# ----------------------------------------------------------------------------
def reverse_harvest(event, account):
    now = clock.now()

    # Close the replacement lot at its market value (the cash for its shares is
    # conceptually returned, but the net cash effect is folded into the snapshot
    # restore below so the invariant is exact).
    repl_lot = db.tax_lots.get(event.get("replacement_lot_id"))
    if repl_lot is not None and repl_lot["status"] == "OPEN":
        sec = db.securities.get(repl_lot["security_id"])
        if sec is not None:
            mv = market_value_cents(repl_lot["quantity"], sec["price_cents"])
        else:
            mv = repl_lot["cost_basis_cents"]
        repl_lot["status"] = "CLOSED"
        repl_lot["_disposed_dt"] = now
        repl_lot["disposed_at"] = iso_ms(now)
        repl_lot["proceeds_cents"] = mv
        repl_lot["realized_gain_cents"] = mv - repl_lot["cost_basis_cents"]
        touch(repl_lot)

    # Undo the wash-sale basis carryover bumped onto any survivor lot at execute.
    survivor_id = event.get("_wash_survivor_lot_id")
    bump = event.get("_wash_basis_bump", 0) or 0
    if survivor_id is not None and bump:
        survivor = db.tax_lots.get(survivor_id)
        if survivor is not None:
            survivor["cost_basis_cents"] -= bump
            touch(survivor)

    # Reopen the source lot, clearing all disposal fields (PRD §3.7).
    source_lot = db.tax_lots.get(event["source_lot_id"])
    if source_lot is not None:
        source_lot["status"] = "OPEN"
        source_lot["_disposed_dt"] = None
        source_lot["disposed_at"] = None
        source_lot["proceeds_cents"] = None
        source_lot["realized_gain_cents"] = None
        source_lot["wash_sale_disallowed_cents"] = 0
        source_lot["closed_by_harvest_id"] = None
        touch(source_lot)

    # Restore cash to its exact pre-harvest value. At execute the only cash change
    # was the credited reinvestment remainder; closing the replacement here removes
    # it from invested_value while reopening the source restores the source's value,
    # so resetting cash to the snapshot makes total_value_cents land precisely on the
    # pre-harvest figure (PRD §3.7 compensating_invariant).
    if "_pre_harvest_cash" in event:
        account["cash_balance_cents"] = event["_pre_harvest_cash"]

    event["status"] = "REVERSED"
    recompute_account_aggregates(account)
    apply_drift_status(account)
    touch(account)
    return event


# ----------------------------------------------------------------------------
# Rebalance execute (PRD §3.6) — trade to drive every drift below threshold
# ----------------------------------------------------------------------------
def execute_rebalance(event, account, model):
    """Generate the buys/sells needed to bring each asset_class drift below the
    model's threshold. Deterministic: compute the per-class target market value
    from the current invested_value, then for each class trade whole shares of a
    single representative security to approach the target. Sells consume OPEN lots
    in the model's lot_selection order (FIFO/HIFO); buys open a fresh lot."""
    now = clock.now()
    trades = 0
    cash_consumed = 0

    # Anchor the rebalance on the current invested value (target weights applied
    # to the existing invested pool; cash is left as the trading buffer).
    open_lots = open_lots_for_account(account["id"])
    invested = 0
    for lot in open_lots:
        sec = db.securities.get(lot["security_id"])
        if sec is not None:
            invested += market_value_cents(lot["quantity"], sec["price_cents"])

    # Map asset_class -> representative security (lowest ticker for determinism),
    # preferring a security the account already holds in that class.
    held_sec_by_class = {}
    for lot in open_lots:
        sec = db.securities.get(lot["security_id"])
        if sec is None:
            continue
        held_sec_by_class.setdefault(sec["asset_class"], sec)

    lot_selection = model.get("lot_selection", "FIFO") or "FIFO"

    for entry in model["targets"]:
        ac = entry["asset_class"]
        target_pct = entry["target_pct"]
        target_value = round_half_up(Decimal(invested) * Decimal(target_pct) / Decimal(100))

        # current market value held in this class
        class_lots = []
        current_value = 0
        for lot in open_lots_for_account(account["id"]):
            sec = db.securities.get(lot["security_id"])
            if sec is None or sec["asset_class"] != ac:
                continue
            class_lots.append((lot, sec))
            current_value += market_value_cents(lot["quantity"], sec["price_cents"])

        diff = target_value - current_value
        sec = held_sec_by_class.get(ac)
        if sec is None or sec["price_cents"] <= 0:
            continue
        price = sec["price_cents"]

        if diff > 0:
            # BUY whole shares to approach the target.
            qty = diff // price
            if qty > 0:
                cost = qty * price
                if cost > account["cash_balance_cents"]:
                    qty = account["cash_balance_cents"] // price
                    cost = qty * price
                if qty > 0:
                    new_lot = new_common(with_version=True)
                    new_lot.update({
                        "account_id": account["id"],
                        "security_id": sec["id"],
                        "quantity": qty,
                        "cost_basis_cents": cost,
                        "_acquired_dt": now,
                        "acquired_at": iso_ms(now),
                        "status": "OPEN",
                        "_disposed_dt": None,
                        "disposed_at": None,
                        "proceeds_cents": None,
                        "realized_gain_cents": None,
                        "wash_sale_disallowed_cents": 0,
                        "closed_by_harvest_id": None,
                    })
                    db.tax_lots[new_lot["id"]] = new_lot
                    account["cash_balance_cents"] -= cost
                    cash_consumed += cost
                    trades += 1
        elif diff < 0:
            # SELL whole shares; consume lots in lot_selection order.
            shares_to_sell = (-diff) // price
            if shares_to_sell > 0:
                trades += _sell_shares(account, sec, shares_to_sell, lot_selection, now)

    event["trades_count"] = trades
    event["cash_consumed_cents"] = cash_consumed
    event["status"] = "EXECUTED"

    recompute_account_aggregates(account)
    # Drive to ACTIVE per PRD §3.6 (rebalance clears the drift flag).
    account["status"] = "ACTIVE"
    touch(account)
    return event


def _sell_shares(account, security, shares_to_sell, lot_selection, now):
    """Consume OPEN lots of (account, security) in the pinned order, closing whole
    lots and recording realized gain (capital_gain_realization). Returns the
    number of trades (lots touched)."""
    lots = [l for l in db.tax_lots.values()
            if l["account_id"] == account["id"]
            and l["security_id"] == security["id"]
            and l["status"] == "OPEN"]
    if lot_selection == "HIFO":
        lots.sort(key=lambda l: (
            -(Decimal(l["cost_basis_cents"]) / Decimal(str(l["quantity"]))),
            l["_acquired_dt"], l["_created_seq"],
        ))
    else:  # FIFO default
        lots.sort(key=lambda l: (l["_acquired_dt"], l["_created_seq"]))

    price = security["price_cents"]
    remaining = Decimal(str(shares_to_sell))
    trades = 0
    for lot in lots:
        if remaining <= 0:
            break
        lot_qty = Decimal(str(lot["quantity"]))
        consume = min(lot_qty, remaining)
        proceeds = round_half_up(consume * Decimal(price))
        if consume >= lot_qty:
            # close the whole lot
            cost = lot["cost_basis_cents"]
            lot["status"] = "CLOSED"
            lot["_disposed_dt"] = now
            lot["disposed_at"] = iso_ms(now)
            lot["proceeds_cents"] = proceeds
            lot["realized_gain_cents"] = proceeds - cost
            touch(lot)
            account["cash_balance_cents"] += proceeds
            # wash-sale scan on a loss sell
            if lot["realized_gain_cents"] < 0:
                disallowed, _, _ = wash_sale_scan(lot, account)
                lot["wash_sale_disallowed_cents"] = disallowed
        else:
            # partial consume: reduce the lot's quantity and basis proportionally
            frac = consume / lot_qty
            consumed_cost = round_half_up(Decimal(lot["cost_basis_cents"]) * frac)
            lot["quantity"] = float(lot_qty - consume)
            lot["cost_basis_cents"] = lot["cost_basis_cents"] - consumed_cost
            touch(lot)
            account["cash_balance_cents"] += proceeds
        remaining -= consume
        trades += 1
    return trades
