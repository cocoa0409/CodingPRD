"""Parts orders: assembly, pricing, disclosure, confirmation, delivery, service steps."""
from flask import Blueprint, g

import db
from db import base_row, setf, touch
from errors import ApiError
from middleware import COMPLIANCE_OFFICER, FAILURE_ANALYSIS_ENGINEER, PROGRAM_ADMIN, \
    REPAIR_PROVIDER_TECH, SAFETY_REVIEWER, SELF_REPAIR_CUSTOMER, check_order_ownership, \
    check_provider_scope, endpoint
from response import collection, created, ok
from routes.helpers import filter_eq, find_profile, get_ack, get_assessment, get_line, \
    get_order, get_part, get_provider, obligation_for
from serializers import ack_json, line_json, order_json
from services.compliance import published_revision, select_compat
from services.orders import commit_core_liability, rental_occupancy, release_core_liability, \
    rollup_closure, settle_core
from services.pricing import CONSUMER_CORE_DEPOSIT_CAP_CENTS, order_lines, \
    price_order, prospective_core_deposit
from util import days, new_token
from validation import F, int_range, read_body

bp = Blueprint("orders", __name__)

BUYER_CLASSES = ("SELF_REPAIR_CONSUMER", "AUTHORIZED_PROVIDER")
SCOPES = ("FULL_SELF_REPAIR", "TOOL_RENTAL_ONLY", "PROVIDER_MANAGED")
CORE_CONDITIONS = ("INTACT", "DAMAGED_SHELL", "INCOMPLETE", "NON_RETURNABLE")
ELIGIBLE_DECISIONS = ("ELIGIBLE", "ELIGIBLE_WITH_TOOL_RENTAL")
CORE_DUE_DAYS = 30
CALIBRATION_TOLERANCE_PPM = 150
CALIBRATION_ATTEMPT_CAP = 3

ORDER_READ_ROLES = [PROGRAM_ADMIN, SAFETY_REVIEWER, COMPLIANCE_OFFICER, SELF_REPAIR_CUSTOMER,
                    REPAIR_PROVIDER_TECH, FAILURE_ANALYSIS_ENGINEER]
ACK_READ_ROLES = [PROGRAM_ADMIN, SAFETY_REVIEWER, COMPLIANCE_OFFICER, SELF_REPAIR_CUSTOMER,
                  REPAIR_PROVIDER_TECH]
BUYER_ROLES = [SELF_REPAIR_CUSTOMER, REPAIR_PROVIDER_TECH]

TIER_REQUIREMENTS = {
    "SAFETY_RESTRICTED_HIGH_VOLTAGE": ("TIER_1_UNRESTRICTED",),
    "SAFETY_RESTRICTED_BATTERY": ("TIER_1_UNRESTRICTED", "TIER_2_SAFETY"),
    "PAIRED_SECURITY": ("TIER_1_UNRESTRICTED", "TIER_2_SAFETY"),
}


# --------------------------------------------------------------------------
# shared guards
# --------------------------------------------------------------------------

def _caller_scope(order):
    check_order_ownership(order)
    check_provider_scope(order.get("provider_id"))


def _model_of(order):
    return db.db.models.get(order["model_id"])


def _check_not_restricted(order):
    model = _model_of(order)
    if model is not None and model.get("compliance_posture") == "ORDER_RESTRICTED":
        raise ApiError("ERR_MODEL_ORDER_RESTRICTED")


def _check_core_deposit_cap(order, extra_part=None, extra_quantity=0):
    if order["buyer_class"] != "SELF_REPAIR_CONSUMER":
        return
    prospective = prospective_core_deposit(order, extra_part, extra_quantity)
    if prospective > CONSUMER_CORE_DEPOSIT_CAP_CENTS:
        raise ApiError("ERR_CORE_DEPOSIT_CAP_EXCEEDED")


def _order_assessment(order):
    return db.db.assessments.get(order.get("assessment_id"))


# --------------------------------------------------------------------------
# orders
# --------------------------------------------------------------------------

