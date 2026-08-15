"""Order + order-line endpoints and the lifecycle flows (PRD §3.4-§3.7)."""
import copy

from flask import Blueprint, request, g

import db
from errors import (err_invalid_request, err_not_found, err_invalid_state,
                    err_account_suspended, err_order_empty, err_po_required,
                    err_duplicate_po, err_case_qty_mismatch, err_artwork_required,
                    err_credit_limit_exceeded, err_custom_production_started)
from middleware import (require_roles, get_json_body, check_account_ownership,
                        scoped_account_id)
from response import success_object, success_list, parse_pagination, paginate
from serializers import ser_order, ser_order_line
from services import pricing, sourcing
from util import is_int, is_number, to_decimal

bp = Blueprint("orders", __name__)
PREFIX = "/packaging-distribution"

ORDER_READ_ROLES = ("PlatformAdmin", "CustomerService", "WarehouseOps",
                    "Buyer", "AccountApprover")
ORDER_STATUSES = {"DRAFT", "PENDING", "PO_REVIEW", "STOCK_RESERVED",
                  "CUSTOM_PRODUCTION", "SHIPPED", "PARTIALLY_BACKORDERED",
                  "CANCELLED", "RETURNED"}
LINE_STATUSES = {"OPEN", "ALLOCATED", "IN_PRODUCTION", "SHIPPED",
                 "BACKORDERED", "CANCELLED"}
WAREHOUSE_CODES = {"ATL", "RNO", "DFW"}
CANCELLABLE_STATUSES = {"DRAFT", "PENDING", "STOCK_RESERVED",
                        "PARTIALLY_BACKORDERED", "CUSTOM_PRODUCTION"}

_STORE_NAMES = ("accounts", "products", "warehouses", "inventory",
                "inventory_by_pair", "quantity_breaks", "orders",
                "order_lines", "custom_print_jobs", "returns", "return_lines",
                "restock_notifications")


def _snapshot():
    return {name: copy.deepcopy(getattr(db, name)) for name in _STORE_NAMES}


def _restore(snap):
    for name in _STORE_NAMES:
        store = getattr(db, name)
        store.clear()
        store.update(snap[name])


def _get_order(order_id):
    o = db.orders.get(order_id)
    if o is None:
        raise err_not_found("Order not found.")
    return o


def _get_line_in_order(order, line_id):
    line = db.order_lines.get(line_id)
    if line is None or line["order_id"] != order["id"]:
        raise err_not_found("Order line not found.")
    return line


def _validate_requested_warehouse(code, product):
    if code is None:
        return
    if not isinstance(code, str) or code not in WAREHOUSE_CODES:
        raise err_invalid_request("Field 'requested_warehouse_code' must be one of ATL | RNO | DFW | null.")
    wh = next((w for w in db.warehouses.values() if w["code"] == code), None)
    if wh is None:
        raise err_not_found("Referenced warehouse does not exist in the registry.")
    if product["oversize"] and not wh["oversize_capable"]:
        from errors import err_no_warehouse_capable
        raise err_no_warehouse_capable("Requested warehouse cannot ship oversize lines.")


def _validate_qty_for_product(product, qty):
    """Priority 9: case multiple + qty >= 1 under ERR_CASE_QTY_MISMATCH for CASE;
    qty < 1 on EACH products is a malformed payload (400)."""
    if product["uom"] == "CASE":
        if qty < 1 or qty % product["case_qty"] != 0:
            raise err_case_qty_mismatch()
    else:
        if qty < 1:
            raise err_invalid_request("Field 'qty' must be >= 1.")


