"""Trading order matching engine — price-time priority for EXCHANGE channel."""

from decimal import Decimal

import clock
import db
from helpers import bump, common_create, to_dec, round_half_up_2
from services import audit
from services.calculations import calc_trade_fee


def _balance_for(enterprise, instrument):
    """For QUOTA: total spendable = quota_balance + paid_quota_balance.
       For CCER: ccer_balance."""
    if instrument == "QUOTA":
        return to_dec(enterprise["quota_balance"]) + to_dec(enterprise["paid_quota_balance"])
    return to_dec(enterprise["ccer_balance"])


def _debit_seller(enterprise, instrument, qty):
    """Debit instrument balance from seller. Spends free quota first, then paid."""
    qty = to_dec(qty)
    if instrument == "QUOTA":
        free = to_dec(enterprise["quota_balance"])
        spend_free = min(free, qty)
        enterprise["quota_balance"] = free - spend_free
        remaining = qty - spend_free
        if remaining > 0:
            enterprise["paid_quota_balance"] = to_dec(enterprise["paid_quota_balance"]) - remaining
    else:
        enterprise["ccer_balance"] = to_dec(enterprise["ccer_balance"]) - qty


def _credit_buyer(enterprise, instrument, qty):
    """Credit instrument balance to buyer.
       Per scaffold: buyer's paid_quota_balance += matched_qty for QUOTA."""
    qty = to_dec(qty)
    if instrument == "QUOTA":
        enterprise["paid_quota_balance"] = to_dec(enterprise["paid_quota_balance"]) + qty
    else:
        enterprise["ccer_balance"] = to_dec(enterprise["ccer_balance"]) + qty


def _resting_book(side, instrument, channel):
    """Open or partially-filled orders on the opposite side, same instrument and channel."""
    out = []
    for o in db.trading_orders.values():
        if o["status"] not in ("OPEN", "PARTIALLY_FILLED"):
            continue
        if o["side"] != side:
            continue
        if o["instrument"] != instrument:
            continue
        if o["channel"] != channel:
            continue
        out.append(o)
    return out


def _create_trade(buy_order, sell_order, instrument, channel, quantity, price):
    """Create a Trade, compute fees, update balances, append audit log."""
    gross_value, fee_per_side = calc_trade_fee(channel, quantity, price)
    now = clock.now()
    trade = {
        "id": db.new_id(),
        "buy_order_id": buy_order["id"],
        "sell_order_id": sell_order["id"],
        "instrument": instrument,
        "channel": channel,
        "quantity": to_dec(quantity),
        "price": to_dec(price),
        "gross_value": gross_value,
        "buyer_fee": fee_per_side,
        "seller_fee": fee_per_side,
        "settlement_status": "SETTLED",   # Apply balance changes synchronously.
        "executed_at": now,
        "created_at": now,
    }
    db.trades[trade["id"]] = trade

    # Apply balance changes.
    buyer = db.enterprises[buy_order["enterprise_id"]]
    seller = db.enterprises[sell_order["enterprise_id"]]
    qty = to_dec(quantity)
    _credit_buyer(buyer, instrument, qty)
    _debit_seller(seller, instrument, qty)
    bump(buyer)
    bump(seller)

    # Audit log per trade.
    audit.append(
        subject_type="TRADE_RECORD",
        subject_id=trade["id"],
        enterprise_id=buyer["id"],
        action="TRADE_EXECUTED",
        delta_quota=qty if instrument == "QUOTA" else Decimal("0"),
        delta_ccer=qty if instrument == "CCER" else Decimal("0"),
        external_system=None,
    )
    audit.append(
        subject_type="TRADE_RECORD",
        subject_id=trade["id"],
        enterprise_id=seller["id"],
        action="TRADE_EXECUTED",
        delta_quota=(-qty) if instrument == "QUOTA" else Decimal("0"),
        delta_ccer=(-qty) if instrument == "CCER" else Decimal("0"),
        external_system=None,
    )
    return trade


def _advance_status(order):
    """Update order's status based on filled_quantity vs quantity."""
    qty = to_dec(order["quantity"])
    filled = to_dec(order["filled_quantity"])
    if filled >= qty:
        order["status"] = "FILLED"
    elif filled > 0:
        order["status"] = "PARTIALLY_FILLED"
    # otherwise leave as OPEN.
    bump(order)


def _can_match_price(taker, maker):
    """True if taker buy >= maker sell (or vice versa)."""
    if taker["order_type"] == "MARKET":
        return True
    if maker["order_type"] == "MARKET":
        return True
    taker_price = to_dec(taker["limit_price"])
    maker_price = to_dec(maker["limit_price"])
    if taker["side"] == "BUY":
        return taker_price >= maker_price
    return taker_price <= maker_price


def _maker_sort_key(side):
    """For BUYers (taker), best ask = lowest price first; for SELLers, best bid = highest first.
    Tie-break by placed_at ASC (older first)."""
    if side == "BUY":
        return lambda m: (to_dec(m["limit_price"]) if m["limit_price"] is not None else Decimal("0"),
                          m["placed_at"])
    # taker SELL: pair against BUYers, want highest price first
    return lambda m: (-(to_dec(m["limit_price"]) if m["limit_price"] is not None else Decimal("0")),
                      m["placed_at"])


