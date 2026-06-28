"""SalesOrder + OrderLine endpoints and the order state machine.

Parallel state dimensions (PRD 3.x): fulfillment_status and payment_status
evolve independently on the same row.

Validation ordering for action endpoints follows the priority sequence in
PRD 3.11 / scaffold 1.4: auth -> authz -> existence -> request-validity ->
duplicate -> ERR_INVALID_STATE (state transition defined) -> domain guards in
priority order, with OCC (version) checked last on place/fulfill.
"""
from flask import Blueprint, request

import calc
import db
import errors
import helpers
import serialize
import validate
import clock
from auth import authenticate, require_roles
from response import ok, created, ok_list

bp = Blueprint("sales", __name__)


def _lines_of(order_id):
    return [l for l in db.order_lines.values() if l["sales_order_id"] == order_id]


def _has_account(order):
    return order["contractor_account_id"] is not None


def _recompute_order_total(order, status_filter):
    """Recompute subtotal/discount/total over lines in the given status."""
    line_totals = [
        l["line_total_cents"] for l in _lines_of(order["id"]) if l["status"] == status_filter
    ]
    subtotal, discount, total = calc.order_total(line_totals, _has_account(order))
    order["subtotal_cents"] = subtotal
    order["loyalty_discount_cents"] = discount
    order["total_cents"] = total


def _contractor_can_view_order(caller, order):
    if caller.is_contractor and order["contractor_account_id"] != caller.user_id:
        raise errors.unauthorized()


# -------------------------------------------------------------- SalesOrder ---

@bp.route("/sales-orders", methods=["POST"])
def create_order():
    caller = authenticate()
    require_roles(caller, {"SalesAssociate"})
    data = validate.body()
    account_id = validate.opt_str(data, "contractor_account_id", default=None)
    with db.lock:
        if account_id is not None:
            helpers.get_or_404(db.contractor_accounts, account_id)
        rec = db.new_record({
            "contractor_account_id": account_id,
            "fulfillment_status": "DRAFT",
            "payment_status": "UNBILLED",
            "pricing_mode": "PROVISIONAL",
            "subtotal_cents": 0,
            "loyalty_discount_cents": 0,
            "total_cents": 0,
            "points_accrued": 0,
        })
        db.sales_orders[rec["id"]] = rec
        return created(serialize.sales_order(rec))


@bp.route("/sales-orders/<rid>", methods=["GET"])
def get_order(rid):
    caller = authenticate()
    require_roles(caller, {"SalesAssociate", "AccountsManager", "Contractor"})
    with db.lock:
        rec = helpers.get_or_404(db.sales_orders, rid)
        _contractor_can_view_order(caller, rec)
        return ok(serialize.sales_order(rec))


@bp.route("/sales-orders", methods=["GET"])
def list_orders():
    caller = authenticate()
    require_roles(caller, {"SalesAssociate", "AccountsManager", "Contractor"})
    limit, offset = validate.pagination()
    account_id = request.args.get("contractor_account_id")
    fulfillment = request.args.get("fulfillment_status")
    payment = request.args.get("payment_status")
    with db.lock:
        items = list(db.sales_orders.values())
        if caller.is_contractor:
            items = [o for o in items if o["contractor_account_id"] == caller.user_id]
        if account_id is not None:
            items = [o for o in items if o["contractor_account_id"] == account_id]
        if fulfillment is not None:
            items = [o for o in items if o["fulfillment_status"] == fulfillment]
        if payment is not None:
            items = [o for o in items if o["payment_status"] == payment]
        items = helpers.sorted_by_creation(items)
        page, total = helpers.paginate(items, limit, offset)
        return ok_list([serialize.sales_order(o) for o in page], limit, offset, total)


# --------------------------------------------------------------- OrderLine ---

@bp.route("/sales-orders/<rid>/lines", methods=["POST"])
def add_line(rid):
    caller = authenticate()
    require_roles(caller, {"SalesAssociate"})
    data = validate.body()
    with db.lock:
        # path existence (priority 3) before body request-validity (priority 4)
        order = helpers.get_or_404(db.sales_orders, rid)
        product_id = validate.require_str(data, "product_id")
        qty = validate.require_number(data, "qty", exclusive_min=0)
        cut_count = validate.opt_int(data, "cut_count", default=0, minimum=0)
        product = helpers.get_or_404(db.products, product_id)
        # adding a line is only allowed while DRAFT
        if order["fulfillment_status"] != "DRAFT":
            raise errors.invalid_state("lines may only be added while order is DRAFT")
        line_total = calc.line_total(product, qty, cut_count)
        line = db.new_record({
            "sales_order_id": rid,
            "product_id": product_id,
            "qty": qty,
            "cut_count": cut_count,
            "line_total_cents": line_total,
            "status": "PENDING",
        })
        db.order_lines[line["id"]] = line
        # recompute provisional totals; does NOT bump order.version (PRD 3.2)
        _recompute_order_total(order, "PENDING")
        order["updated_at"] = clock.now()
        return created(serialize.order_line(line))


