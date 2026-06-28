"""Quote-assembly child routes: event-profiles, coverages, riders.

(PRD §3.2, §3.3; scaffold §1.5)
"""
from flask import Blueprint

from clock import clock
from db import db, new_common
from errors import err
from middleware import get_user_context, require_role
from response import success, list_success
from serializers import public
from services.lookups import (
    children_by_policy,
    get_coverage,
    get_policy,
    get_vendor,
)
from timeutil import fmt, parse_iso
from validators import (
    get_body,
    get_pagination,
    opt_str,
    query_str,
    req_enum,
    req_int,
    req_str,
)

bp = Blueprint("quote_items", __name__)

RIDER_TYPES = {"RINGS", "ATTIRE", "GIFTS", "SPECIAL_PROPERTY"}


def _paginate(items):
    limit, offset = get_pagination()
    total = len(items)
    page = items[offset:offset + limit]
    return [public(x) for x in page], limit, offset, total


# ---- EventProfile (PRD §3.2) -----------------------------------------------
@bp.route("/policies/<policy_id>/event-profiles", methods=["POST"])
def add_event_profile(policy_id):
    _, role = get_user_context()
    require_role(role, {"Policyholder"})
    policy = get_policy(policy_id)
    body = get_body()

    event_name = req_str(body, "event_name")
    venue_vendor_id = req_str(body, "venue_vendor_id")
    expected_attendance = req_int(body, "expected_attendance", minimum=1)
    event_start_at = parse_iso(req_str(body, "event_start_at"))
    event_end_at = parse_iso(req_str(body, "event_end_at"))

    # Body FK resolution (priority 5).
    vendor = db.vendors.get(venue_vendor_id)
    if vendor is None:
        raise err("ERR_REFERENCE_NOT_FOUND", "venue_vendor_id does not resolve")

    # Business-referential: referenced vendor category must be VENUE (priority 6).
    if vendor["category"] != "VENUE":
        raise err("ERR_VENUE_VENDOR_REQUIRED", "venue_vendor_id must reference a VENUE vendor")

    # Single-event constraint (priority 9).
    if policy["policy_form"] == "SINGLE_EVENT":
        existing = children_by_policy(db.event_profiles, policy_id)
        if len(existing) >= 1:
            raise err("ERR_SINGLE_EVENT_MULTIPLE_PROFILES", "SINGLE_EVENT policy may have at most one event profile")

    # Event window coherence (priority 10).
    policy_created = policy["_created_dt"]
    if not (event_end_at > event_start_at) or not (event_start_at > policy_created):
        raise err("ERR_INVALID_EVENT_WINDOW", "event window is incoherent")

    profile = new_common()
    profile.update({
        "policy_id": policy_id,
        "event_name": event_name,
        "venue_vendor_id": venue_vendor_id,
        "expected_attendance": expected_attendance,
        "event_start_at": fmt(event_start_at),
        "event_end_at": fmt(event_end_at),
        "_event_start_dt": event_start_at,
        "_event_end_dt": event_end_at,
    })
    db.event_profiles[profile["id"]] = profile
    return success(public(profile), status=201)


@bp.route("/policies/<policy_id>/event-profiles", methods=["GET"])
def list_event_profiles(policy_id):
    _, role = get_user_context()
    require_role(role, {"PlatformAdmin", "UnderwritingAgent", "Policyholder", "ClaimsAdjuster"})
    get_policy(policy_id)
    items = children_by_policy(db.event_profiles, policy_id)
    data, limit, offset, total = _paginate(items)
    return list_success(data, limit, offset, total)


