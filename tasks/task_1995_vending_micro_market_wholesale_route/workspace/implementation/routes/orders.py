"""ReplenishmentOrder endpoints (scaffold §1.5; lifecycle per PRD §3.5-§3.6)."""
from flask import Blueprint, request
import db
from middleware import get_auth, require_role, require_operator_ownership
from response import success_object, success_list, parse_pagination
from util import get_json_body, req_string, req_array, stamp_new, touch, positive_int_value
from errors import (
    ApiError, ERR_LOCATION_NOT_FOUND, ERR_ORDER_NOT_FOUND, ERR_PRODUCT_NOT_FOUND,
    ERR_TELEMETRY_EVENT_NOT_FOUND, ERR_INVALID_REQUEST, ERR_INVALID_QUANTITY,
    ERR_ORDER_NOT_DRAFT, ERR_ORDER_NOT_SUBMITTED, ERR_ORDER_NOT_CONFIRMED,
    ERR_ORDER_NOT_OPEN_FOR_SETTLEMENT, ERR_INVALID_STATE_TRANSITION,
    ERR_OPERATOR_NOT_ACTIVE, ERR_NO_ACTIVE_PLANOGRAM,
    ERR_DELIVERY_DATE_NOT_FUTURE, ERR_DELIVERY_DAY_NOT_SERVED, ERR_EMPTY_ORDER,
    ERR_PRODUCT_DISCONTINUED, ERR_PRODUCT_NOT_ELIGIBLE_FOR_LOCATION_TYPE,
    ERR_PRODUCT_NOT_ON_PLANOGRAM, ERR_MIN_ORDER_NOT_MET,
    ERR_ROUTE_CAPACITY_EXCEEDED, ERR_INSUFFICIENT_CREDIT_BALANCE,
    ERR_EMPTY_SUGGESTION, ERR_STALE_VERSION, ERR_TELEMETRY_EVENT_LOCATION_MISMATCH,
)
from services import pricing
import clock

bp = Blueprint("orders", __name__)

TENDERS = {"CASH", "CASHLESS"}


def view(o):
    return {k: v for k, v in o.items()}


def _get_order(orderId):
    o = db.orders.get(orderId)
    if o is None:
        raise ApiError(ERR_ORDER_NOT_FOUND, 404, "ReplenishmentOrder id does not exist")
    return o


def _validate_lines_shape(lines):
    """Tier 2 shape: rows are objects; product_id string; quantity_cases int > 0."""
    for row in lines:
        if not isinstance(row, dict):
            raise ApiError(ERR_INVALID_REQUEST, 400, "lines rows must be objects")
        pid = row.get("product_id")
        if not isinstance(pid, str) or not pid:
            raise ApiError(ERR_INVALID_REQUEST, 400, "lines[].product_id required")
        qty = row.get("quantity_cases")
        if isinstance(qty, bool) or not isinstance(qty, int):
            raise ApiError(ERR_INVALID_QUANTITY, 400, "quantity_cases must be a positive integer")
        if qty <= 0:
            raise ApiError(ERR_INVALID_QUANTITY, 400, "quantity_cases must be greater than zero")


def _validate_date_field(body, name):
    raw = req_string(body, name)
    try:
        clock.parse_date(raw)
    except ValueError:
        raise ApiError(ERR_INVALID_REQUEST, 400, f"{name} must be YYYY-MM-DD")
    return raw


@bp.post("/wholesale/orders")
def create_order():
    user_id, role = get_auth()
    body = get_json_body()
    require_role(role, ["OperatorManager"])
    location_id = req_string(body, "location_id")
    requested_delivery_date = _validate_date_field(body, "requested_delivery_date")
    lines = req_array(body, "lines")
    _validate_lines_shape(lines)
    # Creation is deliberately lenient (PRD §3.5): existence checks only.
    location = db.locations.get(location_id)
    if location is None:
        raise ApiError(ERR_LOCATION_NOT_FOUND, 404, "Location id does not exist")
    require_operator_ownership(role, user_id, location["operator_id"])
    for row in lines:
        if row["product_id"] not in db.products:
            raise ApiError(ERR_PRODUCT_NOT_FOUND, 404, "Product id does not exist")
    clean_lines = [{"product_id": r["product_id"], "quantity_cases": r["quantity_cases"]} for r in lines]
    order = stamp_new({
        "operator_id": location["operator_id"],
        "location_id": location_id,
        "route_id": location["route_id"],
        "source": "MANUAL",
        "requested_delivery_date": requested_delivery_date,
        "lines": clean_lines,
        "total_cases": sum(r["quantity_cases"] for r in clean_lines),
        "order_total_cents": 0,
        "promo_discount_cents": 0,
        "provisional_margin_per_vend_cents": None,
        "realized_margin_per_vend_cents": None,
        "cashless_fee_cents": None,
        "amount_due_cents": 0,
        "credit_applied_cents": 0,
        "settled_tender": None,
        "settlement_telemetry_event_id": None,
        "fulfillment_status": "DRAFT",
        "settlement_status": "UNINVOICED",
    })
    db.orders[order["id"]] = order
    return success_object(view(order), 201)


