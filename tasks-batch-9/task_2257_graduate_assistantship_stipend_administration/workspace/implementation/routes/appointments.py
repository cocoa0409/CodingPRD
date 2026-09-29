"""Appointments: drafting, the submission battery, approval and the payroll axis."""
from decimal import Decimal

from flask import Blueprint

import calc
import serialize
import validate as v
from db import db, insert, update, force_update, now_iso, today
from errors import ApiError
from middleware import authenticate, require_owner
from response import ok, created, ok_list
from services import effects, queries

bp = Blueprint("appointments", __name__)

ASSISTANTSHIP_TYPES = ("TEACHING", "RESEARCH", "ADMINISTRATIVE")
LIFECYCLE_STATUSES = (
    "DRAFT", "SUBMITTED", "RETURNED", "FUNDING_VERIFIED", "APPROVED", "ACTIVE",
    "NON_RENEWAL_PENDING", "COMPLETED", "TERMINATED", "CANCELLED",
)
PAYROLL_STATUSES = (
    "NOT_SCHEDULED", "SCHEDULED", "PARTIALLY_DISBURSED", "FULLY_DISBURSED",
    "PAY_SUSPENDED", "PAY_VOIDED",
)

READ_ROLES = ["GradSchoolAdmin", "DepartmentAdmin", "GrantAccountant",
              "FacultySupervisor", "StudentUser"]


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------
def _term_of(appointment):
    return db.academic_terms.get(appointment["term_id"])


def _require_term_open(appointment):
    term = _term_of(appointment)
    if term is None or term["status"] != "OPEN":
        raise ApiError("ERR_TERM_NOT_OPEN",
                       "The governing term must be OPEN for this operation")
    return term


def _require_state(appointment, allowed):
    if appointment["lifecycle_status"] not in allowed:
        raise ApiError("ERR_INVALID_APPOINTMENT_STATE",
                       "Appointment lifecycle_status %s does not permit this transition"
                       % appointment["lifecycle_status"])


def _policy_for(appointment, student):
    policy = queries.find_policy(appointment["term_id"],
                                 appointment["assistantship_type"],
                                 student["degree_level"])
    if policy is None:
        raise ApiError("ERR_STIPEND_POLICY_MISSING",
                       "No stipend policy governs this term, assistantship type and degree level")
    return policy


def _apply_calculations(appointment, student, policy, term, extra_fields):
    """Runs the four submission calculations and writes every money field."""
    allocations = queries.active_allocations(appointment["id"])
    periods = queries.pay_periods_of_term(term["id"])
    schedule = calc.pay_schedule(appointment, periods, term["proration_method"])
    total_stipend = sum(row["gross_amount_cents"] for row in schedule)

    remission_total, per_remission = effects.compute_remission(
        appointment, student, policy, allocations)
    _, per_stipend = calc.split_by_share(total_stipend, allocations)
    subsidy, employee, net = calc.insurance_and_net(
        total_stipend, appointment["insurance_eligible"], policy)

    fields = dict(extra_fields)
    fields.update({
        "projected_pay_period_count": len(schedule),
        "total_stipend_cents": total_stipend,
        "tuition_remission_cents": remission_total,
        "insurance_subsidy_cents": subsidy,
        "employee_premium_cents": employee,
        "net_term_stipend_cents": net,
    })
    force_update(appointment, **fields)

    touched = []
    for alloc in sorted(allocations, key=lambda a: (a["plan_sequence"], a["_seq"])):
        update(alloc,
               allocated_stipend_cents=per_stipend.get(alloc["id"], 0),
               allocated_remission_cents=per_remission.get(alloc["id"], 0))
        if alloc["status"] == "COMMITTED":
            touched.append(alloc["funding_source_id"])
    effects.recompute_source_balances(touched)
    effects.auto_reinstate(touched)


