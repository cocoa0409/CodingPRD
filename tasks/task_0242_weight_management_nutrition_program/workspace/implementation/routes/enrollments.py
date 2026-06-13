"""Enrollment endpoints + lifecycle (PRD 3.4, 3.5, 3.11)."""
from flask import Blueprint, request

from common import (as_int, as_str, get_body, init_common, parse_pagination,
                    require, sort_by_creation, touch)
from db import db
from errors import (ERR_BILLING_PERIOD_OVERLAP, ERR_GRADUATION_CRITERIA_NOT_MET,
                    ERR_INTAKE_MEMBER_MISMATCH, ERR_INTAKE_NOT_APPROVED,
                    ERR_INVALID_REQUEST, ERR_INVALID_STATE, ERR_PLAN_RETIRED,
                    ERR_RX_AUTHORIZATION_REQUIRED, raise_error)
from lookups import (get_enrollment, get_intake, get_member, get_plan,
                     get_program, iso_from_seconds, parse_instant,
                     program_clock_seconds)
from middleware import require_roles
from response import paginated, success
from serializers import serialize
import calculations as calc
import services

bp = Blueprint("enrollments", __name__)

ALL_ROLES = ("ProgramAdmin", "Clinician", "BillingAgent", "Coach", "Member")


@bp.route("/wm/enrollments", methods=["POST"])
@require_roles("ProgramAdmin")
def create_enrollment():
    body = get_body()
    member_id = as_str(require(body, "member_id"), "member_id")
    plan_id = as_str(require(body, "plan_id"), "plan_id")
    intake_id = as_str(require(body, "intake_assessment_id"), "intake_assessment_id")

    cycle_length_days = 30
    if body.get("cycle_length_days") is not None:
        cycle_length_days = as_int(body["cycle_length_days"], "cycle_length_days")
        if cycle_length_days < 1 or cycle_length_days > 90:
            raise_error(ERR_INVALID_REQUEST, "cycle_length_days must be in 1..90")

    # FK existence, validated in body order (member, plan, intake)
    member = get_member(member_id)
    plan = get_plan(plan_id)
    intake = get_intake(intake_id)

    # intake must belong to the same member (priority 9)
    if intake["member_id"] != member_id:
        raise_error(ERR_INTAKE_MEMBER_MISMATCH,
                    "intake_assessment does not belong to member")

    # plan must be active (priority 11)
    if not plan["active"]:
        raise_error(ERR_PLAN_RETIRED, "Plan is retired")

    enrollment = {
        "member_id": member_id,
        "program_id": member["program_id"],
        "plan_id": plan_id,
        "intake_assessment_id": intake_id,
        "billing_anchor_utc": None,
        "cycle_length_days": cycle_length_days,
        "clinical_status": "PENDING_CLINICAL",
        "billing_status": "UNBILLED",
        "cycles_billed": 0,
        "graduation_eligible": False,
    }
    init_common(enrollment)
    db.enrollments[enrollment["id"]] = enrollment
    return success(serialize(enrollment), 201)


@bp.route("/wm/enrollments", methods=["GET"])
@require_roles(*ALL_ROLES)
def list_enrollments():
    limit, offset = parse_pagination()
    items = list(db.enrollments.values())
    member_id = request.args.get("member_id")
    program_id = request.args.get("program_id")
    plan_id = request.args.get("plan_id")
    intake_id = request.args.get("intake_assessment_id")
    clinical_status = request.args.get("clinical_status")
    if member_id is not None:
        items = [e for e in items if e["member_id"] == member_id]
    if program_id is not None:
        items = [e for e in items if e["program_id"] == program_id]
    if plan_id is not None:
        items = [e for e in items if e["plan_id"] == plan_id]
    if intake_id is not None:
        items = [e for e in items if e["intake_assessment_id"] == intake_id]
    if clinical_status is not None:
        items = [e for e in items if e["clinical_status"] == clinical_status]
    items = sort_by_creation(items)
    total = len(items)
    page = items[offset:offset + limit]
    return paginated([serialize(e) for e in page], limit, offset, total)


@bp.route("/wm/enrollments/<enrollment_id>", methods=["GET"])
@require_roles(*ALL_ROLES)
def get_one_enrollment(enrollment_id):
    return success(serialize(get_enrollment(enrollment_id)), 200)


@bp.route("/wm/enrollments/<enrollment_id>/activate", methods=["POST"])
@require_roles("ProgramAdmin")
def activate_enrollment(enrollment_id):
    enrollment = get_enrollment(enrollment_id)

    # state gate first (priority 8)
    if enrollment["clinical_status"] != "PENDING_CLINICAL":
        raise_error(ERR_INVALID_STATE, "Activation requires PENDING_CLINICAL")

    intake = get_intake(enrollment["intake_assessment_id"])
    if intake["status"] != "APPROVED":
        raise_error(ERR_INTAKE_NOT_APPROVED, "IntakeAssessment must be APPROVED")

    plan = get_plan(enrollment["plan_id"])
    if plan["tier"] == "RX":
        has_issued = any(
            rx["enrollment_id"] == enrollment_id and rx["status"] == "ISSUED"
            for rx in db.rx_authorizations.values()
        )
        if not has_issued:
            raise_error(ERR_RX_AUTHORIZATION_REQUIRED,
                        "RX-tier activation requires an ISSUED RxAuthorization")

    if not plan["active"]:
        raise_error(ERR_PLAN_RETIRED, "Plan is retired")

    program = get_program(enrollment["program_id"])
    member = get_member(enrollment["member_id"])

    enrollment["clinical_status"] = "ACTIVE"
    enrollment["billing_status"] = "CURRENT"
    enrollment["billing_anchor_utc"] = program["current_utc"]
    member["status"] = "ENROLLED"
    touch(member)

    # cycle-0 invoice
    _issue_recurring_invoice(enrollment, plan, member, program, cycle_index=0)
    enrollment["cycles_billed"] = 1
    touch(enrollment)
    return success(serialize(enrollment), 200)


