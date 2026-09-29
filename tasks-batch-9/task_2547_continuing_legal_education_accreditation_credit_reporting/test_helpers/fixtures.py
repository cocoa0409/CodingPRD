"""Composite setup helpers.

Every helper builds its preconditions from scratch through the API the PRD
declares, because each test begins against an empty register. Setup calls use
the lenient success reader so a broken precondition surfaces as a setup
failure rather than as a confusing assertion.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .test_users import (
    TEST_USERS,
    make_attorney_headers,
    make_board_admin_headers,
    make_panelist_headers,
    make_provider_admin_headers,
    make_reviewer_headers,
)
from . import factories as f

BOARD = TEST_USERS["board_admin_headers"]
REVIEWER = TEST_USERS["accreditation_reviewer_headers"]
PANELIST = TEST_USERS["appeals_panelist_headers"]


# =========================================================================
# The logical clock
# =========================================================================

def set_clock(to_iso8601: str) -> None:
    """Move the board's logical clock to an exact instant."""
    get_success_data(api_client.set_clock(to_iso8601, BOARD))


# =========================================================================
# Reads
# =========================================================================

def read_provider(provider_id: str) -> dict:
    return get_success_data(api_client.get_provider(provider_id, BOARD))


def read_course(course_id: str) -> dict:
    return get_success_data(api_client.get_course(course_id, BOARD))


def read_application(application_id: str) -> dict:
    return get_success_data(api_client.get_course_application(application_id, BOARD))


def read_attorney(attorney_id: str) -> dict:
    return get_success_data(api_client.get_attorney(attorney_id, BOARD))


def read_cycle(cycle_id: str) -> dict:
    return get_success_data(api_client.get_compliance_cycle(cycle_id, BOARD))


def read_cycle_summary(cycle_id: str) -> dict:
    return get_success_data(api_client.get_cycle_summary(cycle_id, BOARD))


def read_credit_record(record_id: str) -> dict:
    return get_success_data(api_client.get_credit_record(record_id, BOARD))


def read_audit(audit_id: str) -> dict:
    return get_success_data(api_client.get_provider_audit(audit_id, BOARD))


def read_complaint(complaint_id: str) -> dict:
    return get_success_data(api_client.get_complaint(complaint_id, BOARD))


def read_fee_assessment(fee_assessment_id: str) -> dict:
    return get_success_data(api_client.get_fee_assessment(fee_assessment_id, BOARD))


def list_fee_assessments(**params) -> list:
    data = get_success_data(api_client.list_fee_assessments(BOARD, params=params or None))
    return data["items"] if isinstance(data, dict) else data


def list_credit_records(**params) -> list:
    data = get_success_data(api_client.list_credit_records(BOARD, params=params or None))
    return data["items"] if isinstance(data, dict) else data


def list_cycles(**params) -> list:
    data = get_success_data(api_client.list_compliance_cycles(BOARD, params=params or None))
    return data["items"] if isinstance(data, dict) else data


def list_courses(**params) -> list:
    data = get_success_data(api_client.list_courses(BOARD, params=params or None))
    return data["items"] if isinstance(data, dict) else data


def list_audits(**params) -> list:
    data = get_success_data(api_client.list_provider_audits(BOARD, params=params or None))
    return data["items"] if isinstance(data, dict) else data


def list_allocations(course_id: str) -> list:
    data = get_success_data(api_client.list_course_credit_allocations(course_id, BOARD))
    return data["items"] if isinstance(data, dict) else data


def list_affirmations(cycle_id: str) -> list:
    data = get_success_data(api_client.list_affirmations(cycle_id, BOARD))
    return data["items"] if isinstance(data, dict) else data


def list_applications(course_id: str) -> list:
    data = get_success_data(api_client.list_course_applications(course_id, BOARD))
    return data["items"] if isinstance(data, dict) else data


def list_attendance_reports(course_id: str) -> list:
    data = get_success_data(api_client.list_course_attendance_reports(course_id, BOARD))
    return data["items"] if isinstance(data, dict) else data


def list_reciprocity_claims(attorney_id: str) -> list:
    data = get_success_data(
        api_client.list_attorney_reciprocity_claims(attorney_id, BOARD)
    )
    return data["items"] if isinstance(data, dict) else data


# =========================================================================
# Tier 1 — sponsors and their standing
# =========================================================================

