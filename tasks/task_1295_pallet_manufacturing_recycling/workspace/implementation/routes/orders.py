"""SalesOrder and OrderLine endpoints: create, lines, confirm, allocate,
cancel, record-payment. Confirm/allocate are OCC-guarded via
expected_order_version (checked BEFORE state preconditions)."""

from flask import Blueprint, request

from db import db, now
from errors import raise_err
from middleware import (
    require_roles, get_json_body, parse_pagination, paginate,
    req_field, opt_field, as_str, as_int, as_bool, as_enum, as_datetime,
)
from response import success
from services.calc import (
    PRICE_BOOK_CENTS, compute_order_pricing, select_lot_for_line,
)
from services.helpers import (
    init_common, touch, serialize, serialize_list, sorted_by_creation,
    get_or_404, ref_or_404,
)

bp = Blueprint("orders", __name__)

QUALITY_GRADES = ("NEW", "A", "B")


def _check_expected_version(body, order):
    """OCC gate: expected_order_version is required and must match the order's
    current version. Pinned before state checks per validation priority 6."""
    expected = req_field(body, "expected_order_version")
    expected = as_int(expected, "expected_order_version")
    if expected != order["version"]:
        raise_err(
            "ERR_STALE_VERSION",
            "expected_order_version does not match the order's current version",
        )


def _make_line(order_id, spec, quantity, grade_requested, ht_required):
    line = {
        "order_id": order_id,
        "spec_id": spec["id"],
        "quantity": quantity,
        "quality_grade_requested": grade_requested,
        "heat_treatment_required": ht_required,
        "unit_price_cents": PRICE_BOOK_CENTS[grade_requested],
        "extended_price_cents": None,
        "allocated_lot_id": None,
        "status": "OPEN",
    }
    init_common(line)
    db.order_lines[line["id"]] = line
    return line


def _parse_line_fields(body):
    spec_id = as_str(req_field(body, "spec_id"), "spec_id")
    spec = ref_or_404(db.specs, spec_id, "spec_id")
    quantity = as_int(req_field(body, "quantity"), "quantity", minimum=1)
    grade = as_enum(req_field(body, "quality_grade_requested"), "quality_grade_requested", QUALITY_GRADES)
    ht = body.get("heat_treatment_required")
    if ht is None:
        ht = spec["requires_heat_treatment_default"]
    else:
        ht = as_bool(ht, "heat_treatment_required")
    return spec, quantity, grade, ht


@bp.post("/pallet-ops/orders")
def create_order():
    require_roles("SalesRep")
    body = get_json_body()
    customer_id = as_str(req_field(body, "customer_id"), "customer_id")
    customer = ref_or_404(db.customers, customer_id, "customer_id")
    requested_delivery_date = as_datetime(
        req_field(body, "requested_delivery_date"), "requested_delivery_date"
    )
    spec, quantity, grade, ht = _parse_line_fields(body)

    # Credit standing checked at the door.
    if customer["status"] != "ACTIVE" or customer["credit_hold"]:
        raise_err(
            "ERR_CUSTOMER_CREDIT_HOLD",
            "Customer on credit hold or not ACTIVE for order create",
        )

    order = {
        "customer_id": customer_id,
        "order_date": None,  # stamped below from the logical clock
        "requested_delivery_date": body["requested_delivery_date"],
        "subtotal_cents": None,
        "seasonal_adjustment_cents": None,
        "pool_credit_applied_cents": 0,
        "total_cents": None,
        "payment_status": "UNPAID",
        "fulfillment_status": "DRAFT",
        "_order_date": now(),
    }
    init_common(order)
    from db import iso as _iso
    order["order_date"] = _iso(order["_order_date"])
    db.orders[order["id"]] = order
    _make_line(order["id"], spec, quantity, grade, ht)
    return success(serialize(order), status=201)


