"""Orders: checkout, capture-payment, cancel (PRD §3.4, §3.7)."""
from flask import Blueprint, request

import db
from errors import err
from middleware import require_role
from response import success, list_success
from services.common import (
    serialize, serialize_list, get_json, require_found, require_str,
    require_enum, require_int, paginate,
)
from services.carts import recompute_cart, cart_lines_for
from services.orders import order_lines_for, recompute_invoice

bp = Blueprint("orders", __name__)

FULFILLMENT_MODES = {"PSC", "HOME_KIT"}
HOME_KIT_BANNED_STATES = {"NY", "NJ", "RI"}


def _is_pwn_restricted(test_code):
    """PWN-restricted iff test_code starts with case-sensitive prefix 'TST'."""
    return test_code.startswith("TST")


def _owns(role, user_id, patient_id):
    return not (role == "Patient" and user_id != patient_id)


@bp.route("/catalog/orders", methods=["POST"])
def place_order():
    user_id, role = require_role(["Patient"])
    body = get_json()
    # PRD §2.5: identifier existence (ERR_NOT_FOUND) is resolved before request-body
    # well-formedness (ERR_INVALID_REQUEST). cart_id is the only referenced identifier.
    cart_id = require_str(body, "cart_id")
    cart = require_found("carts", cart_id)
    if not _owns(role, user_id, cart["patient_id"]):
        raise err("ERR_NOT_RESOURCE_OWNER", "Not the owning patient")

    # Body well-formedness only after existence resolves.
    mode = body.get("fulfillment_mode")
    require_enum(mode, FULFILLMENT_MODES, "fulfillment_mode")
    if body.get("expected_cart_version") is None:
        raise err("ERR_INVALID_REQUEST", "Missing required field: expected_cart_version")
    expected_version = require_int(body, "expected_cart_version", non_negative=True)

    # OCC version check runs BEFORE state preconditions (PRD §2.5, §2.8).
    if expected_version != cart["version"]:
        raise err("ERR_STALE_CART_VERSION", "Cart version has advanced")

    # Empty cart cannot be checked out.
    recompute_cart(cart)
    if cart["line_count"] == 0:
        raise err("ERR_EMPTY_CART", "Cannot checkout an empty cart")

    patient = require_found("patients", cart["patient_id"])
    lines = cart_lines_for(cart_id)

    # HOME_KIT shipping eligibility validated at checkout (PRD §3.4, §3.5).
    if mode == "HOME_KIT":
        if patient["state_code"] in HOME_KIT_BANNED_STATES:
            raise err("ERR_HOME_KIT_STATE_BANNED", "Home kit cannot ship to this state")
        for ln in lines:
            offering = db.get("test_offerings", ln["test_offering_id"])
            if offering is None or not offering.get("home_kit_eligible"):
                raise err("ERR_HOME_KIT_STATE_BANNED", "Offering is not home_kit_eligible")

    # Mint the order.
    order = db.new_record({
        "patient_id": cart["patient_id"],
        "cart_id": cart_id,
        "fulfillment_mode": mode,
        "fund_source": cart["fund_source"],
        "invoiced_total_cents": 0,
        "hsa_applied_cents": 0,
        "patient_due_cents": 0,
        "payment_status": "AUTH_PENDING",
        "fulfillment_status": "AWAITING_COLLECTION",
    })
    db.insert("orders", order)

    # Mint order lines from cart lines.
    for ln in lines:
        ol = db.new_record({
            "order_id": order["id"],
            "test_offering_id": ln["test_offering_id"],
            "test_code": ln["test_code"],
            "unit_list_price_cents": ln["unit_list_price_cents"],
            "repeat_discount_applied": ln.get("repeat_discount_applied", False),
            "requires_physician_order": _is_pwn_restricted(ln["test_code"]),
            "status": "ORDERED",
        })
        db.insert("order_lines", ol)
        # Each restricted line mints a SUBMITTED physician order.
        if ol["requires_physician_order"]:
            po = db.new_record({
                "order_line_id": ol["id"],
                "patient_id": order["patient_id"],
                "reviewing_physician_id": None,
                "clinical_note": None,
                "status": "SUBMITTED",
            })
            db.insert("physician_orders", po)

    # Payment authorized for the cart's estimated patient-due, captured now.
    auth_amount = cart["estimated_patient_due_cents"]
    payment = db.new_record({
        "order_id": order["id"],
        "fund_source": order["fund_source"],
        "authorized_amount_cents": auth_amount,
        "captured_amount_cents": 0,
        "hsa_drawn_cents": 0,
        "status": "AUTHORIZED",
    })
    db.insert("payments", payment)
    # Payment axis advances AUTH_PENDING -> AUTHORIZED at placement.
    order["payment_status"] = "AUTHORIZED"

    # Cart consumed.
    cart["status"] = "CHECKED_OUT"
    db.touch(cart)

    return success(serialize(order), status=201)


@bp.route("/catalog/orders/<rid>", methods=["GET"])
def get_order(rid):
    user_id, role = require_role(["Patient", "CatalogAdmin", "LabTech", "PhlebotomyTech"])
    order = require_found("orders", rid)
    if role == "Patient" and user_id != order["patient_id"]:
        raise err("ERR_NOT_RESOURCE_OWNER", "Not the owning patient")
    return success(serialize(order))


@bp.route("/catalog/orders", methods=["GET"])
def list_orders():
    user_id, role = require_role(["Patient", "CatalogAdmin", "LabTech"])
    rows = db.sorted_rows(db.all_rows("orders"))
    patient_id = request.args.get("patient_id")
    cart_id = request.args.get("cart_id")
    if patient_id:
        rows = [r for r in rows if r["patient_id"] == patient_id]
    if cart_id:
        rows = [r for r in rows if r["cart_id"] == cart_id]
    if role == "Patient":
        rows = [r for r in rows if r["patient_id"] == user_id]
    page, limit, offset, total = paginate(rows)
    return list_success(serialize_list(page), limit, offset, total)


