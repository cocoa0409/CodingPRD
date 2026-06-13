"""Employer, AdvanceLimitPolicy, FeeSchedule, and test-clock endpoints."""
from flask import Blueprint

import clock
import db
import errors
from middleware import authenticate, require_role
from response import object_response, array_response
from services import domain, serialize, validate

bp = Blueprint("employers", __name__)

PAY_FREQUENCIES = {"WEEKLY", "BIWEEKLY", "SEMIMONTHLY"}
TIERS = {"PROBATION", "STANDARD", "SENIOR"}


# ---------------------------------------------------------------------------
# Employer
# ---------------------------------------------------------------------------
@bp.route("/employers", methods=["POST"])
def create_employer():
    _, role = authenticate()
    require_role(role, {"PlatformAdmin"})
    body = validate.get_body()

    legal_name = validate.require_str(body, "legal_name")
    state_code = validate.require_str(body, "state_code")
    pay_frequency = validate.require_enum(body, "pay_frequency", PAY_FREQUENCIES)
    funding = validate.optional_int(body, "funding_balance_cents", default=0, minimum=0)
    max_pct = validate.optional_number(body, "max_advance_pct_of_available", default=0.50)
    if not (0 < max_pct <= 1.0):
        raise errors.invalid_request("max_advance_pct_of_available must be in (0, 1.0]")
    cap_count = validate.optional_int(body, "per_period_advance_cap_count", default=3, minimum=1)
    cooling = validate.optional_int(body, "cooling_off_hours", default=24, minimum=0)

    common = db.new_common_fields()
    employer = {
        **common,
        "legal_name": legal_name,
        "state_code": state_code,
        "pay_frequency": pay_frequency,
        "funding_balance_cents": funding,
        "max_advance_pct_of_available": max_pct,
        "per_period_advance_cap_count": cap_count,
        "cooling_off_hours": cooling,
        "posture": "HEALTHY",
        "outstanding_principal_cents": 0,
    }
    db.employers[employer["id"]] = employer
    return object_response(serialize.employer(employer), status=201)


@bp.route("/employers/<employer_id>", methods=["GET"])
def get_employer(employer_id):
    _, role = authenticate()
    require_role(role, {"PlatformAdmin", "PayrollOfficer", "ComplianceOfficer"})
    employer = db.employers.get(employer_id)
    if employer is None:
        raise errors.not_found()
    return object_response(serialize.employer(employer))


@bp.route("/employers", methods=["GET"])
def list_employers():
    _, role = authenticate()
    require_role(role, {"PlatformAdmin"})
    limit, offset = validate.pagination()
    page, total = validate.paginate(list(db.employers.values()), limit, offset)
    return array_response([serialize.employer(e) for e in page], limit, offset, total)


@bp.route("/employers/<employer_id>/funding-deposits", methods=["POST"])
def funding_deposit(employer_id):
    _, role = authenticate()
    require_role(role, {"PlatformAdmin"})
    employer = db.employers.get(employer_id)
    if employer is None:
        raise errors.not_found()
    body = validate.get_body()
    amount = validate.require_int(body, "amount_cents", minimum=1)
    employer["funding_balance_cents"] += amount
    db.touch(employer)
    domain.refresh_employer(employer)
    return object_response(serialize.employer(employer))


# ---------------------------------------------------------------------------
# AdvanceLimitPolicy
# ---------------------------------------------------------------------------
@bp.route("/advance-policies", methods=["POST"])
def create_policy():
    _, role = authenticate()
    require_role(role, {"PlatformAdmin"})
    body = validate.get_body()
    employer_id = validate.require_str(body, "employer_id")
    employer = db.employers.get(employer_id)
    if employer is None:
        raise errors.not_found("Employer not found")
    tier = validate.require_enum(body, "tier", TIERS)
    min_tenure = validate.require_int(body, "min_tenure_days", minimum=0)
    floor_cents = validate.optional_int(body, "per_advance_floor_cents", default=1000)
    ceiling = validate.require_int(body, "per_advance_ceiling_cents")
    cumulative = validate.require_int(body, "cumulative_period_ceiling_cents")

    # Archive prior ACTIVE policy for the same employer+tier (PRD §3.1).
    for p in db.advance_policies.values():
        if p["employer_id"] == employer_id and p["tier"] == tier and p["status"] == "ACTIVE":
            p["status"] = "ARCHIVED"
            db.touch(p)

    common = db.new_common_fields()
    policy = {
        **common,
        "employer_id": employer_id,
        "tier": tier,
        "min_tenure_days": min_tenure,
        "per_advance_floor_cents": floor_cents,
        "per_advance_ceiling_cents": ceiling,
        "cumulative_period_ceiling_cents": cumulative,
        "status": "ACTIVE",
    }
    db.advance_policies[policy["id"]] = policy
    return object_response(serialize.advance_policy(policy), status=201)


