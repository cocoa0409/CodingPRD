"""Tool orders: pricing, routing, confirmation and fulfilment (PRD 3.8)."""

from flask import Blueprint

import calculations as calc
import db
import validation as v
from errors import ApiError
from middleware import authenticate
from response import array_response, object_response
from routes import common as c
from services import derive, serialize

bp = Blueprint("orders", __name__)

RAISERS = ["Customer", "ApplicationEngineer"]
CONFIRMERS = ["ApplicationEngineer", "ProductionPlanner"]
SHIPPERS = ["ProductionPlanner"]
CANCELLERS = ["Customer", "ApplicationEngineer", "ProductionPlanner"]
READ_ROLES = ["Customer", "ApplicationEngineer", "ProductionPlanner", "QualityApprover"]

SUBMITTED_LOAD_STATES = ("SUBMITTED", "ENGINEERING_REVIEW", "CONFIRMED", "ON_HOLD")


def _scope(role, user_id, customer_id):
    if role == "Customer" and customer_id != user_id:
        raise ApiError(
            "ERR_CUSTOMER_SCOPE_VIOLATION",
            "A Customer caller may act only on its own orders.",
        )


def _orderable(product):
    """Priority 17."""
    if product["release_status"] in ("RESTRICTED", "WITHDRAWN") or (
        product["supply_status"] == "UNAVAILABLE"
    ):
        raise ApiError(
            "ERR_PRODUCT_NOT_ORDERABLE",
            "The product is not orderable (release_status=%s, supply_status=%s)."
            % (product["release_status"], product["supply_status"]),
        )


def _account_orderable(customer):
    """Priority 42."""
    if customer["account_status"] == "CREDIT_HOLD":
        raise ApiError("ERR_CUSTOMER_CREDIT_HOLD", "The customer account is on credit hold.")
    if customer["account_status"] == "CLOSED":
        raise ApiError("ERR_CUSTOMER_CLOSED", "The customer account is closed.")


@bp.route("/tooling/tool-orders", methods=["POST"])
def create():
    user_id, role = authenticate(RAISERS)
    payload = v.body(
        required=(
            "customer_id",
            "product_id",
            "order_code",
            "quantity",
            "expected_product_version",
        ),
        optional=("expedite_requested",),
    )
    customer_id = v.as_id(payload, "customer_id")
    product_id = v.as_id(payload, "product_id")
    order_code = v.as_string(payload, "order_code")
    quantity = v.as_int(payload, "quantity", minimum=1)
    expedite = v.as_bool(payload, "expedite_requested", default=False)
    expected_version = v.as_int(payload, "expected_product_version", minimum=1)

    customer = derive.must_exist("customers", customer_id)
    product = derive.must_exist("products", product_id)

    _scope(role, user_id, customer["id"])

    if expected_version != product["version"]:
        raise ApiError(
            "ERR_STALE_PRODUCT_VERSION",
            "The product is at version %d, not %d." % (product["version"], expected_version),
        )

    derive.require_unique("orders", "order_code", order_code)

    if product["release_status"] == "WITHDRAWN":
        raise ApiError(
            "ERR_INVALID_PRODUCT_STATE", "A WITHDRAWN product accepts no new orders."
        )
    _orderable(product)

    if quantity < product["min_order_qty"]:
        raise ApiError(
            "ERR_BELOW_MIN_ORDER_QTY",
            "The product's minimum order quantity is %d." % product["min_order_qty"],
        )
    if expedite and not product["expedite_eligible"]:
        raise ApiError(
            "ERR_EXPEDITE_NOT_ELIGIBLE", "The product is not eligible for expediting."
        )

    row = db.new_row(
        {
            "customer_id": customer["id"],
            "product_id": product["id"],
            "order_code": order_code,
            "order_class": product["order_class"],
            "quantity": quantity,
            "expedite_requested": expedite,
            "status": "DRAFT",
            "per_unit_net_cents": None,
            "total_price_cents": None,
            "promised_lead_time_days": None,
            "requires_reconfirmation": False,
            "hold_reason": None,
            "shipped_at": None,
        }
    )
    db.orders[row["id"]] = row
    db.touch(product)
    return object_response(serialize.order(row), 201)


@bp.route("/tooling/tool-orders", methods=["GET"])
def index():
    user_id, role = authenticate(READ_ROLES)
    limit, offset = v.pagination()
    filters = {}
    for key in ("customer_id", "product_id"):
        value = v.query_value(key)
        if value is not None:
            filters[key] = value
    status = v.query_enum("status", c.ORDER_STATUSES)
    if status is not None:
        filters["status"] = status
    if role == "Customer":
        filters["customer_id"] = user_id
    rows = derive.where("orders", **filters)
    return c.list_response("orders", rows, limit, offset)


@bp.route("/tooling/tool-orders/<order_id>", methods=["GET"])
def read(order_id):
    user_id, role = authenticate(READ_ROLES)
    v.pagination()
    order = derive.must_exist("orders", order_id)
    _scope(role, user_id, order["customer_id"])
    return object_response(serialize.order(order))


