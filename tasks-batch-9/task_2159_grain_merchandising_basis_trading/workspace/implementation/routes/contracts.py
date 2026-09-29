"""Purchase contracts and pricing orders."""
from datetime import timedelta
from decimal import Decimal

from flask import Blueprint, request

from aggregates import (compute_damages, derive_delivery_status, derive_pricing,
                        finish_contract_release, recompute_desk,
                        settle_hedge_lift, sync_bid, sync_location,
                        sync_position)
from auth import ALL_ROLES, endpoint
from calc import (DEFAULT_GRACE_DAYS, ROLL_SERVICE_FEE_CENTS, hedge_lots_for,
                  weighted_average)
from errors import fail
from response import ok, paged
from serializers import contract_out, pricing_order_out
from store import (D, apply_changes, db, end_of_day, new_row, parse_date, r2,
                   sort_rows)
from validate import (COMPONENTS, CONTRACT_TYPES, DAMAGES_METHODS,
                      SETTLEMENT_BASES, body, guard_payload, lookup, lookup_fk,
                      opt_enum, req_date, req_enum, req_num, req_str)

bp = Blueprint("contracts", __name__)


# --------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------
def _committed_overlapping(location_id, start, end, exclude_id=None):
    """Bushels on ACTIVE contracts at the elevator whose CLOSED delivery
    interval intersects [start, end]; touching endpoints DO intersect."""
    total = Decimal(0)
    for contract in db.purchase_contracts.values():
        if contract["location_id"] != location_id or contract["status"] != "ACTIVE":
            continue
        if exclude_id is not None and contract["id"] == exclude_id:
            continue
        other_start = parse_date(contract["delivery_start"])
        other_end = parse_date(contract["delivery_end"])
        if other_start <= end and start <= other_end:
            total += D(contract["bushels"])
    return total


def _legs_for_type(contract_type, bushels, futures_price, bid_basis):
    if contract_type == "CASH":
        return futures_price, bid_basis, D(bushels), D(bushels)
    if contract_type == "HTA":
        return futures_price, None, D(bushels), Decimal(0)
    if contract_type == "BASIS":
        return None, bid_basis, Decimal(0), D(bushels)
    return None, None, Decimal(0), Decimal(0)


def _new_contract(**fields):
    row = new_row()
    row.update({
        "bid_id": None,
        "desk_id": None,
        "location_id": None,
        "hedge_position_id": None,
        "rolled_from_contract_id": None,
        "contract_type": None,
        "commodity_code": None,
        "futures_month": None,
        "seller_name": None,
        "bushels": Decimal(0),
        "delivery_start": None,
        "delivery_end": None,
        "settlement_basis": "SHRINK_FIRST",
        "futures_price_cents": None,
        "basis_cents": None,
        "roll_adjustment_cents": Decimal(0),
        "gross_unit_price_cents": None,
        "priced_futures_bushels": Decimal(0),
        "priced_basis_bushels": Decimal(0),
        "unpriced_bushels": Decimal(0),
        "hedge_lots_assigned": 0,
        "delivered_bushels": Decimal(0),
        "settled_value_usd": Decimal("0.00"),
        "damages_usd": Decimal("0.00"),
        "termination_reason": None,
        "created_by_user_id": None,
        "pricing_locked": False,
        "pricing_status": "UNPRICED",
        "delivery_status": "OPEN",
        "status": "ACTIVE",
    })
    row.update(fields)
    changes = {}
    derive_pricing(row, changes)
    row.update(changes)
    db.purchase_contracts[row["id"]] = row
    return row


def maybe_settle(contract):
    """ACTIVE -> SETTLED when delivery is COMPLETE on a FULLY_PRICED contract."""
    if contract["status"] != "ACTIVE":
        return False
    if contract["delivery_status"] != "COMPLETE":
        return False
    if contract["pricing_status"] != "FULLY_PRICED":
        return False
    apply_changes(contract, {"status": "SETTLED"})
    settle_hedge_lift(contract)
    return True