@bp.post("/parts-orders")
@endpoint(BUYER_ROLES)
def create_order():
    body = read_body([
        F("assessment_id", "string", required=True),
        F("region_code", "string", required=True),
        F("buyer_class", "enum", required=True, enum=BUYER_CLASSES),
        F("provider_id", "string"),
        F("rental_window_start", "datetime"),
        F("rental_window_end", "datetime"),
    ])
    if body["buyer_class"] == "AUTHORIZED_PROVIDER" and body["provider_id"] is None:
        raise ApiError("ERR_INVALID_REQUEST",
                       "provider_id is required for an AUTHORIZED_PROVIDER order.")
    start, end = body["rental_window_start"], body["rental_window_end"]
    if start is not None and end is not None and end < start:
        raise ApiError("ERR_INVALID_DATE_RANGE",
                       "rental_window_end precedes rental_window_start.")

    assessment = get_assessment(body["assessment_id"])
    profile = find_profile(body["region_code"])
    provider = None
    if body["provider_id"] is not None:
        provider = get_provider(body["provider_id"])

    check_provider_scope(body["provider_id"])

    if assessment["status"] != "VALID":
        raise ApiError("ERR_ASSESSMENT_NOT_VALID")
    if assessment["decision"] not in ELIGIBLE_DECISIONS:
        raise ApiError("ERR_ASSESSMENT_BLOCKED")

    pinned_revision = None
    if assessment.get("pinned_manual_revision_id") is not None:
        pinned_revision = db.db.revisions.get(assessment["pinned_manual_revision_id"])

    row = base_row()
    row.update({
        "assessment_id": assessment["id"],
        "model_id": assessment["model_id"],
        "provider_id": provider["id"] if provider is not None else None,
        "pinned_manual_revision_id": assessment.get("pinned_manual_revision_id"),
        "pinned_manual_revision_number": (
            pinned_revision["revision_number"] if pinned_revision is not None else None),
        "region_code": profile["region_code"],
        "buyer_class": body["buyer_class"],
        "customer_user_id": g.user_id,
        "rental_window_start": start,
        "rental_window_end": end,
        "fulfillment_status": "DRAFT",
        "core_return_status": "NOT_REQUIRED",
        "warranty_impact_class": assessment.get("warranty_impact_class"),
        "parts_subtotal_cents": 0,
        "tool_purchase_cents": 0,
        "rental_deposit_cents": 0,
        "documentation_fee_cents": 0,
        "core_deposit_cents": 0,
        "total_due_cents": 0,
        "core_credit_provisional_cents": 0,
        "core_credit_final_cents": None,
        "core_return_due_at": None,
        "core_days_late": None,
        "disclosure_acknowledged_at": None,
        "confirmed_at": None,
        "delivered_at": None,
        "blocked_reason": None,
        "cancellation_reason": None,
    })
    db.db.orders.add(row)
    setf(assessment, "status", "CONSUMED")
    return created(order_json(row))


@bp.get("/parts-orders/<order_id>")
@endpoint(ORDER_READ_ROLES)
def read_order(order_id):
    return ok(order_json(get_order(order_id)))


@bp.get("/parts-orders")
@endpoint(ORDER_READ_ROLES)
def list_orders():
    rows = db.db.orders.all()
    for field in ("model_id", "assessment_id", "provider_id", "pinned_manual_revision_id",
                  "fulfillment_status", "core_return_status"):
        rows = filter_eq(rows, field)
    return collection(rows, order_json)


# --------------------------------------------------------------------------
# lines
# --------------------------------------------------------------------------

