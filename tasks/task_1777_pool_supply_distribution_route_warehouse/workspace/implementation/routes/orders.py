"""Sales order and order line endpoints (PRD 3.4-3.6)."""
from flask import Blueprint, request

from db import db
from errors import (
    raise_error, ERR_INVALID_REQUEST, ERR_ORDER_NOT_DRAFT, ERR_ORDER_NOT_CONFIRMED,
    ERR_ORDER_NOT_LOADED, ERR_ORDER_NOT_CANCELLABLE, ERR_ORDER_LINES_SHORT,
    ERR_ORDER_ALREADY_INVOICED, ERR_ORDER_NOT_INVOICED, ERR_ORDER_UNPAID,
    ERR_BRANCH_CLOSED, ERR_BRANCH_FROZEN, ERR_BRANCH_NOT_HAZMAT_CERTIFIED,
    ERR_HAZMAT_LICENSE_EXPIRED, ERR_ROUTE_DATE_OUTSIDE_WINDOW,
    ERR_WILLCALL_NOT_AUTHORIZED, ERR_ACCOUNT_NOT_ORDERABLE, ERR_COMMITMENT_EXHAUSTED,
    ERR_STALE_BRANCH_VERSION,
)
from middleware import check_account_ownership, get_caller, require_roles
from response import success_object
from routes.helpers import ALL_READ_ROLES, STAFF_ROLES, get_one, list_response, public
from services import (
    compute_posture, create_backorder, fefo_allocate, freight_charge, new_child_record,
    new_record, price_line, ratchet_tier, reserve_bucket_for_channel, touch,
)
from util import CLOCK, parse_date
from validate import (
    get_body, opt_str, req_enum, req_str, require_path_resource, require_ref,
)

bp = Blueprint("orders", __name__)

CHANNELS = {"WILL_CALL", "ROUTE_DELIVERY"}
ORDER_WRITE_ROLES = ["CounterRep", "RouteDispatcher", "Account", "BranchManager"]


def order_lines(order_id):
    return sorted(
        (l for l in db["order_lines"].values() if l["order_id"] == order_id),
        key=lambda l: l["_seq"],
    )


# --- creation / reads ------------------------------------------------------

@bp.post("/pool-supply/orders")
def create_order():
    caller = get_caller()
    require_roles(caller, ORDER_WRITE_ROLES)
    body = get_body()
    branch_id = req_str(body, "branch_id")
    account_id = req_str(body, "account_id")
    channel = req_enum(body, "channel", CHANNELS)
    commitment_id = opt_str(body, "commitment_id")
    route_date = body.get("route_date")
    requested_pickup_slot = body.get("requested_pickup_slot")
    lines_in = body.get("lines")
    if lines_in is None or not isinstance(lines_in, list):
        raise_error(ERR_INVALID_REQUEST, "lines must be an array")
    if channel == "ROUTE_DELIVERY":
        if route_date is None:
            raise_error(ERR_INVALID_REQUEST, "route_date is required for ROUTE_DELIVERY")
    if channel == "WILL_CALL":
        if requested_pickup_slot is None:
            raise_error(ERR_INVALID_REQUEST, "requested_pickup_slot is required for WILL_CALL")
    if route_date is not None:
        from validate import req_date
        req_date(body, "route_date")
    if requested_pickup_slot is not None:
        from validate import req_datetime
        req_datetime(body, "requested_pickup_slot")
    # existence (priority 4)
    require_ref("branches", branch_id, "branch_id")
    require_ref("accounts", account_id, "account_id")
    if commitment_id is not None:
        require_ref("seasonal_commitments", commitment_id, "commitment_id")
    parsed_lines = []
    for i, item in enumerate(lines_in):
        if not isinstance(item, dict):
            raise_error(ERR_INVALID_REQUEST, f"lines[{i}] must be an object")
        pid = item.get("product_id")
        if pid is None or not isinstance(pid, str) or pid.strip() == "":
            raise_error(ERR_INVALID_REQUEST, f"lines[{i}].product_id is required")
        qty = item.get("qty")
        if qty is None or isinstance(qty, bool) or not isinstance(qty, int):
            raise_error(ERR_INVALID_REQUEST, f"lines[{i}].qty must be an integer")
        if qty < 1:
            raise_error(ERR_INVALID_REQUEST, f"lines[{i}].qty must be >= 1")
        require_ref("products", pid, f"lines[{i}].product_id")
        parsed_lines.append((pid, qty))
    order = new_record("orders", {
        "branch_id": branch_id,
        "account_id": account_id,
        "channel": channel,
        "commitment_id": commitment_id,
        "fulfillment_status": "DRAFT",
        "payment_status": "UNINVOICED",
        "order_subtotal_cents": 0,
        "freight_charge_cents": 0,
        "invoiced_cents": 0,
        "tier_at_confirm": None,
        "route_date": route_date,
        "requested_pickup_slot": requested_pickup_slot,
    })
    for pid, qty in parsed_lines:
        new_child_record("order_lines", {
            "order_id": order["id"],
            "product_id": pid,
            "qty": qty,
            "unit_price_cents": 0,
            "extended_price_cents": 0,
            "allocated_lot_id": None,
            "allocated_qty": 0,
            "backordered_qty": 0,
        })
    return success_object(public(order), status=201)


