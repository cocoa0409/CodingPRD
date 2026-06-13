"""Order reserve, matching engine, and fill cascade (§3.8, §3.9)."""
from decimal import Decimal

from db import db, new_id, next_seq
from numeric import D, round_half_up, round_up, round_usd, to_number
from services.common import (
    touch, available,
    credit_available, debit_available,
    credit_reserved, debit_reserved,
)
from services.cost_basis import create_lot, dispose
from services.fees import fee_bps_for_account

MARKET_SLIPPAGE_CEILING = D("0.05")
MAX_TAKER_FEE_BPS = D("30")  # TIER_BASE worst-case headroom


def _best_ask(base_asset, quote_asset):
    """Lowest limit_price among OPEN/PARTIALLY_FILLED resting SELL orders for the pair."""
    best = None
    for o in db.orders.values():
        if (o["base_asset"] == base_asset and o["quote_asset"] == quote_asset
                and o["side"] == "SELL" and o["order_type"] == "LIMIT"
                and o["lifecycle_status"] in ("OPEN", "PARTIALLY_FILLED")
                and D(o["reserved_remaining"]) > 0):
            p = D(o["limit_price"])
            if best is None or p < best:
                best = p
    return best


def has_resting_sell(base_asset, quote_asset):
    return _best_ask(base_asset, quote_asset) is not None


def compute_reserve(order, base_asset_cfg, quote_asset_cfg):
    """Return (reserve_asset_symbol, reserve_qty Decimal). Raises ERR_NO_LIQUIDITY for empty market-buy book."""
    from errors import err
    side = order["side"]
    qty = D(order["quantity"])
    if side == "SELL":
        reserve_asset = order["base_asset"]
        reserve_qty = qty
        decimals = base_asset_cfg["decimals"]
    else:  # BUY
        reserve_asset = order["quote_asset"]
        decimals = quote_asset_cfg["decimals"]
        if order["order_type"] == "LIMIT":
            gross = qty * D(order["limit_price"])
            reserve_qty = gross * (D(1) + MAX_TAKER_FEE_BPS / D(10000))
        else:  # MARKET BUY
            best = _best_ask(order["base_asset"], order["quote_asset"])
            if best is None:
                raise err("ERR_NO_LIQUIDITY", "No resting sell liquidity for market buy")
            reserve_qty = (qty * best
                           * (D(1) + MARKET_SLIPPAGE_CEILING)
                           * (D(1) + MAX_TAKER_FEE_BPS / D(10000)))
    reserve_qty = round_up(reserve_qty, decimals)
    return reserve_asset, reserve_qty


def _crossing_candidates(incoming):
    base = incoming["base_asset"]
    quote = incoming["quote_asset"]
    opp = "SELL" if incoming["side"] == "BUY" else "BUY"
    is_market = incoming["order_type"] == "MARKET"
    cands = []
    for o in db.orders.values():
        if o["id"] == incoming["id"]:
            continue
        if o["base_asset"] != base or o["quote_asset"] != quote:
            continue
        if o["side"] != opp:
            continue
        if o["lifecycle_status"] not in ("OPEN", "PARTIALLY_FILLED"):
            continue
        if o["order_type"] != "LIMIT":
            continue
        resting_remaining = D(o["quantity"]) - D(o["filled_quantity"])
        if resting_remaining <= 0:
            continue
        rprice = D(o["limit_price"])
        if incoming["side"] == "BUY":
            crosses = is_market or D(incoming["limit_price"]) >= rprice
        else:
            crosses = is_market or D(incoming["limit_price"]) <= rprice
        if crosses:
            cands.append(o)
    # Rank by price-time priority.
    if incoming["side"] == "BUY":
        cands.sort(key=lambda o: (D(o["limit_price"]), o["created_at"], o["_seq"]))
    else:
        cands.sort(key=lambda o: (-D(o["limit_price"]), o["created_at"], o["_seq"]))
    return cands


def _recompute_avg_fill(order):
    # notional-weighted average across this order's trades.
    total_qty = D(0)
    total_notional = D(0)
    for t in db.trades.values():
        if t["maker_order_id"] == order["id"] or t["taker_order_id"] == order["id"]:
            q = D(t["quantity"])
            total_qty += q
            total_notional += q * D(t["price"])
    if total_qty == 0:
        order["avg_fill_price"] = None
    else:
        order["avg_fill_price"] = total_notional / total_qty


