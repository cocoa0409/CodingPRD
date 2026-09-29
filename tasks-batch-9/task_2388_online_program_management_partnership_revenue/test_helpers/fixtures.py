"""Scenario builders that drive the API through the PRD's documented workflows.

Every builder speaks to the API only through the public endpoints, uses the
lenient success reader so that a builder never masks the assertion a test is
really making, and accepts `**overrides` so a test can vary one input.

The composite builders at the bottom assemble the states that several tests
share: an executed contract, a launched program with an approved course, an
active paid enrollment, and a cut September settlement statement.
"""

from __future__ import annotations

from typing import Any, Dict, Optional, Sequence

from prd_bench_local_runner.testing import get_success_data

from . import factories as f
from .api_client import ApiClient
from .constants import DEFAULT_CLOCK_UTC
from .test_users import (
    COMPLIANCE_AUDITOR_USER_ID,
    make_bursar_headers,
    make_compliance_auditor_headers,
    make_faculty_chair_headers,
    make_partner_account_lead_headers,
    make_platform_admin_headers,
    make_provost_headers,
)

# Instants used by the shared scenarios, all expressed on the logical clock.
CLOCK_AUG_1 = DEFAULT_CLOCK_UTC
CLOCK_AUG_15 = "2026-08-15T09:30:00Z"
CLOCK_SEP_5 = "2026-09-05T00:00:00Z"
CLOCK_SEP_8 = "2026-09-08T00:00:00Z"
CLOCK_OCT_1 = "2026-10-01T00:00:00Z"
CLOCK_OCT_16 = "2026-10-16T00:00:00Z"
CLOCK_NOV_1 = "2026-11-01T00:00:00Z"
CLOCK_DEC_31 = "2026-12-31T00:00:00Z"
CLOCK_PAST_EXPIRY = "2033-08-01T00:00:00Z"

FACULTY_APPROVER_NAME = "Dr. Imani Osei"


# --- Logical clock --------------------------------------------------------


def set_clock(api: ApiClient, instant: str) -> Dict[str, Any]:
    return get_success_data(api.set_clock(instant, headers=make_platform_admin_headers()))


# --- Reads ----------------------------------------------------------------


def read_partnership(api: ApiClient, partnership_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_partnership(partnership_id, headers=make_bursar_headers()))


def read_program(api: ApiClient, program_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_program(program_id, headers=make_provost_headers()))


def read_course(api: ApiClient, course_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_course(course_id, headers=make_provost_headers()))


def read_counselor(api: ApiClient, counselor_id: str) -> Dict[str, Any]:
    return get_success_data(
        api.get_enrollment_counselor(counselor_id, headers=make_provost_headers())
    )


def read_lead(api: ApiClient, lead_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_lead(lead_id, headers=make_provost_headers()))


def read_enrollment(api: ApiClient, enrollment_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_enrollment(enrollment_id, headers=make_provost_headers()))


def read_statement(api: ApiClient, statement_id: str) -> Dict[str, Any]:
    return get_success_data(
        api.get_remittance_statement(statement_id, headers=make_provost_headers())
    )


def current_partnership_version(api: ApiClient, partnership_id: str) -> int:
    return read_partnership(api, partnership_id)["version"]


# --- Partnership ----------------------------------------------------------


def register_partnership(api: ApiClient, **overrides: Any) -> Dict[str, Any]:
    """Register a partnership; it lands in DRAFT with version 1."""
    return get_success_data(
        api.create_partnership(f.partnership_payload(**overrides), headers=make_platform_admin_headers())
    )


def submit_partnership_for_review(api: ApiClient, partnership_id: str) -> Dict[str, Any]:
    return get_success_data(
        api.post_contract_action(
            partnership_id,
            f.contract_action_payload("SUBMIT_FOR_REVIEW"),
            headers=make_partner_account_lead_headers(partnership_id),
        )
    )


def execute_partnership(
    api: ApiClient, partnership_id: str, executed_date: str = "2026-08-01"
) -> Dict[str, Any]:
    return get_success_data(
        api.post_contract_action(
            partnership_id,
            f.contract_action_payload("EXECUTE", executed_date=executed_date),
            headers=make_provost_headers(),
        )
    )


def wind_down_partnership(api: ApiClient, partnership_id: str, **overrides: Any) -> Dict[str, Any]:
    payload = f.contract_action_payload(
        "WIND_DOWN",
        wind_down_reason="Partner exit agreed",
        wind_down_effective_date="2026-08-15",
        **overrides,
    )
    return get_success_data(
        api.post_contract_action(partnership_id, payload, headers=make_provost_headers())
    )