@bp.route("/sales-orders/<rid>/lines", methods=["GET"])
def list_order_lines(rid):
    caller = authenticate()
    require_roles(caller, {"SalesAssociate", "AccountsManager", "Contractor"})
    limit, offset = validate.pagination()
    with db.lock:
        order = helpers.get_or_404(db.sales_orders, rid)
        _contractor_can_view_order(caller, order)
        items = helpers.sorted_by_creation(_lines_of(rid))
        page, total = helpers.paginate(items, limit, offset)
        return ok_list([serialize.order_line(l) for l in page], limit, offset, total)


@bp.route("/order-lines/<rid>", methods=["GET"])
def get_order_line(rid):
    caller = authenticate()
    require_roles(caller, {"SalesAssociate", "AccountsManager", "Contractor"})
    with db.lock:
        line = helpers.get_or_404(db.order_lines, rid)
        if caller.is_contractor:
            order = db.sales_orders.get(line["sales_order_id"])
            if order is None or order["contractor_account_id"] != caller.user_id:
                raise errors.unauthorized()
        return ok(serialize.order_line(line))


@bp.route("/order-lines", methods=["GET"])
def list_lines():
    caller = authenticate()
    require_roles(caller, {"SalesAssociate", "AccountsManager", "InventoryManager"})
    limit, offset = validate.pagination()
    product_id = request.args.get("product_id")
    sales_order_id = request.args.get("sales_order_id")
    with db.lock:
        items = list(db.order_lines.values())
        if product_id is not None:
            items = [l for l in items if l["product_id"] == product_id]
        if sales_order_id is not None:
            items = [l for l in items if l["sales_order_id"] == sales_order_id]
        items = helpers.sorted_by_creation(items)
        page, total = helpers.paginate(items, limit, offset)
        return ok_list([serialize.order_line(l) for l in page], limit, offset, total)


# --------------------------------------------------- state-machine actions ---

@bp.route("/sales-orders/<rid>/place", methods=["POST"])
def place_order(rid):
    caller = authenticate()
    require_roles(caller, {"SalesAssociate"})
    data = validate.body()
    with db.lock:
        # existence (priority 3) is checked before request-validity (priority 4)
        order = helpers.get_or_404(db.sales_orders, rid)
        expected_version = validate.require_int(data, "expected_sales_order_version")
        # state: transition defined only from DRAFT
        if order["fulfillment_status"] != "DRAFT":
            raise errors.invalid_state("place is only defined from DRAFT")
        lines = _lines_of(rid)
        pending = [l for l in lines if l["status"] == "PENDING"]
        # priority 10: empty order
        if not pending:
            raise errors.ApiError(errors.ERR_EMPTY_ORDER, 409, "order has no PENDING lines")
        # priority 13: product discontinued
        for l in pending:
            product = db.products.get(l["product_id"])
            if product is None or product["status"] != "ACTIVE":
                raise errors.ApiError(errors.ERR_PRODUCT_DISCONTINUED, 409,
                                      "a line references a discontinued product")
        # account-specific checks (only for net-term orders)
        account = None
        if _has_account(order):
            account = db.contractor_accounts.get(order["contractor_account_id"])
            # priority 14: account suspended
            if account["status"] != "ACTIVE":
                raise errors.ApiError(errors.ERR_ACCOUNT_SUSPENDED, 409,
                                      "account is suspended")
        # recompute provisional total before the credit check (PRD 3.3)
        _recompute_order_total(order, "PENDING")
        if account is not None:
            # priority 18: credit limit (committed view: balance + this order total)
            balance = serialize.account_balance_cents(account["id"])
            if balance + order["total_cents"] > account["credit_limit_cents"]:
                raise errors.ApiError(errors.ERR_CREDIT_LIMIT_EXCEEDED, 409,
                                      "placement would exceed credit limit")
        # priority 19: OCC version check (LAST)
        if expected_version != order["version"]:
            raise errors.ApiError(errors.ERR_STALE_ORDER_VERSION, 412,
                                  "expected_sales_order_version is stale")
        # commit
        order["fulfillment_status"] = "PLACED"
        order["pricing_mode"] = "PROVISIONAL"
        db.touch(order)
        if account is not None:
            db.touch(account)  # committed_cents recomputed (derived)
        return ok(serialize.sales_order(order))