def create_provider(name=None, provider_type="BAR_ASSOCIATION", **overrides) -> dict:
    """Files an accreditation application. The sponsor lands in APPLIED."""
    payload = f.create_provider_payload(
        name=name or ("Sponsor " + f.unique_suffix()),
        provider_type=provider_type,
        **overrides,
    )
    return get_success_data(api_client.create_provider(payload, BOARD))


def accreditation_action(provider_id, action, expected_provider_version, **extra) -> dict:
    payload = f.accreditation_action_payload(action, expected_provider_version, **extra)
    return get_success_data(
        api_client.provider_accreditation_action(provider_id, payload, BOARD)
    )


def create_accredited_provider(name=None, provider_type="BAR_ASSOCIATION", **overrides) -> dict:
    """Sponsor taken APPLIED -> ACCREDITED, so it self-certifies its courses."""
    provider = create_provider(name=name, provider_type=provider_type, **overrides)
    return accreditation_action(provider["id"], "GRANT_FULL", provider["version"])


def create_probationary_provider(name=None, provider_type="COMMERCIAL", **overrides) -> dict:
    """Sponsor taken APPLIED -> PROBATIONARY, so its courses need board review."""
    provider = create_provider(name=name, provider_type=provider_type, **overrides)
    return accreditation_action(provider["id"], "GRANT_PROBATIONARY", provider["version"])


# =========================================================================
# Tier 2 — courses
# =========================================================================

def create_self_certified_course(provider, **overrides) -> dict:
    """A course filed by an accredited sponsor for itself: approved on filing."""
    payload = f.create_course_payload(provider_id=provider["id"], **overrides)
    return get_success_data(
        api_client.create_course(payload, make_provider_admin_headers(provider["id"]))
    )


def create_sponsor_course(provider, **overrides) -> dict:
    """A course filed by a sponsor that does not self-certify: awaits approval."""
    return create_self_certified_course(provider, **overrides)


def create_individual_course(headers, **overrides) -> dict:
    """A course filed with no sponsor named: the individual-approval pathway."""
    payload = f.create_course_payload(**overrides)
    payload.pop("provider_id", None)
    return get_success_data(api_client.create_course(payload, headers))


def submit_application(course_id, headers) -> dict:
    return get_success_data(api_client.create_course_application(course_id, headers))


def review_action(application_id, action, reviewer_user_id="reviewer-alpha", **extra) -> dict:
    payload = f.review_action_payload(action, **extra)
    return get_success_data(
        api_client.application_review_action(
            application_id, payload, make_reviewer_headers(reviewer_user_id)
        )
    )


def appellant_action(application_id, action, headers, **extra) -> dict:
    payload = f.appellant_action_payload(action, **extra)
    return get_success_data(
        api_client.application_appellant_action(application_id, payload, headers)
    )


def appeal_decision(application_id, disposition, panelist_user_id="panelist-one", **extra) -> dict:
    payload = f.appeal_decision_payload(disposition, **extra)
    return get_success_data(
        api_client.application_appeal_decision(
            application_id, payload, make_panelist_headers(panelist_user_id)
        )
    )


def approve_course_by_review(course, applicant_headers, reviewer_user_id="reviewer-alpha"):
    """Files an application on the course and has a reviewer approve it.
    Returns (application, refreshed course)."""
    application = submit_application(course["id"], applicant_headers)
    application = review_action(application["id"], "APPROVE", reviewer_user_id)
    return application, read_course(course["id"])


def setup_reviewed_course(provider=None, applicant_headers=None,
                          reviewer_user_id="reviewer-alpha", **course_overrides):
    """A probationary sponsor's course carried to APPROVED through board review.
    Returns (provider, course, application)."""
    provider = provider or create_probationary_provider()
    headers = applicant_headers or make_provider_admin_headers(provider["id"])
    course = create_self_certified_course(provider, **course_overrides)
    application = submit_application(course["id"], headers)
    application = review_action(application["id"], "APPROVE", reviewer_user_id)
    return provider, read_course(course["id"]), application


def setup_denied_application(provider=None, denial_reason="The materials lack substantive content.",
                             reviewer_user_id="reviewer-alpha", **course_overrides):
    """A course whose application was denied. Returns (provider, course, application)."""
    provider = provider or create_probationary_provider()
    headers = make_provider_admin_headers(provider["id"])
    course = create_self_certified_course(provider, **course_overrides)
    application = submit_application(course["id"], headers)
    application = review_action(
        application["id"], "DENY", reviewer_user_id, denial_reason=denial_reason
    )
    return provider, read_course(course["id"]), application