@bp.get("/pallet-ops/orders")
def list_orders():
    require_roles()
    limit, offset = parse_pagination()
    items = list(db.orders.values())
    customer_id = request.args.get("customer_id")
    if customer_id is not None:
        items = [o for o in items if o["customer_id"] == customer_id]
    fstat = request.args.get("fulfillment_status")
    if fstat is not None:
        items = [o for o in items if o["fulfillment_status"] == fstat]
    pstat = request.args.get("payment_status")
    if pstat is not None:
        items = [o for o in items if o["payment_status"] == pstat]
    items = sorted_by_creation(items)
    page, pagination = paginate(items, limit, offset)
    return success(serialize_list(page), pagination=pagination, is_list=True)


@bp.get("/pallet-ops/orders/<oid>")
def get_order(oid):
    require_roles()
    order = get_or_404(db.orders, oid, "SalesOrder")
    return success(serialize(order))


@bp.post("/pallet-ops/orders/<oid>/lines")
def add_order_line(oid):
    require_roles("SalesRep")
    order = get_or_404(db.orders, oid, "SalesOrder")
    body = get_json_body()
    spec, quantity, grade, ht = _parse_line_fields(body)
    if order["fulfillment_status"] != "DRAFT":
        raise_err("ERR_INVALID_STATE", "add-line requires order DRAFT")
    line = _make_line(oid, spec, quantity, grade, ht)
    return success(serialize(line), status=201)


@bp.get("/pallet-ops/order-lines")
def list_order_lines():
    require_roles()
    limit, offset = parse_pagination()
    items = list(db.order_lines.values())
    order_id = request.args.get("order_id")
    if order_id is not None:
        items = [l for l in items if l["order_id"] == order_id]
    spec_id = request.args.get("spec_id")
    if spec_id is not None:
        items = [l for l in items if l["spec_id"] == spec_id]
    status = request.args.get("status")
    if status is not None:
        items = [l for l in items if l["status"] == status]
    lot_id = request.args.get("allocated_lot_id")
    if lot_id is not None:
        items = [l for l in items if l.get("allocated_lot_id") == lot_id]
    items = sorted_by_creation(items)
    page, pagination = paginate(items, limit, offset)
    return success(serialize_list(page), pagination=pagination, is_list=True)


@bp.get("/pallet-ops/order-lines/<lid>")
def get_order_line(lid):
    require_roles()
    line = get_or_404(db.order_lines, lid, "OrderLine")
    return success(serialize(line))


@bp.post("/pallet-ops/orders/<oid>/confirm")
def confirm_order(oid):
    require_roles("SalesRep")
    order = get_or_404(db.orders, oid, "SalesOrder")
    body = get_json_body()
    # OCC check pinned before state preconditions.
    _check_expected_version(body, order)

    if order["fulfillment_status"] != "DRAFT":
        raise_err("ERR_ORDER_NOT_DRAFT", "confirm requires order DRAFT")
    open_lines = [
        l for l in db.order_lines.values()
        if l["order_id"] == oid and l["status"] == "OPEN"
    ]
    if not open_lines:
        raise_err("ERR_ORDER_EMPTY", "confirm requires at least one OPEN line")
    customer = db.customers.get(order["customer_id"])
    if customer is None or customer["status"] != "ACTIVE" or customer["credit_hold"]:
        raise_err(
            "ERR_CUSTOMER_CREDIT_HOLD",
            "Customer on credit hold or not ACTIVE for order confirm",
        )

    open_lines.sort(key=lambda l: l["_created_sort"])
    subtotal, seasonal, credit_applied, total = compute_order_pricing(order, open_lines, customer)

    # Ledger sync: debit the customer's pool credit balance.
    customer["pool_credit_balance_cents"] -= credit_applied
    touch(customer)
    for line in open_lines:
        touch(line)

    order["subtotal_cents"] = subtotal
    order["seasonal_adjustment_cents"] = seasonal
    order["pool_credit_applied_cents"] = credit_applied
    order["total_cents"] = total
    order["payment_status"] = "CREDIT_SETTLED" if total == 0 else "UNPAID"
    order["fulfillment_status"] = "CONFIRMED"
    touch(order)
    return success(serialize(order))