@bp.post("/parts-orders/<order_id>/lines")
@endpoint(BUYER_ROLES)
def append_line(order_id):
    body = read_body([
        F("part_id", "string", required=True),
        F("quantity", "int", required=True),
        F("expected_order_version", "int", required=True),
    ])
    int_range(body["quantity"], "quantity", 1, 500)

    order = get_order(order_id)
    part = get_part(body["part_id"])

    if body["expected_order_version"] != order.get("version"):
        raise ApiError("ERR_STALE_ORDER_VERSION")

    _caller_scope(order)

    if order["fulfillment_status"] != "DRAFT":
        raise ApiError("ERR_INVALID_STATE_TRANSITION")

    at = db.now()
    compat = select_compat(part["id"], order["model_id"], at)
    if part["status"] != "PUBLISHED" or compat is None:
        raise ApiError("ERR_PART_NOT_PUBLISHED")

    _check_not_restricted(order)

    if order["buyer_class"] == "AUTHORIZED_PROVIDER":
        allowed = TIER_REQUIREMENTS.get(part["safety_class"])
        if allowed is not None:
            provider = db.db.providers.get(order.get("provider_id"))
            tier = provider.get("parts_access_tier") if provider is not None else None
            if tier not in allowed:
                raise ApiError("ERR_PARTS_ACCESS_TIER_INSUFFICIENT")

    if part["part_class"] == "RENTAL_KIT":
        start = order.get("rental_window_start")
        end = order.get("rental_window_end")
        if start is None or end is None or start.date() < at.date():
            raise ApiError("ERR_RENTAL_WINDOW_REQUIRED")
        capacity = part.get("concurrent_rental_capacity") or 0
        occupied = rental_occupancy(part["id"], order, start, end)
        if occupied + body["quantity"] > capacity:
            raise ApiError("ERR_RENTAL_CAPACITY_EXCEEDED")

    _check_core_deposit_cap(order, part, body["quantity"])

    row = base_row()
    row.update({
        "order_id": order["id"],
        "part_id": part["id"],
        "quantity": body["quantity"],
        "buyer_multiplier": None,
        "volume_multiplier": None,
        "tier_surcharge_multiplier": None,
        "unit_price_cents": 0,
        "line_total_cents": 0,
        "authentication_status": "NOT_REQUIRED",
        "calibration_status": "NOT_REQUIRED",
        "calibration_attempt_count": 0,
        "last_measured_offset_ppm": None,
        "pairing_token": None,
    })
    db.db.lines.add(row)

    price_order(order)
    touch(order)
    return created(line_json(row))


@bp.get("/parts-orders/<order_id>/lines")
@endpoint(ORDER_READ_ROLES)
def list_order_lines(order_id):
    get_order(order_id)
    rows = [l for l in db.db.lines.all() if l["order_id"] == order_id]
    for field in ("part_id", "calibration_status", "authentication_status"):
        rows = filter_eq(rows, field)
    return collection(rows, line_json)


@bp.get("/order-lines/<line_id>")
@endpoint(ORDER_READ_ROLES)
def read_line(line_id):
    return ok(line_json(get_line(line_id)))


@bp.get("/order-lines")
@endpoint(ORDER_READ_ROLES)
def list_lines():
    rows = db.db.lines.all()
    for field in ("order_id", "part_id", "calibration_status", "authentication_status"):
        rows = filter_eq(rows, field)
    return collection(rows, line_json)


# --------------------------------------------------------------------------
# disclosure
# --------------------------------------------------------------------------

@bp.post("/parts-orders/<order_id>/request-disclosure")
@endpoint(BUYER_ROLES)
def request_disclosure(order_id):
    read_body([])
    order = get_order(order_id)
    _caller_scope(order)

    if order["fulfillment_status"] != "DRAFT":
        raise ApiError("ERR_INVALID_STATE_TRANSITION")

    assessment = _order_assessment(order)
    if assessment is None or assessment["status"] in ("REVOKED_BY_SAFETY", "EXPIRED") \
            or assessment["decision"] not in ELIGIBLE_DECISIONS:
        raise ApiError("ERR_ASSESSMENT_NOT_VALID")

    if not order_lines(order["id"]):
        raise ApiError("ERR_ORDER_HAS_NO_LINES")

    _check_not_restricted(order)
    _check_core_deposit_cap(order)

    price_order(order)
    setf(order, "warranty_impact_class", assessment.get("warranty_impact_class"))
    setf(order, "fulfillment_status", "PENDING_DISCLOSURE")
    touch(order)
    return ok(order_json(order))


def _order_has_component_line(order_id):
    for line in order_lines(order_id):
        part = db.db.parts.get(line["part_id"])
        if part is not None and part["part_class"] == "COMPONENT":
            return True
    return False


def _acceptable_scopes(order):
    if order["buyer_class"] == "AUTHORIZED_PROVIDER":
        return ("PROVIDER_MANAGED",)
    for line in order_lines(order["id"]):
        part = db.db.parts.get(line["part_id"])
        if part is not None and part["part_class"] in ("COMPONENT", "CONSUMABLE"):
            return ("FULL_SELF_REPAIR",)
    return ("FULL_SELF_REPAIR", "TOOL_RENTAL_ONLY")