@bp.post("/wholesale/orders/generate-from-telemetry")
def generate_from_telemetry():
    user_id, role = get_auth()
    body = get_json_body()
    require_role(role, ["OperatorManager"])
    location_id = req_string(body, "location_id")
    requested_delivery_date = _validate_date_field(body, "requested_delivery_date")
    location = db.locations.get(location_id)
    if location is None:
        raise ApiError(ERR_LOCATION_NOT_FOUND, 404, "Location id does not exist")
    require_operator_ownership(role, user_id, location["operator_id"])
    # Related-entity gate (tier 8): location must have an ACTIVE planogram.
    planogram = pricing.active_planogram_for_location(location_id)
    if planogram is None:
        raise ApiError(ERR_NO_ACTIVE_PLANOGRAM, 409, "Location has no ACTIVE planogram")
    _, lines = pricing.suggested_lines(location)
    if not lines:
        raise ApiError(ERR_EMPTY_SUGGESTION, 422, "generate-from-telemetry produced zero suggested lines")
    order = stamp_new({
        "operator_id": location["operator_id"],
        "location_id": location_id,
        "route_id": location["route_id"],
        "source": "TELEMETRY_SUGGESTED",
        "requested_delivery_date": requested_delivery_date,
        "lines": lines,
        "total_cases": sum(r["quantity_cases"] for r in lines),
        "order_total_cents": 0,
        "promo_discount_cents": 0,
        "provisional_margin_per_vend_cents": None,
        "realized_margin_per_vend_cents": None,
        "cashless_fee_cents": None,
        "amount_due_cents": 0,
        "credit_applied_cents": 0,
        "settled_tender": None,
        "settlement_telemetry_event_id": None,
        "fulfillment_status": "DRAFT",
        "settlement_status": "UNINVOICED",
    })
    db.orders[order["id"]] = order
    return success_object(view(order), 201)


@bp.get("/wholesale/orders")
def list_orders():
    get_auth()
    limit, offset = parse_pagination(request.args)
    op_f = request.args.get("operator_id")
    loc_f = request.args.get("location_id")
    route_f = request.args.get("route_id")
    ff_f = request.args.get("fulfillment_status")
    ste_f = request.args.get("settlement_telemetry_event_id")
    items = list(db.orders.values())
    if op_f is not None:
        items = [o for o in items if o["operator_id"] == op_f]
    if loc_f is not None:
        items = [o for o in items if o["location_id"] == loc_f]
    if route_f is not None:
        items = [o for o in items if o["route_id"] == route_f]
    if ff_f is not None:
        items = [o for o in items if o["fulfillment_status"] == ff_f]
    if ste_f is not None:
        items = [o for o in items if o.get("settlement_telemetry_event_id") == ste_f]
    items.sort(key=lambda o: o["created_at"])
    total = len(items)
    return success_list([view(o) for o in items[offset:offset + limit]], limit, offset, total)


@bp.get("/wholesale/orders/<orderId>")
def get_order(orderId):
    get_auth()
    order = _get_order(orderId)
    return success_object(view(order))