# ---------------------------------------------------------------------------
# Order CRUD
# ---------------------------------------------------------------------------
@bp.route(f"{PREFIX}/orders", methods=["POST"])
@require_roles("Buyer")
def create_order():
    body = get_json_body(required=True)
    account_id = body.get("account_id")
    if not isinstance(account_id, str) or not account_id:
        raise err_invalid_request("Missing required field: account_id.")
    check_account_ownership(account_id)
    account = db.accounts.get(account_id)
    if account is None:
        raise err_not_found("Account not found.")
    ship_zone = body.get("ship_zone")
    if not is_int(ship_zone):
        raise err_invalid_request("Field 'ship_zone' must be an integer.")
    if ship_zone < 1 or ship_zone > 8:
        raise err_invalid_request("Field 'ship_zone' must be in 1..8.")
    po_number = body.get("po_number")
    if po_number is not None and not isinstance(po_number, str):
        raise err_invalid_request("Field 'po_number' must be a string.")

    now = db.now()
    o = {
        "id": db.new_id(),
        "_seq": db.next_seq(),
        "account_id": account_id,
        "status": "DRAFT",
        "ship_zone": ship_zone,
        "po_number": po_number,
        "subtotal_cents": 0,
        "pallet_discount_cents": 0,
        "oversize_surcharge_cents": 0,
        "freight_estimate_cents": 0,
        "grand_total_cents": 0,
        "invoice_status": "OPEN",
        "submitted_at": None,
        "promised_ship_date": None,
        "_stock_promise": None,
        "created_at": now,
        "updated_at": now,
        "version": 1,
    }
    db.orders[o["id"]] = o
    return success_object(ser_order(o), status=201)


@bp.route(f"{PREFIX}/orders", methods=["GET"])
@require_roles(*ORDER_READ_ROLES)
def list_orders():
    limit, offset = parse_pagination(request.args)
    account_f = request.args.get("account_id")
    status_f = request.args.get("status")
    if status_f is not None and status_f not in ORDER_STATUSES:
        raise err_invalid_request("Invalid 'status' filter.")
    scoped = scoped_account_id()
    items = sorted(db.orders.values(), key=lambda o: (o["created_at"], o["_seq"]))
    if scoped is not None:
        items = [o for o in items if o["account_id"] == scoped]
    if account_f is not None:
        items = [o for o in items if o["account_id"] == account_f]
    if status_f is not None:
        items = [o for o in items if o["status"] == status_f]
    page, pagination = paginate(items, limit, offset)
    return success_list([ser_order(o) for o in page], pagination)


@bp.route(f"{PREFIX}/orders/<order_id>", methods=["GET"])
@require_roles(*ORDER_READ_ROLES)
def get_order(order_id):
    o = _get_order(order_id)
    check_account_ownership(o["account_id"])
    return success_object(ser_order(o))


# ---------------------------------------------------------------------------
# Order lines
# ---------------------------------------------------------------------------
@bp.route(f"{PREFIX}/orders/<order_id>/lines", methods=["POST"])
@require_roles("Buyer")
def add_order_line(order_id):
    order = _get_order(order_id)
    check_account_ownership(order["account_id"])
    body = get_json_body(required=True)
    if order["status"] != "DRAFT":
        raise err_invalid_state("Lines can be added only while the order is DRAFT.")
    product_id = body.get("product_id")
    if not isinstance(product_id, str) or not product_id:
        raise err_invalid_request("Missing required field: product_id.")
    product = db.products.get(product_id)
    if product is None:
        raise err_not_found("Product not found.")
    qty = body.get("qty")
    if not is_int(qty):
        raise err_invalid_request("Field 'qty' must be an integer.")
    requested_code = body.get("requested_warehouse_code")
    artwork = body.get("print_artwork_ref")
    if artwork is not None and not isinstance(artwork, str):
        raise err_invalid_request("Field 'print_artwork_ref' must be a string.")
    tolerance = body.get("over_under_tolerance_pct")
    if tolerance is not None and not is_number(tolerance):
        raise err_invalid_request("Field 'over_under_tolerance_pct' must be a number.")

    _validate_qty_for_product(product, qty)

    if product["is_custom_print"]:
        bad_tolerance = tolerance is None or to_decimal(tolerance) < 0 or to_decimal(tolerance) > 20
        if not artwork or bad_tolerance:
            raise err_artwork_required()

    if product["status"] == "DISCONTINUED":
        raise err_invalid_state("A DISCONTINUED product is not orderable.")

    _validate_requested_warehouse(requested_code, product)

    now = db.now()
    line = {
        "id": db.new_id(),
        "_seq": db.next_seq(),
        "order_id": order["id"],
        "product_id": product_id,
        "qty": qty,
        "requested_warehouse_code": requested_code,
        "print_artwork_ref": artwork,
        "over_under_tolerance_pct": tolerance,
        "unit_price_cents": 0,
        "freight_class": None,
        "allocated_warehouse_id": None,
        "status": "OPEN",
        "shipped_qty": 0,
        "_ready_date": None,
        "created_at": now,
        "updated_at": now,
        "version": 1,
    }
    db.order_lines[line["id"]] = line
    # compute unit price + freight class now (recomputed again at submit)
    pricing.recompute_line_price(line)
    # Derived totals refresh in DRAFT: no Order.version increment (PRD §2.4).
    pricing.calc_order_pricing(order)
    return success_object(ser_order_line(line), status=201)