def setup_appealed_application(provider=None, appeal_grounds="The denial overlooked the filed syllabus.",
                               reviewer_user_id="reviewer-alpha", **course_overrides):
    """A denied application carried into APPEALED. Returns (provider, course, application)."""
    provider, course, application = setup_denied_application(
        provider=provider, reviewer_user_id=reviewer_user_id, **course_overrides
    )
    application = appellant_action(
        application["id"], "APPEAL",
        make_provider_admin_headers(provider["id"]),
        appeal_grounds=appeal_grounds,
    )
    return provider, course, application


# =========================================================================
# Tier 3 — attorneys and compliance periods
# =========================================================================

def create_attorney(**overrides) -> dict:
    payload = f.create_attorney_payload(**overrides)
    return get_success_data(api_client.create_attorney(payload, BOARD))


def change_attorney_status(attorney_id, status, **extra) -> dict:
    payload = f.status_change_payload(status, **extra)
    return get_success_data(
        api_client.attorney_status_change(attorney_id, payload, BOARD)
    )


def create_cycle(attorney_id, period_start, period_end, **extra) -> dict:
    payload = f.create_compliance_cycle_payload(
        period_start=period_start, period_end=period_end, **extra
    )
    return get_success_data(
        api_client.create_compliance_cycle(attorney_id, payload, BOARD)
    )


def setup_attorney_with_cycle(period_start="2026-01-01T00:00:00Z",
                              period_end="2028-01-01T00:00:00Z",
                              attorney_overrides=None, **cycle_extra):
    """One attorney on the register with one compliance period.
    Returns (attorney, cycle)."""
    attorney = create_attorney(**(attorney_overrides or {}))
    cycle = create_cycle(attorney["id"], period_start, period_end, **cycle_extra)
    return attorney, cycle


def reinstate_attorney(attorney_id, cycle_id, cure_basis="FEES_AND_CREDITS_CURED", **extra) -> dict:
    payload = f.reinstatement_payload(cycle_id, cure_basis, **extra)
    return get_success_data(
        api_client.attorney_reinstatement(attorney_id, payload, BOARD)
    )


# =========================================================================
# Tier 3 — credit claims, affirmations and adjudication
# =========================================================================

def file_credit_record(attorney, course_id, **overrides) -> dict:
    payload = f.create_credit_record_payload(attorney["id"], course_id, **overrides)
    return get_success_data(
        api_client.create_credit_record(payload, make_attorney_headers(attorney["id"]))
    )


def file_code_verified_record(attorney, course, attended_minutes=None,
                              completion_date=None, **overrides) -> dict:
    """Files a claim against an attendance-code course, so the record is born
    verified in the same request."""
    return file_credit_record(
        attorney,
        course["id"],
        verification_method="ATTENDANCE_CODE",
        attendance_code=course["attendance_code"],
        attended_minutes=attended_minutes or course["total_minutes"],
        completion_date=completion_date or course["presented_at"],
        certificate_reference=None,
        **overrides,
    )


def adjudicate_record(record_id, action, **extra) -> dict:
    payload = f.adjudication_payload(action, **extra)
    return get_success_data(
        api_client.credit_record_adjudication(record_id, payload, BOARD)
    )


def file_affirmation(cycle_id, attorney_id, affirmation_type, **extra) -> dict:
    payload = f.create_affirmation_payload(affirmation_type, **extra)
    return get_success_data(
        api_client.create_affirmation(cycle_id, payload, make_attorney_headers(attorney_id))
    )


def file_final_affirmation(cycle_id, attorney_id,
                           statement="I affirm the credits reported for this compliance period.") -> dict:
    return file_affirmation(
        cycle_id, attorney_id, "FINAL_COMPLIANCE_AFFIRMATION", statement=statement
    )


def certify_cycle(cycle_id, attorney_id, **extra) -> dict:
    payload = f.certification_payload(**extra)
    return get_success_data(
        api_client.certify_cycle(cycle_id, payload, make_attorney_headers(attorney_id))
    )


def affirm_and_certify(cycle_id, attorney_id, **extra) -> dict:
    """Files the final compliance affirmation the certification requires, then
    certifies the period."""
    file_final_affirmation(cycle_id, attorney_id)
    return certify_cycle(cycle_id, attorney_id, **extra)


