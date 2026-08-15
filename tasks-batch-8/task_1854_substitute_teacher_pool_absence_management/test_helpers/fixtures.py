"""Composite setup helpers for multi-step test prerequisites.

Every helper builds preconditions from scratch against an empty database using
only endpoints declared in PRD 4 (the harness restarts the server before each
test). Internally helpers use get_success_data() so a setup failure surfaces
as a clear "Setup failed" message rather than a confusing assertion error.

Identity threading: Teacher/SchoolCoordinator calls use headers built from the
acting StaffMember's id; Substitute calls use the acting Substitute's id
(PRD 2.1). Opaque roles (DistrictAdmin, PayrollClerk) use the shared constant.
"""
from datetime import date, timedelta
from typing import Any, Dict, List, Optional, Sequence, Tuple

from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import TEST_DEFAULTS
from .factories import (
    create_absence_payload,
    create_assignment_payload,
    create_clearance_payload,
    create_coverage_payload,
    create_dispatch_batch_payload,
    create_district_payload,
    create_mark_payload,
    create_payroll_period_payload,
    create_performance_flag_payload,
    create_qualification_payload,
    create_school_payload,
    create_staff_member_payload,
    create_substitute_payload,
    create_timesheet_payload,
)
from .test_users import (
    TEST_USERS,
    make_coordinator_headers,
    make_substitute_headers,
    make_teacher_headers,
)

ADMIN = TEST_USERS["district_admin_headers"]
CLERK = TEST_USERS["payroll_clerk_headers"]


# ---------------------------------------------------------------------------
# Pure date helpers
# ---------------------------------------------------------------------------

def weekday_dates(start_date: str, end_date: str) -> List[str]:
    """All Monday-Friday ISO dates inside the inclusive [start, end] range."""
    start = date.fromisoformat(start_date)
    end = date.fromisoformat(end_date)
    out = []
    cursor = start
    while cursor <= end:
        if cursor.weekday() < 5:
            out.append(cursor.isoformat())
        cursor += timedelta(days=1)
    return out


def weekday_count(start_date: str, end_date: str) -> int:
    return len(weekday_dates(start_date, end_date))


# ---------------------------------------------------------------------------
# Atomic step helpers (one endpoint call each, success-asserted)
# ---------------------------------------------------------------------------

def set_logical_clock(to_iso8601: str) -> None:
    """Set the logical clock (PRD 2.5)."""
    get_success_data(api_client.set_clock({"to_iso8601": to_iso8601}, ADMIN))


def make_district(**config_overrides) -> Dict[str, Any]:
    return get_success_data(
        api_client.create_district(create_district_payload(**config_overrides), ADMIN)
    )


def make_school(
    district_id: str,
    *,
    name: str = "S1",
    budget: int = TEST_DEFAULTS["SCHOOL_BUDGET_CENTS"],
    tier: Optional[str] = None,
) -> Dict[str, Any]:
    payload = create_school_payload(
        district_id, name=name, coverage_budget_total_cents=budget
    )
    if tier is not None:
        payload["hard_to_fill_tier"] = tier
    return get_success_data(api_client.create_school(payload, ADMIN))


def make_staff(
    school_id: str,
    *,
    full_name: str = "Teach One",
    subject: str = "MATH",
    grade_band: str = "HIGH",
    is_coordinator: bool = False,
) -> Dict[str, Any]:
    payload = create_staff_member_payload(
        school_id,
        full_name=full_name,
        subject=subject,
        grade_band=grade_band,
        is_coordinator=is_coordinator,
    )
    return get_success_data(api_client.create_staff_member(payload, ADMIN))


def make_coordinator(school_id: str, *, full_name: str = "Coord One") -> Dict[str, Any]:
    return make_staff(
        school_id,
        full_name=full_name,
        subject="ADMIN",
        grade_band="HIGH",
        is_coordinator=True,
    )


