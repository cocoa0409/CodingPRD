"""Pump orders, prior authorizations, shipments, claims, resupply schedules,
resupply orders, warranty claims."""
from flask import Blueprint

from db import store, now_iso, today, next_seq
from errors import ApiError
from response import ok
from middleware import (
    authorize, check_ownership, body, get_or_404, req_str, opt_str, req_int,
    req_enum, parse_date, paginate, filter_query, scope_member_list, public,
    ALL_ROLES,
)
from services import (
    create_entity, bump, order_lines, primary_line, recompute_pricing,
    garment_qty, compute_next_eligible, recompute_member_aggregates,
    add_months, adjudication_waterfall, rhu,
    MAX_WARRANTY_REPLACEMENTS, MAX_REOPENS,
)
from decimal import Decimal

bp = Blueprint("ops", __name__, url_prefix="/dme")

PA_DECISIONS = ["APPROVED", "DENIED", "PENDED"]
SHIPMENT_STATUSES = [
    "LABEL_CREATED", "IN_TRANSIT", "OUT_FOR_DELIVERY", "DELIVERED", "RETURNED", "LOST",
]
CLAIM_OUTCOMES = ["APPROVED", "DENIED"]
WARRANTY_ISSUES = [
    "MOTOR_FAILURE", "BATTERY_FAILURE", "SUCTION_LOSS", "PHYSICAL_DAMAGE", "OTHER",
]
WARRANTY_DECISIONS = ["APPROVED_REPAIR", "APPROVED_REPLACE", "DENIED"]
SCHEDULE_PATCH_STATUSES = ["ACTIVE", "SUSPENDED"]

READ_ORDER_ROLES = ALL_ROLES
LINE_READ_ROLES = ["Member", "CareCoordinator", "InsuranceSpecialist", "BillingSpecialist", "PlatformAdmin"]
PA_READ_ROLES = ["Member", "CareCoordinator", "InsuranceSpecialist", "BillingSpecialist", "PlatformAdmin"]
SHIPMENT_READ_ROLES = ["Member", "CareCoordinator", "WarehouseOperator", "InsuranceSpecialist", "PlatformAdmin"]
CLAIM_READ_ROLES = ["Member", "InsuranceSpecialist", "BillingSpecialist", "PlatformAdmin"]
SCHEDULE_READ_ROLES = ["Member", "CareCoordinator", "PlatformAdmin"]
RESUPPLY_READ_ROLES = ["Member", "CareCoordinator", "WarehouseOperator", "PlatformAdmin"]
WARRANTY_READ_ROLES = ["Member", "CareCoordinator", "PlatformAdmin"]


def _check_fk(b, key, collection, error_id):
    """Pipeline priority 4: a present FK must resolve; runs before shape checks."""
    if isinstance(b.get(key), str):
        get_or_404(collection, b[key], error_id)


def _check_polymorphic(b, a, b_key):
    va, vb = b.get(a), b.get(b_key)
    for v in (va, vb):
        if v is not None and not isinstance(v, str):
            raise ApiError("ERR_VALIDATION", "Polymorphic reference must be a string id", 400)
    if (va is None) == (vb is None):
        raise ApiError(
            "ERR_VALIDATION",
            "Exactly one of %s / %s must be set" % (a, b_key),
            400,
        )


# ------------------------------------------------------------ pump orders ----

