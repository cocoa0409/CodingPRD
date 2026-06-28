"""Enrollment lifecycle + funding endpoints (PRD §3.5, §3.6, §3.7, §3.10).

Parallel state dimensions:
  lifecycle_status: PENDING -> ACTIVE -> TERMINATED -> PORTED ; PENDING -> DECLINED
  funding_status  : UNFUNDED <-> CURRENT <-> LAPSED  (driven by payroll postings)
"""

from flask import Blueprint, request

import calculations
import errors
import serializers
import services
from clock import clock, format_iso8601_ms
from db import db
from middleware import require_roles
from response import success, list_success
from validation import (
    get_json_body, require_str, optional_bool, require_int,
    require_enum, parse_pagination, paginate,
)

bp = Blueprint("enrollments", __name__)


# --------------------------------------------------------------------------- #
# Create enrollment (premium + GI freeze, deduction conversion) (PRD §3.5)    #
# --------------------------------------------------------------------------- #

@bp.route("/benefits/enrollments", methods=["POST"])
@require_roles("BenefitsAdmin", "Employee")
def create_enrollment():
    body = get_json_body()
    employee_id = require_str(body, "employee_id")
    plan_product_id = require_str(body, "plan_product_id")
    enrollment_period_id = require_str(body, "enrollment_period_id")
    pretax = optional_bool(body, "pretax", default=False)

    # Existence (priority 3) — left-to-right.
    employee = services.find_employee(employee_id)
    if employee is None:
        raise errors.not_found("Employee not found")
    product = services.find_plan_product(plan_product_id)
    if product is None:
        raise errors.not_found("Plan product not found")
    period = services.find_period(enrollment_period_id)
    if period is None:
        raise errors.not_found("Enrollment period not found")

    # Referential consistency (priority 4): the product must belong to the
    # employer that owns the employee, and the period must belong to that same
    # employer (PRD §2.7).
    if product["employer_id"] != employee["employer_id"]:
        raise errors.reference_mismatch("Product does not belong to the employee's employer")
    if period["employer_id"] != employee["employer_id"]:
        raise errors.reference_mismatch("Period does not belong to the employee's employer")

    with db.lock:
        # State (priority 5): only an OPEN product accepts enrollments (PRD §3.2).
        if product["status"] != "OPEN":
            raise errors.product_not_open("Plan product is not OPEN")

        # NOTE: PRD §3.5 (creating an enrollment) imposes NO Section 125
        # active-plan gate; the `pretax` flag is merely recorded at creation.
        # The ERR_SECTION125_INACTIVE rule is enforced only at activation
        # (PRD §3.6), so it must not be applied here.
        employer = services.find_employer(employee["employer_id"])

        # Duplicate enrollment (priority 15): at most one non-terminal (PENDING/
        # ACTIVE) enrollment per product per employee (PRD §3.5).
        for enr in db.enrollments.all():
            if (enr["employee_id"] == employee_id
                    and enr["plan_product_id"] == plan_product_id
                    and enr["lifecycle_status"] in ("PENDING", "ACTIVE")):
                raise errors.duplicate_enrollment(
                    "Employee already holds a non-terminal enrollment in this product"
                )

        enrolled_at = clock.now()
        gi_status, weekly_premium_cents = calculations.premium_assessment(
            product, period, enrolled_at
        )
        weekly_deduction_cents = calculations.deduction_conversion(
            weekly_premium_cents, employer["pay_periods_per_year"]
        )
        benefit_remaining = calculations.benefit_remaining(
            product["annual_benefit_cap_cents"], 0
        )

        record = {
            "employee_id": employee_id,
            "plan_product_id": plan_product_id,
            "enrollment_period_id": enrollment_period_id,
            "pretax": pretax,
            "enrolled_at": format_iso8601_ms(enrolled_at),
            "gi_status": gi_status,
            "weekly_premium_cents": weekly_premium_cents,
            "weekly_deduction_cents": weekly_deduction_cents,
            "benefit_paid_cents": 0,
            "benefit_remaining_cents": benefit_remaining,
            "lifecycle_status": "PENDING",
            "funding_status": "UNFUNDED",
            # internal: consecutive payroll-failure tally (PRD §3.7)
            "_consecutive_failed_count": 0,
            "_enrolled_at_dt": enrolled_at,
        }
        db.enrollments.insert(record)
    return success(serializers.enrollment(record), 201)