# --------------------------------------------------------------------------
# POST /grain/purchase-contracts
# --------------------------------------------------------------------------
@bp.post("/grain/purchase-contracts")
@endpoint(["Merchandiser"])
def create_contract(actor):
    payload = guard_payload(body())
    bid = lookup_fk(payload, "bid_id", "bids")                       # ladder 4
    position = lookup_fk(payload, "hedge_position_id", "hedge_positions")
    if bid is None or position is None:
        fail("ERR_INVALID_REQUEST")

    contract_type = req_enum(payload, "contract_type", CONTRACT_TYPES)  # ladder 5
    bushels = req_num(payload, "bushels", minimum=0, exclusive_min=True)
    seller_name = req_str(payload, "seller_name")
    delivery_start = req_date(payload, "delivery_start")
    delivery_end = req_date(payload, "delivery_end")
    settlement_basis = opt_enum(payload, "settlement_basis", SETTLEMENT_BASES,
                                "SHRINK_FIRST")
    supplies_futures = contract_type in ("CASH", "HTA")
    has_futures = payload.get("futures_price_cents") is not None
    if supplies_futures and not has_futures:
        fail("ERR_INVALID_REQUEST",
             "futures_price_cents is required for CASH and HTA contracts.")
    if not supplies_futures and has_futures:
        fail("ERR_INVALID_REQUEST",
             "futures_price_cents must be omitted for BASIS and DEFERRED contracts.")
    futures_price = req_num(payload, "futures_price_cents") if supplies_futures else None

    location = db.elevator_locations[bid["location_id"]]
    desk = db.trading_desks[location["desk_id"]]

    if bid["status"] != "ACTIVE":                                    # ladder 11
        fail("ERR_BID_NOT_ACTIVE")
    if position["status"] != "OPEN":                                 # ladder 12
        fail("ERR_HEDGE_POSITION_NOT_OPEN")
    if (position["desk_id"] != desk["id"]                            # ladder 14
            or position["commodity_code"] != bid["commodity_code"]
            or position["futures_month"] != bid["futures_month"]):
        fail("ERR_HEDGE_POSITION_MISMATCH")

    period_start = parse_date(bid["delivery_period_start"])          # ladder 17
    period_end = parse_date(bid["delivery_period_end"])
    if not (period_start <= delivery_start <= delivery_end <= period_end):
        fail("ERR_DELIVERY_WINDOW_INVALID")

    if desk["posture"] == "FROZEN":                                  # ladder 22
        fail("ERR_DESK_FROZEN")
    if contract_type == "DEFERRED" and desk["posture"] == "RESTRICTED":
        fail("ERR_DESK_RESTRICTED")                                  # ladder 23

    _f, _b, priced_futures, priced_basis = _legs_for_type(
        contract_type, bushels, futures_price, bid["basis_cents"])
    new_unpriced = D(bushels) - min(priced_futures, priced_basis)

    limit_row = None                                                 # ladder 24
    for row in db.risk_limits.values():
        if row["desk_id"] == desk["id"] and row["status"] == "ACTIVE" \
                and row["commodity_code"] == bid["commodity_code"]:
            limit_row = row
            break
    if limit_row is not None:
        projected = D(desk["unpriced_bushels"]) + new_unpriced
        if projected > D(limit_row["max_unpriced_bushels"]):
            fail("ERR_RISK_LIMIT_BREACH")

    committed = _committed_overlapping(location["id"], delivery_start, delivery_end)
    if committed + D(bushels) > D(location["intake_capacity_bushels"]):
        fail("ERR_LOCATION_CAPACITY_EXCEEDED")                       # ladder 28

    hedge_lots = hedge_lots_for(bushels)                             # ladder 33
    if position["lots_open"] - position["lots_committed"] < hedge_lots:
        fail("ERR_INSUFFICIENT_HEDGE_LOTS")

    if D(bid["contracted_bushels"]) + D(bushels) > D(bid["max_bushels"]):
        fail("ERR_BID_MAX_BUSHELS_EXCEEDED")                         # ladder 34

    futures_leg, basis_leg, priced_futures, priced_basis = _legs_for_type(
        contract_type, bushels, futures_price, bid["basis_cents"])
    contract = _new_contract(
        bid_id=bid["id"],
        desk_id=desk["id"],
        location_id=location["id"],
        hedge_position_id=position["id"],
        contract_type=contract_type,
        commodity_code=bid["commodity_code"],
        futures_month=bid["futures_month"],
        seller_name=seller_name,
        bushels=D(bushels),
        delivery_start=delivery_start.isoformat(),
        delivery_end=delivery_end.isoformat(),
        settlement_basis=settlement_basis,
        futures_price_cents=futures_leg,
        basis_cents=basis_leg,
        priced_futures_bushels=priced_futures,
        priced_basis_bushels=priced_basis,
        hedge_lots_assigned=hedge_lots,
        created_by_user_id=actor["user_id"],
    )
    sync_position(position)
    sync_bid(bid)
    sync_location(location)
    recompute_desk(desk)
    return ok(contract_out(contract), 201)