@bp.route("/catalog/orders/<rid>/capture-payment", methods=["POST"])
def capture_payment(rid):
    user_id, role = require_role(["Patient"])
    order = require_found("orders", rid)
    if role == "Patient" and user_id != order["patient_id"]:
        raise err("ERR_NOT_RESOURCE_OWNER", "Not the owning patient")
    body = get_json()
    if body.get("expected_order_version") is None:
        raise err("ERR_INVALID_REQUEST", "Missing required field: expected_order_version")
    expected_version = require_int(body, "expected_order_version", non_negative=True)

    # OCC version check before state preconditions (PRD §2.5, §2.8).
    if expected_version != order["version"]:
        raise err("ERR_STALE_ORDER_VERSION", "Order version has advanced")

    # State preconditions: fulfillment COMPLETED, then payment AUTHORIZED.
    if order["fulfillment_status"] != "COMPLETED":
        raise err("ERR_ORDER_NOT_COMPLETE_FOR_CAPTURE", "Order not COMPLETED")
    if order["payment_status"] != "AUTHORIZED":
        raise err("ERR_PAYMENT_NOT_CAPTURABLE", "Payment not AUTHORIZED")

    # The invoice was finalized when the order reached COMPLETED (the last result
    # release / specimen rejection) per PRD §3.6/§3.7; capture settles the already-
    # finalized invoice and does NOT recompute it. Recomputing here would re-derive
    # hsa_applied against the patient's *current* balance and mask an
    # ERR_INSUFFICIENT_HSA_FUNDS when the balance was drained after completion.
    patient = db.get("patients", order["patient_id"])
    payment = _payment_for(order["id"])

    if order["fund_source"] == "HSA_FSA":
        draw = order["hsa_applied_cents"]
        if patient is None or draw > patient["hsa_balance_cents"]:
            raise err("ERR_INSUFFICIENT_HSA_FUNDS", "HSA draw exceeds balance")
        patient["hsa_balance_cents"] -= draw
        db.touch(patient)
        payment["hsa_drawn_cents"] = draw

    payment["captured_amount_cents"] = order["patient_due_cents"]
    payment["status"] = "CAPTURED"
    db.touch(payment)

    order["payment_status"] = "CAPTURED"
    db.touch(order)
    return success(serialize(order))


@bp.route("/catalog/orders/<rid>/cancel", methods=["POST"])
def cancel_order(rid):
    user_id, role = require_role(["Patient"])
    order = require_found("orders", rid)
    if role == "Patient" and user_id != order["patient_id"]:
        raise err("ERR_NOT_RESOURCE_OWNER", "Not the owning patient")
    body = get_json()
    if body.get("expected_order_version") is None:
        raise err("ERR_INVALID_REQUEST", "Missing required field: expected_order_version")
    expected_version = require_int(body, "expected_order_version", non_negative=True)

    # OCC version check before state preconditions.
    if expected_version != order["version"]:
        raise err("ERR_STALE_ORDER_VERSION", "Order version has advanced")

    # Cancellable only from AWAITING_COLLECTION/IN_PROCESSING/PARTIALLY_RESULTED.
    if order["fulfillment_status"] not in (
        "AWAITING_COLLECTION", "IN_PROCESSING", "PARTIALLY_RESULTED"
    ):
        raise err("ERR_ORDER_HAS_RESULTED_LINES", "Order not cancellable in current state")

    lines = order_lines_for(order["id"])
    if any(ol["status"] == "RESULTED" for ol in lines):
        raise err("ERR_ORDER_HAS_RESULTED_LINES", "Order already has a RESULTED line")

    payment = _payment_for(order["id"])
    if payment is None or payment["status"] not in ("AUTHORIZED", "CAPTURED"):
        raise err("ERR_PAYMENT_NOT_REFUNDABLE", "Payment not refundable")

    # Hop 1: non-terminal lines ORDERED/COLLECTED -> CANCELLED.
    for ol in lines:
        if ol["status"] in ("ORDERED", "COLLECTED"):
            ol["status"] = "CANCELLED"
            db.touch(ol)
            # Hop 2: each cancelled line's non-terminal specimen -> REJECTED.
            for sp in db.all_rows("specimens"):
                if sp["order_line_id"] == ol["id"] and sp["status"] in ("COLLECTED", "IN_ANALYSIS"):
                    sp["status"] = "REJECTED"
                    db.touch(sp)

    # Any BOOKED appointment for the order -> CANCELLED.
    for ap in db.all_rows("appointments"):
        if ap["order_id"] == order["id"] and ap["status"] == "BOOKED":
            ap["status"] = "CANCELLED"
            db.touch(ap)

    # Hop 3: payment refund along the payment axis.
    if payment["status"] == "CAPTURED":
        # Restore HSA when fund_source is HSA_FSA (HSA conserved).
        if order["fund_source"] == "HSA_FSA":
            patient = db.get("patients", order["patient_id"])
            if patient is not None:
                patient["hsa_balance_cents"] += payment["hsa_drawn_cents"]
                db.touch(patient)
        payment["status"] = "REFUNDED"
        db.touch(payment)
        order["payment_status"] = "REFUNDED"
    elif payment["status"] == "AUTHORIZED":
        payment["status"] = "REFUNDED"
        db.touch(payment)
        order["payment_status"] = "REFUNDED"

    order["fulfillment_status"] = "CANCELLED"
    db.touch(order)
    return success(serialize(order))


def _payment_for(order_id):
    for p in db.all_rows("payments"):
        if p["order_id"] == order_id:
            return p
    return None
