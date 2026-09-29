"""TradeOrder, Block and TaxLot routes, including CASCADE-B (PRD 3.7)."""

from flask import Blueprint, g

from core import (
    ApiError, READ_ROLES, ROLE_PLATFORM_ADMIN, ROLE_SPONSOR_OPERATOR, arg,
    body_json, clock, db, lookup, new_row, ok, paged, qfilter, require_roles,
    sequence_sort_key, serialize, sponsor_scope, touch, v_int,
)
from calc import (
    account_restrictions, apply_hifo_plan, hifo_plan, pro_rata_allocation,
    settled_shares, wash_window_occupied,
)
from entities import (
    block_members, recompute_block_allocation, recompute_block_membership,
)

bp = Blueprint("trading", __name__)


# -------------------------------------------------------------- TradeOrder --
@bp.get("/sma/trade-orders/<trade_order_id>")
@require_roles(*READ_ROLES)
def get_trade_order(trade_order_id):
    row = lookup(db.trade_orders, trade_order_id, "ERR_TRADE_ORDER_NOT_FOUND")
    return ok(serialize(row))


@bp.get("/sma/trade-orders")
@require_roles(*READ_ROLES)
def list_trade_orders():
    rows = qfilter(db.trade_orders.values(),
                   account_id=arg("account_id"),
                   security_id=arg("security_id"),
                   model_version_id=arg("model_version_id"),
                   block_id=arg("block_id"),
                   status=arg("status"),
                   source=arg("source"),
                   side=arg("side"))
    return paged(rows, sort_key=sequence_sort_key)


@bp.post("/sma/trade-orders/<trade_order_id>/cancel")
@require_roles(ROLE_SPONSOR_OPERATOR)
def cancel_trade_order(trade_order_id):
    order = lookup(db.trade_orders, trade_order_id, "ERR_TRADE_ORDER_NOT_FOUND")
    account = db.accounts.get(order["account_id"])
    if account is not None:
        sponsor_scope(account["sponsor_id"])

    if order["status"] == "PROPOSED":
        order["status"] = "CANCELLED"
        touch(order)
    elif order["status"] == "BLOCKED":
        block = db.blocks.get(order.get("block_id"))
        if block is None or block["status"] != "OPEN":
            raise ApiError("ERR_INVALID_STATE",
                           "A blocked order may only be cancelled while its block is OPEN.")
        order["status"] = "CANCELLED"
        order["block_id"] = None
        touch(order)
        recompute_block_membership(block)
    else:
        raise ApiError("ERR_INVALID_STATE", "The order cannot be cancelled from its current state.")
    return ok(serialize(order))


# ------------------------------------------------------------------- Block --
def _security_restricted(account_id, security_id):
    security = db.securities.get(security_id)
    if security is not None and security.get("restricted_globally"):
        return True
    for restriction in account_restrictions(account_id):
        if (restriction["security_id"] == security_id
                and restriction["restriction_type"] in ("DO_NOT_BUY", "DO_NOT_HOLD")):
            return True
    return False