# ---------------------------------------------------------------------------
# create / read / list
# ---------------------------------------------------------------------------
@bp.post("/appointments")
def create_appointment():
    authenticate(["DepartmentAdmin"])
    body = v.body_dict()

    term_ref = v.ref_value(body, "term_id")
    term = queries.term_or_404(term_ref) if term_ref is not None else None
    department_ref = v.ref_value(body, "department_id")
    if department_ref is not None:
        queries.department_or_404(department_ref)
    student_ref = v.ref_value(body, "student_id")
    student = queries.student_or_404(student_ref) if student_ref is not None else None
    predecessor_ref = v.ref_value(body, "renewed_from_appointment_id")
    if predecessor_ref is not None:
        queries.appointment_or_404(predecessor_ref)

    student_id = v.field_id(body, "student_id")
    department_id = v.field_id(body, "department_id")
    term_id = v.field_id(body, "term_id")
    assistantship_type = v.field_enum(body, "assistantship_type", ASSISTANTSHIP_TYPES)
    effort_pct = v.field_int(body, "effort_pct", minimum=1, maximum=100)
    start_date = v.field_date(body, "start_date")
    end_date = v.field_date(body, "end_date")
    monthly_stipend_cents = v.field_int(body, "monthly_stipend_cents", minimum=1)
    supervisor_user_id = v.field_str(body, "supervisor_user_id")
    renewed_from = v.field_id(body, "renewed_from_appointment_id", required=False)
    if end_date < start_date:
        raise v.invalid("end_date must be on or after start_date")

    if (start_date.isoformat() < term["term_start"]
            or end_date.isoformat() > term["term_end"]):
        raise ApiError("ERR_APPOINTMENT_DATES_OUTSIDE_TERM",
                       "The appointment window must sit inside the term window")

    policy = queries.find_policy(term_id, assistantship_type, student["degree_level"])
    if policy is None:
        raise ApiError("ERR_STIPEND_POLICY_MISSING",
                       "No stipend policy governs this term, assistantship type and degree level")

    duration_days = calc.duration_days_for(start_date, end_date)
    row = insert(db.appointments, {
        "student_id": student_id,
        "department_id": department_id,
        "term_id": term_id,
        "renewed_from_appointment_id": renewed_from,
        "assistantship_type": assistantship_type,
        "effort_pct": effort_pct,
        "start_date": start_date.isoformat(),
        "end_date": end_date.isoformat(),
        "monthly_stipend_cents": monthly_stipend_cents,
        "supervisor_user_id": supervisor_user_id,
        "weekly_hours": calc.weekly_hours_for(effort_pct),
        "duration_days": duration_days,
        "tuition_remission_pct": calc.remission_band_pct(effort_pct),
        "insurance_eligible": calc.insurance_eligible_for(effort_pct, duration_days, policy),
        "projected_pay_period_count": 0,
        "total_stipend_cents": 0,
        "tuition_remission_cents": 0,
        "insurance_subsidy_cents": 0,
        "employee_premium_cents": 0,
        "net_term_stipend_cents": 0,
        "lifecycle_status": "DRAFT",
        "payroll_status": "NOT_SCHEDULED",
        "renewal_eligible": True,
        "submitted_by_user_id": None,
        "approved_by_user_id": None,
        "return_reason": None,
        "pay_suspension_reason": None,
        "termination_reason": None,
        "termination_date": None,
    })
    return created(serialize.appointment(row))


@bp.get("/appointments/<appointment_id>")
def read_appointment(appointment_id):
    actor_id, role = authenticate(READ_ROLES)
    appointment = queries.appointment_or_404(appointment_id)
    require_owner(actor_id, role, appointment["student_id"])
    return ok(serialize.appointment(appointment))


