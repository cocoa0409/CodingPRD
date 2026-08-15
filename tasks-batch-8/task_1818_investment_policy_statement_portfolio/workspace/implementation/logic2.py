"""Generation, waterfall, execution, void, withdrawal model/settle, performance."""
from datetime import timedelta
from decimal import Decimal
from fractions import Fraction

import store as db
import logical_clock as clock
from errors import ApiError
from logic import (CLASS_ORDER, PROPOSAL_TTL_DAYS, CAP_GAINS_BPS, new_id,
                   touch, new_common, rhu_frac, rhu_dec, ceil_frac,
                   positions_of, mv, cash_balance, total_value,
                   is_restricted, has_active_no_trade, append_event,
                   compute_drift, refresh_portfolio, revert_modeled_withdrawals,
                   cancel_open_trades)


# ---------------------------------------------------------- trade generation
def _new_trade(prop, sec, side, qty, price, pf, lot):
    est_proceeds = qty * price
    est_tax = 0
    if side == "SELL" and pf["tax_status"] == "TAXABLE" and lot is not None:
        relief = rhu_frac(Fraction(lot["cost_basis_cents"] * qty, lot["quantity"]))
        est_tax = rhu_frac(Fraction(max(0, est_proceeds - relief) * CAP_GAINS_BPS, 10000))
    t = new_common()
    t.update({
        "proposal_id": prop["id"], "security_id": sec["id"], "side": side,
        "quantity": qty, "pinned_price_cents": price,
        "est_proceeds_cents": est_proceeds, "est_tax_impact_cents": est_tax,
        "status": "PENDING", "executed_at_dt": None, "executed_price_cents": None,
        "voided_at_dt": None, "_relief_cents": None, "_executed_amount_cents": None,
    })
    db.trades[t["id"]] = t
    return t


