"""Policy endpoints: quote (POST /properties/{id}/policies), get, and the
lifecycle transitions bind / expire-quote / activate / cancel / lapse
(PRD §3.4–§3.6).
"""

from flask import Blueprint, g

import errors
from db import db, new_id, now_ts
from clock import clock, format_iso8601_ms, parse_iso8601, add_days, floor_days_between
from middleware import require_roles
from response import success
from serializers import serialize_policy
from helpers import (
    get_body, require_enum, require_number, opt_number, opt_bool, require_int,
)
from services.policy import quote_premium
from services.calculations import (
    prorate_earned, TERM_DAYS, STANDARD_WAITING_DAYS, LENDER_WAITING_DAYS,
)

bp = Blueprint("policies", __name__)

RATING_METHODS = {"RISK_RATING_2_0", "LEGACY_SUBSIDIZED"}
ALLOWED_DEDUCTIBLES = {1000, 2000, 5000, 10000}


def _validate_coverage(building_coverage, contents_coverage,
                       building_deductible, contents_deductible):
    """Coverage caps (PRD §3.4): building in [0,250000], contents in [0,100000],
    deductibles in {1000,2000,5000,10000} -> ERR_COVERAGE_LIMIT_EXCEEDED (422)."""
    if building_coverage < 0 or building_coverage > 250000:
        raise errors.ApiError(errors.ERR_COVERAGE_LIMIT_EXCEEDED, 422,
                              "building_coverage must be in [0,250000]")
    if contents_coverage < 0 or contents_coverage > 100000:
        raise errors.ApiError(errors.ERR_COVERAGE_LIMIT_EXCEEDED, 422,
                              "contents_coverage must be in [0,100000]")
    if building_deductible not in ALLOWED_DEDUCTIBLES:
        raise errors.ApiError(errors.ERR_COVERAGE_LIMIT_EXCEEDED, 422,
                              "building_deductible must be one of 1000,2000,5000,10000")
    if contents_deductible not in ALLOWED_DEDUCTIBLES:
        raise errors.ApiError(errors.ERR_COVERAGE_LIMIT_EXCEEDED, 422,
                              "contents_deductible must be one of 1000,2000,5000,10000")


@bp.route("/properties/<pid>/policies", methods=["POST"])
@require_roles("PolicyHolder", "Underwriter")
def quote_policy(pid):
    body = get_body()

    # Existence (priority 3): property in path must resolve.
    prop = db.properties.get(pid)
    if prop is None:
        raise errors.not_found("Property not found")

    # Ownership (priority 4): a PolicyHolder may only quote on a property they own.
    if g.user_role == "PolicyHolder" and prop["owner_id"] != g.user_id:
        raise errors.not_resource_owner("Not the owner of this property")

    rating_method = require_enum(body, "rating_method", RATING_METHODS)
    building_coverage = require_number(body, "building_coverage")
    contents_coverage = require_number(body, "contents_coverage")
    building_deductible = opt_number(body, "building_deductible", 2000)
    contents_deductible = opt_number(body, "contents_deductible", 1000)
    is_lender_required = opt_bool(body, "is_lender_required", False)

    # Rating-method eligibility (priority 7): LEGACY_SUBSIDIZED requires SFHA.
    if rating_method == "LEGACY_SUBSIDIZED" and not prop["is_sfha"]:
        raise errors.ApiError(errors.ERR_RATING_METHOD_NOT_ELIGIBLE, 422,
                              "LEGACY_SUBSIDIZED is only valid in SFHA zones")

    # Coverage caps (priority 8).
    _validate_coverage(building_coverage, contents_coverage,
                       building_deductible, contents_deductible)

    community = db.communities.get(prop["community_id"])
    # community always exists because Property creation validated community_id.

    ts = now_ts()
    pol_id = new_id()
    record = {
        "id": pol_id,
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
        "property_id": pid,
        "holder_id": prop["owner_id"],
        "rating_method": rating_method,
        "building_coverage": building_coverage,
        "contents_coverage": contents_coverage,
        "building_deductible": building_deductible,
        "contents_deductible": contents_deductible,
        "is_lender_required": is_lender_required,
        "status": "QUOTED",
        "quoted_premium": 0,
        "bind_date": None,
        "effective_date": None,
        "expiration_date": None,
        "earned_premium": 0,
        "premium_credit_balance": 0,
        "total_claims_paid": 0,
        "refund_to_holder": 0,
    }
    record["quoted_premium"] = quote_premium(record, prop, community)
    db.policies[pol_id] = record
    return success(serialize_policy(record), status=201)


@bp.route("/policies/<pid>", methods=["GET"])
@require_roles("PolicyHolder", "Underwriter", "Adjuster", "FemaAdmin")
def get_policy(pid):
    record = db.policies.get(pid)
    if record is None:
        raise errors.not_found("Policy not found")
    if g.user_role == "PolicyHolder" and record["holder_id"] != g.user_id:
        raise errors.not_resource_owner("Not the holder of this policy")
    return success(serialize_policy(record), status=200)