@bp.post("/sma/blocks")
@require_roles(ROLE_SPONSOR_OPERATOR)
def create_block():
    body = body_json()
    raw = body.get("trade_order_ids")

    # Rung 3: sponsor scope over every resolvable member order.
    if isinstance(raw, list):
        for item in raw:
            if isinstance(item, str):
                order = db.trade_orders.get(item)
                if order is not None:
                    account = db.accounts.get(order["account_id"])
                    if account is not None:
                        sponsor_scope(account["sponsor_id"])

    # Rung 6: body reference existence.
    if isinstance(raw, list):
        for item in raw:
            if isinstance(item, str) and item not in db.trade_orders:
                raise ApiError("ERR_TRADE_ORDER_NOT_FOUND", "Trade order '%s' does not exist." % item)

    # Rung 7: request shape.
    if raw is None or not isinstance(raw, list):
        raise ApiError("ERR_INVALID_REQUEST", "Field 'trade_order_ids' must be an array.")
    for item in raw:
        if not isinstance(item, str) or not item:
            raise ApiError("ERR_INVALID_REQUEST",
                           "Every entry of 'trade_order_ids' must be a string id.")

    seen = set()
    orders = []
    for item in raw:
        if item in seen:
            continue
        seen.add(item)
        orders.append(db.trade_orders[item])

    # Rung 9: no member order's account may be SUSPENDED.
    for order in orders:
        account = db.accounts.get(order["account_id"])
        if account is not None and account["implementation_status"] == "SUSPENDED":
            raise ApiError("ERR_ACCOUNT_SUSPENDED", "A member order's account is suspended.")

    # Rung 13: restricted securities on the BUY side.
    for order in orders:
        if order["side"] == "BUY" and _security_restricted(order["account_id"], order["security_id"]):
            raise ApiError("ERR_SECURITY_RESTRICTED",
                           "A BUY order targets a security restricted for its account.")

    # Rung 14: wash-window occupation on the BUY side.
    for order in orders:
        if order["side"] == "BUY" and wash_window_occupied(order["account_id"], order["security_id"]):
            raise ApiError("ERR_WASH_SALE_WINDOW_CONFLICT",
                           "A losing lot's wash window covers the current clock date.")

    # Rung 20: block composition.
    if not orders:
        raise ApiError("ERR_BLOCK_COMPOSITION_INVALID", "'trade_order_ids' must be non-empty.")
    for order in orders:
        if order["status"] != "PROPOSED":
            raise ApiError("ERR_BLOCK_COMPOSITION_INVALID",
                           "Every listed order must be in status PROPOSED.")
    securities = {o["security_id"] for o in orders}
    sides = {o["side"] for o in orders}
    if len(securities) != 1 or len(sides) != 1:
        raise ApiError("ERR_BLOCK_COMPOSITION_INVALID",
                       "Every listed order must share one security and one side.")

    block = new_row(
        security_id=orders[0]["security_id"],
        side=orders[0]["side"],
        status="OPEN",
        requested_shares=sum(o["shares"] for o in orders),
        filled_shares=0,
        allocated_shares=0,
        unallocated_shares=0,
        avg_fill_price_cents=None,
        order_count=len(orders),
        executed_at=None,
        allocated_at=None,
    )
    db.blocks[block["id"]] = block
    for order in orders:
        order["status"] = "BLOCKED"
        order["block_id"] = block["id"]
        touch(order)
    return ok(serialize(block), 201)


@bp.get("/sma/blocks/<block_id>")
@require_roles(*READ_ROLES)
def get_block(block_id):
    row = lookup(db.blocks, block_id, "ERR_BLOCK_NOT_FOUND")
    return ok(serialize(row))


@bp.get("/sma/blocks")
@require_roles(*READ_ROLES)
def list_blocks():
    rows = qfilter(db.blocks.values(),
                   security_id=arg("security_id"),
                   status=arg("status"),
                   side=arg("side"))
    return paged(rows)


@bp.post("/sma/blocks/<block_id>/execute")
@require_roles(ROLE_PLATFORM_ADMIN)
def execute_block(block_id):
    block = lookup(db.blocks, block_id, "ERR_BLOCK_NOT_FOUND")
    body = body_json()
    filled_shares = v_int(body, "filled_shares")
    avg_fill_price_cents = v_int(body, "avg_fill_price_cents", minimum=1)

    if block["status"] != "OPEN":
        raise ApiError("ERR_INVALID_STATE", "Only an OPEN block may be executed.")
    if filled_shares < 1 or filled_shares > block["requested_shares"]:
        raise ApiError("ERR_FILL_EXCEEDS_REQUEST",
                       "'filled_shares' must be between 1 and the block's requested_shares.")

    block["filled_shares"] = filled_shares
    block["avg_fill_price_cents"] = avg_fill_price_cents
    block["executed_at"] = clock()
    block["status"] = "FILLED"
    block["allocated_shares"] = 0
    block["unallocated_shares"] = filled_shares
    touch(block)
    return ok(serialize(block))


