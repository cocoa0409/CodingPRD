"""OrderLine endpoints (PRD §3.2)."""
from flask import Blueprint

import db
import helpers
import response
from errors import err
from middleware import get_auth, require_role
from services import calculations as calc
from services import domain, serializers

bp = Blueprint("order_lines", __name__)


def _compute_line_figures(line, product):
    unit_price = calc.line_unit_config_price(product, line["fabric_code"], line["size_code"])
    line["unit_config_price_cents"] = unit_price
    line["line_total_cents"] = unit_price * line["quantity"]
    line["addon_fee_cents"] = calc.line_addon_fee(
        line["add_assembly"], line["add_haul_away"], line["quantity"])


@bp.post("/order-lines")
def create_order_line():
    _, role = get_auth()
    require_role(role, {"SalesAssociate", "StoreManager"})
    body = helpers.get_body()

    # Existence (priority 4): validate body FKs left-to-right (order then product).
    order_id = helpers.require_str(body, "order_id")
    product_id = helpers.require_str(body, "product_id")
    order = helpers.fetch(db.orders, order_id)
    product = helpers.fetch(db.products, product_id)

    # Shape (priority 5).
    fabric_code = helpers.require_str(body, "fabric_code")
    size_code = helpers.require_str(body, "size_code")
    quantity = helpers.optional_int(body, "quantity", default=1, minimum=1)
    add_assembly = helpers.optional_bool(body, "add_assembly", default=False)
    add_haul_away = helpers.optional_bool(body, "add_haul_away", default=False)

    # Configuration (priority 6): fabric/size must be offered by the product.
    fabric_codes = {f["code"] for f in product["available_fabrics"]}
    size_codes = {s["code"] for s in product["available_sizes"]}
    if fabric_code not in fabric_codes or size_code not in size_codes:
        raise err("ERR_INVALID_CONFIGURATION",
                  "fabric_code or size_code not offered by the product.")

    # State (priority 8): lines may only be added while order is DRAFT.
    if order["fulfillment_status"] != "DRAFT":
        raise err("ERR_ORDER_NOT_DRAFT", "Order is not in DRAFT.")

    line = {
        "order_id": order_id,
        "product_id": product_id,
        "fabric_code": fabric_code,
        "size_code": size_code,
        "quantity": quantity,
        "add_assembly": add_assembly,
        "add_haul_away": add_haul_away,
        "status": "ACTIVE",
    }
    _compute_line_figures(line, product)
    helpers.stamp_create(line)
    db.order_lines[line["id"]] = line

    # Recompute order totals as a side effect (this is a mutation of the order).
    domain.recompute_order_totals(order)
    helpers.touch(order)

    return response.object_response(serializers.order_line(line), status=201)


@bp.get("/order-lines/<lid>")
def get_order_line(lid):
    user_id, role = get_auth()
    require_role(role, {"SalesAssociate", "StoreManager", "Customer"})
    line = helpers.fetch(db.order_lines, lid)
    if role == "Customer":
        order = db.orders.get(line["order_id"])
        if order is None or user_id != order["customer_id"]:
            raise err("ERR_FORBIDDEN_NOT_OWNER", "Not the owning customer.")
    return response.object_response(serializers.order_line(line))


@bp.delete("/order-lines/<lid>")
def delete_order_line(lid):
    _, role = get_auth()
    require_role(role, {"SalesAssociate", "StoreManager"})
    line = helpers.fetch(db.order_lines, lid)
    order = db.orders.get(line["order_id"])

    if order is None or order["fulfillment_status"] != "DRAFT":
        raise err("ERR_ORDER_NOT_DRAFT", "Order is not in DRAFT.")

    line["status"] = "CANCELLED"
    helpers.touch(line)

    domain.recompute_order_totals(order)
    helpers.touch(order)

    return response.object_response(serializers.order_line(line))


@bp.get("/order-lines/<lid>/protection-plans")
def list_line_protection_plans(lid):
    user_id, role = get_auth()
    require_role(role, {"SalesAssociate", "StoreManager", "Customer"})
    line = helpers.fetch(db.order_lines, lid)
    if role == "Customer":
        order = db.orders.get(line["order_id"])
        if order is None or user_id != order["customer_id"]:
            raise err("ERR_FORBIDDEN_NOT_OWNER", "Not the owning customer.")
    limit, offset = helpers.get_pagination()
    rows = [p for p in db.protection_plans.values() if p["order_line_id"] == lid]
    page, total = helpers.paginate(rows, limit, offset)
    return response.array_response(
        [serializers.protection_plan(p) for p in page], limit, offset, total)


@bp.get("/order-lines/<lid>/return-requests")
def list_line_return_requests(lid):
    user_id, role = get_auth()
    require_role(role, {"Customer", "SalesAssociate", "StoreManager"})
    line = helpers.fetch(db.order_lines, lid)
    if role == "Customer":
        order = db.orders.get(line["order_id"])
        if order is None or user_id != order["customer_id"]:
            raise err("ERR_FORBIDDEN_NOT_OWNER", "Not the owning customer.")
    limit, offset = helpers.get_pagination()
    rows = [r for r in db.return_requests.values() if r["order_line_id"] == lid]
    page, total = helpers.paginate(rows, limit, offset)
    return response.array_response(
        [serializers.return_request(r) for r in page], limit, offset, total)