def file_roster(provider_id, course_id, session_date, entries) -> dict:
    payload = f.create_attendance_report_payload(course_id, session_date, entries)
    return get_success_data(
        api_client.create_attendance_report(payload, make_provider_admin_headers(provider_id))
    )


# =========================================================================
# Tier 3 — out-of-state instruction
# =========================================================================

def file_reciprocity_claim(attorney_id, **overrides) -> dict:
    """Reads the attorney's live version so the claim carries the concurrency
    guard the PRD requires."""
    attorney = read_attorney(attorney_id)
    payload = f.create_reciprocity_claim_payload(
        attorney_id, attorney["version"], **overrides
    )
    return get_success_data(
        api_client.create_reciprocity_claim(payload, make_attorney_headers(attorney_id))
    )


def determine_claim(claim_id, action, **extra) -> dict:
    payload = f.determination_payload(action, **extra)
    return get_success_data(
        api_client.reciprocity_claim_determination(claim_id, payload, BOARD)
    )


# =========================================================================
# Tier 4 — oversight: complaints and audits
# =========================================================================

def file_complaint(subject_type, subject_id, filer_user_id="board-intake-11", **overrides) -> dict:
    payload = f.create_complaint_payload(subject_type, subject_id, **overrides)
    return get_success_data(
        api_client.create_complaint(payload, make_board_admin_headers(filer_user_id))
    )


def dispose_complaint(complaint_id, action, disposer_user_id="board-review-12", **extra) -> dict:
    payload = f.disposition_payload(action, **extra)
    return get_success_data(
        api_client.complaint_disposition(
            complaint_id, payload, make_board_admin_headers(disposer_user_id)
        )
    )


def substantiate_complaint(complaint_id, disposer_user_id="board-review-12",
                           disposition_reason="The allegation is confirmed on the record.") -> dict:
    dispose_complaint(complaint_id, "OPEN_REVIEW", disposer_user_id)
    return dispose_complaint(
        complaint_id, "SUBSTANTIATE", disposer_user_id,
        disposition_reason=disposition_reason,
    )


def open_audit(provider_id, audit_period_start="2026-01-01T00:00:00Z",
               audit_period_end="2026-06-30T00:00:00Z", trigger_type="RANDOM", **extra) -> dict:
    payload = f.create_provider_audit_payload(
        provider_id,
        audit_period_start=audit_period_start,
        audit_period_end=audit_period_end,
        trigger_type=trigger_type,
        **extra,
    )
    return get_success_data(api_client.create_provider_audit(payload, BOARD))


def audit_action(audit_id, action, expected_audit_version, **extra) -> dict:
    payload = f.audit_action_payload(action, expected_audit_version, **extra)
    return get_success_data(
        api_client.provider_audit_action(audit_id, payload, BOARD)
    )


def take_audit_to_cleared(provider_id, audit_period_start="2026-01-01T00:00:00Z",
                          audit_period_end="2026-06-30T00:00:00Z",
                          trigger_type="RANDOM", findings_count=0, **extra) -> dict:
    """Opens an audit and walks it OPENED -> SAMPLED -> FINDINGS_ISSUED -> CLEARED."""
    audit = open_audit(
        provider_id, audit_period_start, audit_period_end, trigger_type, **extra
    )
    audit = audit_action(audit["id"], "DRAW_SAMPLE", audit["version"])
    audit = audit_action(
        audit["id"], "ISSUE_FINDINGS", audit["version"], findings_count=findings_count
    )
    return audit_action(audit["id"], "CLOSE_CLEARED", audit["version"])


def take_audit_to_sanctioned(provider_id, sanction_type="PROBATION",
                             audit_period_start="2026-01-01T00:00:00Z",
                             audit_period_end="2026-06-30T00:00:00Z",
                             trigger_type="RISK_BASED", findings_count=1, **extra) -> dict:
    """Opens an audit and walks it through to SANCTIONED."""
    audit = open_audit(
        provider_id, audit_period_start, audit_period_end, trigger_type, **extra
    )
    audit = audit_action(audit["id"], "DRAW_SAMPLE", audit["version"])
    audit = audit_action(
        audit["id"], "ISSUE_FINDINGS", audit["version"], findings_count=findings_count
    )
    return audit_action(
        audit["id"], "CLOSE_SANCTIONED", audit["version"], sanction_type=sanction_type
    )