@bp.post("/sma/blocks/<block_id>/allocate")
@require_roles(ROLE_PLATFORM_ADMIN)
def allocate_block(block_id):
    block = lookup(db.blocks, block_id, "ERR_BLOCK_NOT_FOUND")

    members = sorted(block_members(block["id"]), key=lambda o: (o["created_at"], o["_seq"]))
    participating = [o for o in members if o["status"] == "BLOCKED"]

    # Rung 9: no member order's account may be SUSPENDED.
    for order in participating:
        account = db.accounts.get(order["account_id"])
        if account is not None and account["implementation_status"] == "SUSPENDED":
            raise ApiError("ERR_ACCOUNT_SUSPENDED", "A member order's account is suspended.")

    # Rung 11: from-state.
    if block["status"] != "FILLED":
        raise ApiError("ERR_INVALID_STATE", "Only a FILLED block may be allocated.")

    alloc = pro_rata_allocation(block["filled_shares"], participating)
    price = block["avg_fill_price_cents"]

    # Rung 27: every BUY allocation must be covered by its account's cash.
    if block["side"] == "BUY":
        needed = {}
        for order in participating:
            cost = alloc[order["id"]] * price
            needed[order["account_id"]] = needed.get(order["account_id"], 0) + cost
        for account_id, cost in needed.items():
            account = db.accounts.get(account_id)
            if account is not None and account["cash_cents"] < cost:
                raise ApiError("ERR_INSUFFICIENT_CASH",
                               "The account's cash does not cover its allocation.")
    else:
        wanted = {}
        for order in participating:
            key = (order["account_id"], order["security_id"])
            wanted[key] = wanted.get(key, 0) + alloc[order["id"]]
        for (account_id, security_id), shares in wanted.items():
            if shares > settled_shares(account_id, security_id):
                raise ApiError("ERR_INSUFFICIENT_SHARES",
                               "The account does not hold enough open shares.")

    # --- CASCADE-B ---------------------------------------------------------
    for order in participating:
        shares = alloc[order["id"]]
        account = db.accounts.get(order["account_id"])
        if shares == 0:
            order["status"] = "CANCELLED"
            order["allocated_shares"] = 0
            touch(order)
            continue

        order["status"] = "ALLOCATED"
        order["allocated_shares"] = shares
        order["fill_price_cents"] = price
        touch(order)

        if account is None:
            continue

        if block["side"] == "BUY":
            lot = new_row(
                account_id=account["id"],
                security_id=order["security_id"],
                parent_tax_lot_id=None,
                opening_trade_order_id=order["id"],
                closing_trade_order_id=None,
                sequence_number=account["next_order_sequence"],
                origin="TRADE",
                open_date=clock(),
                shares_open=shares,
                shares_closed=0,
                cost_basis_cents=shares * price,
                status="OPEN",
                realized_gain_cents=None,
                close_date=None,
                wash_window_start=None,
                wash_window_end=None,
            )
            account["next_order_sequence"] += 1
            db.tax_lots[lot["id"]] = lot
            account["cash_cents"] -= lot["cost_basis_cents"]
        else:
            plan = hifo_plan(account["id"], order["security_id"], shares, price)
            closed_rows = apply_hifo_plan(account, plan, closing_trade_order_id=order["id"])
            account["cash_cents"] += shares * price
            for row in closed_rows:
                realized = row.get("realized_gain_cents")
                if realized is not None and realized < 0:
                    account["realized_loss_ytd_cents"] += abs(realized)
        touch(account)

    block["status"] = "ALLOCATED"
    block["allocated_at"] = clock()
    recompute_block_allocation(block)
    touch(block)
    return ok(serialize(block))