def build_trades(prop, pf):
    """rebalance_trade_generation + rebalance_cash_waterfall. Mutates db.trades.
    Returns (total_buys, total_sells, est_tax_reserve, cash_delta)."""
    ips = db.ips_policies[prop["ips_id"]]
    tgs = sorted([t for t in db.targets.values() if t["ips_id"] == ips["id"]],
                 key=lambda t: CLASS_ORDER.index(t["asset_class"]))
    total = total_value(pf["id"])          # PRE-trade snapshot, never recomputed
    cash = cash_balance(pf["id"])
    created = []
    for t in tgs:
        ac = t["asset_class"]
        if ac == "CASH_EQUIVALENT":
            continue                       # cash sleeve never generates trades
        target_value = rhu_dec(t["target_pct"] * Decimal(total) / Decimal(100))
        lots = [p for p in positions_of(pf["id"], positive=True)
                if db.securities[p["security_id"]]["asset_class"] == ac]
        class_mv = sum(mv(p) for p in lots)
        delta = target_value - class_mv
        if delta < 0:                      # overweight -> SELL
            remaining = -delta
            ranked = sorted(
                lots,
                key=lambda p: (Fraction(mv(p) - p["cost_basis_cents"], p["quantity"]),
                               p["_seq"]))
            for lot in ranked:
                sec = db.securities[lot["security_id"]]
                price = sec["price_cents"]
                sell_qty = min(lot["quantity"], remaining // price)
                if sell_qty >= 1:
                    created.append(_new_trade(prop, sec, "SELL", sell_qty, price, pf, lot))
                    remaining -= sell_qty * price
        elif delta > 0:                    # underweight -> BUY
            cands = [s for s in db.securities.values()
                     if s["asset_class"] == ac and s["trading_status"] == "LISTED"
                     and not is_restricted(s["id"], "BUY")]
            cands.sort(key=lambda s: (s["price_cents"], s["_seq"]))
            if cands:
                chosen = cands[0]
                qty = delta // chosen["price_cents"]
                if qty >= 1:
                    created.append(_new_trade(prop, chosen, "BUY", qty,
                                              chosen["price_cents"], pf, None))
    # ---- cash waterfall (pinned order; sells never recomputed)
    taxable = pf["tax_status"] == "TAXABLE"
    sells = [t for t in created if t["side"] == "SELL"]
    buys = sorted([t for t in created if t["side"] == "BUY"],
                  key=lambda t: (CLASS_ORDER.index(db.securities[t["security_id"]]["asset_class"]),
                                 t["_seq"]))
    total_sells = sum(t["est_proceeds_cents"] for t in sells)
    reserve = sum(t["est_tax_impact_cents"] for t in sells) if taxable else 0
    available = cash + total_sells - reserve
    surviving = []
    for b in buys:
        price = b["pinned_price_cents"]
        cost = b["quantity"] * price
        if cost > available:
            nq = available // price
            if nq < 1:
                continue                    # dropped
            b["quantity"] = nq
            b["est_proceeds_cents"] = nq * price
            cost = nq * price
        available -= cost
        surviving.append(b)
    for b in buys:
        if b not in surviving:
            del db.trades[b["id"]]
    total_buys = sum(t["est_proceeds_cents"] for t in surviving)
    cash_delta = total_sells - reserve - total_buys   # (cash+sells-reserve-buys) - cash
    return total_buys, total_sells, reserve, cash_delta


def generate_proposal_totals(prop, pf):
    tb, ts, reserve, cd = build_trades(prop, pf)
    prop["total_buys_cents"] = tb
    prop["total_sells_cents"] = ts
    prop["est_tax_reserve_cents"] = reserve
    prop["cash_delta_cents"] = cd


# ---------------------------------------------------------- execution / void
def _position_for(pf_id, sec_id):
    for p in db.positions.values():
        if p["portfolio_id"] == pf_id and p["security_id"] == sec_id:
            return p
    return None


def _execute_fill(t, pf):
    sec = db.securities[t["security_id"]]
    price = sec["price_cents"]              # current price, never the pinned estimate
    qty = t["quantity"]
    pos = _position_for(pf["id"], sec["id"])
    if t["side"] == "SELL":
        if pos is not None and pos["quantity"] > 0:
            relief = rhu_frac(Fraction(pos["cost_basis_cents"] * qty, pos["quantity"]))
        else:
            relief = 0
        gain = qty * price - relief
        pos["quantity"] -= qty
        pos["cost_basis_cents"] -= relief
        pf["lifetime_realized_gains_cents"] += gain
        append_event(pf, "TRADE_EXECUTION", qty * price, clock.now(), "TRADE", t["id"])
        t["_relief_cents"] = relief
        t["_executed_amount_cents"] = qty * price
    else:                                   # BUY
        if pos is None:
            pos = new_common()
            pos.update({"portfolio_id": pf["id"], "security_id": sec["id"],
                        "quantity": 0, "cost_basis_cents": 0})
            db.positions[pos["id"]] = pos
        pos["quantity"] += qty
        pos["cost_basis_cents"] += qty * price
        append_event(pf, "TRADE_EXECUTION", -(qty * price), clock.now(), "TRADE", t["id"])
        t["_relief_cents"] = None
        t["_executed_amount_cents"] = qty * price
    t["status"] = "EXECUTED"
    t["executed_at_dt"] = clock.now()
    t["executed_price_cents"] = price
    touch(t)
    touch(pos)


def execute_proposal(prop, pf):
    """Fills PENDING trades: all SELLs in CLASS_ORDER, then all BUYs in
    CLASS_ORDER; ties by trade created order."""
    pend = [t for t in db.trades.values()
            if t["proposal_id"] == prop["id"] and t["status"] == "PENDING"]
    def order_key(t):
        return (CLASS_ORDER.index(db.securities[t["security_id"]]["asset_class"]),
                t["_seq"])
    sells = sorted([t for t in pend if t["side"] == "SELL"], key=order_key)
    buys = sorted([t for t in pend if t["side"] == "BUY"], key=order_key)
    for t in sells + buys:
        _execute_fill(t, pf)
    prop["status"] = "EXECUTED"
    touch(prop)
    refresh_portfolio(pf, revert=True)


def void_trade(t):
    pf = db.portfolios[_proposal_portfolio(t)]
    sec = db.securities[t["security_id"]]
    pos = _position_for(pf["id"], sec["id"])
    price = t["executed_price_cents"]
    qty = t["quantity"]
    if t["side"] == "SELL":
        pos["quantity"] += qty
        pos["cost_basis_cents"] += t["_relief_cents"] or 0
        append_event(pf, "TRADE_VOID", -(qty * price), clock.now(), "TRADE", t["id"])
    else:
        pos["quantity"] -= qty
        pos["cost_basis_cents"] -= t["_executed_amount_cents"] or 0
        append_event(pf, "TRADE_VOID", t["_executed_amount_cents"] or 0,
                     clock.now(), "TRADE", t["id"])
    t["status"] = "VOIDED"
    t["voided_at_dt"] = clock.now()
    touch(t)
    touch(pos)
    refresh_portfolio(pf, revert=True)


def _proposal_portfolio(t):
    return db.proposals[t["proposal_id"]]["portfolio_id"]


# ---------------------------------------------------------- withdrawal model
def _est_gain(pos, qty, price):
    relief = rhu_frac(Fraction(pos["cost_basis_cents"] * qty, pos["quantity"]))
    return qty * price - relief


def run_withdrawal_model(w, pf):
    amount = w["amount_cents"]
    cash = cash_balance(pf["id"])
    total = total_value(pf["id"])
    cash_used = min(amount, cash)
    needed = amount - cash_used
    plan = []
    raised = 0
    if w["funding_mode"] == "CASH_FIRST":
        pass                                # empty plan; cash carries it
    elif w["funding_mode"] == "PRO_RATA":
        invested = total - cash
        for pos in positions_of(pf["id"], positive=True):
            if raised >= needed:
                break
            sec = db.securities[pos["security_id"]]
            price = sec["price_cents"]
            sell_value = Fraction(needed * mv(pos), invested)
            qty = min(pos["quantity"], ceil_frac(sell_value / price))
            if qty >= 1:
                proceeds = qty * price
                plan.append({"position_id": pos["id"], "security_id": sec["id"],
                             "quantity": qty, "est_proceeds_cents": proceeds,
                             "est_gain_cents": _est_gain(pos, qty, price)})
                raised += proceeds
    else:                                   # TAX_AWARE
        lots = [p for p in positions_of(pf["id"], positive=True)
                if not has_active_no_trade(p["security_id"])]
        lots.sort(key=lambda p: (Fraction(mv(p) - p["cost_basis_cents"], p["quantity"]),
                                 p["_seq"]))
        for pos in lots:
            if raised >= needed:
                break
            sec = db.securities[pos["security_id"]]
            price = sec["price_cents"]
            qty = min(pos["quantity"], ceil_frac(Fraction(needed - raised, price)))
            if qty >= 1:
                proceeds = qty * price
                plan.append({"position_id": pos["id"], "security_id": sec["id"],
                             "quantity": qty, "est_proceeds_cents": proceeds,
                             "est_gain_cents": _est_gain(pos, qty, price)})
                raised += proceeds
        if raised < needed and raised + cash < amount:
            raise ApiError("ERR_WITHDRAWAL_EXCEEDS_VALUE", 422,
                           "Liquidation plan cannot fund the withdrawal")
    proceeds_total = sum(l["est_proceeds_cents"] for l in plan)
    tax_cost = 0
    if pf["tax_status"] == "TAXABLE":
        tax_cost = sum(rhu_frac(Fraction(max(0, l["est_gain_cents"]) * CAP_GAINS_BPS, 10000))
                       for l in plan)
    w["modeled_plan"] = plan
    w["modeled_proceeds_cents"] = proceeds_total
    w["modeled_tax_cost_cents"] = tax_cost
    w["modeled_cash_used_cents"] = cash_used
    w["post_withdrawal_drift_status"] = _projected_drift(pf, plan, amount)
    w["modeled_at_dt"] = clock.now()


def _projected_drift(pf, plan, amount):
    """Band check on the post-settlement projection."""
    from logic import active_ips_of_client
    ips = active_ips_of_client(pf["client_id"])
    total = total_value(pf["id"]) - amount
    if total == 0:
        return "WITHIN_BANDS"
    cash_proj = cash_balance(pf["id"]) - amount
    sold_by_pos = {}
    for l in plan:
        sold_by_pos[l["position_id"]] = sold_by_pos.get(l["position_id"], 0) + l["quantity"]
    tgs = [] if ips is None else [t for t in db.targets.values() if t["ips_id"] == ips["id"]]
    target_classes = {t["asset_class"] for t in tgs}
    positions = positions_of(pf["id"], positive=True)
    proj_mv = {}
    held_classes = set()
    for p in positions:
        sec = db.securities[p["security_id"]]
        remaining_qty = p["quantity"] - sold_by_pos.get(p["id"], 0)
        proj_mv[sec["asset_class"]] = proj_mv.get(sec["asset_class"], 0) + remaining_qty * sec["price_cents"]
        if remaining_qty > 0:
            held_classes.add(sec["asset_class"])
    breached = False
    for t in tgs:
        ac = t["asset_class"]
        class_mv = proj_mv.get(ac, 0)
        if ac == "CASH_EQUIVALENT":
            class_mv += cash_proj
        actual_bps = rhu_frac(Fraction(class_mv * 10000, total))
        target_bps = rhu_dec(t["target_pct"] * 100)
        band_bps = rhu_dec(t["band_pct"] * 100)
        if abs(actual_bps - target_bps) > band_bps:
            breached = True
    for hc in held_classes:
        if hc not in target_classes:
            breached = True
    return "BREACHED" if breached else "WITHIN_BANDS"


def settle_withdrawal(w, pf):
    for lot in w["modeled_plan"]:           # atomic feasibility pre-check
        pos = db.positions.get(lot["position_id"])
        if pos is None or pos["quantity"] < lot["quantity"]:
            raise ApiError("ERR_WITHDRAWAL_PLAN_INFEASIBLE", 422,
                           "Modeled lot exceeds current position quantity")
    touched = set()
    for lot in w["modeled_plan"]:
        pos = db.positions[lot["position_id"]]
        sec = db.securities[lot["security_id"]]
        price = sec["price_cents"]
        qty = lot["quantity"]
        relief = rhu_frac(Fraction(pos["cost_basis_cents"] * qty, pos["quantity"])) \
            if pos["quantity"] > 0 else 0
        gain = qty * price - relief
        pos["quantity"] -= qty
        pos["cost_basis_cents"] -= relief
        pf["lifetime_realized_gains_cents"] += gain
        append_event(pf, "SETTLEMENT_PROCEEDS", qty * price, clock.now(),
                     "WITHDRAWAL", w["id"])
        if pos["id"] not in touched:
            touch(pos)
            touched.add(pos["id"])
    append_event(pf, "WITHDRAWAL_DISBURSEMENT", -w["amount_cents"], clock.now(),
                 "WITHDRAWAL", w["id"])
    w["status"] = "SETTLED"
    touch(w)
    refresh_portfolio(pf, revert=True)


# ---------------------------------------------------------- performance
def compute_return_bps(report):
    pstart = report["period_start_d"]
    pend = report["period_end_d"]
    flows = [e for e in db.events.values()
             if e["portfolio_id"] == report["portfolio_id"]
             and e["occurred_dt"].date() > pstart
             and e["occurred_dt"].date() <= pend]
    flows.sort(key=lambda e: (e["occurred_dt"], e["_seq"]))
    beginning = report["beginning_value_cents"]
    ending = report["ending_value_cents"]
    if report["calculation_method"] == "TIME_WEIGHTED":
        prev_post = beginning
        product = Fraction(1)
        for f in flows:
            vb = f["valuation_before_cents"]
            r_i = Fraction(vb, prev_post) if prev_post != 0 else Fraction(1)
            product *= r_i
            prev_post = vb + f["amount_cents"]
        r_t = Fraction(ending, prev_post) if prev_post != 0 else Fraction(1)
        product *= r_t
        return rhu_frac((product - 1) * 10000)
    # MONEY_WEIGHTED (Modified Dietz)
    t_days = (pend - pstart).days
    if t_days == 0:
        t_days = 1
    numerator = ending - beginning - sum(f["amount_cents"] for f in flows)
    denom = Fraction(beginning)
    for f in flows:
        offset = (f["occurred_dt"].date() - pstart).days
        w_f = Fraction(t_days - offset, t_days)
        denom += w_f * f["amount_cents"]
    if denom == 0:
        return 0
    return rhu_frac(Fraction(numerator, 1) / denom * 10000)