@bp.route(f"{PREFIX}/orders/<order_id>/lines", methods=["GET"])
@require_roles(*ORDER_READ_ROLES)
def list_order_lines(order_id):
    order = _get_order(order_id)
    check_account_ownership(order["account_id"])
    limit, offset = parse_pagination(request.args)
    items = pricing.order_lines_of(order["id"], include_cancelled=True)
    page, pagination = paginate(items, limit, offset)
    return success_list([ser_order_line(l) for l in page], pagination)


@bp.route(f"{PREFIX}/order-lines", methods=["GET"])
@require_roles(*ORDER_READ_ROLES)
def list_order_lines_flat():
    limit, offset = parse_pagination(request.args)
    order_f = request.args.get("order_id")
    product_f = request.args.get("product_id")
    wh_f = request.args.get("allocated_warehouse_id")
    status_f = request.args.get("status")
    if status_f is not None and status_f not in LINE_STATUSES:
        raise err_invalid_request("Invalid 'status' filter.")
    scoped = scoped_account_id()
    items = sorted(db.order_lines.values(), key=lambda l: (l["created_at"], l["_seq"]))
    if scoped is not None:
        items = [l for l in items
                 if l["order_id"] in db.orders and db.orders[l["order_id"]]["account_id"] == scoped]
    if order_f is not None:
        items = [l for l in items if l["order_id"] == order_f]
    if product_f is not None:
        items = [l for l in items if l["product_id"] == product_f]
    if wh_f is not None:
        items = [l for l in items if l["allocated_warehouse_id"] == wh_f]
    if status_f is not None:
        items = [l for l in items if l["status"] == status_f]
    page, pagination = paginate(items, limit, offset)
    return success_list([ser_order_line(l) for l in page], pagination)


@bp.route(f"{PREFIX}/order-lines/<line_id>", methods=["GET"])
@require_roles(*ORDER_READ_ROLES)
def get_order_line(line_id):
    line = db.order_lines.get(line_id)
    if line is None:
        raise err_not_found("Order line not found.")
    order = db.orders.get(line["order_id"])
    if order is not None:
        check_account_ownership(order["account_id"])
    return success_object(ser_order_line(line))


@bp.route(f"{PREFIX}/orders/<order_id>/lines/<line_id>", methods=["PUT"])
@require_roles("Buyer")
def update_order_line(order_id, line_id):
    order = _get_order(order_id)
    line = _get_line_in_order(order, line_id)
    check_account_ownership(order["account_id"])
    body = get_json_body(required=True)
    if order["status"] != "DRAFT":
        raise err_invalid_state("Lines can be updated only while the order is DRAFT.")
    product = db.products[line["product_id"]]

    if "qty" in body and body["qty"] is not None:
        qty = body["qty"]
        if not is_int(qty):
            raise err_invalid_request("Field 'qty' must be an integer.")
        _validate_qty_for_product(product, qty)
        line["qty"] = qty
    if "requested_warehouse_code" in body:
        code = body["requested_warehouse_code"]
        _validate_requested_warehouse(code, product)
        line["requested_warehouse_code"] = code
    if "print_artwork_ref" in body:
        artwork = body["print_artwork_ref"]
        if artwork is not None and not isinstance(artwork, str):
            raise err_invalid_request("Field 'print_artwork_ref' must be a string.")
        line["print_artwork_ref"] = artwork
    if "over_under_tolerance_pct" in body and body["over_under_tolerance_pct"] is not None:
        tolerance = body["over_under_tolerance_pct"]
        # On update, an out-of-range tolerance is a malformed payload (PRD §3.4).
        if not is_number(tolerance) or to_decimal(tolerance) < 0 or to_decimal(tolerance) > 20:
            raise err_invalid_request("Field 'over_under_tolerance_pct' must be within 0..20.")
        line["over_under_tolerance_pct"] = tolerance

    db.touch(line)
    pricing.recompute_line_price(line)
    pricing.calc_order_pricing(order)
    return success_object(ser_order_line(line))