@bp.get("/appointments")
def list_appointments():
    actor_id, role = authenticate(READ_ROLES)
    student_id = v.query_str("student_id")
    if role == "StudentUser":
        if student_id is not None and student_id != actor_id:
            raise ApiError("ERR_NOT_RESOURCE_OWNER",
                           "A StudentUser may only list its own appointments")
        student_id = actor_id
    department_id = v.query_str("department_id")
    term_id = v.query_str("term_id")
    renewed_from = v.query_str("renewed_from_appointment_id")
    lifecycle_status = v.query_enum("lifecycle_status", LIFECYCLE_STATUSES)
    payroll_status = v.query_enum("payroll_status", PAYROLL_STATUSES)

    rows = list(db.appointments.values())
    if student_id:
        rows = [r for r in rows if r["student_id"] == student_id]
    if department_id:
        rows = [r for r in rows if r["department_id"] == department_id]
    if term_id:
        rows = [r for r in rows if r["term_id"] == term_id]
    if renewed_from:
        rows = [r for r in rows if r["renewed_from_appointment_id"] == renewed_from]
    if lifecycle_status:
        rows = [r for r in rows if r["lifecycle_status"] == lifecycle_status]
    if payroll_status:
        rows = [r for r in rows if r["payroll_status"] == payroll_status]
    page, meta = v.paginate(queries.by_created(rows))
    return ok_list([serialize.appointment(r) for r in page], meta)


# ---------------------------------------------------------------------------
# funding plan replacement (OCC)
# ---------------------------------------------------------------------------
@bp.put("/appointments/<appointment_id>/funding-plan")
def replace_funding_plan(appointment_id):
    authenticate(["DepartmentAdmin", "GrantAccountant"])
    appointment = queries.appointment_or_404(appointment_id)
    body = v.body_dict()

    raw_allocations = body.get("allocations")
    if isinstance(raw_allocations, list):
        for element in raw_allocations:
            if isinstance(element, dict):
                source_ref = v.ref_value(element, "funding_source_id")
                if source_ref is not None:
                    queries.source_or_404(source_ref)

    expected_version = v.field_int(body, "expected_appointment_version", minimum=0)
    if not isinstance(raw_allocations, list):
        raise v.invalid("Field 'allocations' must be an array")
    if not (1 <= len(raw_allocations) <= 5):
        raise v.invalid("Field 'allocations' must hold between 1 and 5 elements")
    parsed = []
    for index, element in enumerate(raw_allocations):
        if not isinstance(element, dict):
            raise v.invalid("Each element of 'allocations' must be an object")
        source_id = v.field_id(element, "funding_source_id")
        share_pct = v.field_decimal(element, "share_pct", minimum="0.01",
                                    maximum="100.00", max_decimals=2)
        is_cost_share = v.field_bool(element, "is_cost_share", required=False, default=False)
        parsed.append({
            "funding_source_id": source_id,
            "share_pct": share_pct,
            "is_cost_share": is_cost_share,
            "plan_sequence": index + 1,
        })

    if expected_version != appointment["version"]:
        raise ApiError("ERR_STALE_APPOINTMENT_VERSION",
                       "expected_appointment_version %s does not match the current version %s"
                       % (expected_version, appointment["version"]))

    _require_state(appointment, ("DRAFT", "RETURNED", "SUBMITTED"))
    _require_term_open(appointment)

    superseded = sorted(queries.active_allocations(appointment["id"]),
                        key=lambda a: (a["plan_sequence"], a["_seq"]))
    touched = effects.release_allocations(superseded, "PLAN_SUPERSEDED")

    for element in parsed:
        insert(db.funding_allocations, {
            "appointment_id": appointment["id"],
            "funding_source_id": element["funding_source_id"],
            "share_pct": element["share_pct"],
            "is_cost_share": element["is_cost_share"],
            "plan_sequence": element["plan_sequence"],
            "allocated_stipend_cents": 0,
            "allocated_remission_cents": 0,
            "disbursed_amount_cents": 0,
            "status": "PROPOSED",
            "release_reason": None,
        })
        touched.append(element["funding_source_id"])
    effects.recompute_source_balances(touched)

    force_update(appointment)
    return ok(serialize.appointment(appointment))