# --------------------------------------------------------------------------
# POST /grain/purchase-contracts/{contractId}/roll
# --------------------------------------------------------------------------
@bp.post("/grain/purchase-contracts/<contract_id>/roll")
@endpoint(["Merchandiser"])
def roll_contract(actor, contract_id):
    contract = lookup("purchase_contracts", contract_id)             # ladder 3
    payload = guard_payload(body())
    position = lookup_fk(payload, "new_hedge_position_id", "hedge_positions")
    if position is None:
        fail("ERR_INVALID_REQUEST")
    new_start = req_date(payload, "new_delivery_start")              # ladder 5
    new_end = req_date(payload, "new_delivery_end")
    roll_spread = req_num(payload, "roll_spread_cents")

    if contract["status"] != "ACTIVE":                               # ladder 9
        fail("ERR_CONTRACT_NOT_ACTIVE")
    if contract["delivery_status"] == "COMPLETE":
        fail("ERR_INVALID_STATE", "a fully delivered contract has no balance to roll.")

    if position["status"] != "OPEN":                                 # ladder 12
        fail("ERR_HEDGE_POSITION_NOT_OPEN")
    if (position["desk_id"] != contract["desk_id"]                   # ladder 14
            or position["commodity_code"] != contract["commodity_code"]):
        fail("ERR_HEDGE_POSITION_MISMATCH")

    bid = db.bids.get(contract["bid_id"])                            # ladder 17
    period_start = parse_date(bid["delivery_period_start"])
    period_end = parse_date(bid["delivery_period_end"])
    if not (period_start <= new_start <= new_end <= period_end):
        fail("ERR_DELIVERY_WINDOW_INVALID")

    if contract["pricing_locked"]:                                   # ladder 21
        fail("ERR_PRICING_LOCKED")
    desk = db.trading_desks[contract["desk_id"]]
    if desk["posture"] == "FROZEN":                                  # ladder 22
        fail("ERR_DESK_FROZEN")

    location = db.elevator_locations[contract["location_id"]]
    successor_bushels = D(contract["bushels"]) - D(contract["delivered_bushels"])
    committed = _committed_overlapping(location["id"], new_start, new_end,
                                       exclude_id=contract["id"])
    if committed + successor_bushels > D(location["intake_capacity_bushels"]):
        fail("ERR_LOCATION_CAPACITY_EXCEEDED")                       # ladder 28

    hedge_lots = hedge_lots_for(successor_bushels)                   # ladder 33
    if position["lots_open"] - position["lots_committed"] < hedge_lots:
        fail("ERR_INSUFFICIENT_HEDGE_LOTS")

    old_position = db.hedge_positions.get(contract["hedge_position_id"])
    apply_changes(contract, {"status": "ROLLED"})

    successor = _new_contract(
        bid_id=contract["bid_id"],
        desk_id=contract["desk_id"],
        location_id=contract["location_id"],
        hedge_position_id=position["id"],
        rolled_from_contract_id=contract["id"],
        contract_type=contract["contract_type"],
        commodity_code=contract["commodity_code"],
        futures_month=position["futures_month"],
        seller_name=contract["seller_name"],
        bushels=successor_bushels,
        delivery_start=new_start.isoformat(),
        delivery_end=new_end.isoformat(),
        settlement_basis=contract["settlement_basis"],
        futures_price_cents=contract["futures_price_cents"],
        basis_cents=contract["basis_cents"],
        roll_adjustment_cents=D(roll_spread) - ROLL_SERVICE_FEE_CENTS,
        priced_futures_bushels=min(D(contract["priced_futures_bushels"]),
                                   successor_bushels),
        priced_basis_bushels=min(D(contract["priced_basis_bushels"]),
                                 successor_bushels),
        hedge_lots_assigned=hedge_lots,
        created_by_user_id=actor["user_id"],
    )

    if old_position is not None:
        sync_position(old_position)
    sync_position(position)
    sync_bid(bid)
    sync_location(location)
    recompute_desk(desk)
    return ok(contract_out(successor), 201)