def onboard_substitute(
    *,
    full_name: str = "Sub A",
    rate_cents: int = TEST_DEFAULTS["SUB_BASE_DAILY_RATE_CENTS"],
    qualifications: Sequence[Tuple[str, str]] = (("MATH", "HIGH"),),
    background_expires_on: str = TEST_DEFAULTS["CLEARANCE_EXPIRES_ON"],
    credential_expires_on: str = TEST_DEFAULTS["CLEARANCE_EXPIRES_ON"],
    activate: bool = True,
) -> Dict[str, Any]:
    """Register a substitute, grant qualifications, register and verify the
    required BACKGROUND_CHECK + TEACHING_CREDENTIAL clearances, and activate.
    Returns the substitute as of the final GET."""
    sub = get_success_data(
        api_client.create_substitute(
            create_substitute_payload(full_name=full_name, base_daily_rate_cents=rate_cents),
            ADMIN,
        )
    )
    for subject, band in qualifications:
        get_success_data(
            api_client.create_qualification(
                create_qualification_payload(sub["id"], subject=subject, grade_band=band),
                ADMIN,
            )
        )
    for clearance_type, expires_on in (
        ("BACKGROUND_CHECK", background_expires_on),
        ("TEACHING_CREDENTIAL", credential_expires_on),
    ):
        clearance = get_success_data(
            api_client.create_clearance(
                create_clearance_payload(
                    sub["id"], clearance_type=clearance_type, expires_on=expires_on
                ),
                ADMIN,
            )
        )
        get_success_data(api_client.verify_clearance(clearance["id"], ADMIN))
    if activate:
        get_success_data(api_client.activate_substitute(sub["id"], ADMIN))
    return get_success_data(api_client.get_substitute(sub["id"], ADMIN))