def create_executed_partnership(api: ApiClient, **overrides: Any) -> Dict[str, Any]:
    """Register, submit for review and execute a partnership in one step."""
    partnership = register_partnership(api, **overrides)
    submit_partnership_for_review(api, partnership["id"])
    return execute_partnership(api, partnership["id"])


# --- Program --------------------------------------------------------------


def create_program(api: ApiClient, partnership_id: str, **overrides: Any) -> Dict[str, Any]:
    return get_success_data(
        api.create_program(
            f.program_payload(partnership_id, **overrides),
            headers=make_partner_account_lead_headers(partnership_id),
        )
    )


def submit_program(api: ApiClient, partnership_id: str, program_id: str, **overrides: Any) -> Dict[str, Any]:
    return get_success_data(
        api.post_program_lifecycle_action(
            program_id,
            f.lifecycle_action_payload("SUBMIT", **overrides),
            headers=make_partner_account_lead_headers(partnership_id),
        )
    )


def approve_program(api: ApiClient, program_id: str) -> Dict[str, Any]:
    return get_success_data(
        api.post_program_lifecycle_action(
            program_id, f.lifecycle_action_payload("APPROVE"), headers=make_provost_headers()
        )
    )


def launch_program(api: ApiClient, partnership_id: str, program_id: str) -> Dict[str, Any]:
    return get_success_data(
        api.post_program_lifecycle_action(
            program_id,
            f.lifecycle_action_payload("LAUNCH"),
            headers=make_partner_account_lead_headers(partnership_id),
        )
    )


def suspend_program(api: ApiClient, program_id: str) -> Dict[str, Any]:
    return get_success_data(
        api.post_program_lifecycle_action(
            program_id, f.lifecycle_action_payload("SUSPEND"), headers=make_provost_headers()
        )
    )


def resume_program(api: ApiClient, program_id: str) -> Dict[str, Any]:
    return get_success_data(
        api.post_program_lifecycle_action(
            program_id, f.lifecycle_action_payload("RESUME"), headers=make_provost_headers()
        )
    )


def begin_teach_out(api: ApiClient, program_id: str, **overrides: Any) -> Dict[str, Any]:
    return get_success_data(
        api.post_program_lifecycle_action(
            program_id,
            f.lifecycle_action_payload("BEGIN_TEACH_OUT", **overrides),
            headers=make_provost_headers(),
        )
    )


# --- Course ---------------------------------------------------------------


def add_course(api: ApiClient, partnership_id: str, program_id: str, **overrides: Any) -> Dict[str, Any]:
    return get_success_data(
        api.create_course(
            program_id,
            f.course_payload(**overrides),
            headers=make_partner_account_lead_headers(partnership_id),
        )
    )


def start_course_design(api: ApiClient, partnership_id: str, course_id: str) -> Dict[str, Any]:
    return get_success_data(
        api.post_course_design_action(
            course_id,
            f.design_action_payload("START_DESIGN"),
            headers=make_partner_account_lead_headers(partnership_id),
        )
    )


def submit_course_for_faculty_review(
    api: ApiClient, partnership_id: str, course_id: str
) -> Dict[str, Any]:
    return get_success_data(
        api.post_course_design_action(
            course_id,
            f.design_action_payload("SUBMIT_FOR_FACULTY_REVIEW"),
            headers=make_partner_account_lead_headers(partnership_id),
        )
    )


def approve_course(
    api: ApiClient, course_id: str, faculty_approver_name: str = FACULTY_APPROVER_NAME
) -> Dict[str, Any]:
    return get_success_data(
        api.post_course_design_action(
            course_id,
            f.design_action_payload("APPROVE", faculty_approver_name=faculty_approver_name),
            headers=make_faculty_chair_headers(),
        )
    )


def create_approved_course(
    api: ApiClient, partnership_id: str, program_id: str, **overrides: Any
) -> Dict[str, Any]:
    """Add a course and drive it NOT_STARTED -> IN_DESIGN -> FACULTY_REVIEW -> APPROVED."""
    course = add_course(api, partnership_id, program_id, **overrides)
    start_course_design(api, partnership_id, course["id"])
    submit_course_for_faculty_review(api, partnership_id, course["id"])
    return approve_course(api, course["id"])


# --- Service scope --------------------------------------------------------


def assign_service_scope(
    api: ApiClient, program_id: str, service_domain: str = "MARKETING", **overrides: Any
) -> Dict[str, Any]:
    return get_success_data(
        api.create_service_scope_assignment(
            program_id,
            f.service_scope_payload(service_domain, **overrides),
            headers=make_provost_headers(),
        )
    )


