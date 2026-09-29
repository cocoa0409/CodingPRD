"""Product orders: per-line tax, shipping, the seventy percent rule, payment."""

from flask import Blueprint, g

from common import (
    apply_bp,
    bad,
    clock_dt,
    clock_str,
    is_int,
    new_row,
    pagination,
    paginate,
    q_enum,
    q_str,
    raw_body,
    req_enum,
    req_int,
    req_list,
    req_str,
    touch,
)
from db import db
from errors import ApiError
from middleware import auth, own_consultant
from response import created, ok, ok_list
from services.genealogy import by_created
from services.lookup import fetch, jurisdiction_by_state, peek, period_by_code
from services.qual import (
    ensure_row,
    latest_closed_row,
    recompute_group_fields_for_period,
    refresh_period_totals,
)

bp = Blueprint("orders", __name__)

ORDER_TYPES = ("PERSONAL_INVENTORY", "RETAIL_CUSTOMER", "BUSINESS_SUPPLY")
PAYMENT_STATUSES = ("PENDING", "PAID", "REFUNDED_PARTIAL", "REFUNDED_FULL")
FULFILLMENT_STATUSES = ("NEW", "SHIPPED", "DELIVERED", "RETURNED_PARTIAL", "RETURNED_FULL")

READ_ROLES = [
    "Consultant",
    "ComplianceOfficer",
    "CommissionAnalyst",
    "FinanceController",
    "PlatformAdmin",
]


def order_sort_key(order):
    return (order["created_at"], order["merchandise_subtotal_cents"], order["_seq"])


@bp.post("/product-orders")
def create_order():
    auth(["Consultant", "PlatformAdmin"])
    body = raw_body()

    # Row ownership runs before body validation.
    if g.get("role") == "Consultant" and isinstance(body.get("consultant_id"), str):
        own_consultant(body["consultant_id"])

    consultant_id = req_str(body, "consultant_id", min_len=1)
    order_type = req_enum(body, "order_type", ORDER_TYPES)
    posted_period_code = req_str(body, "posted_period_code", min_len=1)
    ship_to_state_code = req_str(body, "ship_to_state_code", min_len=1)
    lines = req_list(body, "lines", min_len=1, max_len=20)
    for line in lines:
        if not isinstance(line.get("product_id"), str) or not line["product_id"]:
            bad()
        if not is_int(line.get("quantity")) or line["quantity"] < 1:
            bad()

    consultant = fetch("consultant", consultant_id)
    period = period_by_code(consultant["compensation_plan_id"], posted_period_code)
    jurisdiction = jurisdiction_by_state(ship_to_state_code)

    products = []
    for line in lines:
        products.append(fetch("product", line["product_id"]))

    plan = db.plans.get(consultant["compensation_plan_id"])

    # Domain rules, in PRD order.
    for product in products:
        if product["is_starter_kit"]:
            raise ApiError("ERR_PRODUCT_NOT_ORDERABLE")
    if consultant["status"] not in ("ACTIVE", "PROBATION"):
        raise ApiError("ERR_CONSULTANT_NOT_ORDER_ELIGIBLE")
    if period["status"] not in ("OPEN", "REOPENED"):
        raise ApiError("ERR_PERIOD_NOT_ACCEPTING_VOLUME")
    now = clock_dt()
    if not (period["_period_start_dt"] <= now < period["_period_end_dt"]):
        raise ApiError("ERR_PERIOD_CODE_MISMATCH")
    if order_type == "PERSONAL_INVENTORY":
        reference = latest_closed_row(consultant["compensation_plan_id"], consultant["id"])
        if reference is not None and int(reference["sell_through_bp"]) < int(plan["seventy_rule_bp"]):
            raise ApiError("ERR_INVENTORY_LOADING_VIOLATION")

    tax_basis_mode = jurisdiction["tax_basis_mode"]
    tax_rate_bp = int(jurisdiction["tax_rate_bp"])

    priced_lines = []
    for line, product in zip(lines, products):
        quantity = int(line["quantity"])
        wholesale_subtotal = int(product["wholesale_price_cents"]) * quantity
        srp_subtotal = int(product["srp_cents"]) * quantity
        basis = srp_subtotal if tax_basis_mode == "SRP" else wholesale_subtotal
        priced_lines.append(
            {
                "product_id": product["id"],
                "quantity": quantity,
                "unit_wholesale_price_cents": int(product["wholesale_price_cents"]),
                "unit_srp_cents": int(product["srp_cents"]),
                "volume_points_per_unit": int(product["volume_points_per_unit"]),
                "commissionable": bool(product["commissionable"]),
                "line_wholesale_subtotal_cents": wholesale_subtotal,
                "line_srp_subtotal_cents": srp_subtotal,
                "line_tax_cents": apply_bp(basis, tax_rate_bp),
                "line_volume_points": int(product["volume_points_per_unit"]) * quantity,
                "returned_quantity": 0,
            }
        )

    merchandise_subtotal = sum(l["line_wholesale_subtotal_cents"] for l in priced_lines)
    srp_basis = sum(l["line_srp_subtotal_cents"] for l in priced_lines)
    tax_total = sum(l["line_tax_cents"] for l in priced_lines)
    shipping = (
        int(plan["flat_shipping_cents"])
        if merchandise_subtotal < int(plan["free_shipping_threshold_cents"])
        else 0
    )

    row = new_row()
    row.update(
        {
            "consultant_id": consultant["id"],
            "order_type": order_type,
            "posted_period_code": posted_period_code,
            "ship_to_state_code": ship_to_state_code,
            "lines": priced_lines,
            "placed_at": clock_str(),
            "payment_status": "PENDING",
            "fulfillment_status": "NEW",
            "merchandise_subtotal_cents": merchandise_subtotal,
            "srp_basis_cents": srp_basis,
            "tax_basis_mode": tax_basis_mode,
            "tax_remitter": jurisdiction["remitter"],
            "tax_rate_bp": tax_rate_bp,
            "tax_total_cents": tax_total,
            "shipping_cents": shipping,
            "total_due_cents": merchandise_subtotal + tax_total + shipping,
            "total_volume_points": sum(l["line_volume_points"] for l in priced_lines),
            "commissionable_volume_points": sum(
                l["line_volume_points"] for l in priced_lines if l["commissionable"]
            ),
            "returned_volume_points": 0,
            "payment_reference": None,
            "volume_posted": False,
            "refunded_cents": 0,
        }
    )
    db.orders[row["id"]] = row
    return created(row)


