"""Derived aggregates, cascades and compensating reversals (PRD 2.9, 2.10)."""
from decimal import Decimal

from calc import (INITIAL_MARGIN_USD_PER_LOT, POSTURE_FROZEN_AT,
                  POSTURE_RESTRICTED_AT, REPLACEMENT_ADMIN_FEE_USD,
                  realized_on_close)
from errors import fail
from store import D, apply_changes, db, parse_date, r2, r4, sort_rows, touch


# --------------------------------------------------------------------------
# Derivations on a single purchase contract row
# --------------------------------------------------------------------------
def derive_pricing(contract, changes):
    """Fill unpriced_bushels / gross_unit_price_cents / pricing_status."""
    def value(field):
        return changes[field] if field in changes else contract.get(field)

    bushels = D(value("bushels"))
    priced_f = D(value("priced_futures_bushels"))
    priced_b = D(value("priced_basis_bushels"))
    changes["unpriced_bushels"] = bushels - min(priced_f, priced_b)

    futures = value("futures_price_cents")
    basis = value("basis_cents")
    if futures is None or basis is None:
        changes["gross_unit_price_cents"] = None
    else:
        changes["gross_unit_price_cents"] = (
            D(futures) + D(basis) + D(value("roll_adjustment_cents")))

    if priced_f >= bushels and priced_b >= bushels:
        changes["pricing_status"] = "FULLY_PRICED"
    elif priced_f == 0 and priced_b == 0:
        changes["pricing_status"] = "UNPRICED"
    else:
        changes["pricing_status"] = "PARTIALLY_PRICED"
    return changes


def derive_delivery_status(bushels, delivered):
    if D(delivered) <= 0:
        return "OPEN"
    if D(delivered) >= D(bushels):
        return "COMPLETE"
    return "PARTIALLY_DELIVERED"


# --------------------------------------------------------------------------
# Position / bid / location aggregates
# --------------------------------------------------------------------------
def sync_position(position, changes=None):
    changes = dict(changes or {})
    lots_open = changes.get("lots_open", position["lots_open"])
    committed = 0
    for contract in db.purchase_contracts.values():
        if contract["hedge_position_id"] == position["id"] \
                and contract["status"] == "ACTIVE":
            committed += contract["hedge_lots_assigned"]
    changes["lots_committed"] = committed
    changes["lots_available"] = lots_open - committed
    apply_changes(position, changes)


def sync_bid(bid):
    total = Decimal(0)
    for contract in db.purchase_contracts.values():
        if contract["bid_id"] == bid["id"] and \
                contract["status"] in ("ACTIVE", "SETTLED", "ROLLED"):
            total += D(contract["bushels"])
    apply_changes(bid, {"contracted_bushels": r2(total)})


def sync_location(location):
    total = Decimal(0)
    for contract in db.purchase_contracts.values():
        if contract["location_id"] == location["id"] \
                and contract["status"] == "ACTIVE":
            total += D(contract["bushels"])
    apply_changes(location, {"committed_intake_bushels": r2(total)})


# --------------------------------------------------------------------------
# Desk credit posture (PRD 2.9) and the freeze / unlock cascade (PRD 2.10)
# --------------------------------------------------------------------------
def desk_positions(desk_id):
    return [p for p in db.hedge_positions.values() if p["desk_id"] == desk_id]


def recompute_desk(desk):
    positions = desk_positions(desk["id"])
    live = [p for p in positions if p["status"] in ("OPEN", "MARGIN_CALL")]

    margin_requirement = r2(sum(
        (D(p["lots_open"]) * INITIAL_MARGIN_USD_PER_LOT[p["commodity_code"]]
         for p in live), Decimal(0)))

    open_calls = Decimal(0)
    for call in db.margin_calls.values():
        if call["status"] != "OPEN":
            continue
        position = db.hedge_positions.get(call["hedge_position_id"])
        if position is not None and position["desk_id"] == desk["id"]:
            open_calls += D(call["call_amount_usd"])
    open_calls = r2(open_calls)

    credit_line = D(desk["credit_line_usd"])
    available = r2(credit_line - margin_requirement - open_calls)
    utilization = r4((margin_requirement + open_calls) / credit_line)

    if utilization >= POSTURE_FROZEN_AT:
        posture = "FROZEN"
    elif utilization >= POSTURE_RESTRICTED_AT:
        posture = "RESTRICTED"
    else:
        posture = "NORMAL"

    committed_lots = sum(p["lots_committed"] for p in live)

    active = [c for c in db.purchase_contracts.values()
              if c["desk_id"] == desk["id"] and c["status"] == "ACTIVE"]
    open_bushels = r2(sum((D(c["bushels"]) - D(c["delivered_bushels"])
                           for c in active), Decimal(0)))
    unpriced = r2(sum((D(c["unpriced_bushels"]) for c in active), Decimal(0)))
    realized = r2(sum((D(p["realized_pnl_usd"]) for p in positions), Decimal(0)))

    previous_posture = desk["posture"]
    apply_changes(desk, {
        "margin_requirement_usd": margin_requirement,
        "open_margin_call_usd": open_calls,
        "available_credit_usd": available,
        "credit_utilization": utilization,
        "posture": posture,
        "committed_hedge_lots": committed_lots,
        "open_bushel_commitment": open_bushels,
        "unpriced_bushels": unpriced,
        "realized_hedge_pnl_usd": realized,
    })

    if posture == "FROZEN" and previous_posture != "FROZEN":
        for contract in active:
            if contract["pricing_status"] != "FULLY_PRICED":
                apply_changes(contract, {"pricing_locked": True})
    elif previous_posture == "FROZEN" and posture != "FROZEN":
        for contract in active:
            apply_changes(contract, {"pricing_locked": False})