@bp.get("/pool-supply/orders")
def list_orders():
    filters = {
        "branch_id": request.args.get("branch_id"),
        "account_id": request.args.get("account_id"),
        "channel": request.args.get("channel"),
        "fulfillment_status": request.args.get("fulfillment_status"),
        "payment_status": request.args.get("payment_status"),
        "commitment_id": request.args.get("commitment_id"),
    }
    return list_response("orders", ALL_READ_ROLES, filters)


@bp.get("/pool-supply/orders/<rid>")
def get_order(rid):
    return get_one("orders", rid, ALL_READ_ROLES)


@bp.get("/pool-supply/order-lines")
def list_order_lines():
    filters = {
        "product_id": request.args.get("product_id"),
        "allocated_lot_id": request.args.get("allocated_lot_id"),
        "order_id": request.args.get("order_id"),
    }
    return list_response("order_lines", STAFF_ROLES, filters)


@bp.get("/pool-supply/order-lines/<rid>")
def get_order_line(rid):
    return get_one("order_lines", rid, STAFF_ROLES)


@bp.get("/pool-supply/orders/<rid>/lines")
def list_order_lines_for_order(rid):
    caller = get_caller()
    require_roles(caller, ALL_READ_ROLES)
    require_path_resource("orders", rid)
    lines = order_lines(rid)
    from routes.helpers import get_pagination
    from response import success_list
    total = len(lines)
    limit, offset = get_pagination()
    page = lines[offset:offset + limit]
    return success_list([public(l) for l in page], total, limit, offset)


# --- confirm ---------------------------------------------------------------