@bp.post("/parts-orders/<order_id>/acknowledgments")
@endpoint(BUYER_ROLES)
def create_acknowledgment(order_id):
    body = read_body([
        F("warranty_impact_class_ack", "string", required=True),
        F("liability_warning_version", "string", required=True),
        F("acknowledged_scope", "enum", required=True, enum=SCOPES),
    ])
    order = get_order(order_id)

    if order.get("customer_user_id") != g.user_id:
        raise ApiError("ERR_ORDER_NOT_OWNED")
    check_provider_scope(order.get("provider_id"))

    if order["fulfillment_status"] != "PENDING_DISCLOSURE":
        raise ApiError("ERR_INVALID_STATE_TRANSITION")

    if body["warranty_impact_class_ack"] != order.get("warranty_impact_class"):
        raise ApiError("ERR_DISCLOSURE_MISMATCH",
                       "warranty_impact_class_ack does not match the order.")
    if body["acknowledged_scope"] == "TOOL_RENTAL_ONLY" \
            and _order_has_component_line(order["id"]):
        raise ApiError("ERR_DISCLOSURE_MISMATCH",
                       "TOOL_RENTAL_ONLY does not cover a component line.")

    assessment = _order_assessment(order)
    pinned_warning = assessment.get("liability_warning_version") if assessment else None
    if body["liability_warning_version"] != pinned_warning:
        raise ApiError("ERR_LIABILITY_WARNING_STALE")

    at = db.now()
    row = base_row(with_common=False)
    row.update({
        "order_id": order["id"],
        "warranty_impact_class_ack": body["warranty_impact_class_ack"],
        "liability_warning_version": body["liability_warning_version"],
        "acknowledged_scope": body["acknowledged_scope"],
        "acknowledged_by_user_id": g.user_id,
        "manual_revision_number": order.get("pinned_manual_revision_number"),
        "acknowledged_at": at,
    })
    db.db.acks.add(row)

    if order.get("disclosure_acknowledged_at") is None:
        setf(order, "disclosure_acknowledged_at", at)
    return created(ack_json(row))


@bp.get("/parts-orders/<order_id>/acknowledgments")
@endpoint(ACK_READ_ROLES)
def list_order_acks(order_id):
    get_order(order_id)
    rows = [a for a in db.db.acks.all() if a["order_id"] == order_id]
    rows = filter_eq(rows, "acknowledged_scope")
    return collection(rows, ack_json)


@bp.get("/disclosure-acknowledgments/<acknowledgment_id>")
@endpoint(ACK_READ_ROLES)
def read_ack(acknowledgment_id):
    return ok(ack_json(get_ack(acknowledgment_id)))


@bp.get("/disclosure-acknowledgments")
@endpoint(ACK_READ_ROLES)
def list_acks():
    rows = db.db.acks.all()
    rows = filter_eq(rows, "order_id")
    rows = filter_eq(rows, "acknowledged_scope")
    return collection(rows, ack_json)


# --------------------------------------------------------------------------
# confirmation, delivery, cancellation
# --------------------------------------------------------------------------