@bp.get("/product-orders")
def list_orders():
    auth(READ_ROLES)
    limit, offset = pagination()
    filters = {
        "consultant_id": q_str("consultant_id"),
        "order_type": q_enum("order_type", ORDER_TYPES),
        "posted_period_code": q_str("posted_period_code"),
        "payment_status": q_enum("payment_status", PAYMENT_STATUSES),
        "fulfillment_status": q_enum("fulfillment_status", FULFILLMENT_STATUSES),
    }
    rows = sorted(db.orders.values(), key=order_sort_key)
    for field, value in filters.items():
        if value is not None:
            rows = [r for r in rows if r.get(field) == value]
    page, total = paginate(rows, limit, offset)
    return ok_list(page, total, limit, offset)


@bp.get("/product-orders/<order_id>")
def read_order(order_id):
    auth(READ_ROLES)
    existing = peek("order", order_id)
    if existing is not None:
        own_consultant(existing["consultant_id"])
    return ok(fetch("order", order_id))


@bp.post("/product-orders/<order_id>/pay")
def pay_order(order_id):
    auth(["Consultant", "PlatformAdmin"])
    existing = peek("order", order_id)
    if existing is not None:
        own_consultant(existing["consultant_id"])

    body = raw_body()
    amount_cents = req_int(body, "amount_cents", minimum=0)
    payment_reference = req_str(body, "payment_reference", min_len=1)

    order = fetch("order", order_id)
    consultant = db.consultants.get(order["consultant_id"])
    period = period_by_code(consultant["compensation_plan_id"], order["posted_period_code"])

    if consultant["status"] not in ("ACTIVE", "PROBATION"):
        raise ApiError("ERR_CONSULTANT_NOT_ORDER_ELIGIBLE")
    if period["status"] not in ("OPEN", "REOPENED"):
        raise ApiError("ERR_PERIOD_NOT_ACCEPTING_VOLUME")
    if amount_cents != int(order["total_due_cents"]):
        raise ApiError("ERR_ORDER_AMOUNT_MISMATCH")
    if order["payment_status"] != "PENDING":
        raise ApiError("ERR_ORDER_ALREADY_PAID")

    order["payment_status"] = "PAID"
    order["payment_reference"] = payment_reference
    order["volume_posted"] = True
    touch(order)

    contribution = int(order["total_volume_points"])
    row = ensure_row(period, consultant["id"])
    row["personal_volume_points"] = int(row["personal_volume_points"]) + contribution
    if order["order_type"] == "RETAIL_CUSTOMER":
        row["retail_volume_points"] = int(row["retail_volume_points"]) + contribution
    elif order["order_type"] == "PERSONAL_INVENTORY":
        row["inventory_volume_points"] = int(row["inventory_volume_points"]) + contribution
    row["net_personal_volume_points"] = int(row["personal_volume_points"]) - int(
        row["returned_volume_points"]
    )
    touch(row)

    recompute_group_fields_for_period(period)
    refresh_period_totals(period)

    return ok(order)


@bp.post("/product-orders/<order_id>/fulfillment")
def fulfillment(order_id):
    auth(["PlatformAdmin"])
    body = raw_body()
    event = req_enum(body, "event", ("SHIP", "DELIVER"))

    order = fetch("order", order_id)
    if event == "SHIP":
        if order["fulfillment_status"] != "NEW" or order["payment_status"] != "PAID":
            raise ApiError("ERR_FULFILLMENT_SEQUENCE_INVALID")
        order["fulfillment_status"] = "SHIPPED"
    else:
        if order["fulfillment_status"] != "SHIPPED":
            raise ApiError("ERR_FULFILLMENT_SEQUENCE_INVALID")
        order["fulfillment_status"] = "DELIVERED"
    touch(order)
    return ok(order)