# ---------------------------------------------------------------------------
# submission battery
# ---------------------------------------------------------------------------
@bp.post("/appointments/<appointment_id>/submit")
def submit_appointment(appointment_id):
    actor_id, _ = authenticate(["DepartmentAdmin"])
    appointment = queries.appointment_or_404(appointment_id)
    _require_state(appointment, ("DRAFT", "RETURNED"))
    term = _require_term_open(appointment)
    student = queries.student_or_404(appointment["student_id"])

    total_effort, overlapping = effects.candidate_effort_total(student["id"], appointment)

    # 14. international hour limit
    if student["is_international"] and term["session_type"] == "IN_SESSION":
        hours = calc.hours_1dp(Decimal(total_effort) * calc.FULL_TIME_WEEKLY_HOURS
                               / Decimal(100)) + student["external_weekly_hours"]
        if hours > calc.INTERNATIONAL_MAX_WEEKLY_HOURS:
            raise ApiError("ERR_INTERNATIONAL_HOUR_LIMIT_EXCEEDED",
                           "An international student may work at most 20.0 hours per week "
                           "during an IN_SESSION term")

    # 17. aggregate effort cap
    if total_effort > student["effort_cap_pct"]:
        raise ApiError("ERR_OVER_APPOINTMENT",
                       "Aggregate effort %s exceeds the student's cap of %s"
                       % (total_effort, student["effort_cap_pct"]))

    # 18. dual-role conflict
    types = set([appointment["assistantship_type"]])
    types.update(a["assistantship_type"] for a in overlapping)
    if "TEACHING" in types and "ADMINISTRATIVE" in types:
        raise ApiError("ERR_DUAL_ROLE_CONFLICT",
                       "A student may not hold overlapping TEACHING and ADMINISTRATIVE "
                       "appointments")

    proposed = sorted([a for a in queries.allocations_of_appointment(appointment["id"])
                       if a["status"] == "PROPOSED"],
                      key=lambda a: (a["plan_sequence"], a["_seq"]))
    sources = {}
    for alloc in proposed:
        sources[alloc["id"]] = db.funding_sources.get(alloc["funding_source_id"])

    # 24. funding budget window coverage
    for alloc in proposed:
        source = sources[alloc["id"]]
        if source is None:
            continue
        if (source["budget_period_start"] > appointment["start_date"]
                or appointment["end_date"] > source["budget_period_end"]):
            raise ApiError("ERR_FUNDING_PERIOD_MISMATCH",
                           "Funding source %s does not cover the whole appointment window"
                           % source["source_code"])

    # 27. funding plan present
    if not proposed:
        raise ApiError("ERR_FUNDING_ALLOCATION_MISSING",
                       "The appointment has no proposed funding allocation")

    # 28. shares total
    share_total = sum((a["share_pct"] for a in proposed), Decimal(0))
    if share_total != Decimal("100.00"):
        raise ApiError("ERR_ALLOCATION_SHARES_INVALID",
                       "The proposed allocation shares must total exactly 100.00")

    # 29. cost-share composition
    cost_share = [a for a in proposed if a["is_cost_share"]]
    for alloc in cost_share:
        source = sources[alloc["id"]]
        if source is None or source["source_type"] != "DEPARTMENTAL_BUDGET":
            raise ApiError("ERR_COST_SHARE_SOURCE_INVALID",
                           "A cost-share allocation must reference a DEPARTMENTAL_BUDGET source")
    if cost_share and len(cost_share) == len(proposed):
        raise ApiError("ERR_COST_SHARE_SOURCE_INVALID",
                       "A plan containing a cost-share allocation must also contain a "
                       "non-cost-share allocation")

    # 30. stipend policy present
    policy = _policy_for(appointment, student)

    # 31. fellowship service conflict
    if appointment["assistantship_type"] == "TEACHING":
        for alloc in proposed:
            source = sources[alloc["id"]]
            if source is not None and source["source_type"] == "FELLOWSHIP":
                raise ApiError("ERR_FELLOWSHIP_SERVICE_CONFLICT",
                               "A FELLOWSHIP source may not fund a TEACHING appointment")

    # 34. stipend minimum
    fte_monthly = calc.rhu_cents(Decimal(appointment["monthly_stipend_cents"]) * Decimal(100)
                                 / Decimal(appointment["effort_pct"]))
    if fte_monthly < policy["min_fte_monthly_stipend_cents"]:
        raise ApiError("ERR_STIPEND_BELOW_MINIMUM",
                       "The full-time-equivalent monthly stipend %s is below the policy "
                       "minimum %s" % (fte_monthly, policy["min_fte_monthly_stipend_cents"]))

    # 35. grant effort cap
    for alloc in proposed:
        source = sources[alloc["id"]]
        if source is None or source["source_type"] != "GRANT":
            continue
        drawn = Decimal(appointment["effort_pct"]) * alloc["share_pct"] / Decimal(100)
        if drawn > Decimal(source["grant_effort_cap_pct"]):
            raise ApiError("ERR_GRANT_EFFORT_CAP_EXCEEDED",
                           "Allocation draws %s effort from grant %s whose cap is %s"
                           % (drawn, source["source_code"], source["grant_effort_cap_pct"]))

    _apply_calculations(appointment, student, policy, term, {
        "lifecycle_status": "SUBMITTED",
        "submitted_by_user_id": actor_id,
        "return_reason": None,
    })
    effects.recompute_student_effort(student)
    return ok(serialize.appointment(appointment))