# --------------------------------------------------------------------------
# cancel / declare-default
# --------------------------------------------------------------------------
@bp.post("/grain/purchase-contracts/<contract_id>/cancel")
@endpoint(["RiskOfficer"])
def cancel_contract(actor, contract_id):
    contract = lookup("purchase_contracts", contract_id)
    payload = guard_payload(body())
    method = req_enum(payload, "damages_method", DAMAGES_METHODS)
    reason = req_str(payload, "cancellation_reason")

    if contract["status"] != "ACTIVE":                               # ladder 9
        fail("ERR_CONTRACT_NOT_ACTIVE")
    if actor["user_id"] == contract["created_by_user_id"]:           # ladder 25
        fail("ERR_SEGREGATION_OF_DUTIES")

    damages = compute_damages(contract, method)                      # ladder 30/31
    apply_changes(contract, {
        "status": "CANCELLED",
        "damages_usd": r2(damages),
        "termination_reason": reason,
    })
    finish_contract_release(contract)
    return ok(contract_out(contract))


@bp.post("/grain/purchase-contracts/<contract_id>/declare-default")
@endpoint(["RiskOfficer"])
def declare_default(actor, contract_id):
    contract = lookup("purchase_contracts", contract_id)
    payload = guard_payload(body())
    reason = req_str(payload, "default_reason")

    if contract["status"] != "ACTIVE":                               # ladder 9
        fail("ERR_CONTRACT_NOT_ACTIVE")
    if contract["delivery_status"] == "COMPLETE":
        fail("ERR_INVALID_STATE", "delivery is already complete.")

    deadline = end_of_day(parse_date(contract["delivery_end"])) \
        + timedelta(days=DEFAULT_GRACE_DAYS)
    if not (db.now > deadline):                                      # ladder 20
        fail("ERR_GRACE_PERIOD_NOT_ELAPSED")

    damages = compute_damages(contract, "MARKET_LOSS")               # ladder 30
    apply_changes(contract, {
        "status": "DEFAULTED",
        "damages_usd": r2(damages),
        "termination_reason": reason,
    })
    finish_contract_release(contract)
    return ok(contract_out(contract))


@bp.get("/grain/purchase-contracts")
@endpoint(ALL_ROLES)
def list_contracts(actor):
    rows = list(db.purchase_contracts.values())
    for field in ("bid_id", "desk_id", "location_id", "hedge_position_id",
                  "rolled_from_contract_id", "status"):
        value = request.args.get(field)
        if value:
            rows = [r for r in rows if r[field] == value]
    return paged(sort_rows(rows), contract_out)