# =========================================================================
# Tier 4 — the batch run and the fee ledger
# =========================================================================

def run_sweep() -> dict:
    """Executes the board's batch reporting run against the logical clock."""
    return get_success_data(api_client.create_reporting_sweep(BOARD))


def settle_fee(fee_assessment_id, action, headers, **extra) -> dict:
    payload = f.settlement_payload(action, **extra)
    return get_success_data(
        api_client.fee_settlement(fee_assessment_id, payload, headers)
    )


def pay_fee_as_attorney(fee_assessment_id, attorney_id) -> dict:
    return settle_fee(fee_assessment_id, "PAY", make_attorney_headers(attorney_id))


def waive_fee_as_board(fee_assessment_id, waiver_reason="The board waived the assessment.") -> dict:
    return settle_fee(fee_assessment_id, "WAIVE", BOARD, waiver_reason=waiver_reason)


def clear_all_fees(attorney_id) -> None:
    """Pays every assessment still outstanding against one attorney."""
    for assessment in list_fee_assessments(attorney_id=attorney_id, status="ASSESSED"):
        pay_fee_as_attorney(assessment["id"], attorney_id)


# =========================================================================
# Tier 5 — accumulated states worth several calls to reach
# =========================================================================

def create_code_verified_course(provider, total_minutes, presented_at,
                                credit_allocations=None,
                                delivery_format="LIVE_IN_PERSON", **overrides) -> dict:
    """A self-certified course whose attendance is proved by the minted code,
    so a claim against it is verified on filing."""
    return create_self_certified_course(
        provider,
        title=overrides.pop("title", "Session " + f.unique_suffix()),
        delivery_format=delivery_format,
        total_minutes=total_minutes,
        presented_at=presented_at,
        attendance_verification_method="ATTENDANCE_CODE",
        credit_allocations=credit_allocations
        or [f.credit_allocation_entry("GENERAL", total_minutes)],
        **overrides,
    )


def setup_earned_minutes(sessions, attorney=None, cycle=None,
                         period_start="2024-01-01T00:00:00Z",
                         period_end="2026-01-01T00:00:00Z",
                         attorney_overrides=None, provider=None, **cycle_extra):
    """Builds an accredited sponsor, a set of attendance-code sessions, and one
    verified credit record per session against a single attorney's period.

    `sessions` is a list of dicts, each carrying `total_minutes`,
    `presented_at`, optionally `credit_allocations`, `delivery_format`,
    `attended_minutes` and `completion_date`.

    Returns (provider, attorney, cycle, courses, records).
    """
    provider = provider or create_accredited_provider()
    if attorney is None:
        attorney = create_attorney(**(attorney_overrides or {}))
    if cycle is None:
        cycle = create_cycle(attorney["id"], period_start, period_end, **cycle_extra)
    courses, records = [], []
    for session in sessions:
        course = create_code_verified_course(
            provider,
            session["total_minutes"],
            session["presented_at"],
            credit_allocations=session.get("credit_allocations"),
            delivery_format=session.get("delivery_format", "LIVE_IN_PERSON"),
        )
        record = file_code_verified_record(
            attorney,
            course,
            attended_minutes=session.get("attended_minutes"),
            completion_date=session.get("completion_date"),
        )
        courses.append(course)
        records.append(record)
    return provider, attorney, read_cycle(cycle["id"]), courses, records


def setup_delinquent_cycle(period_start="2024-01-01T00:00:00Z",
                           period_end="2026-01-01T00:00:00Z",
                           compliance_group="GROUP_1",
                           admission_date="2009-09-01T00:00:00Z",
                           attorney_overrides=None):
    """One attorney whose period ran out uncertified, carried past its filing
    deadline by one batch run. Returns (attorney, cycle, sweep, late_fee)."""
    overrides = {"compliance_group": compliance_group, "admission_date": admission_date}
    overrides.update(attorney_overrides or {})
    attorney = create_attorney(**overrides)
    cycle = create_cycle(attorney["id"], period_start, period_end)
    sweep = run_sweep()
    late_fees = list_fee_assessments(attorney_id=attorney["id"], fee_type="LATE_COMPLIANCE")
    late_fee = late_fees[0] if late_fees else None
    return read_attorney(attorney["id"]), read_cycle(cycle["id"]), sweep, late_fee


