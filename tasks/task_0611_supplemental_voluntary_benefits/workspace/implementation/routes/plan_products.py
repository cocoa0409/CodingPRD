"""PlanProduct and BenefitScheduleItem endpoints (PRD §3.2).

PlanProduct lifecycle: DRAFT -> OPEN -> CLOSED.
Schedule lines may be added only while the product is DRAFT.
"""

from flask import Blueprint, request

import errors
import serializers
import services
from db import db
from middleware import require_roles
from response import success, list_success
from validation import (
    get_json_body, require_str, require_int, optional_int, optional_bool,
    require_enum, parse_pagination, paginate,
)

bp = Blueprint("plan_products", __name__)

POLICY_TYPES = {"ACCIDENT", "CRITICAL_ILLNESS", "HOSPITAL_INDEMNITY"}


# --------------------------------------------------------------------------- #
# PlanProduct                                                                  #
# --------------------------------------------------------------------------- #

@bp.route("/benefits/plan-products", methods=["POST"])
@require_roles("BenefitsAdmin")
def create_plan_product():
    body = get_json_body()
    employer_id = require_str(body, "employer_id")
    policy_type = require_enum(body, "policy_type", POLICY_TYPES)
    product_name = require_str(body, "product_name")
    weekly_premium_cents = require_int(body, "weekly_premium_cents", minimum=0)
    annual_benefit_cap_cents = require_int(body, "annual_benefit_cap_cents", minimum=0)
    eoi_surcharge_bps = optional_int(body, "eoi_surcharge_bps", default=0, minimum=0)
    portability_loadup_bps = optional_int(body, "portability_loadup_bps", default=1000, minimum=0)

    # Existence (priority 3)
    if services.find_employer(employer_id) is None:
        raise errors.not_found("Employer not found")

    record = {
        "employer_id": employer_id,
        "policy_type": policy_type,
        "product_name": product_name,
        "weekly_premium_cents": weekly_premium_cents,
        "eoi_surcharge_bps": eoi_surcharge_bps,
        "annual_benefit_cap_cents": annual_benefit_cap_cents,
        "portability_loadup_bps": portability_loadup_bps,
        "status": "DRAFT",
    }
    with db.lock:
        db.plan_products.insert(record)
    return success(serializers.plan_product(record), 201)


@bp.route("/benefits/plan-products", methods=["GET"])
@require_roles("BenefitsAdmin", "ClaimsAdjuster", "Employee")
def list_plan_products():
    limit, offset = parse_pagination()
    employer_id = request.args.get("employer_id")
    policy_type = request.args.get("policy_type")
    status = request.args.get("status")

    items = db.plan_products.all()
    if employer_id is not None:
        items = [p for p in items if p["employer_id"] == employer_id]
    if policy_type is not None:
        items = [p for p in items if p["policy_type"] == policy_type]
    if status is not None:
        items = [p for p in items if p["status"] == status]

    page, total = paginate(items, limit, offset)
    return list_success([serializers.plan_product(p) for p in page], limit, offset, total)


@bp.route("/benefits/plan-products/<plan_product_id>", methods=["GET"])
@require_roles("BenefitsAdmin", "ClaimsAdjuster", "Employee")
def get_plan_product(plan_product_id):
    record = db.plan_products.get(plan_product_id)
    if record is None:
        raise errors.not_found("Plan product not found")
    return success(serializers.plan_product(record), 200)


@bp.route("/benefits/plan-products/<plan_product_id>/open", methods=["POST"])
@require_roles("BenefitsAdmin")
def open_plan_product(plan_product_id):
    record = db.plan_products.get(plan_product_id)
    if record is None:
        raise errors.not_found("Plan product not found")
    with db.lock:
        # State precedence: must be DRAFT (priority 5) before the schedule check.
        if record["status"] != "DRAFT":
            raise errors.invalid_state("Plan product must be DRAFT to open")
        if not services.schedule_items_for_product(plan_product_id):
            raise errors.schedule_empty("Plan product has no benefit-schedule item")
        record["status"] = "OPEN"
        db.plan_products.touch(record)
    return success(serializers.plan_product(record), 200)


@bp.route("/benefits/plan-products/<plan_product_id>/close", methods=["POST"])
@require_roles("BenefitsAdmin")
def close_plan_product(plan_product_id):
    record = db.plan_products.get(plan_product_id)
    if record is None:
        raise errors.not_found("Plan product not found")
    with db.lock:
        if record["status"] != "OPEN":
            raise errors.invalid_state("Plan product must be OPEN to close")
        record["status"] = "CLOSED"
        db.plan_products.touch(record)
    return success(serializers.plan_product(record), 200)


# --------------------------------------------------------------------------- #
# BenefitScheduleItem                                                          #
# --------------------------------------------------------------------------- #

@bp.route("/benefits/schedule-items", methods=["POST"])
@require_roles("BenefitsAdmin")
def create_schedule_item():
    body = get_json_body()
    plan_product_id = require_str(body, "plan_product_id")
    event_code = require_str(body, "event_code")
    flat_benefit_cents = require_int(body, "flat_benefit_cents", minimum=0)
    lifetime_max_occurrences = optional_int(body, "lifetime_max_occurrences", default=0, minimum=0)
    is_wellness = optional_bool(body, "is_wellness", default=False)

    product = services.find_plan_product(plan_product_id)
    if product is None:
        raise errors.not_found("Plan product not found")

    with db.lock:
        # Schedule lines may be added only while DRAFT (PRD §3.2).
        if product["status"] != "DRAFT":
            raise errors.invalid_state("Schedule items may be added only to a DRAFT product")
        # event_code unique per product (PRD §3.2).
        if services.schedule_item_for_event(plan_product_id, event_code) is not None:
            raise errors.duplicate_schedule_event("event_code already exists on this product")

        record = {
            "plan_product_id": plan_product_id,
            "event_code": event_code,
            "flat_benefit_cents": flat_benefit_cents,
            "lifetime_max_occurrences": lifetime_max_occurrences,
            "is_wellness": is_wellness,
        }
        # Immutable entity: only id + created_at (PRD §2.4).
        db.schedule_items.insert(record, with_version=False)
    return success(serializers.schedule_item(record), 201)


@bp.route("/benefits/schedule-items", methods=["GET"])
@require_roles("BenefitsAdmin", "ClaimsAdjuster", "Employee")
def list_schedule_items():
    limit, offset = parse_pagination()
    plan_product_id = request.args.get("plan_product_id")
    event_code = request.args.get("event_code")

    items = db.schedule_items.all()
    if plan_product_id is not None:
        items = [s for s in items if s["plan_product_id"] == plan_product_id]
    if event_code is not None:
        items = [s for s in items if s["event_code"] == event_code]

    page, total = paginate(items, limit, offset)
    return list_success([serializers.schedule_item(s) for s in page], limit, offset, total)


@bp.route("/benefits/schedule-items/<schedule_item_id>", methods=["GET"])
@require_roles("BenefitsAdmin", "ClaimsAdjuster", "Employee")
def get_schedule_item(schedule_item_id):
    record = db.schedule_items.get(schedule_item_id)
    if record is None:
        raise errors.not_found("Schedule item not found")
    return success(serializers.schedule_item(record), 200)