@bp.get("/grain/purchase-contracts/<contract_id>")
@endpoint(ALL_ROLES)
def read_contract(actor, contract_id):
    return ok(contract_out(lookup("purchase_contracts", contract_id)))


# --------------------------------------------------------------------------
# PricingOrder
# --------------------------------------------------------------------------
_ALLOWED_COMPONENTS = {
    "CASH": (),
    "HTA": ("BASIS",),
    "BASIS": ("FUTURES",),
    "DEFERRED": ("FUTURES", "BASIS"),
}


@bp.post("/grain/pricing-orders")
@endpoint(["Merchandiser", "FuturesTrader"])
def create_pricing_order(actor):
    payload = guard_payload(body())
    contract = lookup_fk(payload, "contract_id", "purchase_contracts")  # ladder 4
    if contract is None:
        fail("ERR_INVALID_REQUEST")
    component = req_enum(payload, "component", COMPONENTS)              # ladder 5
    bushels = req_num(payload, "bushels", minimum=0, exclusive_min=True)
    price_cents = req_num(payload, "price_cents")

    if contract["status"] != "ACTIVE":                                  # ladder 9
        fail("ERR_CONTRACT_NOT_ACTIVE")

    position = db.hedge_positions.get(contract["hedge_position_id"])
    if component == "FUTURES":                                          # ladder 12
        if position is None or position["status"] != "OPEN":
            fail("ERR_HEDGE_POSITION_NOT_OPEN")

    if contract["pricing_locked"]:                                      # ladder 21
        fail("ERR_PRICING_LOCKED")
    desk = db.trading_desks[contract["desk_id"]]
    if desk["posture"] == "FROZEN":                                     # ladder 22
        fail("ERR_DESK_FROZEN")

    if component not in _ALLOWED_COMPONENTS[contract["contract_type"]]:  # ladder 35
        fail("ERR_CONTRACT_ALREADY_PRICED")
    priced_field = ("priced_futures_bushels" if component == "FUTURES"
                    else "priced_basis_bushels")
    remaining = D(contract["bushels"]) - D(contract[priced_field])
    if remaining <= 0 or D(bushels) > remaining:
        fail("ERR_CONTRACT_ALREADY_PRICED")

    order = new_row(versioned=False)
    order.update({
        "contract_id": contract["id"],
        "component": component,
        "bushels": D(bushels),
        "price_cents": D(price_cents),
        "placed_by_user_id": actor["user_id"],
    })
    db.pricing_orders[order["id"]] = order

    siblings = [o for o in sort_rows(db.pricing_orders.values())
                if o["contract_id"] == contract["id"] and o["component"] == component]
    leg_price, priced_bushels = weighted_average(
        [(o["price_cents"], o["bushels"]) for o in siblings])

    changes = {priced_field: priced_bushels}
    if component == "FUTURES":
        changes["futures_price_cents"] = leg_price
    else:
        changes["basis_cents"] = leg_price
    derive_pricing(contract, changes)
    apply_changes(contract, changes)

    recompute_desk(desk)
    maybe_settle(contract)
    return ok(pricing_order_out(order), 201)


@bp.get("/grain/pricing-orders")
@endpoint(ALL_ROLES)
def list_pricing_orders(actor):
    rows = list(db.pricing_orders.values())
    for field in ("contract_id", "component"):
        value = request.args.get(field)
        if value:
            rows = [r for r in rows if r[field] == value]
    return paged(sort_rows(rows), pricing_order_out)


@bp.get("/grain/pricing-orders/<pricing_order_id>")
@endpoint(ALL_ROLES)
def read_pricing_order(actor, pricing_order_id):
    return ok(pricing_order_out(lookup("pricing_orders", pricing_order_id)))
