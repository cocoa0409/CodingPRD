"""Build spec endpoints (custom build pipeline)."""
from flask import Blueprint, request

from db import db
from errors import raise_err
from middleware import get_auth, require_role
from response import success_response, parse_pagination, apply_pagination
from services.calculations import (
    build_provisional_quote, build_final_price, recompute_credit_balance,
)
from services.common import (
    new_entity, touch, get_spec, get_customer, get_session,
    get_component_item, check_ownership, append_ledger_entry,
)
from services.serializers import serialize_build_spec
from services.sweeps import allocation_sweep

bp = Blueprint("specs", __name__)

READ_ROLES = {"ShopManager", "FittingSpecialist", "Customer"}


def _body():
    data = request.get_json(silent=True)
    return data if isinstance(data, dict) else {}


@bp.post("/build-specs")
def create_spec():
    user_id, role = get_auth()
    require_role(role, {"FittingSpecialist"})
    data = _body()
    customer_id = data.get("customer_id")
    fitting_session_id = data.get("fitting_session_id")
    head_item_id = data.get("head_item_id")
    shaft_item_id = data.get("shaft_item_id")
    grip_item_id = data.get("grip_item_id")
    length_inches = data.get("length_inches")
    loft_deg = data.get("loft_deg")
    lie_deg = data.get("lie_deg")
    labor_cents = data.get("labor_cents")

    # Body shape validation (priority 3)
    for field, val in (
        ("customer_id", customer_id),
        ("fitting_session_id", fitting_session_id),
        ("head_item_id", head_item_id),
        ("shaft_item_id", shaft_item_id),
        ("grip_item_id", grip_item_id),
    ):
        if not isinstance(val, str) or not val.strip():
            raise_err("ERR_VALIDATION", f"{field} is required")
    for field, val in (("length_inches", length_inches), ("loft_deg", loft_deg),
                       ("lie_deg", lie_deg)):
        if not isinstance(val, (int, float)) or isinstance(val, bool):
            raise_err("ERR_VALIDATION", f"{field} must be a number")
    if not isinstance(labor_cents, int) or isinstance(labor_cents, bool):
        raise_err("ERR_VALIDATION", "labor_cents must be an integer")

    # Existence of body FK ids (priority 4)
    get_customer(customer_id)
    get_session(fitting_session_id)
    head = get_component_item(head_item_id)
    shaft = get_component_item(shaft_item_id)
    grip = get_component_item(grip_item_id)

    # Structural constraints (priority 11): component slot type matching
    if head["component_type"] != "HEAD":
        raise_err("ERR_COMPONENT_TYPE_MISMATCH", "head_item_id must reference a HEAD item")
    if shaft["component_type"] != "SHAFT":
        raise_err("ERR_COMPONENT_TYPE_MISMATCH", "shaft_item_id must reference a SHAFT item")
    if grip["component_type"] != "GRIP":
        raise_err("ERR_COMPONENT_TYPE_MISMATCH", "grip_item_id must reference a GRIP item")

    s = new_entity()
    s.update({
        "customer_id": customer_id,
        "fitting_session_id": fitting_session_id,
        "head_item_id": head_item_id,
        "shaft_item_id": shaft_item_id,
        "grip_item_id": grip_item_id,
        "length_inches": length_inches,
        "loft_deg": loft_deg,
        "lie_deg": lie_deg,
        "labor_cents": labor_cents,
        "status": "DRAFT",
        "provisional_quote_cents": None,
        "final_price_cents": None,
        "payment_method": None,
        "delivered_at": None,
    })
    db.build_specs[s["id"]] = s
    return success_response(serialize_build_spec(s), status=201)


@bp.get("/build-specs/<sid>")
def read_spec(sid):
    user_id, role = get_auth()
    require_role(role, READ_ROLES)
    s = get_spec(sid)
    check_ownership(s, user_id, role)
    return success_response(serialize_build_spec(s))


@bp.get("/build-specs")
def list_specs():
    user_id, role = get_auth()
    require_role(role, READ_ROLES)
    limit, offset = parse_pagination(request.args)
    items = list(db.build_specs.values())
    if role == "Customer":
        items = [s for s in items if s["customer_id"] == user_id]
    for field in ("customer_id", "fitting_session_id", "status",
                  "head_item_id", "shaft_item_id", "grip_item_id"):
        val = request.args.get(field)
        if val is not None:
            items = [s for s in items if s.get(field) == val]
    items.sort(key=lambda s: s["created_at"])
    page, pagination = apply_pagination(items, limit, offset)
    return success_response(
        [serialize_build_spec(s) for s in page],
        response_type="array", pagination=pagination,
    )


@bp.post("/build-specs/<sid>/quote")
def quote_spec(sid):
    user_id, role = get_auth()
    require_role(role, {"FittingSpecialist"})
    data = _body()
    expected_version = data.get("expected_build_spec_version")
    if not isinstance(expected_version, int) or isinstance(expected_version, bool):
        raise_err("ERR_VALIDATION", "expected_build_spec_version is required")
    s = get_spec(sid)
    # OCC (priority 6)
    if expected_version != s["version"]:
        raise_err("ERR_STALE_VERSION", "spec version has advanced")
    # State guard (priority 7): quote allowed from DRAFT or QUOTED
    if s["status"] not in ("DRAFT", "QUOTED"):
        raise_err("ERR_INVALID_STATE_TRANSITION",
                  "quote is not defined from the spec's current state")
    s["provisional_quote_cents"] = build_provisional_quote(s)
    s["status"] = "QUOTED"
    touch(s)
    return success_response(serialize_build_spec(s))


