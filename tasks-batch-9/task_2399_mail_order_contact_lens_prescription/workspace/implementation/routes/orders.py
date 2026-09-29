"""Order placement, substitution, shipping, delivery and compensating cancellation."""

from flask import Blueprint

from db import db, now, sort_rows, today, touch
from errors import ApiError
from middleware import (
    ROLE_ADMIN,
    ROLE_COMPLIANCE,
    ROLE_CUSTOMER,
    ROLE_FULFILLMENT,
    identity,
    lookup,
    paginate,
    parse_body,
    parse_pagination,
    parse_query,
    require_owner,
    require_role,
)
from response import list_response, object_response
from services import calc
from services.events import append_event
from services.ledger import has_open_hold
from services.workflow import cancel_order, create_order

bp = Blueprint("orders", __name__)

VERIFICATION_STATES = ("RX_PENDING", "RX_CLEARED", "RX_BLOCKED")
FULFILLMENT_STATES = ("PENDING", "SHIPPED", "DELIVERED", "CANCELLED")
CANCELLATION_REASONS = ("CUSTOMER_REQUEST", "DISPUTE_UPHELD", "PRESCRIBER_DENIED", "RX_EXPIRED")


@bp.post("/orders")
def place_order():
    user_id, role = identity()
    body = parse_body(
        {
            "customer_id": {"type": "uuid", "required": True},
            "prescription_id": {"type": "uuid", "required": True},
            "ordered_product_id": {"type": "uuid", "required": True},
            "boxes_od": {"type": "int", "required": True, "min": 0},
            "boxes_os": {"type": "int", "required": True, "min": 0},
            "itemized_receipt_reference": {"type": "string"},
        }
    )
    if body["boxes_od"] + body["boxes_os"] < 1:
        raise ApiError("ERR_INVALID_REQUEST", "boxes_od plus boxes_os must be at least 1.")
    require_role(role, [ROLE_CUSTOMER, ROLE_FULFILLMENT, ROLE_ADMIN])
    customer = lookup("customer", body["customer_id"])
    prescription = lookup("prescription", body["prescription_id"])
    product = lookup("product", body["ordered_product_id"])
    require_owner(role, user_id, customer["id"])
    if prescription["status"] == "EXPIRED" or prescription["expiry_date"] <= today():
        raise ApiError("ERR_PRESCRIPTION_EXPIRED")
    if prescription["status"] == "INVALIDATED":
        raise ApiError("ERR_PRESCRIPTION_INVALIDATED")
    if product["status"] == "INACTIVE":
        raise ApiError("ERR_PRODUCT_INACTIVE")
    requested = body["boxes_od"] + body["boxes_os"]
    if prescription["boxes_consumed"] + requested > prescription["boxes_authorized_total"]:
        raise ApiError("ERR_BOX_AUTHORIZATION_EXCEEDED")
    order = create_order(
        customer,
        prescription,
        product,
        body["boxes_od"],
        body["boxes_os"],
        body["itemized_receipt_reference"],
    )
    return object_response(order, 201)


@bp.get("/orders/<order_id>")
def get_order(order_id):
    user_id, role = identity()
    parse_query({})
    require_role(role, [ROLE_ADMIN, ROLE_COMPLIANCE, ROLE_FULFILLMENT, ROLE_CUSTOMER])
    order = lookup("order", order_id)
    require_owner(role, user_id, order["customer_id"])
    return object_response(order)


@bp.get("/orders")
def list_orders():
    user_id, role = identity()
    filters = parse_query(
        {
            "customer_id": {"type": "string"},
            "prescription_id": {"type": "string"},
            "ordered_product_id": {"type": "string"},
            "fulfilled_product_id": {"type": "string"},
            "verification_state": {"type": "enum", "values": VERIFICATION_STATES},
            "fulfillment_state": {"type": "enum", "values": FULFILLMENT_STATES},
        }
    )
    limit, offset = parse_pagination()
    require_role(role, [ROLE_ADMIN, ROLE_COMPLIANCE, ROLE_FULFILLMENT, ROLE_CUSTOMER])
    rows = list(db.orders.values())
    if role == ROLE_CUSTOMER:
        rows = [r for r in rows if r["customer_id"] == user_id]
    for field in (
        "customer_id",
        "prescription_id",
        "ordered_product_id",
        "fulfilled_product_id",
        "verification_state",
        "fulfillment_state",
    ):
        if filters[field]:
            rows = [r for r in rows if r[field] == filters[field]]
    page, total = paginate(sort_rows(rows), limit, offset)
    return list_response(page, limit, offset, total)


def _active_mapping(from_product_id, to_product_id):
    for row in sort_rows(list(db.lens_equivalences.values())):
        if (
            row["from_product_id"] == from_product_id
            and row["to_product_id"] == to_product_id
            and row["status"] == "ACTIVE"
        ):
            return row
    return None