def match_exchange(taker):
    """Run price-time priority matching for an EXCHANGE order."""
    opposite = "SELL" if taker["side"] == "BUY" else "BUY"
    candidates = _resting_book(opposite, taker["instrument"], "EXCHANGE")
    # MARKET makers shouldn't typically rest; filter out makers without a price for sort,
    # but keep them for matching as price-takers (sorted last).
    candidates_with_price = [c for c in candidates if c.get("limit_price") is not None]
    candidates_with_price.sort(key=_maker_sort_key(taker["side"]))

    for maker in candidates_with_price:
        remaining_taker = to_dec(taker["quantity"]) - to_dec(taker["filled_quantity"])
        if remaining_taker <= 0:
            break
        if not _can_match_price(taker, maker):
            break
        remaining_maker = to_dec(maker["quantity"]) - to_dec(maker["filled_quantity"])
        if remaining_maker <= 0:
            continue

        # Re-validate seller balance (concurrency check at fill time).
        sell_order = maker if maker["side"] == "SELL" else taker
        seller = db.enterprises[sell_order["enterprise_id"]]
        # available balance on the instrument
        avail = _balance_for(seller, taker["instrument"])
        match_qty = min(remaining_taker, remaining_maker, avail)
        if match_qty <= 0:
            # Seller balance exhausted; if maker is the seller, leave it open;
            # if taker is the seller, we'll exit and reject below.
            if sell_order["id"] == taker["id"]:
                break
            continue

        # Match price = price of resting (older) order = maker's limit_price.
        price = to_dec(maker["limit_price"])
        buy_order = taker if taker["side"] == "BUY" else maker
        # sell_order already set above.
        _create_trade(buy_order, sell_order, taker["instrument"], "EXCHANGE",
                      match_qty, price)

        taker["filled_quantity"] = to_dec(taker["filled_quantity"]) + match_qty
        maker["filled_quantity"] = to_dec(maker["filled_quantity"]) + match_qty
        _advance_status(maker)


def match_block(taker):
    """BLOCK channel: requires explicit counterparty acceptance, which we model
    as the presence of an open opposite-side order with matching quantity & price."""
    opposite = "SELL" if taker["side"] == "BUY" else "BUY"
    candidates = _resting_book(opposite, taker["instrument"], "BLOCK")
    # Accept first candidate that matches price exactly and has enough size.
    for maker in candidates:
        if not _can_match_price(taker, maker):
            continue
        remaining_taker = to_dec(taker["quantity"]) - to_dec(taker["filled_quantity"])
        remaining_maker = to_dec(maker["quantity"]) - to_dec(maker["filled_quantity"])
        # Block trades match the smaller of the two.
        match_qty = min(remaining_taker, remaining_maker)
        if match_qty <= 0:
            continue
        sell_order = maker if maker["side"] == "SELL" else taker
        seller = db.enterprises[sell_order["enterprise_id"]]
        avail = _balance_for(seller, taker["instrument"])
        if avail < match_qty:
            continue
        price = to_dec(maker["limit_price"]) if maker["limit_price"] is not None else to_dec(taker["limit_price"])
        buy_order = taker if taker["side"] == "BUY" else maker
        _create_trade(buy_order, sell_order, taker["instrument"], "BLOCK",
                      match_qty, price)
        taker["filled_quantity"] = to_dec(taker["filled_quantity"]) + match_qty
        maker["filled_quantity"] = to_dec(maker["filled_quantity"]) + match_qty
        _advance_status(maker)
        if to_dec(taker["filled_quantity"]) >= to_dec(taker["quantity"]):
            break


def match_otc(taker):
    """OTC: match like EXCHANGE against opposite OTC orders, settled directly."""
    opposite = "SELL" if taker["side"] == "BUY" else "BUY"
    candidates = _resting_book(opposite, taker["instrument"], "OTC")
    candidates_with_price = [c for c in candidates if c.get("limit_price") is not None]
    candidates_with_price.sort(key=_maker_sort_key(taker["side"]))

    for maker in candidates_with_price:
        if not _can_match_price(taker, maker):
            break
        remaining_taker = to_dec(taker["quantity"]) - to_dec(taker["filled_quantity"])
        if remaining_taker <= 0:
            break
        remaining_maker = to_dec(maker["quantity"]) - to_dec(maker["filled_quantity"])
        sell_order = maker if maker["side"] == "SELL" else taker
        seller = db.enterprises[sell_order["enterprise_id"]]
        avail = _balance_for(seller, taker["instrument"])
        match_qty = min(remaining_taker, remaining_maker, avail)
        if match_qty <= 0:
            if sell_order["id"] == taker["id"]:
                break
            continue
        price = to_dec(maker["limit_price"])
        buy_order = taker if taker["side"] == "BUY" else maker
        _create_trade(buy_order, sell_order, taker["instrument"], "OTC",
                      match_qty, price)
        taker["filled_quantity"] = to_dec(taker["filled_quantity"]) + match_qty
        maker["filled_quantity"] = to_dec(maker["filled_quantity"]) + match_qty
        _advance_status(maker)


def run_matching(taker):
    """Dispatch matching by channel."""
    if taker["channel"] == "EXCHANGE":
        match_exchange(taker)
    elif taker["channel"] == "BLOCK":
        match_block(taker)
    elif taker["channel"] == "OTC":
        match_otc(taker)
    _advance_status(taker)