@bp.route("/benefits/enrollments", methods=["GET"])
@require_roles("BenefitsAdmin", "ClaimsAdjuster", "Employee")
def list_enrollments():
    limit, offset = parse_pagination()
    employee_id = request.args.get("employee_id")
    plan_product_id = request.args.get("plan_product_id")
    enrollment_period_id = request.args.get("enrollment_period_id")
    lifecycle_status = request.args.get("lifecycle_status")
    funding_status = request.args.get("funding_status")

    items = db.enrollments.all()
    if employee_id is not None:
        items = [e for e in items if e["employee_id"] == employee_id]
    if plan_product_id is not None:
        items = [e for e in items if e["plan_product_id"] == plan_product_id]
    if enrollment_period_id is not None:
        items = [e for e in items if e["enrollment_period_id"] == enrollment_period_id]
    if lifecycle_status is not None:
        items = [e for e in items if e["lifecycle_status"] == lifecycle_status]
    if funding_status is not None:
        items = [e for e in items if e["funding_status"] == funding_status]

    page, total = paginate(items, limit, offset)
    return list_success([serializers.enrollment(e) for e in page], limit, offset, total)


@bp.route("/benefits/enrollments/<enrollment_id>", methods=["GET"])
@require_roles("BenefitsAdmin", "ClaimsAdjuster", "Employee")
def get_enrollment(enrollment_id):
    record = db.enrollments.get(enrollment_id)
    if record is None:
        raise errors.not_found("Enrollment not found")
    return success(serializers.enrollment(record), 200)


# --------------------------------------------------------------------------- #
# Activate / Decline / Terminate (lifecycle dimension) (PRD §3.6)             #
# --------------------------------------------------------------------------- #

@bp.route("/benefits/enrollments/<enrollment_id>/activate", methods=["POST"])
@require_roles("BenefitsAdmin")
def activate_enrollment(enrollment_id):
    record = db.enrollments.get(enrollment_id)
    if record is None:
        raise errors.not_found("Enrollment not found")

    with db.lock:
        # State (priority 5): allowed only from PENDING.
        if record["lifecycle_status"] != "PENDING":
            raise errors.invalid_state("Enrollment must be PENDING to activate")

        product = services.find_plan_product(record["plan_product_id"])
        employee = services.find_employee(record["employee_id"])
        employer = services.find_employer(employee["employer_id"])

        # Activation preconditions (PRD §3.6).
        if product["status"] != "OPEN":
            raise errors.product_not_open("Plan product is not OPEN")
        if employee["employment_status"] != "EMPLOYED":
            raise errors.employee_terminated("Employee is TERMINATED")
        if record["pretax"] and not employer["section_125_plan_active"]:
            raise errors.section125_inactive("Employer Section 125 plan is not active")

        record["lifecycle_status"] = "ACTIVE"
        db.enrollments.touch(record)

        # Recompute the employee aggregate (now includes this ACTIVE enrollment).
        services.recompute_employee_total_deduction(employee)

        # If pretax, create a LOCKED Section125Election (PRD §3.6).
        if record["pretax"]:
            annual_pretax = record["weekly_premium_cents"] * 52
            plan_year_label = _derive_plan_year_label(record)
            election = {
                "enrollment_id": record["id"],
                "plan_year_label": plan_year_label,
                "annual_pretax_amount_cents": annual_pretax,
                "status": "LOCKED",
                "qualifying_event": None,
            }
            db.section125_elections.insert(election)

    return success(serializers.enrollment(record), 200)


def _derive_plan_year_label(enrollment):
    """plan_year_label for the cafeteria plan year. The PRD requires the field to
    be present; we derive it from the enrollment's benefit-year context (the
    period's benefit_year_start year), falling back to the enrolled_at year."""
    period = services.find_period(enrollment["enrollment_period_id"])
    dt = None
    if period is not None:
        dt = period.get("_benefit_year_start_dt")
    if dt is None:
        dt = enrollment.get("_enrolled_at_dt")
    return str(dt.year) if dt is not None else ""