# --- Enrollment counselor -------------------------------------------------


def create_counselor(api: ApiClient, partnership_id: str, **overrides: Any) -> Dict[str, Any]:
    return get_success_data(
        api.create_enrollment_counselor(
            f.counselor_payload(partnership_id, **overrides),
            headers=make_partner_account_lead_headers(partnership_id),
        )
    )


def file_compensation_plan(
    api: ApiClient, partnership_id: str, counselor_id: str, **overrides: Any
) -> Dict[str, Any]:
    return get_success_data(
        api.file_compensation_plan(
            counselor_id,
            f.compensation_plan_payload(**overrides),
            headers=make_partner_account_lead_headers(partnership_id),
        )
    )


def review_counselor(
    api: ApiClient,
    counselor_id: str,
    decision: str = "APPROVE",
    reviewer_user_id: str = COMPLIANCE_AUDITOR_USER_ID,
    **overrides: Any,
) -> Dict[str, Any]:
    return get_success_data(
        api.post_compliance_review(
            counselor_id,
            f.compliance_review_payload(decision, **overrides),
            headers=make_compliance_auditor_headers(reviewer_user_id),
        )
    )


def create_eligible_counselor(
    api: ApiClient, partnership_id: str, plan_overrides: Optional[Dict[str, Any]] = None, **overrides: Any
) -> Dict[str, Any]:
    """Onboard a counselor, file a permitted plan and have it approved for eligibility."""
    counselor = create_counselor(api, partnership_id, **overrides)
    file_compensation_plan(api, partnership_id, counselor["id"], **(plan_overrides or {}))
    return review_counselor(api, counselor["id"], "APPROVE")


def run_performance_evaluation(api: ApiClient, partnership_id: str, **overrides: Any) -> Dict[str, Any]:
    return get_success_data(
        api.create_counselor_performance_run(
            partnership_id,
            f.performance_run_payload(**overrides),
            headers=make_partner_account_lead_headers(partnership_id),
        )
    )


# --- Leads and enrollments ------------------------------------------------


def create_lead(
    api: ApiClient, partnership_id: str, program_id: str, counselor_id: str, **overrides: Any
) -> Dict[str, Any]:
    return get_success_data(
        api.create_lead(
            f.lead_payload(program_id, counselor_id, **overrides),
            headers=make_partner_account_lead_headers(partnership_id),
        )
    )


def contact_lead(
    api: ApiClient, partnership_id: str, lead_id: str, hours_to_first_contact: int = 6
) -> Dict[str, Any]:
    return get_success_data(
        api.advance_lead(
            lead_id,
            f.advance_payload("CONTACT", hours_to_first_contact=hours_to_first_contact),
            headers=make_partner_account_lead_headers(partnership_id),
        )
    )


def apply_lead(api: ApiClient, partnership_id: str, lead_id: str) -> Dict[str, Any]:
    return get_success_data(
        api.advance_lead(
            lead_id,
            f.advance_payload("APPLY"),
            headers=make_partner_account_lead_headers(partnership_id),
        )
    )


def disqualify_lead(
    api: ApiClient, partnership_id: str, lead_id: str, reason: str = "NOT_QUALIFIED"
) -> Dict[str, Any]:
    return get_success_data(
        api.advance_lead(
            lead_id,
            f.advance_payload("DISQUALIFY", disqualification_reason=reason),
            headers=make_partner_account_lead_headers(partnership_id),
        )
    )


def create_applied_lead(
    api: ApiClient,
    partnership_id: str,
    program_id: str,
    counselor_id: str,
    hours_to_first_contact: int = 6,
    **overrides: Any,
) -> Dict[str, Any]:
    """Create a lead and advance it NEW -> CONTACTED -> APPLIED."""
    lead = create_lead(api, partnership_id, program_id, counselor_id, **overrides)
    contact_lead(api, partnership_id, lead["id"], hours_to_first_contact)
    return apply_lead(api, partnership_id, lead["id"])


def enroll_lead(api: ApiClient, lead_id: str, **overrides: Any) -> Dict[str, Any]:
    return get_success_data(
        api.enroll_lead(lead_id, f.enroll_payload(**overrides), headers=make_bursar_headers())
    )


def post_tuition_entry(api: ApiClient, enrollment_id: str, **overrides: Any) -> Dict[str, Any]:
    return get_success_data(
        api.create_tuition_payment(
            enrollment_id, f.tuition_payment_payload(**overrides), headers=make_bursar_headers()
        )
    )