def _issue_recurring_invoice(enrollment, plan, member, program, cycle_index):
    """Generate a recurring invoice (cycle 0 at activation, or subsequent).

    PRD 2.4: an invoice's period boundaries are read from the owning program's
    `current_utc` at the moment of the operation. The half-open period therefore
    starts at the program clock's current instant and ends `cycle_length_days`
    later (PRD 3.5: "the end equals the start plus `cycle_length_days`"). At
    cycle-0 activation this coincides with `billing_anchor_utc`, since both are
    stamped from `current_utc` in the same operation.
    """
    cycle_len = enrollment["cycle_length_days"]
    period_start_secs = program_clock_seconds(program)
    period_end_secs = period_start_secs + cycle_len * calc.SECONDS_PER_DAY
    period_start = iso_from_seconds(period_start_secs)
    period_end = iso_from_seconds(period_end_secs)

    # overlap check vs existing non-VOID invoices (half-open intervals)
    for inv in db.invoices.values():
        if inv["enrollment_id"] != enrollment["id"] or inv["status"] == "VOID":
            continue
        existing_start = parse_instant(inv["period_start_utc"], "period_start_utc")
        existing_end = parse_instant(inv["period_end_utc"], "period_end_utc")
        # overlap if start < existing_end and existing_start < end (touching allowed)
        if period_start_secs < existing_end and existing_start < period_end_secs:
            raise_error(ERR_BILLING_PERIOD_OVERLAP,
                        "Billing period overlaps an existing invoice")

    lines, subtotal = calc.compute_invoice_lines(
        plan["monthly_fee_cents"], plan["enrollment_fee_cents"], cycle_index
    )

    invoice = {
        "enrollment_id": enrollment["id"],
        "member_id": member["id"],
        "cycle_index": cycle_index,
        "period_start_utc": period_start,
        "period_end_utc": period_end,
        "line_items": lines,
        "subtotal_cents": subtotal,
        "hsa_fsa_eligible_cents": 0,
        "prorated": False,
        "status": "ISSUED",
    }
    init_common(invoice)
    invoice["hsa_fsa_eligible_cents"] = calc.compute_hsa_fsa_eligible_cents(
        invoice["line_items"], services.enrollment_is_hsa_fsa_eligible(enrollment["id"])
    )
    db.invoices[invoice["id"]] = invoice
    return invoice


@bp.route("/wm/enrollments/<enrollment_id>/bill-next-cycle", methods=["POST"])
@require_roles("BillingAgent")
def bill_next_cycle(enrollment_id):
    enrollment = get_enrollment(enrollment_id)
    plan = get_plan(enrollment["plan_id"])
    member = get_member(enrollment["member_id"])
    program = get_program(enrollment["program_id"])

    cycle_index = enrollment["cycles_billed"]
    invoice = _issue_recurring_invoice(enrollment, plan, member, program, cycle_index)
    enrollment["cycles_billed"] += 1
    touch(enrollment)
    return success(serialize(invoice), 201)


@bp.route("/wm/enrollments/<enrollment_id>/graduate", methods=["POST"])
@require_roles("ProgramAdmin")
def graduate_enrollment(enrollment_id):
    enrollment = get_enrollment(enrollment_id)
    if enrollment["clinical_status"] != "ACTIVE":
        raise_error(ERR_INVALID_STATE, "Graduation requires clinical_status ACTIVE")

    services.recompute_graduation_eligibility(enrollment)
    if not enrollment["graduation_eligible"]:
        raise_error(ERR_GRADUATION_CRITERIA_NOT_MET,
                    "Enrollment is not graduation-eligible")

    program = get_program(enrollment["program_id"])
    member = get_member(enrollment["member_id"])
    plan = get_plan(enrollment["plan_id"])

    enrollment["clinical_status"] = "GRADUATED"
    member["status"] = "GRADUATED"
    touch(member)

    services.run_enrollment_end_cascade(enrollment, program)
    services.issue_settlement_invoice(enrollment, program, plan, member)
    enrollment["billing_status"] = "CLOSED"
    touch(enrollment)
    return success(serialize(enrollment), 200)


@bp.route("/wm/enrollments/<enrollment_id>/withdraw", methods=["POST"])
@require_roles("ProgramAdmin")
def withdraw_enrollment(enrollment_id):
    enrollment = get_enrollment(enrollment_id)
    status = enrollment["clinical_status"]
    if status not in ("ACTIVE", "PENDING_CLINICAL"):
        raise_error(ERR_INVALID_STATE, "Withdraw requires ACTIVE or PENDING_CLINICAL")

    program = get_program(enrollment["program_id"])
    member = get_member(enrollment["member_id"])
    plan = get_plan(enrollment["plan_id"])

    if status == "PENDING_CLINICAL":
        # no invoice ever issued: no proration/refund
        enrollment["clinical_status"] = "WITHDRAWN"
        member["status"] = "WITHDRAWN"
        touch(member)
        enrollment["billing_status"] = "CLOSED"
        touch(enrollment)
        return success(serialize(enrollment), 200)

    # ACTIVE withdraw: full cascade + settlement
    enrollment["clinical_status"] = "WITHDRAWN"
    member["status"] = "WITHDRAWN"
    touch(member)
    services.run_enrollment_end_cascade(enrollment, program)
    services.issue_settlement_invoice(enrollment, program, plan, member)
    enrollment["billing_status"] = "CLOSED"
    touch(enrollment)
    return success(serialize(enrollment), 200)