@bp.route("/tooling/tool-orders/<order_id>/submit", methods=["POST"])
def submit(order_id):
    user_id, role = authenticate(RAISERS)
    v.no_body()
    order = derive.must_exist("orders", order_id)
    _scope(role, user_id, order["customer_id"])

    if order["status"] != "DRAFT":
        raise ApiError(
            "ERR_INVALID_ORDER_STATE",
            "Only a DRAFT order may be submitted (currently %s)." % order["status"],
        )

    product = db.products.get(order["product_id"])
    customer = db.customers.get(order["customer_id"])
    _orderable(product)

    if order["order_class"] == "CATALOG":
        if product["release_status"] != "RELEASED":
            raise ApiError(
                "ERR_PRODUCT_NOT_ORDERABLE",
                "A CATALOG order requires a RELEASED product (currently %s)."
                % product["release_status"],
            )
    else:
        if product["release_status"] not in ("QUALIFICATION", "RELEASED"):
            raise ApiError(
                "ERR_PRODUCT_NOT_ORDERABLE",
                "A SPECIAL order requires a product in QUALIFICATION or RELEASED "
                "(currently %s)." % product["release_status"],
            )

    _account_orderable(customer)

    grade = db.grades.get(product["grade_id"])
    recipe = (
        db.recipes.get(product["coating_recipe_id"])
        if product["coating_recipe_id"]
        else None
    )
    per_unit, total = calc.order_price(
        product["list_price_cents"],
        order["quantity"],
        order["order_class"],
        grade["target_workpiece_group"] if grade else None,
        recipe,
    )
    lead = product["engineering_lead_time_days"]
    if order["order_class"] == "CATALOG":
        order["status"] = "SUBMITTED"
        order["promised_lead_time_days"] = lead
    else:
        order["status"] = "ENGINEERING_REVIEW"
        order["promised_lead_time_days"] = (
            None if lead is None else lead + calc.SPECIAL_REVIEW_DAYS
        )
    order["per_unit_net_cents"] = per_unit
    order["total_price_cents"] = total
    db.touch(order)
    db.touch(product)
    return object_response(serialize.order(order))


@bp.route("/tooling/tool-orders/<order_id>/confirm", methods=["POST"])
def confirm(order_id):
    authenticate(CONFIRMERS)
    v.no_body()
    order = derive.must_exist("orders", order_id)
    if order["status"] not in ("SUBMITTED", "ENGINEERING_REVIEW"):
        raise ApiError(
            "ERR_INVALID_ORDER_STATE",
            "An order is confirmed from SUBMITTED or ENGINEERING_REVIEW (currently %s)."
            % order["status"],
        )

    product = db.products.get(order["product_id"])
    grade, geometry, recipe = derive.product_refs(product)

    if product["release_status"] != "RELEASED":
        raise ApiError(
            "ERR_PRODUCT_NOT_ORDERABLE",
            "Confirmation requires a RELEASED product (currently %s)."
            % product["release_status"],
        )
    if grade is None or grade["status"] != "QUALIFIED":
        raise ApiError("ERR_GRADE_NOT_QUALIFIED", "The product's grade is not QUALIFIED.")
    if geometry is None or geometry["status"] != "RELEASED":
        raise ApiError("ERR_GEOMETRY_NOT_RELEASED", "The product's geometry is not RELEASED.")
    if recipe is not None and not derive.recipe_is_validated(recipe):
        raise ApiError(
            "ERR_COATING_NOT_VALIDATED", "The product's coating recipe is not validated."
        )
    if (
        product["pinned_grade_revision"] != grade["revision"]
        or product["pinned_geometry_revision"] != geometry["revision"]
        or (recipe is not None and product["pinned_coating_revision"] != recipe["revision"])
    ):
        raise ApiError(
            "ERR_PINNED_REVISION_STALE",
            "The product must be repinned before this order can be confirmed.",
        )

    customer = db.customers.get(order["customer_id"])
    if customer is not None:
        _account_orderable(customer)

    order["status"] = "CONFIRMED"
    order["requires_reconfirmation"] = False
    db.touch(order)
    return object_response(serialize.order(order))


@bp.route("/tooling/tool-orders/<order_id>/ship", methods=["POST"])
def ship(order_id):
    authenticate(SHIPPERS)
    v.no_body()
    order = derive.must_exist("orders", order_id)
    if order["status"] != "CONFIRMED" or order["requires_reconfirmation"]:
        raise ApiError(
            "ERR_INVALID_ORDER_STATE",
            "Only a CONFIRMED order that needs no reconfirmation may ship (currently %s)."
            % order["status"],
        )
    product = db.products.get(order["product_id"])
    if product is None or product["supply_status"] not in ("MAKE_TO_ORDER", "STOCKED"):
        raise ApiError(
            "ERR_PRODUCT_NOT_ORDERABLE",
            "Shipping requires a supply_status of MAKE_TO_ORDER or STOCKED.",
        )

    order["status"] = "SHIPPED"
    order["shipped_at"] = db.logical_iso()
    db.touch(order)
    db.touch(product)
    return object_response(serialize.order(order))


@bp.route("/tooling/tool-orders/<order_id>/cancel", methods=["POST"])
def cancel(order_id):
    user_id, role = authenticate(CANCELLERS)
    payload = v.body(required=("cancel_reason",))
    v.as_string(payload, "cancel_reason")

    order = derive.must_exist("orders", order_id)
    _scope(role, user_id, order["customer_id"])

    if order["status"] not in ("DRAFT",) + SUBMITTED_LOAD_STATES:
        raise ApiError(
            "ERR_INVALID_ORDER_STATE",
            "An order in %s cannot be cancelled." % order["status"],
        )

    counted = order["status"] in SUBMITTED_LOAD_STATES
    order["status"] = "CANCELLED"
    db.touch(order)
    if counted:
        product = db.products.get(order["product_id"])
        if product is not None:
            db.touch(product)
    return object_response(serialize.order(order))