def record_progress(api: ApiClient, enrollment_id: str, credits_completed: int) -> Dict[str, Any]:
    return get_success_data(
        api.post_academic_action(
            enrollment_id,
            f.academic_action_payload("RECORD_PROGRESS", credits_completed=credits_completed),
            headers=make_provost_headers(),
        )
    )


def withdraw_enrollment(
    api: ApiClient, enrollment_id: str, withdrawal_date: str, **overrides: Any
) -> Dict[str, Any]:
    return get_success_data(
        api.post_academic_action(
            enrollment_id,
            f.academic_action_payload("WITHDRAW", withdrawal_date=withdrawal_date, **overrides),
            headers=make_bursar_headers(),
        )
    )


# --- Marketing ledger -----------------------------------------------------


def post_marketing_entry(
    api: ApiClient, partnership_id: str, program_id: str, **overrides: Any
) -> Dict[str, Any]:
    return get_success_data(
        api.create_marketing_spend_entry(
            program_id,
            f.marketing_spend_payload(**overrides),
            headers=make_partner_account_lead_headers(partnership_id),
        )
    )


# --- Settlement -----------------------------------------------------------


def cut_statement(
    api: ApiClient,
    partnership_id: str,
    period_start: str = "2026-09-01",
    period_end: str = "2026-09-30",
    expected_partnership_version: Optional[int] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    """Read the partnership's current version and cut a statement against it."""
    version = (
        expected_partnership_version
        if expected_partnership_version is not None
        else current_partnership_version(api, partnership_id)
    )
    payload = f.statement_payload(
        version, period_start=period_start, period_end=period_end, **overrides
    )
    return get_success_data(
        api.create_remittance_statement(partnership_id, payload, headers=make_bursar_headers())
    )


def dispute_statement(
    api: ApiClient, partnership_id: str, statement_id: str, dispute_reason: str
) -> Dict[str, Any]:
    return get_success_data(
        api.post_statement_action(
            statement_id,
            f.statement_action_payload("DISPUTE", dispute_reason=dispute_reason),
            headers=make_partner_account_lead_headers(partnership_id),
        )
    )


def resolve_statement(api: ApiClient, statement_id: str, **overrides: Any) -> Dict[str, Any]:
    return get_success_data(
        api.post_statement_action(
            statement_id,
            f.statement_action_payload("RESOLVE", **overrides),
            headers=make_bursar_headers(),
        )
    )


def approve_statement(api: ApiClient, statement_id: str) -> Dict[str, Any]:
    return get_success_data(
        api.post_statement_action(
            statement_id, f.statement_action_payload("APPROVE"), headers=make_provost_headers()
        )
    )


def remit_statement(
    api: ApiClient, statement_id: str, remittance_reference: str = "ACH-2026-10-0001"
) -> Dict[str, Any]:
    return get_success_data(
        api.post_statement_action(
            statement_id,
            f.statement_action_payload("REMIT", remittance_reference=remittance_reference),
            headers=make_bursar_headers(),
        )
    )


def recalculate_statement(api: ApiClient, statement_id: str) -> Dict[str, Any]:
    return get_success_data(
        api.post_statement_action(
            statement_id, f.statement_action_payload("RECALCULATE"), headers=make_bursar_headers()
        )
    )


# --- Teach-out ------------------------------------------------------------


def draft_teach_out_plan(api: ApiClient, program_id: str, **overrides: Any) -> Dict[str, Any]:
    return get_success_data(
        api.create_teach_out_plan(
            program_id, f.teach_out_plan_payload(**overrides), headers=make_provost_headers()
        )
    )


def certify_teach_out_plan(api: ApiClient, plan_id: str, **overrides: Any) -> Dict[str, Any]:
    return get_success_data(
        api.certify_teach_out_plan(
            plan_id, f.certify_payload(**overrides), headers=make_compliance_auditor_headers()
        )
    )


# --- Composite scenarios --------------------------------------------------


def build_launched_program(
    api: ApiClient,
    partnership_overrides: Optional[Dict[str, Any]] = None,
    program_overrides: Optional[Dict[str, Any]] = None,
    course_overrides: Optional[Dict[str, Any]] = None,
    service_domains: Sequence[str] = ("MARKETING",),
    with_counselor: bool = True,
) -> Dict[str, Any]:
    """Clock at the default instant, contract executed, one program LAUNCHED.

    The program carries one APPROVED launch-required course and the requested
    service-scope assignments; a counselor with an approved plan is onboarded
    unless the caller opts out.
    """
    set_clock(api, CLOCK_AUG_1)
    partnership = create_executed_partnership(api, **(partnership_overrides or {}))
    ps_id = partnership["id"]
    program = create_program(api, ps_id, **(program_overrides or {}))
    pg_id = program["id"]
    course = create_approved_course(api, ps_id, pg_id, **(course_overrides or {}))
    for domain in service_domains:
        assign_service_scope(api, pg_id, domain)
    submit_program(api, ps_id, pg_id)
    approve_program(api, pg_id)
    program = launch_program(api, ps_id, pg_id)

    context: Dict[str, Any] = {
        "partnership": partnership,
        "ps_id": ps_id,
        "program": program,
        "pg_id": pg_id,
        "course": course,
        "c1_id": course["id"],
    }
    if with_counselor:
        counselor = create_eligible_counselor(api, ps_id)
        context["counselor"] = counselor
        context["co_id"] = counselor["id"]
    return context


def build_paid_enrollment(
    api: ApiClient,
    partnership_overrides: Optional[Dict[str, Any]] = None,
    program_overrides: Optional[Dict[str, Any]] = None,
    service_domains: Sequence[str] = ("MARKETING",),
    credits_completed: Optional[int] = None,
    marketing_spend_cents: Optional[int] = None,
    final_clock: Optional[str] = None,
) -> Dict[str, Any]:
    """A LAUNCHED program with one ACTIVE, fully paid 9-credit enrollment.

    The enrollment is converted from lead P-1001, paid in full on 2026-09-05 so it
    is ACTIVE, optionally credited with completed credits, and optionally
    accompanied by a marketing SPEND on the same date.
    """
    context = build_launched_program(
        api,
        partnership_overrides=partnership_overrides,
        program_overrides=program_overrides,
        service_domains=service_domains,
    )
    ps_id, pg_id, co_id = context["ps_id"], context["pg_id"], context["co_id"]

    lead = create_applied_lead(api, ps_id, pg_id, co_id)
    enrollment = enroll_lead(api, lead["id"])
    set_clock(api, CLOCK_SEP_5)
    post_tuition_entry(api, enrollment["id"])
    if credits_completed is not None:
        record_progress(api, enrollment["id"], credits_completed)
    if marketing_spend_cents is not None:
        post_marketing_entry(api, ps_id, pg_id, amount_cents=marketing_spend_cents)
    if final_clock is not None:
        set_clock(api, final_clock)

    context.update({"lead": lead, "ld_id": lead["id"], "enrollment": enrollment, "en_id": enrollment["id"]})
    return context


def build_september_statement(
    api: ApiClient,
    partnership_overrides: Optional[Dict[str, Any]] = None,
    credits_completed: Optional[int] = 3,
    marketing_spend_cents: Optional[int] = 300000,
) -> Dict[str, Any]:
    """The September 2026 statement cut in CALCULATED with the clock at 2026-10-01."""
    context = build_paid_enrollment(
        api,
        partnership_overrides=partnership_overrides,
        credits_completed=credits_completed,
        marketing_spend_cents=marketing_spend_cents,
        final_clock=CLOCK_OCT_1,
    )
    statement = cut_statement(api, context["ps_id"])
    context.update({"statement": statement, "st_id": statement["id"]})
    return context


def add_second_enrollment(
    api: ApiClient,
    context: Dict[str, Any],
    prospect_external_id: str = "P-1002",
    student_external_id: str = "S-2002",
    source_channel: str = "PAID_SOCIAL",
    hours_to_first_contact: int = 9,
    **enroll_overrides: Any,
) -> Dict[str, Any]:
    """Convert a second lead of the same program into a second enrollment."""
    lead = create_applied_lead(
        api,
        context["ps_id"],
        context["pg_id"],
        context["co_id"],
        hours_to_first_contact=hours_to_first_contact,
        prospect_external_id=prospect_external_id,
        source_channel=source_channel,
    )
    enrollment = enroll_lead(api, lead["id"], student_external_id=student_external_id, **enroll_overrides)
    context.update(
        {"lead_2": lead, "ld2_id": lead["id"], "enrollment_2": enrollment, "en2_id": enrollment["id"]}
    )
    return context


def build_teach_out_program(
    api: ApiClient,
    program_overrides: Optional[Dict[str, Any]] = None,
    with_enrollment: bool = False,
) -> Dict[str, Any]:
    """A program driven into TEACH_OUT, optionally carrying one active enrollment."""
    if with_enrollment:
        context = build_paid_enrollment(api, program_overrides=program_overrides)
    else:
        context = build_launched_program(api, program_overrides=program_overrides)
    begin_teach_out(api, context["pg_id"], teach_out_reason="Program discontinued")
    context["program"] = read_program(api, context["pg_id"])
    return context