def report_absence(
    staff_member: Dict[str, Any],
    *,
    start_date: str = "2026-08-03",
    end_date: str = "2026-08-03",
    absence_type: str = "SICK",
    required_subject: str = "MATH",
    required_grade_band: str = "HIGH",
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """Report an absence. Defaults to the owning teacher's own headers."""
    payload = create_absence_payload(
        staff_member["id"],
        start_date=start_date,
        end_date=end_date,
        absence_type=absence_type,
        required_subject=required_subject,
        required_grade_band=required_grade_band,
    )
    hdrs = headers or make_teacher_headers(staff_member["id"])
    return get_success_data(api_client.create_absence(payload, hdrs))


def review_absence(absence_id: str, decision: str) -> Dict[str, Any]:
    return get_success_data(
        api_client.review_absence(absence_id, {"decision": decision}, ADMIN)
    )


def offer_assignment(
    absence_id: str,
    substitute_id: str,
    headers: Dict[str, str],
) -> Dict[str, Any]:
    """Manual offer (PRD 3.4). `headers` decides coordinator vs admin actor."""
    return get_success_data(
        api_client.create_assignment(
            create_assignment_payload(absence_id, substitute_id), headers
        )
    )


def respond_offer(assignment_id: str, substitute_id: str, decision: str) -> Dict[str, Any]:
    return get_success_data(
        api_client.respond_assignment(
            assignment_id, {"decision": decision}, make_substitute_headers(substitute_id)
        )
    )


def accept_offer(assignment_id: str, substitute_id: str) -> Dict[str, Any]:
    return respond_offer(assignment_id, substitute_id, "ACCEPT")


def decline_offer(assignment_id: str, substitute_id: str) -> Dict[str, Any]:
    return respond_offer(assignment_id, substitute_id, "DECLINE")


def cancel_assignment_ok(assignment_id: str, headers: Dict[str, str]) -> Dict[str, Any]:
    return get_success_data(api_client.cancel_assignment(assignment_id, headers))


def cancel_absence_ok(absence_id: str, headers: Dict[str, str]) -> Dict[str, Any]:
    return get_success_data(api_client.cancel_absence(absence_id, headers))


def report_outcome(assignment_id: str, outcome: str, headers: Dict[str, str]) -> Dict[str, Any]:
    return get_success_data(
        api_client.report_assignment_outcome(assignment_id, {"outcome": outcome}, headers)
    )


def submit_timesheet(
    assignment_id: str,
    substitute_id: str,
    work_date: str,
    hours_worked: float = 8.0,
) -> Dict[str, Any]:
    return get_success_data(
        api_client.create_timesheet(
            create_timesheet_payload(assignment_id, work_date, hours_worked=hours_worked),
            make_substitute_headers(substitute_id),
        )
    )


def review_timesheet(timesheet_id: str, decision: str, headers: Dict[str, str]) -> Dict[str, Any]:
    return get_success_data(
        api_client.review_timesheet(timesheet_id, {"decision": decision}, headers)
    )


def verify_assignment_ok(assignment_id: str, headers: Dict[str, str]) -> Dict[str, Any]:
    return get_success_data(api_client.verify_assignment(assignment_id, headers))


def run_dispatch_batch(district_id: str, run_for_date: Optional[str] = None) -> Dict[str, Any]:
    payload = create_dispatch_batch_payload(district_id)
    if run_for_date is not None:
        payload["run_for_date"] = run_for_date
    return get_success_data(api_client.create_dispatch_batch(payload, ADMIN))


def propose_coverage(
    absence_id: str,
    staff_member_id: str,
    coverage_date: str,
    periods: int,
    headers: Dict[str, str],
) -> Dict[str, Any]:
    return get_success_data(
        api_client.create_internal_coverage(
            create_coverage_payload(
                absence_id, staff_member_id, coverage_date=coverage_date, periods=periods
            ),
            headers,
        )
    )


def review_coverage(coverage_id: str, decision: str) -> Dict[str, Any]:
    """District review of a coverage proposal (DistrictAdmin)."""
    return get_success_data(
        api_client.review_internal_coverage(coverage_id, {"decision": decision}, ADMIN)
    )


def confirm_coverage_worked(coverage_id: str, headers: Dict[str, str]) -> Dict[str, Any]:
    return get_success_data(api_client.confirm_coverage_worked(coverage_id, headers))


def cancel_coverage(coverage_id: str, headers: Dict[str, str]) -> Dict[str, Any]:
    return get_success_data(api_client.cancel_internal_coverage(coverage_id, headers))


def open_payroll_period(
    district_id: str, period_start: str, period_end: str
) -> Dict[str, Any]:
    return get_success_data(
        api_client.create_payroll_period(
            create_payroll_period_payload(
                district_id, period_start=period_start, period_end=period_end
            ),
            CLERK,
        )
    )


def export_period(payroll_period_id: str) -> Dict[str, Any]:
    return get_success_data(api_client.export_payroll_period(payroll_period_id, CLERK))


def raise_flag(
    substitute_id: str,
    school_id: str,
    flag_type: str,
    severity: str,
    headers: Dict[str, str],
    assignment_id: Optional[str] = None,
) -> Dict[str, Any]:
    payload = create_performance_flag_payload(
        substitute_id, school_id, flag_type=flag_type, severity=severity
    )
    if assignment_id is not None:
        payload["assignment_id"] = assignment_id
    return get_success_data(api_client.create_performance_flag(payload, headers))


def review_flag(flag_id: str, decision: str) -> Dict[str, Any]:
    return get_success_data(
        api_client.review_performance_flag(flag_id, {"decision": decision}, ADMIN)
    )


def create_mark_ok(
    school_id: str,
    substitute_id: str,
    mark_type: str,
    headers: Dict[str, str],
    *,
    reason: Optional[str] = None,
    priority_rank: Optional[int] = None,
) -> Dict[str, Any]:
    payload = create_mark_payload(school_id, substitute_id, mark_type=mark_type)
    if reason is not None:
        payload["reason"] = reason
    if priority_rank is not None:
        payload["priority_rank"] = priority_rank
    return get_success_data(api_client.create_mark(payload, headers))


def lift_mark_ok(mark_id: str, headers: Dict[str, str]) -> Dict[str, Any]:
    return get_success_data(api_client.lift_mark(mark_id, headers))


def get_school(school_id: str) -> Dict[str, Any]:
    return get_success_data(api_client.get_school(school_id, ADMIN))


def get_absence(absence_id: str) -> Dict[str, Any]:
    return get_success_data(api_client.get_absence(absence_id, ADMIN))


def get_assignment(assignment_id: str) -> Dict[str, Any]:
    return get_success_data(api_client.get_assignment(assignment_id, ADMIN))


def get_substitute(substitute_id: str) -> Dict[str, Any]:
    return get_success_data(api_client.get_substitute(substitute_id, ADMIN))


def get_timesheet(timesheet_id: str) -> Dict[str, Any]:
    return get_success_data(api_client.get_timesheet(timesheet_id, ADMIN))


# ---------------------------------------------------------------------------
# Composite worlds
# ---------------------------------------------------------------------------

def basic_world(
    *,
    district_config: Optional[Dict[str, Any]] = None,
    school_name: str = "S1",
    budget: int = TEST_DEFAULTS["SCHOOL_BUDGET_CENTS"],
    tier: Optional[str] = None,
    teacher_name: str = "Teach One",
    teacher_subject: str = "MATH",
    teacher_grade: str = "HIGH",
    with_coordinator: bool = True,
    clock: Optional[str] = TEST_DEFAULTS["CLOCK_BEFORE_ABSENCES"],
) -> Dict[str, Any]:
    """District + school + one teacher (+ coordinator) + logical clock set."""
    district = make_district(**(district_config or {}))
    school = make_school(district["id"], name=school_name, budget=budget, tier=tier)
    teacher = make_staff(
        school["id"], full_name=teacher_name, subject=teacher_subject, grade_band=teacher_grade
    )
    coordinator = make_coordinator(school["id"]) if with_coordinator else None
    if clock is not None:
        set_logical_clock(clock)
    return {
        "district": district,
        "school": school,
        "teacher": teacher,
        "coordinator": coordinator,
    }


def world_with_active_sub(**kwargs) -> Dict[str, Any]:
    """basic_world plus one fully onboarded ACTIVE substitute."""
    sub_rate = kwargs.pop("sub_rate", TEST_DEFAULTS["SUB_BASE_DAILY_RATE_CENTS"])
    sub_name = kwargs.pop("sub_name", "Sub A")
    qualifications = kwargs.pop("qualifications", (("MATH", "HIGH"),))
    background_expires_on = kwargs.pop(
        "background_expires_on", TEST_DEFAULTS["CLEARANCE_EXPIRES_ON"]
    )
    credential_expires_on = kwargs.pop(
        "credential_expires_on", TEST_DEFAULTS["CLEARANCE_EXPIRES_ON"]
    )
    ctx = basic_world(**kwargs)
    ctx["sub"] = onboard_substitute(
        full_name=sub_name,
        rate_cents=sub_rate,
        qualifications=qualifications,
        background_expires_on=background_expires_on,
        credential_expires_on=credential_expires_on,
    )
    return ctx


def accepted_assignment_ctx(
    *,
    start_date: str = "2026-08-03",
    end_date: str = "2026-08-03",
    absence_type: str = "SICK",
    required_subject: str = "MATH",
    required_grade_band: str = "HIGH",
    offer_via: str = "coordinator",
    **world_kwargs,
) -> Dict[str, Any]:
    """Full chain: world + ACTIVE sub + absence (+ district approval when the
    range is longer than the district's approval threshold) + manual offer +
    substitute ACCEPT. Returns ctx with absence and assignment keys."""
    ctx = world_with_active_sub(**world_kwargs)
    teacher = ctx["teacher"]
    absence = report_absence(
        teacher,
        start_date=start_date,
        end_date=end_date,
        absence_type=absence_type,
        required_subject=required_subject,
        required_grade_band=required_grade_band,
    )
    approval_threshold = ctx["district"]["long_term_approval_days"]
    if absence["total_days"] > approval_threshold:
        absence = review_absence(absence["id"], "APPROVE")
    offer_headers = (
        make_coordinator_headers(ctx["coordinator"]["id"]) if offer_via == "coordinator" else ADMIN
    )
    assignment = offer_assignment(absence["id"], ctx["sub"]["id"], offer_headers)
    assignment = accept_offer(assignment["id"], ctx["sub"]["id"])
    ctx["absence"] = get_absence(absence["id"])
    ctx["assignment"] = assignment
    return ctx


def worked_assignment_ctx(
    *,
    report_at: Optional[str] = None,
    **kwargs,
) -> Dict[str, Any]:
    """accepted_assignment_ctx + clock advanced past the first day + report
    outcome WORKED. `report_at` defaults to 18:00 on the absence's end date."""
    ctx = accepted_assignment_ctx(**kwargs)
    assignment = ctx["assignment"]
    if report_at is None:
        report_at = f"{assignment['end_date']}T18:00:00Z"
    set_logical_clock(report_at)
    coord_headers = make_coordinator_headers(ctx["coordinator"]["id"])
    ctx["assignment"] = report_outcome(assignment["id"], "WORKED", coord_headers)
    return ctx


def approve_timesheets_for_dates(
    ctx: Dict[str, Any],
    work_dates: Sequence[str],
    *,
    hours_worked: float = 8.0,
    approve: bool = True,
) -> List[Dict[str, Any]]:
    """Submit (and optionally approve) one timesheet per listed date for the
    ctx assignment. Returns the timesheets in submission order."""
    coord_headers = make_coordinator_headers(ctx["coordinator"]["id"])
    sheets = []
    for work_date in work_dates:
        sheet = submit_timesheet(
            ctx["assignment"]["id"], ctx["sub"]["id"], work_date, hours_worked
        )
        if approve:
            sheet = review_timesheet(sheet["id"], "APPROVE", coord_headers)
        sheets.append(sheet)
    return sheets


def verified_assignment_ctx(
    *,
    approved_dates: Optional[Sequence[str]] = None,
    rejected_dates: Sequence[str] = (),
    verify: bool = True,
    **kwargs,
) -> Dict[str, Any]:
    """worked_assignment_ctx + timesheets for the listed dates (default: every
    weekday of the absence range) approved in date order, `rejected_dates`
    submitted then rejected, then assignment verification."""
    ctx = worked_assignment_ctx(**kwargs)
    assignment = ctx["assignment"]
    if approved_dates is None:
        approved_dates = weekday_dates(assignment["start_date"], assignment["end_date"])
    coord_headers = make_coordinator_headers(ctx["coordinator"]["id"])
    ctx["timesheets"] = approve_timesheets_for_dates(ctx, approved_dates)
    for work_date in rejected_dates:
        sheet = submit_timesheet(assignment["id"], ctx["sub"]["id"], work_date)
        review_timesheet(sheet["id"], "REJECT", coord_headers)
    if verify:
        ctx["assignment"] = verify_assignment_ok(assignment["id"], coord_headers)
        ctx["absence"] = get_absence(ctx["absence"]["id"])
    return ctx


def unfilled_absence_ctx(
    *,
    start_date: str = "2026-08-03",
    end_date: str = "2026-08-03",
    required_subject: str = "SCIENCE",
    required_grade_band: str = "HIGH",
    teacher_subject: str = "SCIENCE",
    covering_teacher: bool = True,
    run_for_date: Optional[str] = None,
    clock: Optional[str] = TEST_DEFAULTS["CLOCK_BEFORE_ABSENCES"],
    **world_kwargs,
) -> Dict[str, Any]:
    """Absence with an empty substitute pool driven to UNFILLED by one
    dispatch batch whose run date is on/after the absence start (the batch
    marks cutoff-passed absences UNFILLED and creates offers for eligible open
    absences; the empty pool produces no offer)."""
    ctx = basic_world(
        teacher_subject=teacher_subject, clock=clock, **world_kwargs
    )
    if covering_teacher:
        ctx["covering_teacher"] = make_staff(
            ctx["school"]["id"], full_name="Teach Two", subject="MATH", grade_band="HIGH"
        )
    ctx["absence"] = report_absence(
        ctx["teacher"],
        start_date=start_date,
        end_date=end_date,
        required_subject=required_subject,
        required_grade_band=required_grade_band,
    )
    ctx["batch"] = run_dispatch_batch(
        ctx["district"]["id"], run_for_date or end_date
    )
    ctx["absence"] = get_absence(ctx["absence"]["id"])
    return ctx