@bp.post("/sma/blocks/<block_id>/unwind")
@require_roles(ROLE_PLATFORM_ADMIN)
def unwind_block(block_id):
    block = lookup(db.blocks, block_id, "ERR_BLOCK_NOT_FOUND")
    if block["status"] != "ALLOCATED":
        raise ApiError("ERR_INVALID_STATE", "Only an ALLOCATED block may be unwound.")

    members = sorted(block_members(block["id"]), key=lambda o: (o["created_at"], o["_seq"]))
    member_ids = {o["id"] for o in members}

    # Lots this block's *current* allocation opened.  A lot already REVERSED by
    # an earlier unwind of the same block belongs to a previous round trip.
    opened_lots = [l for l in db.tax_lots.values()
                   if l.get("opening_trade_order_id") in member_ids
                   and l["status"] != "REVERSED"]
    # Rung 22: unwind safety.
    for lot in opened_lots:
        if lot["status"] != "OPEN":
            raise ApiError("ERR_UNWIND_BLOCKED",
                           "A tax lot opened by this block is no longer OPEN.")

    closed_lots = [l for l in db.tax_lots.values()
                   if l.get("closing_trade_order_id") in member_ids and l["status"] == "CLOSED"]

    # Restore disposals.
    for lot in closed_lots:
        account = db.accounts.get(lot["account_id"])
        realized = lot.get("realized_gain_cents")
        if account is not None and realized is not None and realized < 0:
            account["realized_loss_ytd_cents"] -= abs(realized)
            touch(account)
        if lot.get("parent_tax_lot_id") is None:
            lot["status"] = "OPEN"
            lot["shares_open"] = lot["shares_closed"]
            lot["shares_closed"] = 0
            lot["realized_gain_cents"] = None
            lot["close_date"] = None
            lot["closing_trade_order_id"] = None
            lot["wash_window_start"] = None
            lot["wash_window_end"] = None
            touch(lot)
        else:
            parent = db.tax_lots.get(lot["parent_tax_lot_id"])
            if parent is not None:
                parent["shares_open"] += lot["shares_closed"]
                parent["cost_basis_cents"] += lot["cost_basis_cents"]
                touch(parent)
            lot["status"] = "REVERSED"
            touch(lot)

    # Reverse acquisitions.
    for lot in opened_lots:
        account = db.accounts.get(lot["account_id"])
        lot["status"] = "REVERSED"
        lot["shares_open"] = 0
        touch(lot)
        if account is not None:
            account["cash_cents"] += lot["cost_basis_cents"]
            touch(account)

    # Restore member orders and the proceeds their disposals produced.
    for order in members:
        if order["status"] != "ALLOCATED":
            continue
        account = db.accounts.get(order["account_id"])
        if account is not None and block["side"] == "SELL":
            account["cash_cents"] -= order["allocated_shares"] * (order["fill_price_cents"] or 0)
            touch(account)
        order["status"] = "BLOCKED"
        order["allocated_shares"] = 0
        order["fill_price_cents"] = None
        touch(order)

    block["status"] = "FILLED"
    block["allocated_at"] = None
    block["allocated_shares"] = 0
    block["unallocated_shares"] = block["filled_shares"]
    touch(block)
    return ok(serialize(block))


# ------------------------------------------------------------------ TaxLot --
@bp.get("/sma/tax-lots/<tax_lot_id>")
@require_roles(*READ_ROLES)
def get_tax_lot(tax_lot_id):
    row = lookup(db.tax_lots, tax_lot_id, "ERR_TAX_LOT_NOT_FOUND")
    return ok(serialize(row))


@bp.get("/sma/tax-lots")
@require_roles(*READ_ROLES)
def list_tax_lots():
    rows = qfilter(db.tax_lots.values(),
                   account_id=arg("account_id"),
                   security_id=arg("security_id"),
                   parent_tax_lot_id=arg("parent_tax_lot_id"),
                   opening_trade_order_id=arg("opening_trade_order_id"),
                   closing_trade_order_id=arg("closing_trade_order_id"),
                   status=arg("status"),
                   origin=arg("origin"))
    return paged(rows, sort_key=sequence_sort_key)