# ---------------------------------------------------------------------------
# review loop
# ---------------------------------------------------------------------------
@bp.post("/appointments/<appointment_id>/return")
def return_appointment(appointment_id):
    authenticate(["GradSchoolAdmin"])
    appointment = queries.appointment_or_404(appointment_id)
    body = v.body_dict()
    return_reason = v.field_str(body, "return_reason")
    _require_state(appointment, ("SUBMITTED", "FUNDING_VERIFIED"))
    _require_term_open(appointment)

    force_update(appointment, lifecycle_status="RETURNED", return_reason=return_reason)
    committed = sorted([a for a in queries.allocations_of_appointment(appointment["id"])
                        if a["status"] == "COMMITTED"],
                       key=lambda a: (a["plan_sequence"], a["_seq"]))
    effects.release_allocations(committed, "APPOINTMENT_RETURNED")
    student = db.students.get(appointment["student_id"])
    if student is not None:
        effects.recompute_student_effort(student)
    return ok(serialize.appointment(appointment))


@bp.post("/appointments/<appointment_id>/verify-funding")
def verify_funding(appointment_id):
    authenticate(["GrantAccountant"])
    appointment = queries.appointment_or_404(appointment_id)
    _require_state(appointment, ("SUBMITTED",))
    _require_term_open(appointment)

    proposed = sorted([a for a in queries.allocations_of_appointment(appointment["id"])
                       if a["status"] == "PROPOSED"],
                      key=lambda a: (a["plan_sequence"], a["_seq"]))

    # 12. funding source active
    for alloc in proposed:
        source = db.funding_sources.get(alloc["funding_source_id"])
        if source is None or source["status"] != "ACTIVE":
            raise ApiError("ERR_FUNDING_SOURCE_NOT_ACTIVE",
                           "Every funding source of the plan must be ACTIVE")

    # 36. funding sufficiency
    charges = {}
    for alloc in proposed:
        charges[alloc["funding_source_id"]] = (
            charges.get(alloc["funding_source_id"], 0)
            + alloc["allocated_stipend_cents"] + alloc["allocated_remission_cents"])
    for source_id in sorted(charges):
        source = db.funding_sources[source_id]
        if source["available_amount_cents"] - charges[source_id] < 0:
            raise ApiError("ERR_FUNDING_INSUFFICIENT",
                           "Funding source %s cannot bear the charge" % source["source_code"])

    force_update(appointment, lifecycle_status="FUNDING_VERIFIED")
    touched = []
    for alloc in proposed:
        update(alloc, status="COMMITTED")
        touched.append(alloc["funding_source_id"])
    effects.recompute_source_balances(touched)
    return ok(serialize.appointment(appointment))