# ---------------------------------------------------------------------------
# Lifecycle: submit / approve / reject / ship / cancel / invoice pay
# ---------------------------------------------------------------------------
def _run_pricing_and_provisional_freight(order, account):
    """Pricing first, then selection (pure), then provisional freight using the
    selected ship-from warehouses. Returns the simulation decisions."""
    pricing.calc_order_pricing(order)
    decisions = sourcing.simulate_allocation(order, account)
    # Use the selected warehouses for the freight zone distance (provisional set:
    # all non-CANCELLED lines). Lines with no candidates contribute no warehouse.
    pricing.calc_freight_and_oversize(order, "provisional", decisions)
    return decisions


def _apply_and_finish(order, decisions):
    err = sourcing.allocation_error(decisions)
    if err is not None:
        raise err
    sourcing.apply_allocation(order, decisions)
    order["status"] = sourcing.derive_order_status(order)
    order["_stock_promise"] = sourcing.stock_promise_date(order)
    order["promised_ship_date"] = sourcing.compute_order_promise(order)


@bp.route(f"{PREFIX}/orders/<order_id>/submit", methods=["POST"])
@require_roles("Buyer")
def submit_order(order_id):
    order = _get_order(order_id)
    check_account_ownership(order["account_id"])
    if order["status"] != "DRAFT":
        raise err_invalid_state("Only a DRAFT order can be submitted.")
    account = db.accounts[order["account_id"]]
    if account["status"] != "ACTIVE":
        raise err_account_suspended()
    open_lines = [l for l in pricing.order_lines_of(order["id"]) if l["status"] == "OPEN"]
    if not open_lines:
        raise err_order_empty()
    if account["account_type"] == "CORPORATE" and account["po_required"] and not order["po_number"]:
        raise err_po_required()
    if order["po_number"]:
        for other in db.orders.values():
            if (other["id"] != order["id"]
                    and other["account_id"] == account["id"]
                    and other["status"] != "DRAFT"
                    and other["po_number"] == order["po_number"]):
                raise err_duplicate_po()

    snap = _snapshot()
    try:
        decisions = _run_pricing_and_provisional_freight(order, account)
        if (account["account_type"] == "CORPORATE" and account["po_required"]
                and order["grand_total_cents"] > 1000000):
            # Routed to PO_REVIEW: allocation pass deferred to approve.
            order["status"] = "PO_REVIEW"
            order["submitted_at"] = db.now()
            order["promised_ship_date"] = None
            db.touch(order)
            return success_object(ser_order(order))

        _apply_and_finish(order, decisions)
        order["submitted_at"] = db.now()
        db.touch(order)
        return success_object(ser_order(order))
    except Exception:
        _restore(snap)
        raise


@bp.route(f"{PREFIX}/orders/<order_id>/approve", methods=["POST"])
@require_roles("AccountApprover")
def approve_order(order_id):
    order = _get_order(order_id)
    check_account_ownership(order["account_id"])
    if order["status"] != "PO_REVIEW":
        raise err_invalid_state("Only a PO_REVIEW order can be approved.")
    account = db.accounts[order["account_id"]]
    if account["status"] != "ACTIVE":
        raise err_account_suspended()
    from serializers import account_open_receivable
    if account_open_receivable(account["id"]) + order["grand_total_cents"] > account["credit_limit_cents"]:
        raise err_credit_limit_exceeded()

    snap = _snapshot()
    try:
        decisions = _run_pricing_and_provisional_freight(order, account)
        _apply_and_finish(order, decisions)
        db.touch(order)
        return success_object(ser_order(order))
    except Exception:
        _restore(snap)
        raise


@bp.route(f"{PREFIX}/orders/<order_id>/reject", methods=["POST"])
@require_roles("AccountApprover")
def reject_order(order_id):
    order = _get_order(order_id)
    check_account_ownership(order["account_id"])
    if order["status"] != "PO_REVIEW":
        raise err_invalid_state("Only a PO_REVIEW order can be rejected.")
    get_json_body()  # optional reason
    # Back to DRAFT: no reservation was taken; invoice stays OPEN; totals recomputed.
    pricing.calc_order_pricing(order)
    order["status"] = "DRAFT"
    order["promised_ship_date"] = None
    order["_stock_promise"] = None
    db.touch(order)
    return success_object(ser_order(order))