@bp.patch("/wholesale/orders/<orderId>")
def patch_order(orderId):
    user_id, role = get_auth()
    body = get_json_body()
    require_role(role, ["OperatorManager"])
    order = _get_order(orderId)
    require_operator_ownership(role, user_id, order["operator_id"])
    # From-state (tier 7)
    if order["fulfillment_status"] != "DRAFT":
        raise ApiError(ERR_ORDER_NOT_DRAFT, 409, "PATCH requires fulfillment_status == DRAFT")
    # OCC on ReplenishmentOrder.version
    expected = body.get("expected_order_version")
    if isinstance(expected, bool) or not isinstance(expected, int):
        raise ApiError(ERR_INVALID_REQUEST, 400, "expected_order_version must be an integer")
    if expected != order["version"]:
        raise ApiError(ERR_STALE_VERSION, 412, "expected_order_version does not equal the order's current version")
    if "requested_delivery_date" in body and body["requested_delivery_date"] is not None:
        raw = body["requested_delivery_date"]
        if not isinstance(raw, str):
            raise ApiError(ERR_INVALID_REQUEST, 400, "requested_delivery_date must be YYYY-MM-DD")
        try:
            clock.parse_date(raw)
        except ValueError:
            raise ApiError(ERR_INVALID_REQUEST, 400, "requested_delivery_date must be YYYY-MM-DD")
        order["requested_delivery_date"] = raw
    if "lines" in body and body["lines"] is not None:
        lines = body["lines"]
        if not isinstance(lines, list):
            raise ApiError(ERR_INVALID_REQUEST, 400, "lines must be an array")
        _validate_lines_shape(lines)
        for row in lines:
            if row["product_id"] not in db.products:
                raise ApiError(ERR_PRODUCT_NOT_FOUND, 404, "Product id does not exist")
        order["lines"] = [{"product_id": r["product_id"], "quantity_cases": r["quantity_cases"]} for r in lines]
    order["total_cases"] = sum(r["quantity_cases"] for r in order["lines"])
    touch(order)
    return success_object(view(order))


@bp.post("/wholesale/orders/<orderId>/submit")
def submit_order(orderId):
    user_id, role = get_auth()
    get_json_body(required=False)
    require_role(role, ["OperatorManager"])
    order = _get_order(orderId)
    require_operator_ownership(role, user_id, order["operator_id"])
    # Tier 2: shape (every quantity_cases > 0)
    for row in order["lines"]:
        positive_int_value(row.get("quantity_cases"), "quantity_cases")
    # Tier 6: body-referenced existence (line products)
    for row in order["lines"]:
        if row["product_id"] not in db.products:
            raise ApiError(ERR_PRODUCT_NOT_FOUND, 404, "Product id does not exist")
    # Tier 7: from-state
    if order["fulfillment_status"] != "DRAFT":
        raise ApiError(ERR_ORDER_NOT_DRAFT, 409, "submit requires fulfillment_status == DRAFT")
    # Tier 8: related-entity gates
    operator = db.operators[order["operator_id"]]
    if operator["status"] != "ACTIVE":
        raise ApiError(ERR_OPERATOR_NOT_ACTIVE, 409, "Operator must be ACTIVE")
    location = db.locations[order["location_id"]]
    planogram = pricing.active_planogram_for_location(order["location_id"])
    if planogram is None:
        raise ApiError(ERR_NO_ACTIVE_PLANOGRAM, 409, "Location has no ACTIVE planogram")
    # Tier 9: temporal windows
    try:
        delivery_date = clock.parse_date(order["requested_delivery_date"])
    except ValueError:
        raise ApiError(ERR_INVALID_REQUEST, 400, "requested_delivery_date must be YYYY-MM-DD")
    current_date = clock.now().date()
    if not (delivery_date > current_date):
        raise ApiError(ERR_DELIVERY_DATE_NOT_FUTURE, 422, "requested_delivery_date must be strictly after the current logical date")
    route = db.routes[order["route_id"]]
    weekday_name = pricing.WEEKDAY_NAMES[delivery_date.weekday()]
    if weekday_name not in route["delivery_weekdays"]:
        raise ApiError(ERR_DELIVERY_DAY_NOT_SERVED, 422, "requested_delivery_date's weekday not in route.delivery_weekdays")
    # Tier 10: non-empty constraint
    if not order["lines"]:
        raise ApiError(ERR_EMPTY_ORDER, 422, "submit with zero lines")
    # Tier 11: referenced-entity state
    slot_products = {s["product_id"] for s in planogram["slots"]}
    for row in order["lines"]:
        product = db.products[row["product_id"]]
        if product["status"] != "ACTIVE":
            raise ApiError(ERR_PRODUCT_DISCONTINUED, 422, "Product is DISCONTINUED")
        if location["location_type"] not in product["eligible_location_types"]:
            raise ApiError(ERR_PRODUCT_NOT_ELIGIBLE_FOR_LOCATION_TYPE, 422,
                           "Product's eligible_location_types does not include the location's location_type")
        if row["product_id"] not in slot_products:
            raise ApiError(ERR_PRODUCT_NOT_ON_PLANOGRAM, 422,
                           "Order line product is not on the location's ACTIVE planogram")
    # Pricing (pinned rounding per §2.6) then tier 12 fiscal gate
    pricing.price_order_lines(order)
    if order["order_total_cents"] < route["min_order_cents"]:
        raise ApiError(ERR_MIN_ORDER_NOT_MET, 422, "order_total_cents < route.min_order_cents at submit")
    pricing.compute_provisional_margin(order)
    order["fulfillment_status"] = "SUBMITTED"
    touch(order)
    return success_object(view(order))