@bp.route("/benefits/enrollments/<enrollment_id>/decline", methods=["POST"])
@require_roles("BenefitsAdmin", "Employee")
def decline_enrollment(enrollment_id):
    record = db.enrollments.get(enrollment_id)
    if record is None:
        raise errors.not_found("Enrollment not found")
    with db.lock:
        if record["lifecycle_status"] != "PENDING":
            raise errors.invalid_state("Enrollment must be PENDING to decline")
        record["lifecycle_status"] = "DECLINED"
        db.enrollments.touch(record)
    return success(serializers.enrollment(record), 200)


@bp.route("/benefits/enrollments/<enrollment_id>/terminate", methods=["POST"])
@require_roles("BenefitsAdmin")
def terminate_enrollment(enrollment_id):
    record = db.enrollments.get(enrollment_id)
    if record is None:
        raise errors.not_found("Enrollment not found")
    with db.lock:
        if record["lifecycle_status"] != "ACTIVE":
            raise errors.invalid_state("Enrollment must be ACTIVE to terminate")
        services.terminate_enrollment_core(record)
    return success(serializers.enrollment(record), 200)


# --------------------------------------------------------------------------- #
# Payroll deductions (funding dimension) (PRD §3.7)                           #
# --------------------------------------------------------------------------- #

@bp.route("/benefits/enrollments/<enrollment_id>/payroll-deductions", methods=["POST"])
@require_roles("Payroll", "System")
def post_payroll_deduction(enrollment_id):
    record = db.enrollments.get(enrollment_id)
    if record is None:
        raise errors.not_found("Enrollment not found")

    body = get_json_body()
    pay_period_index = require_int(body, "pay_period_index", minimum=0)
    outcome = require_enum(body, "outcome", {"POSTED", "FAILED"})

    with db.lock:
        # Posting is permitted only while lifecycle_status == ACTIVE (PRD §3.7).
        if record["lifecycle_status"] != "ACTIVE":
            raise errors.enrollment_not_active("Enrollment is not ACTIVE")

        # pay_period_index unique per enrollment (PRD §3.7).
        for d in db.payroll_deductions.all():
            if d["enrollment_id"] == enrollment_id and d["pay_period_index"] == pay_period_index:
                raise errors.duplicate_pay_period("pay_period_index already recorded")

        amount_cents = record["weekly_deduction_cents"]
        deduction = {
            "enrollment_id": enrollment_id,
            "pay_period_index": pay_period_index,
            "amount_cents": amount_cents,
            "outcome": outcome,
        }
        db.payroll_deductions.insert(deduction)

        # Funding evolves from a chronological walk in ascending pay_period_index
        # order — not creation order (PRD §3.7 / lapse_evaluation).
        _recompute_funding(record)

    return success(serializers.payroll_deduction(deduction), 201)


def _recompute_funding(enrollment):
    """Walk this enrollment's deductions in ascending pay_period_index, maintain a
    consecutive-failure count, and derive funding_status (PRD §3.7).

      POSTED -> count = 0, funding_status = CURRENT
      FAILED -> count += 1; lapse to LAPSED only when count reaches 3
    """
    deductions = [
        d for d in db.payroll_deductions.all()
        if d["enrollment_id"] == enrollment["id"]
    ]
    deductions.sort(key=lambda d: d["pay_period_index"])

    funding = "UNFUNDED"
    count = 0
    for d in deductions:
        if d["outcome"] == "POSTED":
            count = 0
            funding = "CURRENT"
        else:  # FAILED
            count += 1
            if count >= calculations.LAPSE_THRESHOLD:
                funding = "LAPSED"
            # a single/second failure leaves funding at its prior value
    enrollment["_consecutive_failed_count"] = count
    if enrollment["funding_status"] != funding:
        enrollment["funding_status"] = funding
        db.enrollments.touch(enrollment)
    else:
        enrollment["funding_status"] = funding


# --------------------------------------------------------------------------- #
# Portability conversion (TERMINATED -> PORTED, OCC) (PRD §3.10, §2.9)        #
# --------------------------------------------------------------------------- #