@bp.post("/pool-supply/orders/<rid>/confirm")
def confirm_order(rid):
    caller = get_caller()
    require_roles(caller, ORDER_WRITE_ROLES)
    order = require_path_resource("orders", rid)
    # ownership (priority 3)
    check_account_ownership(caller, order["account_id"])
    branch = db["branches"][order["branch_id"]]
    account = db["accounts"][order["account_id"]]
    # state preconditions (priority 5) — before the OCC version check (PRD 2.8)
    if order["fulfillment_status"] != "DRAFT":
        raise_error(ERR_ORDER_NOT_DRAFT, "confirm requires fulfillment DRAFT")
    if branch["status"] != "OPEN":
        raise_error(ERR_BRANCH_CLOSED, "branch season is closed")
    # OCC: expected_branch_version (non-optional)
    body = get_body()
    if "expected_branch_version" not in body or body["expected_branch_version"] is None:
        raise_error(ERR_INVALID_REQUEST, "expected_branch_version is required")
    ebv = body["expected_branch_version"]
    if isinstance(ebv, bool) or not isinstance(ebv, int):
        raise_error(ERR_INVALID_REQUEST, "expected_branch_version must be an integer")
    if ebv != branch["version"]:
        raise_error(ERR_STALE_BRANCH_VERSION, "stale branch version; re-read and retry")

    lines = order_lines(order["id"])
    products = {l["product_id"]: db["products"][l["product_id"]] for l in lines}
    hazmat_any = any(p["hazmat_class"] != "NONE" for p in products.values())

    # Business gauntlet in the PRD 3.4 pinned order:
    # storage -> license -> temporal -> will-call -> posture -> commitment -> fiscal
    if hazmat_any and not branch["hazmat_storage_certified"]:
        raise_error(ERR_BRANCH_NOT_HAZMAT_CERTIFIED, "branch lacks hazmat storage certification")
    if hazmat_any and order["channel"] == "ROUTE_DELIVERY":
        lic = account["hazmat_delivery_license_expiry"]
        if lic is None or parse_date(lic) <= parse_date(order["route_date"]):
            raise_error(ERR_HAZMAT_LICENSE_EXPIRED, "hazmat route delivery requires a license expiring after route_date")
    if order["channel"] == "ROUTE_DELIVERY":
        rd = parse_date(order["route_date"])
        if rd < CLOCK.today():
            raise_error(ERR_ROUTE_DATE_OUTSIDE_WINDOW, "route_date is before today")
        if hazmat_any:
            em, ed = (int(x) for x in branch["peak_season_end"].split("-"))
            if (rd.month, rd.day) > (em, ed):
                raise_error(ERR_ROUTE_DATE_OUTSIDE_WINDOW, "hazmat route_date beyond peak season end")
    if order["channel"] == "WILL_CALL" and not account["willcall_authorized"]:
        raise_error(ERR_WILLCALL_NOT_AUTHORIZED, "account is not authorized for will-call")
    if compute_posture(branch["id"]) == "FROZEN":
        raise_error(ERR_BRANCH_FROZEN, "branch posture is FROZEN")
    commitment = None
    total_units = sum(l["qty"] for l in lines)
    if order["commitment_id"] is not None:
        commitment = db["seasonal_commitments"].get(order["commitment_id"])
        if (
            commitment is None
            or commitment["status"] != "COMMITTED"
            or commitment["account_id"] != order["account_id"]
            or commitment["committed_units"] - commitment["consumed_units"] < total_units
        ):
            raise_error(ERR_COMMITMENT_EXHAUSTED, "commitment cannot cover this order")
    if account["status"] != "ACTIVE" or account["credit_hold"]:
        raise_error(ERR_ACCOUNT_NOT_ORDERABLE, "account is suspended or on credit hold")

    # ---- side effects (one act) ----
    tier_snapshot = account["tier"]
    order["tier_at_confirm"] = tier_snapshot
    seasonal_pct = None
    if commitment is not None:
        program = db["seasonal_programs"][commitment["program_id"]]
        seasonal_pct = program["early_buy_discount_pct"]
    bucket = reserve_bucket_for_channel(order["channel"])
    for line in lines:
        product = products[line["product_id"]]
        unit, extended = price_line(product, tier_snapshot, seasonal_pct, line["qty"])
        line["unit_price_cents"] = unit
        line["extended_price_cents"] = extended
        lot, grant = fefo_allocate(branch["id"], line["product_id"], line["qty"])
        if lot is not None and grant > 0:
            line["allocated_lot_id"] = lot["id"]
            line["allocated_qty"] = grant
            lot[bucket] += grant
            touch(lot)
        else:
            line["allocated_lot_id"] = None
            line["allocated_qty"] = 0
        line["backordered_qty"] = line["qty"] - line["allocated_qty"]
        if line["backordered_qty"] > 0:
            create_backorder(branch["id"], line, order, line["backordered_qty"])
    order["order_subtotal_cents"] = sum(l["extended_price_cents"] for l in lines)
    order["freight_charge_cents"] = freight_charge(order, lines)
    order["invoiced_cents"] = order["order_subtotal_cents"] + order["freight_charge_cents"]
    order["fulfillment_status"] = "CONFIRMED"
    touch(order)
    if commitment is not None:
        commitment["consumed_units"] += total_units
        if commitment["consumed_units"] == commitment["committed_units"]:
            commitment["status"] = "FULFILLED"
        touch(commitment)
    touch(branch)  # confirm mutated branch-scoped derived state
    return success_object(public(order))


# --- fulfillment transitions ----------------------------------------------

@bp.post("/pool-supply/orders/<rid>/mark-loaded")
def mark_loaded(rid):
    caller = get_caller()
    require_roles(caller, ["WarehouseLead"])
    order = require_path_resource("orders", rid)
    if order["fulfillment_status"] != "CONFIRMED":
        raise_error(ERR_ORDER_NOT_CONFIRMED, "mark-loaded requires fulfillment CONFIRMED")
    lines = order_lines(order["id"])
    if any(l["backordered_qty"] > 0 for l in lines):
        raise_error(ERR_ORDER_LINES_SHORT, "all lines must be fully allocated to load")
    bucket = reserve_bucket_for_channel(order["channel"])
    for line in lines:
        if line["allocated_lot_id"] is not None and line["allocated_qty"] > 0:
            lot = db["stock_lots"][line["allocated_lot_id"]]
            lot["qty_on_hand"] -= line["allocated_qty"]
            lot[bucket] -= line["allocated_qty"]
            touch(lot)
    order["fulfillment_status"] = "PICKED_LOADED"
    touch(order)
    return success_object(public(order))


@bp.post("/pool-supply/orders/<rid>/complete")
def complete_order(rid):
    caller = get_caller()
    require_roles(caller, ["CounterRep", "RouteDispatcher", "BranchManager"])
    order = require_path_resource("orders", rid)
    if order["fulfillment_status"] != "PICKED_LOADED":
        raise_error(ERR_ORDER_NOT_LOADED, "complete requires fulfillment PICKED_LOADED")
    if order["payment_status"] != "PAID":
        raise_error(ERR_ORDER_UNPAID, "complete requires payment PAID")
    order["fulfillment_status"] = "COMPLETED"
    touch(order)
    return success_object(public(order))