# ---- Coverage (PRD §3.3) ---------------------------------------------------
@bp.route("/policies/<policy_id>/coverages", methods=["POST"])
def add_coverage(policy_id):
    _, role = get_user_context()
    require_role(role, {"Policyholder", "UnderwritingAgent"})
    policy = get_policy(policy_id)
    body = get_body()

    coverage_product_id = req_str(body, "coverage_product_id")
    protected_vendor_id = opt_str(body, "protected_vendor_id")

    # Body FK resolution (priority 5).
    product = db.coverage_products.get(coverage_product_id)
    if product is None:
        raise err("ERR_REFERENCE_NOT_FOUND", "coverage_product_id does not resolve")
    if protected_vendor_id is not None and protected_vendor_id not in db.vendors:
        raise err("ERR_REFERENCE_NOT_FOUND", "protected_vendor_id does not resolve")

    # Business-referential: protected_vendor only on CANCELLATION (priority 7).
    if protected_vendor_id is not None and product["coverage_type"] != "CANCELLATION":
        raise err("ERR_PROTECTED_VENDOR_NOT_ALLOWED", "protected_vendor_id only allowed on CANCELLATION coverage")

    # RETIRED product cannot be added (priority 12).
    if product["status"] == "RETIRED":
        raise err("ERR_PRODUCT_RETIRED", "coverage product is RETIRED")

    # LIQUOR_LIABILITY requires serves_alcohol (priority 11).
    if product["coverage_type"] == "LIQUOR_LIABILITY" and not policy["serves_alcohol"]:
        raise err("ERR_LIQUOR_REQUIRES_ALCOHOL", "LIQUOR_LIABILITY requires serves_alcohol == true")

    # At most one coverage per (coverage_type, tier) (priority 13).
    for existing in children_by_policy(db.coverages, policy_id):
        ep = db.coverage_products[existing["coverage_product_id"]]
        if ep["coverage_type"] == product["coverage_type"] and ep["tier"] == product["tier"]:
            raise err("ERR_DUPLICATE_COVERAGE", "policy already holds this (coverage_type, tier)")

    coverage = new_common()
    coverage.update({
        "policy_id": policy_id,
        "coverage_product_id": coverage_product_id,
        "protected_vendor_id": protected_vendor_id,
        "rated_premium_cents": 0,
        "consumed_limit_cents": 0,
        "status": "SELECTED",
    })
    db.coverages[coverage["id"]] = coverage
    return success(public(coverage), status=201)


@bp.route("/policies/<policy_id>/coverages", methods=["GET"])
def list_coverages(policy_id):
    _, role = get_user_context()
    require_role(role, {"PlatformAdmin", "UnderwritingAgent", "Policyholder", "ClaimsAdjuster"})
    get_policy(policy_id)
    f_status = query_str("status")
    items = children_by_policy(db.coverages, policy_id)
    if f_status is not None:
        items = [c for c in items if c["status"] == f_status]
    data, limit, offset, total = _paginate(items)
    return list_success(data, limit, offset, total)


@bp.route("/policies/<policy_id>/coverages/<coverage_id>", methods=["GET"])
def get_coverage_route(policy_id, coverage_id):
    _, role = get_user_context()
    require_role(role, {"PlatformAdmin", "UnderwritingAgent", "Policyholder", "ClaimsAdjuster"})
    get_policy(policy_id)
    coverage = get_coverage(policy_id, coverage_id)
    return success(public(coverage), status=200)


# ---- Rider (PRD §3.3) ------------------------------------------------------
@bp.route("/policies/<policy_id>/riders", methods=["POST"])
def add_rider(policy_id):
    _, role = get_user_context()
    require_role(role, {"Policyholder", "UnderwritingAgent"})
    get_policy(policy_id)
    body = get_body()

    rider_type = req_enum(body, "rider_type", RIDER_TYPES)
    scheduled_value_cents = req_int(body, "scheduled_value_cents", minimum=1)

    rider = new_common()
    rider.update({
        "policy_id": policy_id,
        "rider_type": rider_type,
        "scheduled_value_cents": scheduled_value_cents,
        "rider_premium_cents": 0,
        "status": "SELECTED",
    })
    db.riders[rider["id"]] = rider
    return success(public(rider), status=201)


@bp.route("/policies/<policy_id>/riders", methods=["GET"])
def list_riders(policy_id):
    _, role = get_user_context()
    require_role(role, {"PlatformAdmin", "UnderwritingAgent", "Policyholder", "ClaimsAdjuster"})
    get_policy(policy_id)
    f_status = query_str("status")
    items = children_by_policy(db.riders, policy_id)
    if f_status is not None:
        items = [r for r in items if r["status"] == f_status]
    data, limit, offset, total = _paginate(items)
    return list_success(data, limit, offset, total)
