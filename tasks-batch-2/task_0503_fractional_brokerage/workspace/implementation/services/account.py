"""Account derived-quantity recompute engine (PRD §2.9, §2.10, §3.4, §3.9).

recompute_account derives, in place and synchronously:
  market values of positions -> equity -> maintenance requirement/excess
  -> buying power -> pdt_flagged -> trading_status posture.

It is a pure derivation: it does NOT bump version. Version increments happen at
the explicit per-endpoint mutation points (see each route)."""
from decimal import Decimal

import constants
from db import db
from money import round_half_up


def positions_for_account(account_id):
    return [p for p in db.positions.values() if p["account_id"] == account_id]


def recompute_positions_for_security(security_id):
    """After a quote update, recompute market_value of every position on the security."""
    sec = db.securities.get(security_id)
    if sec is None:
        return
    for p in db.positions.values():
        if p["security_id"] == security_id:
            recompute_position_market_value(p)


def recompute_positions_for_account_via_security(security_id):
    """Quote-update cascade (PRD §3.2): revalue positions on the security, then
    recompute every affected account's derived quantities and posture. A recompute
    that changes a derived field is a mutation that bumps the account version."""
    from models import touch
    affected_account_ids = set()
    for p in db.positions.values():
        if p["security_id"] == security_id:
            recompute_position_market_value(p)
            affected_account_ids.add(p["account_id"])
    for account_id in affected_account_ids:
        a = db.accounts.get(account_id)
        if a is None:
            continue
        before = _derived_snapshot(a)
        recompute_account(a)
        auto_meet_margin_calls(account_id)
        after = _derived_snapshot(a)
        if before != after:
            touch(a)


def _derived_snapshot(a):
    return (a["account_equity_cents"], a["maintenance_requirement_cents"],
            a["maintenance_excess_cents"], a["buying_power_cents"],
            a["pdt_flagged"], a["trading_status"])


def recompute_position_market_value(p):
    sec = db.securities.get(p["security_id"])
    last = sec["last_price_cents"] if sec else 0
    p["market_value_cents"] = round_half_up(Decimal(str(p["quantity"])) * Decimal(last))


def live_buy_reservation(account_id):
    """Sum of reserved_buying_power_cents over live BUY orders (ACCEPTED or
    PARTIALLY_FILLED) for the account (PRD §3.4)."""
    total = 0
    for o in db.orders.values():
        if (o["account_id"] == account_id and o["side"] == "BUY"
                and o["order_status"] in ("ACCEPTED", "PARTIALLY_FILLED")):
            total += o["reserved_buying_power_cents"]
    return total


def has_issued_margin_call(account_id):
    return any(m["account_id"] == account_id and m["status"] == "ISSUED"
               for m in db.margin_calls.values())


def recompute_account(a):
    """Recompute all derived fields in place. Does not mutate version."""
    account_id = a["id"]
    positions = positions_for_account(account_id)

    # market values first
    market_total = 0
    maintenance_req = 0
    for p in positions:
        recompute_position_market_value(p)
        mv = p["market_value_cents"]
        market_total += mv
        sec = db.securities.get(p["security_id"])
        rate = sec["maintenance_rate_bps"] if sec else 0
        maintenance_req += round_half_up(Decimal(mv) * Decimal(rate) / Decimal(10000))

    equity = a["settled_cash_cents"] + a["unsettled_cash_cents"] + market_total
    a["account_equity_cents"] = equity
    a["maintenance_requirement_cents"] = maintenance_req
    a["maintenance_excess_cents"] = equity - maintenance_req

    # buying power (PRD §3.4) — variant by account_type
    reserved = live_buy_reservation(account_id)
    if a["account_type"] == "CASH":
        bp = a["settled_cash_cents"] + a["instant_credit_cents"] - reserved
    else:  # MARGIN
        excess = equity - maintenance_req
        bp = max(0, constants.MARGIN_MULTIPLIER * excess) - reserved
    a["buying_power_cents"] = bp

    # PDT flag (PRD §3.9). day_trade_count is the count of detected day trades
    # whose detection date is within the trailing 5-business-day window.
    a["day_trade_count"] = _windowed_day_trade_count(a)
    a["pdt_flagged"] = (a["day_trade_count"] >= constants.PDT_THRESHOLD
                        and equity < constants.PDT_MIN_EQUITY_CENTS)

    # trading_status posture — first-match-wins (PRD §2.9)
    a["trading_status"] = _derive_status(a)


def _windowed_day_trade_count(a):
    from timeutil import parse_iso, trailing_business_window_start, date_floor
    start = trailing_business_window_start(db.clock, constants.WINDOW_BUSINESS_DAYS)
    count = 0
    for ev in a.get("_dt_events", []):
        ev_date = date_floor(parse_iso(ev["date"]))
        if ev_date >= start:
            count += ev["count"]
    return count


def _derive_status(a):
    if a["compliance_hold"]:
        return "FROZEN"
    if has_issued_margin_call(a["id"]):
        return "MARGIN_CALL"
    if a["pdt_flagged"] or a["maintenance_excess_cents"] < 0:
        return "RESTRICTED_CLOSING_ONLY"
    return "ACTIVE"


def auto_meet_margin_calls(account_id):
    """If maintenance_excess restored to >= 0, auto-transition ISSUED calls to MET
    (PRD §3.9, §3.10). Must be called after any recompute that could restore excess."""
    a = db.accounts.get(account_id)
    if a is None:
        return
    recompute_account(a)
    if a["maintenance_excess_cents"] >= 0:
        from models import touch
        for m in db.margin_calls.values():
            if m["account_id"] == account_id and m["status"] == "ISSUED":
                m["status"] = "MET"
                touch(m)
        recompute_account(a)