@bp.post("/orders/<order_id>/substitution")
def apply_substitution(order_id):
    user_id, role = identity()
    body = parse_body(
        {
            "substitute_product_id": {"type": "uuid", "required": True},
            "expected_order_version": {"type": "int", "required": True},
            "patient_consent": {"type": "bool", "default": False},
        }
    )
    require_role(role, [ROLE_FULFILLMENT, ROLE_ADMIN])
    order = lookup("order", order_id)
    substitute = lookup("product", body["substitute_product_id"])
    if body["expected_order_version"] != order["version"]:
        raise ApiError("ERR_STALE_ORDER_VERSION")
    prescription = db.prescriptions.get(order["prescription_id"])
    if prescription is not None and prescription["status"] == "INVALIDATED":
        raise ApiError("ERR_PRESCRIPTION_INVALIDATED")

    index, od_fulfilled, os_fulfilled = calc.deviation_index(prescription, substitute)
    if index > calc.CONSENT_MAX_INDEX:
        raise ApiError("ERR_PARAMETER_DEVIATION_EXCEEDED")

    mapping = _active_mapping(order["ordered_product_id"], substitute["id"])
    mapping_requires_consent = mapping is not None and (
        mapping["requires_patient_consent"] or mapping["equivalence_class"] == "MATERIAL_ONLY"
    )
    if (index > calc.AUTO_APPROVE_MAX_INDEX or mapping_requires_consent) and not body["patient_consent"]:
        raise ApiError("ERR_CONSENT_REQUIRED")
    if mapping is None:
        raise ApiError("ERR_NO_EQUIVALENCE_MAPPING")
    if substitute["status"] == "INACTIVE":
        raise ApiError("ERR_PRODUCT_INACTIVE")

    rounded = (
        od_fulfilled != prescription["od_sphere"] or os_fulfilled != prescription["os_sphere"]
    )
    order["fulfilled_product_id"] = substitute["id"]
    order["substitution_type"] = "PARAMETER_ROUNDED" if rounded else "BRAND_EQUIVALENT"
    order["parameter_deviation_index"] = index
    order["fulfilled_od_sphere"] = od_fulfilled
    order["fulfilled_os_sphere"] = os_fulfilled
    touch(order)
    append_event(
        order["prescription_id"], "SUBSTITUTION_APPLIED", "Order", order["id"], (role, user_id)
    )
    return object_response(order)


@bp.post("/orders/<order_id>/ship")
def ship_order(order_id):
    _, role = identity()
    parse_body({})
    require_role(role, [ROLE_FULFILLMENT, ROLE_ADMIN])
    order = lookup("order", order_id)
    if order["fulfillment_state"] != "PENDING":
        raise ApiError("ERR_INVALID_STATE_TRANSITION")
    if order["verification_state"] != "RX_CLEARED":
        raise ApiError("ERR_INVALID_STATE_TRANSITION")
    prescription = db.prescriptions.get(order["prescription_id"])
    if prescription is not None and prescription["status"] == "INVALIDATED":
        raise ApiError("ERR_PRESCRIPTION_INVALIDATED")
    if has_open_hold(order["customer_id"]):
        raise ApiError("ERR_HOLD_OPEN_BLOCKS_ACTION")
    order["fulfillment_state"] = "SHIPPED"
    order["shipped_at"] = now()
    touch(order)
    return object_response(order)


@bp.post("/orders/<order_id>/deliver")
def deliver_order(order_id):
    _, role = identity()
    parse_body({})
    require_role(role, [ROLE_FULFILLMENT, ROLE_ADMIN])
    order = lookup("order", order_id)
    if order["fulfillment_state"] != "SHIPPED" or order.get("shipped_at") is None:
        raise ApiError("ERR_INVALID_STATE_TRANSITION")
    order["fulfillment_state"] = "DELIVERED"
    order["delivered_at"] = now()
    touch(order)
    return object_response(order)


@bp.post("/orders/<order_id>/cancel")
def cancel_order_endpoint(order_id):
    user_id, role = identity()
    body = parse_body(
        {"cancellation_reason": {"type": "enum", "values": CANCELLATION_REASONS, "required": True}}
    )
    require_role(role, [ROLE_CUSTOMER, ROLE_COMPLIANCE, ROLE_ADMIN])
    order = lookup("order", order_id)
    require_owner(role, user_id, order["customer_id"])
    if order["fulfillment_state"] != "PENDING":
        raise ApiError("ERR_INVALID_STATE_TRANSITION")
    cancel_order(order, body["cancellation_reason"], (role, user_id))
    return object_response(order)