def desk_of(row_with_desk_id):
    return db.trading_desks[row_with_desk_id["desk_id"]]


# --------------------------------------------------------------------------
# Settlement cascade (PRD 3.8 hops 3-5)
# --------------------------------------------------------------------------
def settle_hedge_lift(contract):
    """Lift the contract's hedge lots off its position and recompute the desk."""
    position = db.hedge_positions.get(contract["hedge_position_id"])
    if position is not None:
        lifted = contract["hedge_lots_assigned"]
        realized = D(position["realized_pnl_usd"]) + realized_on_close(
            position, position["last_settlement_price_cents"], lifted)
        posted = r2(D(position["posted_margin_usd"]) - D(lifted)
                    * INITIAL_MARGIN_USD_PER_LOT[position["commodity_code"]])
        sync_position(position, {
            "lots_open": position["lots_open"] - lifted,
            "realized_pnl_usd": r2(realized),
            "posted_margin_usd": posted,
        })
    finish_contract_release(contract)


def finish_contract_release(contract):
    """Recompute every aggregate a contract status change touches."""
    position = db.hedge_positions.get(contract["hedge_position_id"])
    if position is not None:
        sync_position(position)
    bid = db.bids.get(contract["bid_id"])
    if bid is not None:
        sync_bid(bid)
    location = db.elevator_locations.get(contract["location_id"])
    if location is not None:
        sync_location(location)
    desk = db.trading_desks.get(contract["desk_id"])
    if desk is not None:
        recompute_desk(desk)


# --------------------------------------------------------------------------
# Damages arithmetic (PRD 3.9)
# --------------------------------------------------------------------------
def _window_covers(bid, delivery_end):
    start = parse_date(bid["delivery_period_start"])
    end = parse_date(bid["delivery_period_end"])
    return start <= delivery_end <= end


def compute_damages(contract, method):
    if contract["pricing_status"] != "FULLY_PRICED":
        return Decimal("0.00")

    delivery_end = parse_date(contract["delivery_end"])
    pool = []
    if method == "MARKET_LOSS":
        for bid in db.bids.values():
            if bid["status"] != "ACTIVE":
                continue
            if bid["location_id"] != contract["location_id"]:
                continue
            if bid["commodity_code"] != contract["commodity_code"]:
                continue
            if not _window_covers(bid, delivery_end):
                continue
            pool.append(bid)
        if not pool:
            fail("ERR_NO_MARKET_BID")
        pool.sort(key=lambda b: (b["created_at"], b["_seq"]), reverse=True)
        best = pool[0]
        top = [b for b in pool if b["created_at"] == best["created_at"]]
        if len(top) > 1:
            top.sort(key=lambda b: (D(b["basis_cents"]), b["_seq"]), reverse=True)
            best = top[0]
        admin_fee = Decimal("0.00")
    else:
        desk_location_ids = {loc["id"] for loc in db.elevator_locations.values()
                             if loc["desk_id"] == contract["desk_id"]}
        for bid in db.bids.values():
            if bid["status"] != "ACTIVE":
                continue
            if bid["commodity_code"] != contract["commodity_code"]:
                continue
            if bid["location_id"] not in desk_location_ids:
                continue
            if not _window_covers(bid, delivery_end):
                continue
            pool.append(bid)
        if not pool:
            fail("ERR_NO_REPLACEMENT_BID")
        pool.sort(key=lambda b: (-D(b["basis_cents"]), b["created_at"], b["_seq"]))
        best = pool[0]
        admin_fee = REPLACEMENT_ADMIN_FEE_USD

    undelivered = D(contract["bushels"]) - D(contract["delivered_bushels"])
    position = db.hedge_positions.get(contract["hedge_position_id"])
    futures_ref = D(position["last_settlement_price_cents"])
    market_unit_price = futures_ref + D(best["basis_cents"])
    spread = market_unit_price - D(contract["gross_unit_price_cents"])
    if spread < 0:
        spread = Decimal(0)
    return r2(spread * undelivered / Decimal(100)) + admin_fee