@bp.route("/policies/<pid>/bind", methods=["POST"])
@require_roles("Underwriter")
def bind_policy(pid):
    record = db.policies.get(pid)
    if record is None:
        raise errors.not_found("Policy not found")

    # State (priority 5): only QUOTED -> BOUND.
    if record["status"] != "QUOTED":
        raise errors.invalid_state("Policy must be QUOTED to bind")

    prop = db.properties.get(record["property_id"])
    community = db.communities.get(prop["community_id"])

    # Community participation (priority 6).
    if not community["participating"]:
        raise errors.ApiError(errors.ERR_COMMUNITY_NOT_PARTICIPATING, 409,
                              "Community is not participating in NFIP")

    # Rating-method eligibility re-checked at bind (priority 7).
    if record["rating_method"] == "LEGACY_SUBSIDIZED" and not prop["is_sfha"]:
        raise errors.ApiError(errors.ERR_RATING_METHOD_NOT_ELIGIBLE, 422,
                              "LEGACY_SUBSIDIZED is only valid in SFHA zones")

    now = clock.now()
    waiting_days = LENDER_WAITING_DAYS if record["is_lender_required"] else STANDARD_WAITING_DAYS
    effective = add_days(now, waiting_days)
    expiration = add_days(effective, TERM_DAYS)

    record["status"] = "BOUND"
    record["bind_date"] = format_iso8601_ms(now)
    record["effective_date"] = format_iso8601_ms(effective)
    record["expiration_date"] = format_iso8601_ms(expiration)
    record["version"] += 1
    record["updated_at"] = now_ts()
    return success(serialize_policy(record), status=200)


@bp.route("/policies/<pid>/expire-quote", methods=["POST"])
@require_roles("Underwriter")
def expire_quote(pid):
    record = db.policies.get(pid)
    if record is None:
        raise errors.not_found("Policy not found")
    if record["status"] != "QUOTED":
        raise errors.invalid_state("Policy must be QUOTED to expire the quote")
    record["status"] = "EXPIRED"
    record["version"] += 1
    record["updated_at"] = now_ts()
    return success(serialize_policy(record), status=200)


@bp.route("/policies/<pid>/activate", methods=["POST"])
@require_roles("Underwriter")
def activate_policy(pid):
    record = db.policies.get(pid)
    if record is None:
        raise errors.not_found("Policy not found")

    # State (priority 5): only BOUND -> ACTIVE.
    if record["status"] != "BOUND":
        raise errors.invalid_state("Policy must be BOUND to activate")

    # Waiting period (priority 9): now must be >= effective_date.
    now = clock.now()
    effective = parse_iso8601(record["effective_date"])
    if now < effective:
        raise errors.ApiError(errors.ERR_WAITING_PERIOD_NOT_ELAPSED, 409,
                              "Waiting period has not elapsed")

    record["status"] = "ACTIVE"
    record["version"] += 1
    record["updated_at"] = now_ts()

    prop = db.properties.get(record["property_id"])
    prop["active_policy_id"] = record["id"]
    if prop["is_sfha"] and prop["has_active_mortgage"]:
        prop["compliance_status"] = "COMPLIANT"
    prop["version"] += 1
    prop["updated_at"] = now_ts()

    return success(serialize_policy(record), status=200)


def _clear_property_pointer_and_compliance(prop):
    prop["active_policy_id"] = None
    if prop["is_sfha"] and prop["has_active_mortgage"]:
        prop["compliance_status"] = "LAPSED"
    prop["version"] += 1
    prop["updated_at"] = now_ts()


@bp.route("/policies/<pid>/cancel", methods=["POST"])
@require_roles("Underwriter")
def cancel_policy(pid):
    body = get_body()
    record = db.policies.get(pid)
    if record is None:
        raise errors.not_found("Policy not found")

    # State (priority 5): cancel allowed only from BOUND or ACTIVE.
    if record["status"] not in ("BOUND", "ACTIVE"):
        raise errors.invalid_state("Policy must be BOUND or ACTIVE to cancel")

    # OCC (priority 16): expected_policy_version must match live version.
    expected = require_int(body, "expected_policy_version")
    if expected != record["version"]:
        raise errors.ApiError(errors.ERR_STALE_POLICY_VERSION, 412,
                              "expected_policy_version does not match live version")

    was_active = record["status"] == "ACTIVE"
    if was_active:
        now = clock.now()
        effective = parse_iso8601(record["effective_date"])
        days_elapsed = floor_days_between(effective, now)
        if days_elapsed < 0:
            days_elapsed = 0
        if days_elapsed > TERM_DAYS:
            days_elapsed = TERM_DAYS
        earned, unearned = prorate_earned(record["quoted_premium"], days_elapsed)
        record["earned_premium"] = earned
        record["refund_to_holder"] = unearned
    else:  # BOUND: coverage never began
        record["earned_premium"] = 0
        record["refund_to_holder"] = int(record["quoted_premium"])

    record["status"] = "CANCELLED"
    record["version"] += 1
    record["updated_at"] = now_ts()

    prop = db.properties.get(record["property_id"])
    _clear_property_pointer_and_compliance(prop)

    return success(serialize_policy(record), status=200)


@bp.route("/policies/<pid>/lapse", methods=["POST"])
@require_roles("Underwriter")
def lapse_policy(pid):
    record = db.policies.get(pid)
    if record is None:
        raise errors.not_found("Policy not found")

    # State (priority 5): lapse only from ACTIVE.
    if record["status"] != "ACTIVE":
        raise errors.invalid_state("Policy must be ACTIVE to lapse")

    # Term elapsed: now must be >= expiration_date else ERR_POLICY_NOT_EXPIRED.
    now = clock.now()
    expiration = parse_iso8601(record["expiration_date"])
    if now < expiration:
        raise errors.ApiError(errors.ERR_POLICY_NOT_EXPIRED, 409,
                              "Policy term has not expired")

    record["status"] = "LAPSED"
    record["version"] += 1
    record["updated_at"] = now_ts()

    prop = db.properties.get(record["property_id"])
    _clear_property_pointer_and_compliance(prop)

    return success(serialize_policy(record), status=200)