@bp.post("/wholesale/orders/<orderId>/revise")
def revise_order(orderId):
    user_id, role = get_auth()
    get_json_body(required=False)
    require_role(role, ["OperatorManager"])
    order = _get_order(orderId)
    require_operator_ownership(role, user_id, order["operator_id"])
    if order["fulfillment_status"] != "SUBMITTED":
        raise ApiError(ERR_ORDER_NOT_SUBMITTED, 409, "revise requires fulfillment_status == SUBMITTED")
    order["order_total_cents"] = 0
    order["promo_discount_cents"] = 0
    order["provisional_margin_per_vend_cents"] = None
    for line in order["lines"]:
        line.pop("unit_price_cents", None)
        line.pop("line_total_cents", None)
    order["fulfillment_status"] = "DRAFT"
    touch(order)
    return success_object(view(order))


@bp.post("/wholesale/orders/<orderId>/confirm")
def confirm_order(orderId):
    user_id, role = get_auth()
    get_json_body(required=False)
    require_role(role, ["RoutePlanner"])
    order = _get_order(orderId)
    if order["fulfillment_status"] != "SUBMITTED":
        raise ApiError(ERR_ORDER_NOT_SUBMITTED, 409, "confirm requires fulfillment_status == SUBMITTED")
    operator = db.operators[order["operator_id"]]
    if operator["status"] != "ACTIVE":
        raise ApiError(ERR_OPERATOR_NOT_ACTIVE, 409, "Operator must be ACTIVE")
    route = db.routes[order["route_id"]]
    firm, _ = pricing.capacity_consumption(order["route_id"], order["requested_delivery_date"])
    if firm + order["total_cases"] > route["daily_case_capacity"]:
        raise ApiError(ERR_ROUTE_CAPACITY_EXCEEDED, 409,
                       "Firm route-day capacity would be exceeded")
    order["fulfillment_status"] = "CONFIRMED"
    touch(order)
    return success_object(view(order))


@bp.post("/wholesale/orders/<orderId>/cancel")
def cancel_order(orderId):
    user_id, role = get_auth()
    get_json_body(required=False)
    require_role(role, ["OperatorManager"])
    order = _get_order(orderId)
    require_operator_ownership(role, user_id, order["operator_id"])
    if order["fulfillment_status"] not in ("DRAFT", "SUBMITTED", "CONFIRMED"):
        raise ApiError(ERR_INVALID_STATE_TRANSITION, 409,
                       "cancel admitted only from DRAFT, SUBMITTED, or CONFIRMED")
    # Capacity is a derived aggregate; cancelling from CONFIRMED removes it from the
    # firm set automatically (compensating action).
    order["fulfillment_status"] = "CANCELLED"
    touch(order)
    return success_object(view(order))


@bp.post("/wholesale/orders/<orderId>/mark-delivered")
def mark_delivered(orderId):
    user_id, role = get_auth()
    get_json_body(required=False)
    require_role(role, ["WarehouseOps"])
    order = _get_order(orderId)
    if order["fulfillment_status"] != "CONFIRMED":
        raise ApiError(ERR_ORDER_NOT_CONFIRMED, 409, "mark-delivered requires fulfillment_status == CONFIRMED")
    order["fulfillment_status"] = "DELIVERED"
    order["amount_due_cents"] = order["order_total_cents"]
    if order["order_total_cents"] == 0:
        order["settlement_status"] = "SETTLED"
    else:
        order["settlement_status"] = "OPEN"
    touch(order)
    return success_object(view(order))