@bp.route("/pump-orders", methods=["POST"])
def create_pump_order():
    uid, role = authorize(["Member", "CareCoordinator"])
    b = body()
    if role == "Member" and isinstance(b.get("member_id"), str) and b["member_id"] != uid:
        raise ApiError("ERR_OWNERSHIP_VIOLATION", "Members may only order for themselves", 403)
    _check_fk(b, "member_id", store.members, "ERR_MEMBER_NOT_FOUND")
    _check_fk(b, "policy_id", store.policies, "ERR_POLICY_NOT_FOUND")
    _check_fk(b, "prescription_id", store.prescriptions, "ERR_PRESCRIPTION_NOT_FOUND")
    _check_fk(b, "pump_item_id", store.catalog_items, "ERR_CATALOG_ITEM_NOT_FOUND")
    member_id = req_str(b, "member_id")
    policy_id = req_str(b, "policy_id")
    prescription_id = req_str(b, "prescription_id")
    pump_item_id = req_str(b, "pump_item_id")
    shipping_address = req_str(b, "shipping_address")
    policy = store.policies[policy_id]
    rx = store.prescriptions[prescription_id]
    item = store.catalog_items[pump_item_id]
    if policy["status"] != "ACTIVE":
        raise ApiError("ERR_POLICY_NOT_ACTIVE", "Policy is not ACTIVE", 409)
    if not (parse_date(policy["benefit_period_start"]) <= today() < parse_date(policy["benefit_period_end"])):
        raise ApiError("ERR_BENEFIT_PERIOD_ENDED", "Current date is outside the benefit period", 422)
    if rx["pump_type"] != item["pump_type"]:
        raise ApiError("ERR_PUMP_TYPE_MISMATCH", "Prescription pump_type does not match the pump item", 422)
    order = create_entity(store.pump_orders, {
        "member_id": member_id,
        "policy_id": policy_id,
        "prescription_id": prescription_id,
        "pump_item_id": pump_item_id,
        "shipping_address": shipping_address,
        "fulfillment_status": "PENDING_QUALIFICATION",
        "billing_status": "UNBILLED",
        "prior_auth_required": False,
        "provisional_allowed_cents": 0,
        "provisional_patient_cents": 0,
        "upgrade_fee_cents": 0,
        "merchandise_subtotal_cents": 0,
        "discount_total_cents": 0,
        "order_total_cents": 0,
        "delivery_date": None,
        "replacement_count": 0,
        "warranty_blocked": False,
    })
    create_entity(store.order_lines, {
        "order_id": order["id"],
        "catalog_item_id": pump_item_id,
        "line_type": "PUMP_PRIMARY",
        "quantity": 1,
        "unit_price_cents": item["unit_price_cents"],
        "line_total_cents": 0,
        "discount_cents": 0,
    })
    recompute_pricing(order)
    return ok(public(order), 201)


@bp.route("/pump-orders/<oid>", methods=["GET"])
def get_pump_order(oid):
    uid, role = authorize(READ_ORDER_ROLES)
    order = get_or_404(store.pump_orders, oid, "ERR_ORDER_NOT_FOUND")
    check_ownership(role, uid, order["member_id"])
    return ok(public(order))


@bp.route("/pump-orders", methods=["GET"])
def list_pump_orders():
    uid, role = authorize(READ_ORDER_ROLES)
    items = scope_member_list(store.pump_orders.values(), role, uid)
    items = filter_query(items, {
        "member_id": "member_id",
        "policy_id": "policy_id",
        "prescription_id": "prescription_id",
        "pump_item_id": "pump_item_id",
        "fulfillment_status": "fulfillment_status",
        "billing_status": "billing_status",
    })
    return paginate(items)