def _settle_fill(maker, taker, price, qty, base_cfg, quote_cfg):
    """Execute one fill: append Trade, move balances, charge fees, lots, volume."""
    base = maker["base_asset"]
    quote = maker["quote_asset"]
    base_dec = base_cfg["decimals"]
    quote_dec = quote_cfg["decimals"]
    now = db.clock.now()

    qty = round_half_up(qty, base_dec)
    notional_quote = qty * price  # quote units
    notional_usd = round_usd(qty * price * D(quote_cfg["spot_price_usd"]))

    # Fees per side, each from its own account's tier.
    maker_bps = fee_bps_for_account(db, maker["account_id"], "maker")
    taker_bps = fee_bps_for_account(db, taker["account_id"], "taker")
    maker_fee = round_half_up(notional_quote * maker_bps / D(10000), quote_dec)
    taker_fee = round_half_up(notional_quote * taker_bps / D(10000), quote_dec)

    # Identify buyer/seller.
    buyer = taker if taker["side"] == "BUY" else maker
    seller = maker if taker["side"] == "BUY" else taker

    buyer_base = db.get_or_create_balance(buyer["account_id"], base)
    buyer_quote = db.get_or_create_balance(buyer["account_id"], quote)
    seller_base = db.get_or_create_balance(seller["account_id"], base)
    seller_quote = db.get_or_create_balance(seller["account_id"], quote)

    # Append the Trade.
    trade = {
        "id": new_id(),
        "maker_order_id": maker["id"],
        "taker_order_id": taker["id"],
        "base_asset": base,
        "quote_asset": quote,
        "price": price,
        "quantity": qty,
        "notional_usd": notional_usd,
        "maker_fee": maker_fee,
        "taker_fee": taker_fee,
        "executed_at": now,
        "created_at": now,
        "_seq": next_seq(),
    }
    db.trades[trade["id"]] = trade

    # --- balance settlement ---
    # Seller delivers base from its reserve (reserved -> out). Buyer receives base.
    debit_reserved(seller_base, qty)
    credit_available(buyer_base, qty)

    # Buyer pays quote: notional from reserve. Seller receives quote notional.
    debit_reserved(buyer_quote, notional_quote)
    credit_available(seller_quote, notional_quote)

    # Fees debited in quote from each side's available.
    if taker_fee > 0:
        debit_available(buyer_quote if buyer is taker else seller_quote, taker_fee)
    if maker_fee > 0:
        debit_available(buyer_quote if buyer is maker else seller_quote, maker_fee)

    # --- reserved_remaining bookkeeping on the orders ---
    # Buyer (quote reserve) releases notional from reserved_remaining.
    # Seller (base reserve) releases qty from reserved_remaining.
    buyer_order = taker if taker["side"] == "BUY" else maker
    seller_order = maker if taker["side"] == "BUY" else taker
    buyer_order["reserved_remaining"] = D(buyer_order["reserved_remaining"]) - notional_quote
    if D(buyer_order["reserved_remaining"]) < 0:
        buyer_order["reserved_remaining"] = D(0)
    seller_order["reserved_remaining"] = D(seller_order["reserved_remaining"]) - qty
    if D(seller_order["reserved_remaining"]) < 0:
        seller_order["reserved_remaining"] = D(0)

    # --- cost basis: buyer acquires (TRADE_BUY), seller disposes ---
    create_lot(buyer["account_id"], base, "TRADE_BUY", trade["id"],
               qty, notional_usd / qty if qty != 0 else D(0), now, base_dec)
    dispose(seller["account_id"], base, qty, notional_usd, _method(seller["account_id"]), base_dec)

    # --- fills ---
    for o in (maker, taker):
        o["filled_quantity"] = round_half_up(D(o["filled_quantity"]) + qty, base_dec)
        _recompute_avg_fill(o)

    return trade


def _method(account_id):
    acct = db.accounts.get(account_id)
    return acct["cost_basis_method"] if acct else "FIFO"


def _release_residual(order):
    """When an order finalises, return its leftover reserve (fee/slippage
    headroom plus any unfilled remainder) from balance.reserved to available."""
    residual = D(order["reserved_remaining"])
    if residual > 0:
        reserve_asset = order["base_asset"] if order["side"] == "SELL" else order["quote_asset"]
        bal = db.get_or_create_balance(order["account_id"], reserve_asset)
        from services.common import debit_reserved, credit_available
        debit_reserved(bal, residual)
        credit_available(bal, residual)
    order["reserved_remaining"] = D(0)


def run_match(incoming, base_cfg, quote_cfg):
    """Walk crossing candidates, filling until exhausted. Mutates orders/balances."""
    base_dec = base_cfg["decimals"]
    incoming_remaining = D(incoming["quantity"]) - D(incoming["filled_quantity"])
    touched_accounts = {incoming["account_id"]}

    while incoming_remaining > 0:
        candidates = _crossing_candidates(incoming)
        if not candidates:
            break
        maker = candidates[0]
        maker_remaining = D(maker["quantity"]) - D(maker["filled_quantity"])
        fill_qty = maker_remaining if maker_remaining < incoming_remaining else incoming_remaining
        fill_qty = round_half_up(fill_qty, base_dec)
        if fill_qty <= 0:
            break
        price = D(maker["limit_price"])
        _settle_fill(maker, incoming, price, fill_qty, base_cfg, quote_cfg)
        touched_accounts.add(maker["account_id"])

        # Update lifecycle of maker.
        if D(maker["filled_quantity"]) >= D(maker["quantity"]):
            _release_residual(maker)
            maker["lifecycle_status"] = "FILLED"
        else:
            maker["lifecycle_status"] = "PARTIALLY_FILLED"
        touch(maker)

        incoming_remaining = D(incoming["quantity"]) - D(incoming["filled_quantity"])

    # Update incoming lifecycle.
    if D(incoming["filled_quantity"]) >= D(incoming["quantity"]):
        _release_residual(incoming)
        incoming["lifecycle_status"] = "FILLED"
    elif D(incoming["filled_quantity"]) > 0:
        incoming["lifecycle_status"] = "PARTIALLY_FILLED"
    else:
        incoming["lifecycle_status"] = "OPEN"

    return touched_accounts