@bp.route("/benefits/enrollments/<enrollment_id>/portability-conversions", methods=["POST"])
@require_roles("Employee")
def create_portability_conversion(enrollment_id):
    record = db.enrollments.get(enrollment_id)
    if record is None:
        raise errors.not_found("Enrollment not found")

    body = get_json_body()
    expected_version = require_int(body, "expected_enrollment_version")

    with db.lock:
        # Porting eligibility (priority 13): must be TERMINATED and have no
        # existing CONVERTED conversion (PRD §3.10).
        if record["lifecycle_status"] != "TERMINATED":
            raise errors.already_ported("Enrollment is not TERMINATED")
        for c in db.portability_conversions.all():
            if c["enrollment_id"] == enrollment_id and c["status"] == "CONVERTED":
                raise errors.already_ported("Enrollment already has a CONVERTED conversion")

        # OCC (priority 14): expected_enrollment_version must match current version.
        if expected_version != record["version"]:
            raise errors.stale_enrollment_version(
                "expected_enrollment_version does not match current version"
            )

        product = services.find_plan_product(record["plan_product_id"])
        direct_bill = calculations.portability_premium(product)

        conversion = {
            "enrollment_id": enrollment_id,
            "expected_enrollment_version": expected_version,
            "direct_bill_weekly_cents": direct_bill,
            "status": "CONVERTED",
        }
        db.portability_conversions.insert(conversion)

        # lifecycle -> PORTED; bump enrollment version by one (PRD §3.10).
        record["lifecycle_status"] = "PORTED"
        db.enrollments.touch(record)

    return success(serializers.portability_conversion(conversion), 201)


@bp.route("/benefits/portability-conversions", methods=["GET"])
@require_roles("BenefitsAdmin", "Employee")
def list_portability_conversions():
    limit, offset = parse_pagination()
    enrollment_id = request.args.get("enrollment_id")
    status = request.args.get("status")

    items = db.portability_conversions.all()
    if enrollment_id is not None:
        items = [c for c in items if c["enrollment_id"] == enrollment_id]
    if status is not None:
        items = [c for c in items if c["status"] == status]

    page, total = paginate(items, limit, offset)
    return list_success(
        [serializers.portability_conversion(c) for c in page], limit, offset, total
    )


@bp.route("/benefits/portability-conversions/<conversion_id>", methods=["GET"])
@require_roles("BenefitsAdmin", "Employee")
def get_portability_conversion(conversion_id):
    record = db.portability_conversions.get(conversion_id)
    if record is None:
        raise errors.not_found("Portability conversion not found")
    return success(serializers.portability_conversion(record), 200)


# --------------------------------------------------------------------------- #
# PayrollDeduction reads                                                       #
# --------------------------------------------------------------------------- #

@bp.route("/benefits/payroll-deductions", methods=["GET"])
@require_roles("BenefitsAdmin", "Payroll", "Employee")
def list_payroll_deductions():
    limit, offset = parse_pagination()
    enrollment_id = request.args.get("enrollment_id")
    outcome = request.args.get("outcome")

    items = db.payroll_deductions.all()
    if enrollment_id is not None:
        items = [d for d in items if d["enrollment_id"] == enrollment_id]
    if outcome is not None:
        items = [d for d in items if d["outcome"] == outcome]

    page, total = paginate(items, limit, offset)
    return list_success(
        [serializers.payroll_deduction(d) for d in page], limit, offset, total
    )


@bp.route("/benefits/payroll-deductions/<deduction_id>", methods=["GET"])
@require_roles("BenefitsAdmin", "Payroll", "Employee")
def get_payroll_deduction(deduction_id):
    record = db.payroll_deductions.get(deduction_id)
    if record is None:
        raise errors.not_found("Payroll deduction not found")
    return success(serializers.payroll_deduction(record), 200)


# --------------------------------------------------------------------------- #
# Section125Election reads                                                     #
# --------------------------------------------------------------------------- #

@bp.route("/benefits/section125-elections", methods=["GET"])
@require_roles("BenefitsAdmin", "Employee")
def list_section125_elections():
    limit, offset = parse_pagination()
    enrollment_id = request.args.get("enrollment_id")
    status = request.args.get("status")

    items = db.section125_elections.all()
    if enrollment_id is not None:
        items = [e for e in items if e["enrollment_id"] == enrollment_id]
    if status is not None:
        items = [e for e in items if e["status"] == status]

    page, total = paginate(items, limit, offset)
    return list_success(
        [serializers.section125_election(e) for e in page], limit, offset, total
    )


@bp.route("/benefits/section125-elections/<election_id>", methods=["GET"])
@require_roles("BenefitsAdmin", "Employee")
def get_section125_election(election_id):
    record = db.section125_elections.get(election_id)
    if record is None:
        raise errors.not_found("Section 125 election not found")
    return success(serializers.section125_election(record), 200)