def setup_admin_suspended_cycle(suspension_instant="2026-09-30T00:00:00Z", **kwargs):
    """Carries a delinquent period all the way to administrative suspension by
    advancing the clock to the suspension day and running the batch again.
    Returns (attorney, cycle, first_sweep, second_sweep)."""
    attorney, cycle, first_sweep, _late_fee = setup_delinquent_cycle(**kwargs)
    set_clock(suspension_instant)
    second_sweep = run_sweep()
    return (
        read_attorney(attorney["id"]),
        read_cycle(cycle["id"]),
        first_sweep,
        second_sweep,
    )


def setup_satisfied_cycle_with_carryover():
    """A completed period that overshot its requirement and elected to carry
    the excess forward, plus the successor period holding the transfer.

    Three attendance-code sessions on separate days supply 2400 countable
    minutes against an 1800-minute requirement, of which 300 are ethics.

    Returns a dict with provider, attorney, cycle_one, cycle_two, courses and
    records (keyed k1/k2/k3 and rk1/rk2/rk3).
    """
    provider = create_accredited_provider(name="Kestrel Advocacy Academy",
                                          provider_type="LAW_SCHOOL")
    k1 = create_code_verified_course(
        provider, 1200, "2024-02-01T09:00:00Z",
        credit_allocations=[
            f.credit_allocation_entry("ETHICS", 300),
            f.credit_allocation_entry("TECHNOLOGY", 60),
            f.credit_allocation_entry("BIAS_ELIMINATION", 120),
            f.credit_allocation_entry("GENERAL", 720),
        ],
        title="Ethics and Bias Intensive",
    )
    k2 = create_code_verified_course(
        provider, 900, "2024-04-01T09:00:00Z", title="Advanced Motion Practice"
    )
    k3 = create_code_verified_course(
        provider, 300, "2024-06-01T09:00:00Z", title="Closing Argument Clinic"
    )
    attorney = create_attorney(
        full_name="Osei Mensah",
        admission_date="2008-05-01T00:00:00Z",
        compliance_group="GROUP_1",
    )
    cycle_one = create_cycle(
        attorney["id"], "2024-01-01T00:00:00Z", "2026-01-01T00:00:00Z",
        carryover_election="CARRY_FORWARD",
    )
    rk1 = file_code_verified_record(
        attorney, k1, attended_minutes=1200, completion_date="2024-02-02T05:00:00Z"
    )
    rk2 = file_code_verified_record(
        attorney, k2, attended_minutes=900, completion_date="2024-04-02T00:00:00Z"
    )
    rk3 = file_code_verified_record(
        attorney, k3, attended_minutes=300, completion_date="2024-06-01T14:00:00Z"
    )
    cycle_one = affirm_and_certify(
        cycle_one["id"], attorney["id"], carryover_election="CARRY_FORWARD"
    )
    cycle_two = create_cycle(
        attorney["id"], "2026-01-01T00:00:00Z", "2028-01-01T00:00:00Z",
        previous_cycle_id=cycle_one["id"], carryover_election="CARRY_FORWARD",
    )
    return {
        "provider": provider,
        "attorney": read_attorney(attorney["id"]),
        "cycle_one": read_cycle(cycle_one["id"]),
        "cycle_two": read_cycle(cycle_two["id"]),
        "k1": k1, "k2": k2, "k3": k3,
        "rk1": rk1, "rk2": rk2, "rk3": rk3,
    }


def setup_two_concurrent_live_sessions(provider=None):
    """An accredited sponsor already teaching two overlapping in-person
    sessions, which is exactly the concurrent capacity the PRD allows.
    Returns (provider, first_course, second_course)."""
    provider = provider or create_accredited_provider(provider_type="LAW_SCHOOL")
    first = create_self_certified_course(
        provider,
        title="Morning Trial Lab A",
        delivery_format="LIVE_IN_PERSON",
        total_minutes=240,
        presented_at="2026-05-01T09:00:00Z",
        attendance_verification_method="ROSTER",
        credit_allocations=[f.credit_allocation_entry("GENERAL", 240)],
    )
    second = create_self_certified_course(
        provider,
        title="Midday Trial Lab B",
        delivery_format="LIVE_IN_PERSON",
        total_minutes=240,
        presented_at="2026-05-01T12:00:00Z",
        attendance_verification_method="ROSTER",
        credit_allocations=[f.credit_allocation_entry("GENERAL", 240)],
    )
    return provider, first, second