@bp.route("/pump-orders/<oid>", methods=["PATCH"])
def patch_pump_order(oid):
    uid, role = authorize(["Member", "CareCoordinator"])
    order = get_or_404(store.pump_orders, oid, "ERR_ORDER_NOT_FOUND")
    check_ownership(role, uid, order["member_id"])
    b = body()
    new_item = None
    if isinstance(b.get("pump_item_id"), str):
        new_item = get_or_404(store.catalog_items, b["pump_item_id"], "ERR_CATALOG_ITEM_NOT_FOUND")
    elif b.get("pump_item_id") is not None:
        raise ApiError("ERR_VALIDATION", "pump_item_id must be a string id", 400)
    ver = b.get("expected_pump_order_version")
    if isinstance(ver, bool) or not isinstance(ver, int):
        raise ApiError("ERR_VALIDATION", "expected_pump_order_version is required", 400)
    if "shipping_address" in b and not isinstance(b["shipping_address"], str):
        raise ApiError("ERR_VALIDATION", "shipping_address must be a string", 400)
    if ver != order["version"]:
        raise ApiError("ERR_STALE_VERSION", "PumpOrder version has advanced", 412)
    if order["fulfillment_status"] != "PENDING_QUALIFICATION":
        raise ApiError("ERR_INVALID_STATE", "Order is not PENDING_QUALIFICATION", 409)
    if new_item is not None and new_item["id"] != order["pump_item_id"]:
        rx = store.prescriptions[order["prescription_id"]]
        policy = store.policies[order["policy_id"]]
        if new_item["pump_type"] != rx["pump_type"]:
            raise ApiError("ERR_PUMP_TYPE_MISMATCH", "Prescription pump_type does not match the pump item", 422)
        if new_item["insurance_tier"] == "UPGRADE" and not policy["upgrade_coverage"]:
            raise ApiError("ERR_UPGRADE_TIER_NOT_COVERED", "UPGRADE tier is not covered by this policy", 422)
        order["pump_item_id"] = new_item["id"]
        pl = primary_line(order["id"])
        pl["catalog_item_id"] = new_item["id"]
        pl["unit_price_cents"] = new_item["unit_price_cents"]
    if "shipping_address" in b:
        order["shipping_address"] = b["shipping_address"]
    recompute_pricing(order)
    bump(order)
    return ok(public(order))


@bp.route("/pump-orders/<oid>/qualify", methods=["POST"])
def qualify_pump_order(oid):
    authorize(["InsuranceSpecialist"])
    order = get_or_404(store.pump_orders, oid, "ERR_ORDER_NOT_FOUND")
    policy = store.policies[order["policy_id"]]
    rx = store.prescriptions[order["prescription_id"]]
    item = store.catalog_items[order["pump_item_id"]]
    # state (priority 6)
    if order["fulfillment_status"] != "PENDING_QUALIFICATION":
        raise ApiError("ERR_INVALID_STATE", "Order is not PENDING_QUALIFICATION", 409)
    if policy["status"] != "ACTIVE":
        raise ApiError("ERR_POLICY_NOT_ACTIVE", "Policy is not ACTIVE", 409)
    if rx["status"] != "VERIFIED":
        raise ApiError("ERR_PRESCRIPTION_NOT_VERIFIED", "Prescription is not VERIFIED", 409)
    # temporal (priority 8)
    if not (parse_date(policy["benefit_period_start"]) <= today() < parse_date(policy["benefit_period_end"])):
        raise ApiError("ERR_BENEFIT_PERIOD_ENDED", "Current date is outside the benefit period", 422)
    if today() > parse_date(rx["expiration_date"]):
        rx["status"] = "EXPIRED"
        bump(rx)
        raise ApiError("ERR_PRESCRIPTION_EXPIRED", "Prescription has expired", 422)
    # business (priority 9)
    if rx["pump_type"] != item["pump_type"]:
        raise ApiError("ERR_PUMP_TYPE_MISMATCH", "Prescription pump_type does not match the pump item", 422)
    # fiscal (priority 10)
    if policy["pumps_consumed_count"] >= policy["pump_allowance_per_period"]:
        raise ApiError("ERR_PUMP_ALLOWANCE_EXHAUSTED", "Pump allowance exhausted", 422)
    if item["insurance_tier"] == "UPGRADE" and not policy["upgrade_coverage"]:
        raise ApiError("ERR_UPGRADE_TIER_NOT_COVERED", "UPGRADE tier is not covered by this policy", 422)
    # provisional_patient_responsibility
    base_allowed = item["unit_price_cents"] - item["upgrade_fee_cents"]
    ded_remaining = max(0, policy["deductible_cents"] - policy["deductible_met_cents"])
    ded_applied = min(base_allowed, ded_remaining)
    coins = rhu(Decimal(base_allowed - ded_applied) * Decimal(str(policy["coinsurance_pct"])))
    order["provisional_allowed_cents"] = item["unit_price_cents"]
    order["provisional_patient_cents"] = ded_applied + coins + item["upgrade_fee_cents"]
    order["upgrade_fee_cents"] = item["upgrade_fee_cents"]
    # prior_auth_requirement (threshold comparison is inclusive)
    order["prior_auth_required"] = bool(
        policy["requires_prior_auth"]
        or order["provisional_allowed_cents"] >= policy["prior_auth_threshold_cents"]
    )
    order["fulfillment_status"] = "QUALIFIED"
    policy["pumps_consumed_count"] += 1
    policy["garments_consumed_count"] += garment_qty(order)
    bump(policy)
    rx["status"] = "CONSUMED"
    rx["consumed_by_order_id"] = order["id"]
    bump(rx)
    bump(order)
    return ok(public(order))


