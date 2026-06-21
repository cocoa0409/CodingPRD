"""Enrollment endpoints (PRD §3.4, §3.5, §3.9, §2.8, §2.10)."""
from __future__ import annotations

from flask import Blueprint, request

import db
import errors as E
from middleware import (
    authenticate, authorize,
    BENEFITS_ADMIN, PAYROLL_OFFICER, COMPLIANCE_OFFICER, DEPENDENT_VERIFIER,
)
import response
from services import common as C
from services import domain as D
from routes._helpers import get_or_404

bp = Blueprint("enrollments", __name__)

ALL_ROLES = {BENEFITS_ADMIN, PAYROLL_OFFICER, COMPLIANCE_OFFICER, DEPENDENT_VERIFIER}


# ---------------------------------------------------------------------------
# Create (DRAFT)
# ---------------------------------------------------------------------------
@bp.route("/employees/<emp_id>/enrollments", methods=["POST"])
def create_enrollment(emp_id):
    role = authenticate()
    authorize(role, {BENEFITS_ADMIN})
    # Existence (priority 3): path emp first, then body FK plan_tier_id.
    emp = get_or_404(db.employees, emp_id, "Employee")
    body = C.get_body()
    C.require_fields(body, ["plan_tier_id", "coverage_start_date"])
    tier_id = body["plan_tier_id"]
    if not C.is_str(tier_id):
        raise E.invalid_request("plan_tier_id must be a string")
    tier = get_or_404(db.plan_tiers, tier_id, "PlanTier")

    coverage_start_date = body["coverage_start_date"]
    C.parse_iso(coverage_start_date)  # validate ISO 8601

    coverage_amount = body.get("coverage_amount_cents", 0)
    if coverage_amount is None:
        coverage_amount = 0
    if not C.is_int(coverage_amount) or coverage_amount < 0:
        raise E.invalid_request("coverage_amount_cents must be a non-negative integer")

    # Archived-plan rule (priority 12.5): creating against an ARCHIVED offering tier.
    offering = D.offering_for_tier(tier)
    if offering is not None and offering["status"] == "ARCHIVED":
        raise E.plan_archived()

    benefit_type = offering["benefit_type"] if offering else None

    enr = C.new_common_fields()
    enr.update({
        "employee_id": emp_id,
        "plan_tier_id": tier_id,
        "benefit_type": benefit_type,
        "coverage_amount_cents": coverage_amount,
        "coverage_start_date": coverage_start_date,
        "coverage_end_date": None,
        "monthly_employee_cost_cents": 0,
        "per_paycheck_deduction_cents": 0,
        "covered_dependent_count": 0,
        "source_life_event_id": None,
        "superseded_by_enrollment_id": None,
        "status": "DRAFT",
    })
    db.enrollments[enr["id"]] = enr
    return response.ok_object(C.serialize(enr), 201)


@bp.route("/enrollments/<enr_id>", methods=["GET"])
def get_enrollment(enr_id):
    role = authenticate()
    authorize(role, ALL_ROLES)
    enr = get_or_404(db.enrollments, enr_id, "Enrollment")
    return response.ok_object(C.serialize(enr), 200)


@bp.route("/enrollments", methods=["GET"])
def list_enrollments():
    role = authenticate()
    authorize(role, ALL_ROLES)
    limit, offset = C.parse_pagination()
    args = request.args
    items = list(db.enrollments.values())
    for key in ("employee_id", "plan_tier_id", "source_life_event_id",
                "superseded_by_enrollment_id", "status", "benefit_type"):
        val = args.get(key)
        if val is not None:
            items = [e for e in items if e.get(key) == val]
    items = C.order_by_created(items)
    page, total = C.paginate(items, limit, offset)
    return response.ok_array(C.serialize_list(page), limit, offset, total, 200)