@bp.post("/wholesale/orders/<orderId>/apply-credit")
def apply_credit(orderId):
    user_id, role = get_auth()
    body = get_json_body(required=False) or {}
    require_role(role, ["OperatorManager"])
    order = _get_order(orderId)
    require_operator_ownership(role, user_id, order["operator_id"])
    if order["settlement_status"] != "OPEN":
        raise ApiError(ERR_ORDER_NOT_OPEN_FOR_SETTLEMENT, 409,
                       "apply-credit requires settlement_status == OPEN")
    operator = db.operators[order["operator_id"]]
    amount_cents = body.get("amount_cents")
    if amount_cents is not None:
        if isinstance(amount_cents, bool) or not isinstance(amount_cents, int):
            raise ApiError(ERR_INVALID_REQUEST, 400, "amount_cents must be an integer")
        if amount_cents <= 0:
            raise ApiError(ERR_INVALID_REQUEST, 400, "amount_cents must be positive")
        if amount_cents > operator["credit_balance_cents"]:
            raise ApiError(ERR_INSUFFICIENT_CREDIT_BALANCE, 422,
                           "amount_cents exceeds operator credit balance")
    if operator["credit_balance_cents"] <= 0:
        raise ApiError(ERR_INSUFFICIENT_CREDIT_BALANCE, 422, "operator credit balance is zero")
    x = min(amount_cents if amount_cents is not None else operator["credit_balance_cents"],
            order["amount_due_cents"])
    operator["credit_balance_cents"] -= x
    touch(operator)
    order["credit_applied_cents"] += x
    order["amount_due_cents"] -= x
    if order["amount_due_cents"] == 0:
        order["settlement_status"] = "SETTLED"  # auto-settle; settled_tender stays null
    touch(order)
    return success_object(view(order))


@bp.post("/wholesale/orders/<orderId>/settle")
def settle_order(orderId):
    user_id, role = get_auth()
    body = get_json_body()
    require_role(role, ["WholesaleAdmin"])
    tender_type = req_string(body, "tender_type")
    if tender_type not in TENDERS:
        raise ApiError(ERR_INVALID_REQUEST, 400, "tender_type must be CASH or CASHLESS")
    telemetry_event_id = req_string(body, "telemetry_event_id")
    order = _get_order(orderId)
    # From-state (tier 7)
    if order["settlement_status"] != "OPEN":
        raise ApiError(ERR_ORDER_NOT_OPEN_FOR_SETTLEMENT, 409,
                       "settle requires settlement_status == OPEN")
    # Body-referenced existence (tier 6) — checked after from-state per cascade order
    # for settle: tier 6 precedes tier 7 numerically, but the event id lives in the
    # body; scaffold tier 6 applies to body FK references.
    event = db.telemetry_events.get(telemetry_event_id)
    if event is None:
        raise ApiError(ERR_TELEMETRY_EVENT_NOT_FOUND, 404, "telemetry_event_id does not exist")
    # Tier 11: event must belong to the order's location
    if event["location_id"] != order["location_id"]:
        raise ApiError(ERR_TELEMETRY_EVENT_LOCATION_MISMATCH, 422,
                       "settle telemetry event's location_id != order.location_id")
    # margin_per_vend realized variant
    cashless_fee = pricing.round_half_up_decimal(
        __import__("decimal").Decimal(event["cashless_sales_cents"]) * pricing.CASHLESS_FEE_BPS / 10000
    )
    order["cashless_fee_cents"] = cashless_fee
    units_vended = sum(item["units_vended"] for item in event["items"])
    if units_vended == 0:
        order["realized_margin_per_vend_cents"] = 0
    else:
        order["realized_margin_per_vend_cents"] = pricing.round_half_up_div(
            event["cash_collected_cents"] + event["cashless_sales_cents"]
            - cashless_fee - order["order_total_cents"],
            units_vended,
        )
    order["settled_tender"] = tender_type
    order["settlement_telemetry_event_id"] = telemetry_event_id
    order["settlement_status"] = "SETTLED"
    touch(order)
    return success_object(view(order))
