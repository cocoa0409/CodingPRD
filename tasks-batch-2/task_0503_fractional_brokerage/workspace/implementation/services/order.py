"""Order placement, fill processing, day-trade detection (PRD §3.3-§3.6, §3.9)."""
from decimal import Decimal

import constants
import errors
from db import db, created_ts
from models import _base_full, touch
from money import round_half_up, bps_of_cents, shares_str
from services.account import recompute_account, auto_meet_margin_calls
from services.position import (get_or_create_position, open_lot, dispose_shares,
                               recompute_position)
from services.routing import select_venue
from timeutil import add_business_days, iso, date_floor, parse_iso


def required_gross_cents(order, security):
    """Pinned step 1 (PRD §3.4): required gross trade value for reservation.
    Notional order -> notional_cents; quantity order -> qty * ref_price half-up,
    ref_price = limit_price for LIMIT else last_price."""
    if order["notional_cents"] > 0:
        return order["notional_cents"]
    if order["order_type"] == "LIMIT":
        ref = order["limit_price_cents"]
    else:
        ref = security["last_price_cents"]
    return round_half_up(Decimal(str(order["quantity"])) * Decimal(ref))


def target_quantity(order, security):
    """Target share quantity an order seeks to fill. For a notional order, the
    target is notional / reference price (truncated to 6dp)."""
    if order["quantity"] > 0:
        return float(order["quantity"])
    ref = (order["limit_price_cents"] if order["order_type"] == "LIMIT"
           else security["last_price_cents"])
    if ref <= 0:
        return 0.0
    from money import truncate_shares
    return truncate_shares(Decimal(str(order["notional_cents"])) / Decimal(ref))


def process_fill(order, security, account, fill_quantity, fill_price_cents):
    """Apply a Fill to an order: lifecycle, lots/disposals, settlement, rebate,
    day-trade detection, account recompute (PRD §3.5, §3.6, §3.9)."""
    gross_value = round_half_up(Decimal(str(fill_quantity)) * Decimal(fill_price_cents))
    rebate = bps_of_cents(gross_value, constants.VENUE_REBATE_BPS[order["pfof_venue"]])

    fill = _base_ref_fill()
    fill.update({
        "order_id": order["id"],
        "account_id": order["account_id"],
        "fill_quantity": shares_str(fill_quantity),
        "fill_price_cents": fill_price_cents,
        "gross_value_cents": gross_value,
        "pfof_rebate_cents": rebate,
        "settlement_id": None,
    })
    db.fills[fill["id"]] = fill

    # order lifecycle updates
    order["filled_quantity"] = shares_str(Decimal(str(order["filled_quantity"]))
                                          + Decimal(str(fill_quantity)))
    order["filled_notional_cents"] += gross_value

    position = get_or_create_position(order["account_id"], order["security_id"],
                                      order.get("_cost_basis_method", "FIFO"))
    qty_before = position["quantity"]

    if order["side"] == "BUY":
        open_lot(position["id"], fill, fill_quantity, gross_value)
        recompute_position(position)
        touch(position)
    else:  # SELL
        dispose_shares(position, fill, fill_quantity, fill_price_cents)

    # Settlement leg (PRD §3.6). The PFOF rebate rides on the leg and is credited
    # to settled cash at settlement, never pre-netted (PRD §3.4).
    settlement = _make_settlement(order, fill, gross_value, rebate)
    fill["settlement_id"] = settlement["id"]

    # provisional cash effects of the fill (before T+1 clears)
    _apply_provisional_cash(account, order, gross_value)

    # determine new order_status
    tgt = order["_target_quantity"]
    cum = Decimal(str(order["filled_quantity"]))
    completed = cum >= Decimal(str(tgt)) - Decimal("0.0000005")
    if completed:
        order["order_status"] = "FILLED"
        if order["side"] == "BUY":
            # release leftover reserved buying power (reservation - actual spend)
            order["reserved_buying_power_cents"] = 0
    else:
        order["order_status"] = "PARTIALLY_FILLED"
    touch(order)

    # day-trade detection (PRD §3.9) — only on a closing fill
    _detect_day_trade(order, security, account, fill, qty_before)

    recompute_account(account)
    auto_meet_margin_calls(account["id"])
    touch(account)  # fill increments Account.version by 1
    return fill


def _apply_provisional_cash(account, order, gross_value):
    """At fill time the unsettled leg carries the pending T+1 movement (PRD §3.6):
      BUY  -> unsettled_cash_cents -= gross_value (a negative reserve: cash owed)
      SELL -> unsettled_cash_cents += gross_value (cash incoming)
    settled_cash is untouched until the settlement sweep crosses settles_on. This
    keeps account equity stable across fill->settle (the position's market value
    appears on the same fill)."""
    if order["side"] == "BUY":
        account["unsettled_cash_cents"] -= gross_value
    else:  # SELL
        account["unsettled_cash_cents"] += gross_value


def _make_settlement(order, fill, gross_value, rebate):
    direction = "DEBIT" if order["side"] == "BUY" else "CREDIT"
    rec = _base_full()
    rec.update({
        "account_id": order["account_id"],
        "fill_id": fill["id"],
        "direction": direction,
        "amount_cents": gross_value,
        "settles_on": iso(add_business_days(db.clock, 1)),
        "status": "UNSETTLED",
        "_pfof_rebate_cents": rebate,  # internal: credited to settled cash at settle
    })
    db.settlements[rec["id"]] = rec
    return rec


def _detect_day_trade(order, security, account, fill, qty_before):
    """On a closing fill, if an opening fill of the same security exists with the
    same logical-clock calendar date, count a day trade (PRD §3.9).

    A day trade is a same-security open-and-close: a BUY-to-open paired with a
    SELL-to-close, or a short open paired with a cover. Detection fires only on a
    *closing* fill — one reducing the position toward zero in the direction it was
    already held. A SELL is closing only when the position was long before this
    fill (qty_before > 0); a BUY is closing only when the position was short
    (qty_before < 0). A BUY that opens a fresh long (qty_before >= 0) is an opening
    fill, not a cover, so it must not count — otherwise repeated same-day round
    trips would be double-counted."""
    closing_side = order["side"]
    if closing_side == "SELL" and qty_before > 0:
        opposite = "BUY"          # SELL closes a long opened by a same-date BUY
    elif closing_side == "BUY" and qty_before < 0:
        opposite = "SELL"         # BUY covers a short opened by a same-date SELL
    else:
        return                    # this fill opens a position; it is not closing

    today = date_floor(db.clock)
    # find any opening fill on same security, opposite side, same calendar date
    for f in db.fills.values():
        if f["id"] == fill["id"]:
            continue
        if f["account_id"] != account["id"]:
            continue
        o = db.orders.get(f["order_id"])
        if o is None or o["security_id"] != security["id"]:
            continue
        if o["side"] != opposite:
            continue
        f_date = date_floor(parse_iso(f["created_at"]))
        if f_date == today:
            # count one day trade
            account["_dt_events"].append({"date": iso(db.clock), "count": 1})
            order["opened_day_trade"] = True
            break


def _base_ref_fill():
    """Fill carries only id + created_at (immutable record, PRD §2.4)."""
    from db import new_id
    return {"id": new_id(), "created_at": created_ts(), "_seq": db.next_seq()}