# ---------------------------------------------------------------------------
# Activate (DRAFT -> ACTIVE)
# ---------------------------------------------------------------------------
@bp.route("/enrollments/<enr_id>/activate", methods=["POST"])
def activate_enrollment(enr_id):
    role = authenticate()
    authorize(role, {BENEFITS_ADMIN})
    enr = get_or_404(db.enrollments, enr_id, "Enrollment")
    body = C.get_body()
    # Body shape (priority 4): expected_employee_version required.
    C.require_fields(body, ["expected_employee_version"])
    expected_version = body["expected_employee_version"]
    if not C.is_int(expected_version):
        raise E.invalid_request("expected_employee_version must be an integer")

    # State (priority 5).
    if enr["status"] != "DRAFT":
        raise E.invalid_state("Enrollment must be DRAFT to activate")

    emp = db.employees[enr["employee_id"]]
    tier = db.plan_tiers[enr["plan_tier_id"]]
    offering = D.offering_for_tier(tier)

    # Business rules in PRD §2.10 precedence: EOI_REQUIRED (7) before
    # EMPLOYEE_NOT_ELIGIBLE (8), before COVERAGE_OVERLAP (11), before OCC (13).
    if (enr["benefit_type"] == "VOLUNTARY_LIFE"
            and offering is not None
            and enr["coverage_amount_cents"] > offering["guaranteed_issue_amount_cents"]):
        raise E.eoi_required()

    if emp["eligibility_status"] != "ELIGIBLE":
        raise E.employee_not_eligible()

    # Coverage-overlap (priority 11): closed inclusive intervals, same benefit_type,
    # other ACTIVE enrollments. Adjacency (prev_end + 1 day == start) allowed.
    new_start = C.date_of(C.parse_iso(enr["coverage_start_date"]))
    new_end = None
    if enr.get("coverage_end_date"):
        new_end = C.date_of(C.parse_iso(enr["coverage_end_date"]))
    for other in db.enrollments.values():
        if other["id"] == enr["id"]:
            continue
        if (other["employee_id"] == enr["employee_id"]
                and other["benefit_type"] == enr["benefit_type"]
                and other["status"] == "ACTIVE"):
            o_start = C.date_of(C.parse_iso(other["coverage_start_date"]))
            o_end = None
            if other.get("coverage_end_date"):
                o_end = C.date_of(C.parse_iso(other["coverage_end_date"]))
            if D.coverage_intervals_overlap(new_start, new_end, o_start, o_end):
                raise E.coverage_overlap()

    # OCC (priority 13).
    if expected_version != emp["version"]:
        raise E.stale_employee_version()

    # Side effects.
    enr["status"] = "ACTIVE"
    D.recompute_enrollment_costs(enr, emp)
    C.touch(enr)
    D.emit_carrier_feed(enr, "ADD")
    C.touch(emp)
    return response.ok_object(C.serialize(enr), 200)


# ---------------------------------------------------------------------------
# Submit EOI (DRAFT -> PENDING_EOI)
# ---------------------------------------------------------------------------
@bp.route("/enrollments/<enr_id>/submit-eoi", methods=["POST"])
def submit_eoi(enr_id):
    role = authenticate()
    authorize(role, {BENEFITS_ADMIN})
    enr = get_or_404(db.enrollments, enr_id, "Enrollment")
    if enr["status"] != "DRAFT":
        raise E.invalid_state("Enrollment must be DRAFT to submit for EOI")

    tier = db.plan_tiers[enr["plan_tier_id"]]
    offering = D.offering_for_tier(tier)
    gi = offering["guaranteed_issue_amount_cents"] if offering else 0
    if not (enr["benefit_type"] == "VOLUNTARY_LIFE"
            and enr["coverage_amount_cents"] > gi):
        # Not an over-GI voluntary-life draft: this transition is not defined.
        raise E.invalid_state("submit-eoi requires VOLUNTARY_LIFE coverage above guaranteed issue")

    eoi = C.new_common_fields()
    eoi.update({
        "enrollment_id": enr["id"],
        "excess_coverage_cents": enr["coverage_amount_cents"] - gi,
        "decision": "PENDING",
    })
    db.eoi_requests[eoi["id"]] = eoi

    enr["status"] = "PENDING_EOI"
    C.touch(enr)
    return response.ok_object(C.serialize(enr), 200)


# ---------------------------------------------------------------------------
# Cancel (DRAFT -> CANCELLED)
# ---------------------------------------------------------------------------
@bp.route("/enrollments/<enr_id>/cancel", methods=["POST"])
def cancel_enrollment(enr_id):
    role = authenticate()
    authorize(role, {BENEFITS_ADMIN})
    enr = get_or_404(db.enrollments, enr_id, "Enrollment")
    if enr["status"] != "DRAFT":
        raise E.invalid_state("Enrollment must be DRAFT to cancel")
    enr["status"] = "CANCELLED"
    C.touch(enr)
    return response.ok_object(C.serialize(enr), 200)


# ---------------------------------------------------------------------------
# Add / remove dependent
# ---------------------------------------------------------------------------
@bp.route("/enrollments/<enr_id>/add-dependent", methods=["POST"])
def add_dependent(enr_id):
    role = authenticate()
    authorize(role, {BENEFITS_ADMIN})
    enr = get_or_404(db.enrollments, enr_id, "Enrollment")
    body = C.get_body()
    C.require_fields(body, ["dependent_id"])
    dep_id = body["dependent_id"]
    if not C.is_str(dep_id):
        raise E.invalid_request("dependent_id must be a string")
    dep = get_or_404(db.dependents, dep_id, "Dependent")

    # Dependent-verified rule (priority 12).
    if dep["verification_status"] != "VERIFIED":
        raise E.dependent_not_verified()

    enr["covered_dependent_count"] = enr.get("covered_dependent_count", 0) + 1
    C.touch(enr)
    return response.ok_object(C.serialize(enr), 200)


@bp.route("/enrollments/<enr_id>/remove-dependent", methods=["POST"])
def remove_dependent(enr_id):
    role = authenticate()
    authorize(role, {BENEFITS_ADMIN})
    enr = get_or_404(db.enrollments, enr_id, "Enrollment")
    body = C.get_body()
    C.require_fields(body, ["dependent_id"])
    dep_id = body["dependent_id"]
    if not C.is_str(dep_id):
        raise E.invalid_request("dependent_id must be a string")
    dep = get_or_404(db.dependents, dep_id, "Dependent")

    enr["covered_dependent_count"] = enr.get("covered_dependent_count", 0) - 1
    C.touch(enr)
    return response.ok_object(C.serialize(enr), 200)