@bp.post("/build-specs/<sid>/approve")
def approve_spec(sid):
    user_id, role = get_auth()
    require_role(role, {"Customer"})
    data = _body()
    payment_method = data.get("payment_method")
    if payment_method not in ("CREDIT", "EXTERNAL"):
        raise_err("ERR_VALIDATION", "payment_method must be CREDIT or EXTERNAL")
    s = get_spec(sid)
    check_ownership(s, user_id, role)
    # State guard
    if s["status"] != "QUOTED":
        raise_err("ERR_SPEC_NOT_QUOTED", "approve called on a spec not in QUOTED")
    # Fiscal: customer ACTIVE
    customer = db.customers[s["customer_id"]]
    if customer["status"] != "ACTIVE":
        raise_err("ERR_CUSTOMER_SUSPENDED", "customer is suspended")
    # Final price crystallizes at approve
    final_price = build_final_price(s)
    if payment_method == "CREDIT" and customer["credit_balance_cents"] < final_price:
        raise_err("ERR_INSUFFICIENT_CREDIT",
                  "credit balance does not cover the final price")

    s["final_price_cents"] = final_price
    s["payment_method"] = payment_method
    s["status"] = "ORDERED"
    touch(s)

    # Component order created as a side effect
    order = new_entity()
    order.update({
        "build_spec_id": s["id"],
        "status": "PENDING_ALLOCATION",
        "lines": [
            {"component_item_id": s["head_item_id"], "required_qty": 1, "allocated_qty": 0},
            {"component_item_id": s["shaft_item_id"], "required_qty": 1, "allocated_qty": 0},
            {"component_item_id": s["grip_item_id"], "required_qty": 1, "allocated_qty": 0},
        ],
        "required_units": 3,
    })
    db.component_orders[order["id"]] = order

    # CREDIT payment ledger entry
    if payment_method == "CREDIT":
        append_ledger_entry(s["customer_id"], -final_price, "BUILD_PAYMENT", s["id"])
        recompute_credit_balance(s["customer_id"])
        touch(customer)

    # Allocation sweep runs immediately; may advance spec ORDERED -> IN_BUILD
    allocation_sweep()
    return success_response(serialize_build_spec(s))


@bp.post("/build-specs/<sid>/cancel")
def cancel_spec(sid):
    user_id, role = get_auth()
    require_role(role, {"Customer", "FittingSpecialist"})
    s = get_spec(sid)
    check_ownership(s, user_id, role)
    if s["status"] not in ("DRAFT", "QUOTED", "ORDERED", "IN_BUILD"):
        raise_err("ERR_INVALID_STATE_TRANSITION",
                  "cancel is not defined from the spec's current state")
    # Cancel its component order, releasing allocated units
    for order in db.component_orders.values():
        if order["build_spec_id"] == s["id"] and order["status"] in (
                "PENDING_ALLOCATION", "BACKORDERED", "ALLOCATED"):
            for line in order["lines"]:
                if line["allocated_qty"] > 0:
                    item = db.component_items[line["component_item_id"]]
                    item["stock_reserved"] -= line["allocated_qty"]
                    item["stock_on_hand"] += line["allocated_qty"]
                    line["allocated_qty"] = 0
            order["status"] = "CANCELLED"
            touch(order)
    # CREDIT refund
    if s["payment_method"] == "CREDIT" and s["final_price_cents"] is not None:
        append_ledger_entry(s["customer_id"], s["final_price_cents"], "BUILD_REFUND", s["id"])
        recompute_credit_balance(s["customer_id"])
        touch(db.customers[s["customer_id"]])
    s["status"] = "CANCELLED"
    touch(s)
    # Release triggers allocation sweep over remaining orders
    allocation_sweep()
    return success_response(serialize_build_spec(s))


@bp.post("/build-specs/<sid>/mark-ready")
def mark_ready_spec(sid):
    user_id, role = get_auth()
    require_role(role, {"RepairTechnician"})
    s = get_spec(sid)
    if s["status"] != "IN_BUILD":
        raise_err("ERR_SPEC_NOT_IN_BUILD", "mark-ready called on a spec not in IN_BUILD")
    # Close the component order, consuming reserved units
    for order in db.component_orders.values():
        if order["build_spec_id"] == s["id"] and order["status"] == "ALLOCATED":
            for line in order["lines"]:
                if line["allocated_qty"] > 0:
                    item = db.component_items[line["component_item_id"]]
                    item["stock_reserved"] -= line["allocated_qty"]
                    item["consumed_total"] += line["allocated_qty"]
            order["status"] = "CLOSED"
            touch(order)
    s["status"] = "READY"
    touch(s)
    return success_response(serialize_build_spec(s))


@bp.post("/build-specs/<sid>/deliver")
def deliver_spec(sid):
    user_id, role = get_auth()
    require_role(role, {"FittingSpecialist", "ShopManager"})
    s = get_spec(sid)
    if s["status"] != "READY":
        raise_err("ERR_SPEC_NOT_READY", "deliver called on a spec not in READY")
    s["status"] = "DELIVERED"
    s["delivered_at"] = db.logical_now
    touch(s)
    customer = db.customers[s["customer_id"]]
    customer["completed_builds_count"] += 1
    touch(customer)
    return success_response(serialize_build_spec(s))