@bp.post("/appointments/<appointment_id>/approve")
def approve_appointment(appointment_id):
    actor_id, _ = authenticate(["GradSchoolAdmin"])
    appointment = queries.appointment_or_404(appointment_id)
    _require_state(appointment, ("FUNDING_VERIFIED",))
    _require_term_open(appointment)
    student = queries.student_or_404(appointment["student_id"])

    if student["sap_status"] != "SATISFACTORY":
        raise ApiError("ERR_SAP_NOT_SATISFACTORY",
                       "The student's sap_status must be SATISFACTORY to approve")
    if (student["cap_override_by_user_id"] is not None
            and student["cap_override_by_user_id"] == actor_id):
        raise ApiError("ERR_SEGREGATION_OF_DUTIES",
                       "The user who raised the student's effort cap may not approve "
                       "that student's appointment")

    force_update(appointment, lifecycle_status="APPROVED", approved_by_user_id=actor_id)
    return ok(serialize.appointment(appointment))


@bp.post("/appointments/<appointment_id>/activate")
def activate_appointment(appointment_id):
    authenticate(["GradSchoolAdmin"])
    appointment = queries.appointment_or_404(appointment_id)
    _require_state(appointment, ("APPROVED",))
    _require_term_open(appointment)
    force_update(appointment, lifecycle_status="ACTIVE")
    return ok(serialize.appointment(appointment))


# ---------------------------------------------------------------------------
# payroll axis
# ---------------------------------------------------------------------------
@bp.post("/appointments/<appointment_id>/schedule-payroll")
def schedule_payroll(appointment_id):
    authenticate(["GradSchoolAdmin"])
    appointment = queries.appointment_or_404(appointment_id)
    if appointment["payroll_status"] != "NOT_SCHEDULED":
        raise ApiError("ERR_INVALID_APPOINTMENT_STATE",
                       "payroll_status must be NOT_SCHEDULED to schedule payroll, not %s"
                       % appointment["payroll_status"])
    _require_state(appointment, ("ACTIVE",))
    term = _require_term_open(appointment)

    allocations = queries.active_allocations(appointment["id"])
    periods = queries.pay_periods_of_term(term["id"])
    for row in calc.pay_schedule(appointment, periods, term["proration_method"]):
        ordered, amounts = calc.split_by_share(row["gross_amount_cents"], allocations)
        split = [{
            "funding_allocation_id": alloc["id"],
            "plan_sequence": alloc["plan_sequence"],
            "amount_cents": amounts.get(alloc["id"], 0),
        } for alloc in ordered]
        insert(db.stipend_disbursements, {
            "appointment_id": appointment["id"],
            "pay_period_id": row["pay_period"]["id"],
            "proration_method_applied": term["proration_method"],
            "covered_units": row["covered_units"],
            "period_units": row["period_units"],
            "gross_amount_cents": row["gross_amount_cents"],
            "allocation_split": split,
            "status": "SCHEDULED",
            "paid_at": None,
            "voided_at": None,
            "reversed_at": None,
            "reversal_reason": None,
        })
    force_update(appointment, payroll_status="SCHEDULED")
    return ok(serialize.appointment(appointment))


@bp.post("/appointments/<appointment_id>/suspend-pay")
def suspend_pay(appointment_id):
    authenticate(["GradSchoolAdmin"])
    appointment = queries.appointment_or_404(appointment_id)
    body = v.body_dict()
    reason = v.field_str(body, "pay_suspension_reason")
    if appointment["payroll_status"] not in ("SCHEDULED", "PARTIALLY_DISBURSED"):
        raise ApiError("ERR_INVALID_APPOINTMENT_STATE",
                       "payroll_status %s does not permit suspension"
                       % appointment["payroll_status"])
    if appointment["lifecycle_status"] not in ("ACTIVE", "NON_RENEWAL_PENDING"):
        raise ApiError("ERR_INVALID_APPOINTMENT_STATE",
                       "lifecycle_status %s does not permit pay suspension"
                       % appointment["lifecycle_status"])
    force_update(appointment, payroll_status="PAY_SUSPENDED",
                 pay_suspension_reason=reason)
    return ok(serialize.appointment(appointment))