@bp.route("/sales-orders/<rid>/fulfill", methods=["POST"])
def fulfill_order(rid):
    caller = authenticate()
    require_roles(caller, {"SalesAssociate"})
    data = validate.body()
    with db.lock:
        # existence (priority 3) before request-validity (priority 4)
        order = helpers.get_or_404(db.sales_orders, rid)
        expected_version = validate.require_int(data, "expected_sales_order_version")
        if order["fulfillment_status"] != "PLACED":
            raise errors.invalid_state("fulfill is only defined from PLACED")
        # payment_status != VOIDED
        if order["payment_status"] == "VOIDED":
            raise errors.invalid_state("cannot fulfill a voided order")
        pending = [l for l in _lines_of(rid) if l["status"] == "PENDING"]
        # priority 13: product discontinued
        for l in pending:
            product = db.products.get(l["product_id"])
            if product is None or product["status"] != "ACTIVE":
                raise errors.ApiError(errors.ERR_PRODUCT_DISCONTINUED, 409,
                                      "a line references a discontinued product")
        # priority 17: insufficient stock
        for l in pending:
            product = db.products[l["product_id"]]
            if product["on_hand"] < l["qty"]:
                raise errors.ApiError(errors.ERR_INSUFFICIENT_STOCK, 409,
                                      "insufficient on-hand stock")
        # priority 19: OCC version check (LAST)
        if expected_version != order["version"]:
            raise errors.ApiError(errors.ERR_STALE_ORDER_VERSION, 412,
                                  "expected_sales_order_version is stale")
        # commit: cascade depth-3
        for l in pending:
            product = db.products[l["product_id"]]
            l["status"] = "FULFILLED"
            db.touch(l)
            product["on_hand"] = product["on_hand"] - l["qty"]
            product["reorder_needed"] = calc.reorder_needed(
                product["on_hand"], product["reorder_point"])
            db.touch(product)
        order["fulfillment_status"] = "FULFILLED"
        order["pricing_mode"] = "FINAL"
        _recompute_order_total(order, "FULFILLED")
        # loyalty accrual (account orders only)
        if _has_account(order):
            points = calc.loyalty_accrual(order["total_cents"])
            order["points_accrued"] = points
            entry = db.new_ledger_record({
                "contractor_account_id": order["contractor_account_id"],
                "delta_points": points,
                "reason": "ORDER_ACCRUAL",
                "sales_order_id": order["id"],
            })
            db.loyalty_ledger[entry["id"]] = entry
            account = db.contractor_accounts.get(order["contractor_account_id"])
            if account is not None:
                db.touch(account)  # loyalty_points recomputed (derived)
        else:
            order["points_accrued"] = 0
        db.touch(order)
        return ok(serialize.sales_order(order))


@bp.route("/sales-orders/<rid>/cancel", methods=["POST"])
def cancel_order(rid):
    caller = authenticate()
    require_roles(caller, {"SalesAssociate"})
    with db.lock:
        order = helpers.get_or_404(db.sales_orders, rid)
        if order["fulfillment_status"] not in ("PLACED", "FULFILLED"):
            raise errors.invalid_state("cancel is only defined from PLACED or FULFILLED")
        # priority 7: billing guard
        if order["payment_status"] != "UNBILLED":
            raise errors.ApiError(errors.ERR_ORDER_ALREADY_BILLED, 409,
                                  "a billed order cannot be cancelled")
        was_fulfilled = order["fulfillment_status"] == "FULFILLED"
        for l in _lines_of(rid):
            if was_fulfilled and l["status"] == "FULFILLED":
                product = db.products.get(l["product_id"])
                l["status"] = "RESTOCKED"
                db.touch(l)
                if product is not None:
                    product["on_hand"] = product["on_hand"] + l["qty"]
                    product["reorder_needed"] = calc.reorder_needed(
                        product["on_hand"], product["reorder_point"])
                    db.touch(product)
            elif l["status"] in ("PENDING", "FULFILLED"):
                # PLACED order: pending lines restocked, no on_hand change
                l["status"] = "RESTOCKED"
                db.touch(l)
        # loyalty reversal if points were accrued
        if was_fulfilled and order["points_accrued"]:
            entry = db.new_ledger_record({
                "contractor_account_id": order["contractor_account_id"],
                "delta_points": -order["points_accrued"],
                "reason": "ORDER_REVERSAL",
                "sales_order_id": order["id"],
            })
            db.loyalty_ledger[entry["id"]] = entry
            order["points_accrued"] = 0
            account = db.contractor_accounts.get(order["contractor_account_id"])
            if account is not None:
                db.touch(account)
        order["fulfillment_status"] = "CANCELLED"
        db.touch(order)
        if _has_account(order):
            account = db.contractor_accounts.get(order["contractor_account_id"])
            if account is not None:
                db.touch(account)  # committed_cents recomputed
        return ok(serialize.sales_order(order))