def setup_probationary_provider_with_sample_pool(
        audit_period_start="2026-06-01T00:00:00Z",
        audit_period_end="2026-06-30T00:00:00Z",
        reviewer_user_id="reviewer-beta"):
    """A probationary sponsor holding one board-approved course inside the
    window an audit will examine, so a sample can actually be drawn.
    Returns (provider, course, application)."""
    provider = create_probationary_provider(provider_type="COMMERCIAL")
    course = create_self_certified_course(
        provider,
        title="Probationary Sponsor Self-Study",
        delivery_format="SELF_STUDY",
        total_minutes=180,
        presented_at="2026-06-10T09:00:00Z",
        attendance_verification_method="AFFIRMATION_ONLY",
        credit_allocations=[f.credit_allocation_entry("GENERAL", 180)],
    )
    application = submit_application(
        course["id"], make_provider_admin_headers(provider["id"])
    )
    application = review_action(application["id"], "APPROVE", reviewer_user_id)
    return read_provider(provider["id"]), read_course(course["id"]), application


def setup_pending_certificate_record(attorney=None, cycle=None, provider=None,
                                     period_start="2026-01-01T00:00:00Z",
                                     period_end="2028-01-01T00:00:00Z",
                                     total_minutes=180, presented_at="2026-06-01T09:00:00Z",
                                     completion_date="2026-06-01T12:00:00Z",
                                     category="GENERAL"):
    """A claim waiting on board adjudication: an accredited sponsor's
    certificate course with one record still awaiting verification.
    Returns (provider, attorney, cycle, course, record)."""
    provider = provider or create_accredited_provider()
    course = create_self_certified_course(
        provider,
        delivery_format="LIVE_IN_PERSON",
        total_minutes=total_minutes,
        presented_at=presented_at,
        attendance_verification_method="CERTIFICATE",
        credit_allocations=[f.credit_allocation_entry(category, total_minutes)],
    )
    if attorney is None:
        attorney = create_attorney()
    if cycle is None:
        cycle = create_cycle(attorney["id"], period_start, period_end)
    record = file_credit_record(
        attorney,
        course["id"],
        verification_method="CERTIFICATE",
        attended_minutes=total_minutes,
        completion_date=completion_date,
    )
    return provider, attorney, read_cycle(cycle["id"]), course, record


# =========================================================================
# Appeal dispositions
# =========================================================================
# The PRD names the panel's three dispositions twice, and the grant and deny
# labels are spelled differently in the two places: the workflow prose calls
# them GRANT and DENY, while the endpoint catalogue calls them GRANT_APPEAL
# and DENY_APPEAL. REMAND is spelled identically in both. Because the contract
# leaves the accepted spelling of the first two open, these helpers submit each
# spelling in turn and return the first accepted result — the tests that use
# them still assert the resulting state strictly.

APPEAL_GRANT_SPELLINGS = ("GRANT", "GRANT_APPEAL")
APPEAL_DENY_SPELLINGS = ("DENY", "DENY_APPEAL")


def _decide_appeal(application_id, spellings, panelist_user_id="panelist-one", **extra) -> dict:
    last_response = None
    for disposition in spellings:
        payload = f.appeal_decision_payload(disposition, **extra)
        response = api_client.application_appeal_decision(
            application_id, payload, make_panelist_headers(panelist_user_id)
        )
        if 200 <= response.status_code < 300:
            return get_success_data(response)
        last_response = response
    return get_success_data(last_response)


def grant_appeal(application_id, panelist_user_id="panelist-one", **extra) -> dict:
    """Decides an appealed application in the appellant's favour."""
    return _decide_appeal(
        application_id, APPEAL_GRANT_SPELLINGS, panelist_user_id, **extra
    )


def deny_appeal(application_id, panelist_user_id="panelist-one", **extra) -> dict:
    """Decides an appealed application against the appellant."""
    return _decide_appeal(
        application_id, APPEAL_DENY_SPELLINGS, panelist_user_id, **extra
    )


def remand_appeal(application_id, panelist_user_id="panelist-one", **extra) -> dict:
    """Sends an appealed application back for re-review."""
    return appeal_decision(application_id, "REMAND", panelist_user_id, **extra)