@bp.post("/appointments/<appointment_id>/resume-pay")
def resume_pay(appointment_id):
    authenticate(["GradSchoolAdmin"])
    appointment = queries.appointment_or_404(appointment_id)
    if appointment["payroll_status"] != "PAY_SUSPENDED":
        raise ApiError("ERR_INVALID_APPOINTMENT_STATE",
                       "payroll_status must be PAY_SUSPENDED to resume, not %s"
                       % appointment["payroll_status"])
    paid = [d for d in queries.disbursements_of_appointment(appointment["id"])
            if d["status"] == "PAID"]
    force_update(appointment,
                 payroll_status="PARTIALLY_DISBURSED" if paid else "SCHEDULED",
                 pay_suspension_reason=None)
    return ok(serialize.appointment(appointment))


# ---------------------------------------------------------------------------
# termination cascade (PRD 3.8)
# ---------------------------------------------------------------------------
@bp.post("/appointments/<appointment_id>/terminate")
def terminate_appointment(appointment_id):
    authenticate(["GradSchoolAdmin"])
    appointment = queries.appointment_or_404(appointment_id)
    body = v.body_dict()
    termination_reason = v.field_str(body, "termination_reason")
    _require_state(appointment, ("APPROVED", "ACTIVE", "NON_RENEWAL_PENDING"))
    term = _term_of(appointment)
    if term is None or term["status"] not in ("OPEN", "PAYROLL_LOCKED"):
        raise ApiError("ERR_INVALID_TERM_STATE",
                       "Termination requires the term to be OPEN or PAYROLL_LOCKED")

    termination_date = today()
    remission = appointment["tuition_remission_cents"]
    if termination_date.isoformat() < term["remission_drop_deadline"]:
        remission = 0

    force_update(appointment,
                 lifecycle_status="TERMINATED",
                 termination_reason=termination_reason,
                 termination_date=termination_date.isoformat(),
                 payroll_status="PAY_VOIDED",
                 tuition_remission_cents=remission)

    # scheduled pay is voided; gross amounts are retained for audit
    for disbursement in sorted(queries.disbursements_of_appointment(appointment["id"]),
                               key=lambda d: d["_seq"]):
        if disbursement["status"] == "SCHEDULED":
            update(disbursement, status="VOIDED", voided_at=now_iso())

    paid_by_allocation = {}
    for disbursement in queries.disbursements_of_appointment(appointment["id"]):
        if disbursement["status"] != "PAID":
            continue
        for element in disbursement["allocation_split"]:
            key = element["funding_allocation_id"]
            paid_by_allocation[key] = paid_by_allocation.get(key, 0) + element["amount_cents"]

    allocations = sorted(queries.allocations_of_appointment(appointment["id"]),
                         key=lambda a: (a["plan_sequence"], a["_seq"]))
    active = [a for a in allocations if a["status"] in calc.ACTIVE_ALLOCATION_STATUSES]
    per_remission = effects.split_remission_over(remission, active)

    touched = []
    for alloc in allocations:
        if alloc["status"] not in calc.ACTIVE_ALLOCATION_STATUSES:
            continue
        stipend = paid_by_allocation.get(alloc["id"], 0)
        remitted = per_remission.get(alloc["id"], 0)
        fields = {
            "allocated_stipend_cents": stipend,
            "allocated_remission_cents": remitted,
        }
        if alloc["status"] == "COMMITTED" and stipend + remitted == 0:
            fields["status"] = "RELEASED"
            fields["release_reason"] = "APPOINTMENT_TERMINATED"
        update(alloc, **fields)
        touched.append(alloc["funding_source_id"])

    effects.recompute_source_balances(touched)
    effects.auto_reinstate(touched)

    student = db.students.get(appointment["student_id"])
    if student is not None:
        effects.recompute_student_aggregates(student, term["tax_calendar_year"])
    return ok(serialize.appointment(appointment))