@bp.route("/pump-orders/<oid>/cancel", methods=["POST"])
def cancel_pump_order(oid):
    uid, role = authorize(["Member", "CareCoordinator"])
    order = get_or_404(store.pump_orders, oid, "ERR_ORDER_NOT_FOUND")
    check_ownership(role, uid, order["member_id"])
    if order["fulfillment_status"] not in ("PENDING_QUALIFICATION", "QUALIFIED"):
        raise ApiError("ERR_INVALID_STATE", "Order can no longer be cancelled", 409)
    if order["fulfillment_status"] == "QUALIFIED":
        policy = store.policies[order["policy_id"]]
        policy["pumps_consumed_count"] -= 1
        policy["garments_consumed_count"] -= garment_qty(order)
        bump(policy)
        rx = store.prescriptions[order["prescription_id"]]
        if rx["status"] == "CONSUMED" and rx["consumed_by_order_id"] == order["id"]:
            rx["status"] = "VERIFIED"
            rx["consumed_by_order_id"] = None
            bump(rx)
        for pa in store.prior_auths.values():
            if pa["pump_order_id"] == order["id"] and pa["status"] in ("SUBMITTED", "PENDED"):
                pa["status"] = "WITHDRAWN"
                bump(pa)
    order["fulfillment_status"] = "CANCELLED"
    bump(order)
    return ok(public(order))


@bp.route("/pump-orders/<oid>/lines", methods=["POST"])
def add_order_line(oid):
    uid, role = authorize(["Member", "CareCoordinator"])
    order = get_or_404(store.pump_orders, oid, "ERR_ORDER_NOT_FOUND")
    check_ownership(role, uid, order["member_id"])
    b = body()
    _check_fk(b, "catalog_item_id", store.catalog_items, "ERR_CATALOG_ITEM_NOT_FOUND")
    catalog_item_id = req_str(b, "catalog_item_id")
    quantity = req_int(b, "quantity")
    if quantity < 1:
        raise ApiError("ERR_VALIDATION", "quantity must be at least 1", 400)
    item = store.catalog_items[catalog_item_id]
    if order["fulfillment_status"] != "PENDING_QUALIFICATION":
        raise ApiError("ERR_INVALID_STATE", "Order is not PENDING_QUALIFICATION", 409)
    if item["item_type"] != "COMPRESSION_GARMENT":
        raise ApiError("ERR_INVALID_ITEM_TYPE", "Add-on lines must be COMPRESSION_GARMENT items", 422)
    policy = store.policies[order["policy_id"]]
    projected = policy["garments_consumed_count"] + garment_qty(order) + quantity
    if projected > policy["garment_allowance_per_period"]:
        raise ApiError("ERR_GARMENT_ALLOWANCE_EXCEEDED", "Garment allowance would be exceeded", 422)
    line = create_entity(store.order_lines, {
        "order_id": order["id"],
        "catalog_item_id": catalog_item_id,
        "line_type": "ADDON_GARMENT",
        "quantity": quantity,
        "unit_price_cents": item["unit_price_cents"],
        "line_total_cents": 0,
        "discount_cents": 0,
    })
    recompute_pricing(order)
    bump(order)
    return ok(public(line), 201)


@bp.route("/pump-orders/<oid>/lines", methods=["GET"])
def list_order_lines(oid):
    uid, role = authorize(LINE_READ_ROLES)
    order = get_or_404(store.pump_orders, oid, "ERR_ORDER_NOT_FOUND")
    check_ownership(role, uid, order["member_id"])
    return paginate(order_lines(order["id"]))