# ----------------------------------------------- payment-axis transitions ---

@bp.route("/sales-orders/<rid>/invoice", methods=["POST"])
def invoice_order(rid):
    caller = authenticate()
    require_roles(caller, {"AccountsManager"})
    with db.lock:
        order = helpers.get_or_404(db.sales_orders, rid)
        # state: payment transition defined only from UNBILLED
        if order["payment_status"] != "UNBILLED":
            raise errors.invalid_state("invoice is only defined from UNBILLED")
        # priority 8: fulfillment readiness
        if order["fulfillment_status"] != "FULFILLED":
            raise errors.ApiError(errors.ERR_ORDER_NOT_FULFILLED, 409,
                                  "order must be FULFILLED before invoicing")
        # cash sales are never invoiced
        if not _has_account(order):
            raise errors.ApiError(errors.ERR_NOT_NET_TERM_ORDER, 409,
                                  "cash sales are never invoiced")
        account = db.contractor_accounts.get(order["contractor_account_id"])
        due_at = clock.now() + _days(account["net_terms_days"])
        inv = db.new_record({
            "sales_order_id": order["id"],
            "contractor_account_id": order["contractor_account_id"],
            "amount_cents": order["total_cents"],
            "due_at": due_at,
            "status": "ISSUED",
        })
        db.invoices[inv["id"]] = inv
        order["payment_status"] = "INVOICED"
        db.touch(order)
        db.touch(account)  # balance_cents recomputed
        return created(serialize.invoice(inv))


@bp.route("/sales-orders/<rid>/pay", methods=["POST"])
def pay_order(rid):
    caller = authenticate()
    require_roles(caller, {"AccountsManager"})
    with db.lock:
        order = helpers.get_or_404(db.sales_orders, rid)
        if order["payment_status"] != "INVOICED":
            raise errors.invalid_state("pay is only defined from INVOICED")
        inv = _issued_invoice_for(order["id"])
        if inv is None:
            raise errors.ApiError(errors.ERR_INVOICE_NOT_FOUND, 409,
                                  "no ISSUED invoice for this order")
        inv["status"] = "PAID"
        db.touch(inv)
        order["payment_status"] = "PAID"
        db.touch(order)
        account = db.contractor_accounts.get(order["contractor_account_id"])
        if account is not None:
            db.touch(account)  # balance_cents recomputed
        return ok(serialize.sales_order(order))


@bp.route("/sales-orders/<rid>/void-invoice", methods=["POST"])
def void_invoice(rid):
    caller = authenticate()
    require_roles(caller, {"AccountsManager"})
    with db.lock:
        order = helpers.get_or_404(db.sales_orders, rid)
        if order["payment_status"] != "INVOICED":
            raise errors.invalid_state("void-invoice is only defined from INVOICED")
        inv = _issued_invoice_for(order["id"])
        if inv is None:
            raise errors.ApiError(errors.ERR_INVOICE_NOT_FOUND, 409,
                                  "no ISSUED invoice for this order")
        inv["status"] = "VOID"
        db.touch(inv)
        order["payment_status"] = "VOIDED"
        db.touch(order)
        account = db.contractor_accounts.get(order["contractor_account_id"])
        if account is not None:
            db.touch(account)  # balance_cents recomputed back to pre-invoice
        return ok(serialize.sales_order(order))


def _issued_invoice_for(order_id):
    for inv in db.invoices.values():
        if inv["sales_order_id"] == order_id and inv["status"] == "ISSUED":
            return inv
    return None


def _days(n):
    from datetime import timedelta
    return timedelta(days=n)