@bp.route("/advance-policies/<policy_id>", methods=["GET"])
def get_policy(policy_id):
    _, role = authenticate()
    require_role(role, {"PlatformAdmin", "PayrollOfficer", "ComplianceOfficer"})
    policy = db.advance_policies.get(policy_id)
    if policy is None:
        raise errors.not_found()
    return object_response(serialize.advance_policy(policy))


@bp.route("/advance-policies", methods=["GET"])
def list_policies():
    from flask import request
    _, role = authenticate()
    require_role(role, {"PlatformAdmin", "PayrollOfficer", "ComplianceOfficer"})
    limit, offset = validate.pagination()
    emp_filter = request.args.get("employer_id")
    items = [
        p for p in db.advance_policies.values()
        if emp_filter is None or p["employer_id"] == emp_filter
    ]
    page, total = validate.paginate(items, limit, offset)
    return array_response([serialize.advance_policy(p) for p in page], limit, offset, total)


# ---------------------------------------------------------------------------
# FeeSchedule
# ---------------------------------------------------------------------------
@bp.route("/fee-schedules", methods=["POST"])
def create_fee_schedule():
    _, role = authenticate()
    require_role(role, {"PlatformAdmin"})
    body = validate.get_body()
    employer_id = validate.require_str(body, "employer_id")
    employer = db.employers.get(employer_id)
    if employer is None:
        raise errors.not_found("Employer not found")
    flat = validate.optional_int(body, "expedite_flat_fee_cents", default=199, minimum=0)
    pct = validate.optional_number(body, "expedite_pct_fee", default=0.0)
    if not (0 <= pct <= 0.05):
        raise errors.invalid_request("expedite_pct_fee must be between 0 and 0.05")
    max_total = validate.optional_int(body, "max_total_fee_cents", default=1500, minimum=0)
    tip_allowed = validate.optional_bool(body, "tip_allowed", default=True)

    # Archive prior ACTIVE schedule for the employer (PRD §3.1).
    for f in db.fee_schedules.values():
        if f["employer_id"] == employer_id and f["status"] == "ACTIVE":
            f["status"] = "ARCHIVED"
            db.touch(f)

    common = db.new_common_fields()
    sched = {
        **common,
        "employer_id": employer_id,
        "expedite_flat_fee_cents": flat,
        "expedite_pct_fee": pct,
        "max_total_fee_cents": max_total,
        "tip_allowed": tip_allowed,
        "status": "ACTIVE",
    }
    db.fee_schedules[sched["id"]] = sched
    return object_response(serialize.fee_schedule(sched), status=201)


@bp.route("/fee-schedules/<fee_schedule_id>", methods=["GET"])
def get_fee_schedule(fee_schedule_id):
    _, role = authenticate()
    require_role(role, {"PlatformAdmin", "PayrollOfficer", "ComplianceOfficer"})
    sched = db.fee_schedules.get(fee_schedule_id)
    if sched is None:
        raise errors.not_found()
    return object_response(serialize.fee_schedule(sched))


@bp.route("/fee-schedules", methods=["GET"])
def list_fee_schedules():
    from flask import request
    _, role = authenticate()
    require_role(role, {"PlatformAdmin", "PayrollOfficer", "ComplianceOfficer"})
    limit, offset = validate.pagination()
    emp_filter = request.args.get("employer_id")
    items = [
        f for f in db.fee_schedules.values()
        if emp_filter is None or f["employer_id"] == emp_filter
    ]
    page, total = validate.paginate(items, limit, offset)
    return array_response([serialize.fee_schedule(f) for f in page], limit, offset, total)


# ---------------------------------------------------------------------------
# Test clock
# ---------------------------------------------------------------------------
@bp.route("/_clock/set_current_utc", methods=["POST"])
def set_clock():
    _, role = authenticate()
    require_role(role, {"PlatformAdmin"})
    body = validate.get_body()
    iso = validate.require_str(body, "to_iso8601")
    try:
        clock.set_clock(iso)
    except Exception:
        raise errors.invalid_request("to_iso8601 must be an ISO 8601 datetime")
    return object_response({})