@bp.post("/parts-orders/<order_id>/confirm")
@endpoint(BUYER_ROLES)
def confirm_order(order_id):
    read_body([])
    order = get_order(order_id)
    _caller_scope(order)

    lines = order_lines(order["id"])

    # band 6
    for line in lines:
        part = db.db.parts.get(line["part_id"])
        if part is not None and part["status"] == "RESTRICTED":
            raise ApiError("ERR_ORDER_CONTAINS_RESTRICTED_PART")

    # band 7
    if order["fulfillment_status"] != "PENDING_DISCLOSURE":
        raise ApiError("ERR_INVALID_STATE_TRANSITION")
    if published_revision(order["model_id"], "DISASSEMBLY_GUIDE") is None:
        raise ApiError("ERR_INVALID_STATE_TRANSITION",
                       "No published DISASSEMBLY_GUIDE exists for this model.")
    if order["buyer_class"] == "AUTHORIZED_PROVIDER":
        provider = db.db.providers.get(order.get("provider_id"))
        if provider is None or provider.get("authorization_status") != "AUTHORIZED":
            raise ApiError("ERR_PROVIDER_NOT_AUTHORIZED")

    at = db.now()
    for line in lines:
        if select_compat(line["part_id"], order["model_id"], at) is None:
            raise ApiError("ERR_PART_NOT_PUBLISHED")

    # band 8
    _check_not_restricted(order)
    if order.get("disclosure_acknowledged_at") is None:
        raise ApiError("ERR_DISCLOSURE_NOT_ACKNOWLEDGED")
    acceptable = _acceptable_scopes(order)
    covered = any(
        a["order_id"] == order["id"] and a["acknowledged_scope"] in acceptable
        for a in db.db.acks.all()
    )
    if not covered:
        raise ApiError("ERR_DISCLOSURE_NOT_ACKNOWLEDGED",
                       "No acknowledgment covers this order's contents.")

    # band 9
    assessment = _order_assessment(order)
    if assessment is not None and assessment.get("expires_at") is not None \
            and assessment["expires_at"] < at:
        raise ApiError("ERR_ASSESSMENT_EXPIRED")
    obligation = obligation_for(order["model_id"], order["region_code"])
    if obligation is not None and obligation.get("parts_available_until") is not None \
            and at > obligation["parts_available_until"]:
        raise ApiError("ERR_PARTS_WINDOW_ELAPSED")

    setf(order, "fulfillment_status", "CONFIRMED")
    setf(order, "confirmed_at", at)

    needs_core = False
    for line in lines:
        part = db.db.parts.get(line["part_id"])
        if part is not None and part.get("core_return_required"):
            needs_core = True
            break
    if needs_core:
        setf(order, "core_return_status", "PENDING_CORE")
        setf(order, "core_return_due_at", at + days(CORE_DUE_DAYS))
        commit_core_liability(order)

    touch(order)
    return ok(order_json(order))


@bp.post("/parts-orders/<order_id>/deliver")
@endpoint([PROGRAM_ADMIN])
def deliver_order(order_id):
    body = read_body([F("delivered_at", "datetime")])
    order = get_order(order_id)

    if order["fulfillment_status"] != "CONFIRMED":
        raise ApiError("ERR_INVALID_STATE_TRANSITION")

    at = body["delivered_at"] if body["delivered_at"] is not None else db.now()
    setf(order, "fulfillment_status", "DELIVERED")
    setf(order, "delivered_at", at)

    for line in order_lines(order["id"]):
        part = db.db.parts.get(line["part_id"])
        if part is None:
            continue
        if part.get("requires_authentication"):
            setf(line, "authentication_status", "PENDING_AUTHENTICATION")
            setf(line, "pairing_token", new_token())
        if part.get("requires_calibration"):
            setf(line, "calibration_status", "CALIBRATION_REQUIRED")

    rollup_closure(order)
    touch(order)
    return ok(order_json(order))


@bp.post("/parts-orders/<order_id>/cancel")
@endpoint([SELF_REPAIR_CUSTOMER, REPAIR_PROVIDER_TECH, PROGRAM_ADMIN])
def cancel_order(order_id):
    body = read_body([F("cancellation_reason", "string")])
    order = get_order(order_id)
    _caller_scope(order)

    if order["fulfillment_status"] not in (
        "DRAFT", "PENDING_DISCLOSURE", "BLOCKED_SAFETY_HOLD", "CONFIRMED"
    ):
        raise ApiError("ERR_INVALID_STATE_TRANSITION")
    if order["fulfillment_status"] == "CONFIRMED" \
            and order["core_return_status"] not in ("NOT_REQUIRED", "PENDING_CORE"):
        raise ApiError("ERR_CORE_LEDGER_INVARIANT")

    setf(order, "cancellation_reason", body["cancellation_reason"])
    if order["core_return_status"] == "PENDING_CORE":
        release_core_liability(order)
        setf(order, "core_return_due_at", None)
    setf(order, "fulfillment_status", "CANCELLED")
    touch(order)
    return ok(order_json(order))


@bp.post("/parts-orders/<order_id>/core-returns")
@endpoint([PROGRAM_ADMIN])
def book_core_return(order_id):
    body = read_body([
        F("core_condition", "enum", required=True, enum=CORE_CONDITIONS),
        F("received_at", "datetime", required=True),
    ])
    order = get_order(order_id)

    if order["core_return_status"] == "NOT_REQUIRED":
        raise ApiError("ERR_INVALID_STATE_TRANSITION")
    if order["core_return_status"] == "PENDING_CORE" \
            and order["fulfillment_status"] != "DELIVERED":
        raise ApiError("ERR_INVALID_STATE_TRANSITION")

    at = db.now()
    received_at = body["received_at"]
    confirmed_at = order.get("confirmed_at")
    if (confirmed_at is not None and received_at < confirmed_at) or received_at > at:
        raise ApiError("ERR_CORE_RECEIPT_BEFORE_CONFIRM")

    if order["core_return_status"] != "PENDING_CORE":
        # Declared but guarded: the face value has already left the outstanding total.
        raise ApiError("ERR_CORE_LEDGER_INVARIANT")

    setf(order, "core_return_status", "CORE_RECEIVED")
    settle_core(order, body["core_condition"], received_at)
    rollup_closure(order)
    touch(order)
    return ok(order_json(order))