@bp.post("/pallet-ops/orders/<oid>/allocate")
def allocate_order(oid):
    require_roles("SalesRep")
    order = get_or_404(db.orders, oid, "SalesOrder")
    body = get_json_body()
    # OCC check pinned before state preconditions.
    _check_expected_version(body, order)

    if order["fulfillment_status"] != "CONFIRMED":
        raise_err("ERR_ORDER_NOT_CONFIRMED", "allocate requires order CONFIRMED")

    open_lines = [
        l for l in db.order_lines.values()
        if l["order_id"] == oid and l["status"] == "OPEN"
    ]
    open_lines.sort(key=lambda l: l["_created_sort"])

    # Atomicity: resolve the selector for every line BEFORE committing any
    # reservation. Since candidate lots are only debited after full resolution,
    # track projected debits so two lines against the same lot see the
    # remaining availability.
    planned = []  # (line, lot)
    projected_debits = {}
    first_error = None
    for line in open_lines:
        lot, err = select_lot_for_line(line)
        if lot is not None:
            remaining = lot["quantity_available"] - projected_debits.get(lot["id"], 0)
            if remaining < line["quantity"]:
                lot, err = None, "ERR_INSUFFICIENT_STOCK"
        if lot is None:
            first_error = err
            break
        planned.append((line, lot))
        projected_debits[lot["id"]] = projected_debits.get(lot["id"], 0) + line["quantity"]

    if first_error is not None:
        raise_err(
            first_error,
            "Allocation failed: %s" % (
                "no lot satisfying spec/grade/quantity filters"
                if first_error == "ERR_INSUFFICIENT_STOCK"
                else "line requires heat treatment but only non-HT-certified lots are candidates"
            ),
        )

    # Commit reservations.
    for line, lot in planned:
        line["allocated_lot_id"] = lot["id"]
        line["status"] = "ALLOCATED"
        touch(line)
        lot["quantity_available"] -= line["quantity"]
        if lot["quantity_available"] == 0:
            lot["status"] = "DEPLETED"
        touch(lot)

    order["fulfillment_status"] = "ALLOCATED"
    touch(order)
    return success(serialize(order))


@bp.post("/pallet-ops/orders/<oid>/cancel")
def cancel_order(oid):
    require_roles("SalesRep")
    order = get_or_404(db.orders, oid, "SalesOrder")
    if order["fulfillment_status"] not in ("DRAFT", "CONFIRMED"):
        raise_err("ERR_ORDER_NOT_CANCELLABLE", "cancel requires DRAFT or CONFIRMED")

    # Compensation: re-credit applied pool credit.
    if order["pool_credit_applied_cents"] > 0:
        customer = db.customers.get(order["customer_id"])
        if customer is not None:
            customer["pool_credit_balance_cents"] += order["pool_credit_applied_cents"]
            touch(customer)

    for line in db.order_lines.values():
        if line["order_id"] == oid and line["status"] == "OPEN":
            line["status"] = "CANCELLED"
            touch(line)

    order["fulfillment_status"] = "CANCELLED"
    touch(order)
    return success(serialize(order))


@bp.post("/pallet-ops/orders/<oid>/record-payment")
def record_payment(oid):
    require_roles("SalesRep")
    order = get_or_404(db.orders, oid, "SalesOrder")
    body = get_json_body()
    amount = req_field(body, "amount_cents")
    amount = as_int(amount, "amount_cents", minimum=0)

    if order["payment_status"] != "UNPAID":
        raise_err("ERR_ORDER_ALREADY_SETTLED", "record-payment requires payment_status == UNPAID")
    if order["fulfillment_status"] in ("DRAFT", "CANCELLED"):
        raise_err("ERR_INVALID_STATE", "payment only against priced orders")
    if amount != order["total_cents"]:
        raise_err(
            "ERR_PAYMENT_AMOUNT_MISMATCH",
            "record-payment amount_cents must equal order total_cents exactly",
        )
    order["payment_status"] = "PAID"
    touch(order)
    return success(serialize(order))