@bp.route(f"{PREFIX}/orders/<order_id>/ship", methods=["POST"])
@require_roles("WarehouseOps")
def ship_order(order_id):
    order = _get_order(order_id)
    lines = pricing.order_lines_of(order["id"])
    if order["status"] == "STOCK_RESERVED":
        if not all(l["status"] == "ALLOCATED" for l in lines):
            raise err_invalid_state("Every line must be ALLOCATED to ship.")
    elif order["status"] == "CUSTOM_PRODUCTION":
        for l in lines:
            product = db.products[l["product_id"]]
            if product["is_custom_print"]:
                job = sourcing.live_job_for_line(l["id"])
                if job is None or job["status"] != "COMPLETED":
                    raise err_invalid_state("Custom-print jobs must be COMPLETED to ship.")
            elif l["status"] != "ALLOCATED":
                raise err_invalid_state("Every non-custom line must be ALLOCATED to ship.")
    elif order["status"] == "PARTIALLY_BACKORDERED":
        if not all(l["status"] in ("ALLOCATED", "BACKORDERED") for l in lines):
            raise err_invalid_state("Every non-BACKORDERED line must be ALLOCATED to ship.")
    else:
        raise err_invalid_state("Order cannot be shipped from its current state.")

    snap = _snapshot()
    try:
        shipping = [l for l in lines if l["status"] == "ALLOCATED"]
        now = db.now()
        for line in shipping:
            inv_id = db.inventory_by_pair.get((line["product_id"], line["allocated_warehouse_id"]))
            if inv_id is not None:
                inv = db.inventory[inv_id]
                inv["on_hand_qty"] -= line["qty"]
                inv["reserved_qty"] -= line["qty"]
                db.touch(inv)
            line["shipped_qty"] = line["qty"]
            line["status"] = "SHIPPED"
            db.touch(line)
        pricing.calc_freight_and_oversize(order, "final")
        order["status"] = "SHIPPED"
        db.touch(order)
        return success_object(ser_order(order))
    except Exception:
        _restore(snap)
        raise


@bp.route(f"{PREFIX}/orders/<order_id>/cancel", methods=["POST"])
@require_roles("Buyer")
def cancel_order(order_id):
    order = _get_order(order_id)
    check_account_ownership(order["account_id"])
    get_json_body()  # optional reason
    if order["status"] not in CANCELLABLE_STATUSES:
        raise err_invalid_state("Order cannot be cancelled from its current state.")
    lines = pricing.order_lines_of(order["id"])
    for l in lines:
        if db.products[l["product_id"]]["is_custom_print"]:
            job = sourcing.live_job_for_line(l["id"])
            if job is not None and job["status"] != "QUEUED":
                raise err_custom_production_started()

    snap = _snapshot()
    try:
        affected_inv = {}
        for l in lines:
            if l["status"] == "ALLOCATED":
                inv_id = db.inventory_by_pair.get((l["product_id"], l["allocated_warehouse_id"]))
                if inv_id is not None:
                    inv = db.inventory[inv_id]
                    if inv_id not in affected_inv:
                        affected_inv[inv_id] = inv["on_hand_qty"] - inv["reserved_qty"]
                    inv["reserved_qty"] -= l["qty"]
                    db.touch(inv)
        for l in lines:
            if l["status"] != "CANCELLED":
                l["status"] = "CANCELLED"
                db.touch(l)
        for l in lines:
            job = sourcing.live_job_for_line(l["id"])
            if job is not None and job["status"] == "QUEUED":
                job["status"] = "SCRAPPED"
                db.touch(job)
        for inv_id, available_before in affected_inv.items():
            sourcing.fire_notifications_for_crossing(db.inventory[inv_id], available_before)
        order["invoice_status"] = "VOID"
        order["status"] = "CANCELLED"
        db.touch(order)
        return success_object(ser_order(order))
    except Exception:
        _restore(snap)
        raise


@bp.route(f"{PREFIX}/orders/<order_id>/invoice/pay", methods=["POST"])
@require_roles("AccountApprover", "PlatformAdmin")
def pay_invoice(order_id):
    order = _get_order(order_id)
    check_account_ownership(order["account_id"])
    if order["status"] != "SHIPPED":
        raise err_invalid_state("Only a SHIPPED order's invoice can be paid.")
    if order["invoice_status"] != "OPEN":
        raise err_invalid_state("Invoice is not OPEN.")
    order["invoice_status"] = "PAID"
    db.touch(order)
    return success_object(ser_order(order))