# --------------------------------------------------------------------------
# per-line service steps
# --------------------------------------------------------------------------

@bp.post("/parts-orders/<order_id>/lines/<line_id>/authenticate")
@endpoint([PROGRAM_ADMIN, REPAIR_PROVIDER_TECH, SELF_REPAIR_CUSTOMER])
def authenticate_line(order_id, line_id):
    body = read_body([F("pairing_token", "string", required=True)])
    order = get_order(order_id)
    line = get_line(line_id, order_id=order["id"])
    _caller_scope(order)

    part = db.db.parts.get(line["part_id"])
    if part is None or not part.get("requires_authentication"):
        raise ApiError("ERR_AUTHENTICATION_NOT_APPLICABLE")

    if order["fulfillment_status"] != "DELIVERED" \
            or line["authentication_status"] != "PENDING_AUTHENTICATION":
        raise ApiError("ERR_INVALID_STATE_TRANSITION")

    if body["pairing_token"] == line.get("pairing_token"):
        setf(line, "authentication_status", "AUTHENTIC")
    else:
        setf(line, "authentication_status", "COUNTERFEIT_SUSPECT")
        if line["calibration_status"] != "NOT_REQUIRED":
            setf(line, "calibration_status", "CALIBRATION_ESCALATED")

    rollup_closure(order)
    return ok(line_json(line))


@bp.post("/parts-orders/<order_id>/lines/<line_id>/calibrate")
@endpoint([PROGRAM_ADMIN, REPAIR_PROVIDER_TECH, SELF_REPAIR_CUSTOMER])
def calibrate_line(order_id, line_id):
    body = read_body([F("measured_offset_ppm", "number", required=True)])
    int_range(body["measured_offset_ppm"], "measured_offset_ppm", -100000, 100000)

    order = get_order(order_id)
    line = get_line(line_id, order_id=order["id"])
    _caller_scope(order)

    part = db.db.parts.get(line["part_id"])

    # band 6
    if part is not None and part.get("requires_authentication") \
            and line["authentication_status"] != "AUTHENTIC":
        raise ApiError("ERR_AUTHENTICATION_REQUIRED_FIRST")
    if line["calibration_status"] == "CALIBRATION_ESCALATED" \
            or line.get("calibration_attempt_count", 0) >= CALIBRATION_ATTEMPT_CAP:
        raise ApiError("ERR_CALIBRATION_ATTEMPTS_EXHAUSTED")

    # band 7
    if order["fulfillment_status"] != "DELIVERED":
        raise ApiError("ERR_INVALID_STATE_TRANSITION")
    if line["calibration_status"] not in ("CALIBRATION_REQUIRED", "CALIBRATION_FAILED"):
        raise ApiError("ERR_INVALID_STATE_TRANSITION")
    if published_revision(order["model_id"], "CALIBRATION_PROCEDURE") is None:
        raise ApiError("ERR_NO_PUBLISHED_CALIBRATION_PROCEDURE")

    offset = body["measured_offset_ppm"]
    line["calibration_attempt_count"] = line.get("calibration_attempt_count", 0) + 1
    setf(line, "last_measured_offset_ppm", offset)
    setf(line, "calibration_status", "CALIBRATION_IN_PROGRESS")
    touch(line)

    if abs(offset) <= CALIBRATION_TOLERANCE_PPM:
        setf(line, "calibration_status", "CALIBRATION_PASSED")
    elif line["calibration_attempt_count"] < CALIBRATION_ATTEMPT_CAP:
        setf(line, "calibration_status", "CALIBRATION_FAILED")
    else:
        setf(line, "calibration_status", "CALIBRATION_ESCALATED")

    rollup_closure(order)
    return ok(line_json(line))