@bp.post("/pool-supply/orders/<rid>/cancel")
def cancel_order(rid):
    caller = get_caller()
    require_roles(caller, ["BranchManager", "Account"])
    order = require_path_resource("orders", rid)
    check_account_ownership(caller, order["account_id"])
    if order["fulfillment_status"] != "CONFIRMED":
        raise_error(ERR_ORDER_NOT_CANCELLABLE, "cancel requires fulfillment CONFIRMED")
    lines = order_lines(order["id"])
    bucket = reserve_bucket_for_channel(order["channel"])
    # release confirm-time reservations
    for line in lines:
        if line["allocated_lot_id"] is not None and line["allocated_qty"] > 0:
            lot = db["stock_lots"][line["allocated_lot_id"]]
            lot[bucket] -= line["allocated_qty"]
            touch(lot)
    # cancel this order's OPEN backorders; roll back its ALLOCATED backorders
    order_line_ids = {l["id"] for l in lines}
    for bo in sorted(db["backorder_requests"].values(), key=lambda b: b["_seq"]):
        if bo["order_line_id"] not in order_line_ids:
            continue
        if bo["status"] == "OPEN":
            bo["status"] = "CANCELLED"
            touch(bo)
        elif bo["status"] == "ALLOCATED":
            # Rollback path (PRD 3.7): the reserving order was cancelled before
            # load. Release the granted reservation; if the freed units cannot be
            # reassigned to another OPEN backorder of the same product, restore
            # qty_open and roll the request back to OPEN.
            granted = bo.get("_granted_units", bo["qty_original"] - bo["qty_open"])
            lot = db["stock_lots"].get(bo.get("_reservation_lot_id"))
            reassigned = 0
            if lot is not None and granted > 0:
                lot[bucket] -= granted
                from services import lot_available, sweep_backorders_for_lot
                avail_before = lot_available(lot)
                sweep_backorders_for_lot(lot)  # only OPEN backorders re-enter; bo is ALLOCATED
                reassigned = avail_before - lot_available(lot)
                touch(lot)
            if lot is None or reassigned < granted:
                bo["qty_open"] += granted
                bo["status"] = "OPEN"
            bo["_granted_units"] = 0
            bo["_reservation_lot_id"] = None
            touch(bo)
    # commitment compensation
    if order["commitment_id"] is not None:
        commitment = db["seasonal_commitments"].get(order["commitment_id"])
        if commitment is not None:
            total_units = sum(l["qty"] for l in lines)
            commitment["consumed_units"] -= total_units
            if commitment["consumed_units"] < 0:
                commitment["consumed_units"] = 0
            if (
                commitment["status"] == "FULFILLED"
                and commitment["consumed_units"] < commitment["committed_units"]
            ):
                commitment["status"] = "COMMITTED"
            touch(commitment)
    # fiscal compensation: volume leaves the ledger; tier ratchet holds
    account = db["accounts"][order["account_id"]]
    if order["payment_status"] in ("INVOICED", "PAID"):
        account["ytd_volume_cents"] -= order["invoiced_cents"]
        if account["ytd_volume_cents"] < 0:
            account["ytd_volume_cents"] = 0
        touch(account)
    order["fulfillment_status"] = "CANCELLED"
    touch(order)
    return success_object(public(order))


# --- payment transitions ----------------------------------------------------

@bp.post("/pool-supply/orders/<rid>/invoice")
def invoice_order(rid):
    caller = get_caller()
    require_roles(caller, ["BranchManager"])
    order = require_path_resource("orders", rid)
    if order["fulfillment_status"] != "CONFIRMED":
        raise_error(ERR_ORDER_NOT_CONFIRMED, "invoice requires fulfillment CONFIRMED")
    if order["payment_status"] != "UNINVOICED":
        raise_error(ERR_ORDER_ALREADY_INVOICED, "invoice requires payment UNINVOICED")
    order["payment_status"] = "INVOICED"  # invoiced_cents was computed at confirm; now frozen
    touch(order)
    account = db["accounts"][order["account_id"]]
    account["ytd_volume_cents"] += order["invoiced_cents"]
    ratchet_tier(account)  # may ratchet upward; never downward
    touch(account)
    return success_object(public(order))


@bp.post("/pool-supply/orders/<rid>/pay")
def pay_order(rid):
    caller = get_caller()
    require_roles(caller, ["BranchManager", "Account"])
    order = require_path_resource("orders", rid)
    check_account_ownership(caller, order["account_id"])
    if order["payment_status"] != "INVOICED":
        raise_error(ERR_ORDER_NOT_INVOICED, "pay requires payment INVOICED")
    order["payment_status"] = "PAID"
    touch(order)
    return success_object(public(order))
