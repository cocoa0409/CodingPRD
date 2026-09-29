"""Requests that break two rules at once, and the single error that must win.

Each test builds its own register through the endpoints the PRD declares,
because the board's database is empty at the start of every test.
"""
from datetime import datetime

from test_helpers import (
    TEST_USERS,
    create_accredited_provider,
    create_attorney,
    create_credit_record_payload,
    create_cycle,
    create_individual_course,
    create_self_certified_course,
    credit_allocation_entry,
    file_code_verified_record,
    list_credit_records,
    list_fee_assessments,
    make_attorney_headers,
    read_attorney,
    read_course,
    read_cycle,
    reinstate_attorney,
    run_sweep,
    set_clock,
    settle_fee,
    validate_error,
)

BOARD_HEADERS = TEST_USERS["board_admin_headers"]


def _instant(value):
    """Parses a wire timestamp so two spellings of the same instant compare."""
    assert isinstance(value, str) and value, f"expected an ISO 8601 instant, got {value!r}"
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def assert_same_instant(actual, expected, label):
    assert _instant(actual) == _instant(expected), (
        f"{label}: expected {expected}, got {actual}"
    )


def register_attorney_with_a_late_period():
    """One attorney whose only compliance period is already past its filing
    deadline at the startup instant of the logical clock."""
    attorney = create_attorney(
        bar_number="BAR-8008",
        full_name="Nadia Farouk",
        admission_date="2009-08-01T00:00:00Z",
        compliance_group="GROUP_1",
        principal_office_jurisdiction="ST",
    )
    cycle = create_cycle(
        attorney["id"], "2024-01-01T00:00:00Z", "2026-01-01T00:00:00Z"
    )
    return attorney, cycle


def register_unapproved_individual_course(attorney):
    """Instruction the attorney filed for itself, which no sponsor certifies
    and no application has yet decided, so it never leaves PENDING_APPROVAL."""
    course = create_individual_course(
        make_attorney_headers(attorney["id"]),
        title="Unreviewed Self-Study on Trust Accounting",
        delivery_format="SELF_STUDY",
        total_minutes=180,
        presented_at="2025-06-01T09:00:00Z",
        attendance_verification_method="AFFIRMATION_ONLY",
        credit_allocations=[credit_allocation_entry("ETHICS", 180)],
    )
    assert course["status"] == "PENDING_APPROVAL", course
    return course


def affirmation_claim_payload(attorney, course):
    """The one claim payload every test in this pair files, unchanged."""
    return create_credit_record_payload(
        attorney["id"],
        course["id"],
        verification_method="AFFIRMATION",
        attended_minutes=180,
        completion_date="2025-07-01T00:00:00Z",
        certificate_reference=None,
    )


def file_claim(api, attorney, course):
    return api.create_credit_record(
        affirmation_claim_payload(attorney, course),
        make_attorney_headers(attorney["id"]),
    )


def drive_cycle_to_administrative_suspension(attorney, cycle):
    """Two reporting runs: the first misses the deadline, the second observes
    the delinquency sixty days old."""
    run_sweep()
    delinquent = read_cycle(cycle["id"])
    assert delinquent["administrative_status"] == "DELINQUENT", delinquent
    set_clock("2026-09-30T00:00:00Z")
    run_sweep()
    suspended = read_cycle(cycle["id"])
    assert suspended["administrative_status"] == "ADMIN_SUSPENDED", suspended
    assert read_attorney(attorney["id"])["status"] == "ADMIN_SUSPENDED"
    return suspended


def test_admin_suspended_cycle_outranks_the_unapproved_course_on_a_credit_claim(api):
    """When a single request violates several rules, the response must name the
    violation that comes first in the following order. This order is normative:
    it is what makes an error response predictable, and it is why, for example,
    a request from an unauthorized role against a non-existent resource returns
    a permission error rather than a not-found error. A cycle whose
    `administrative_status` is `ADMIN_SUSPENDED` accepts no credit-bearing
    write at all — no credit-record creation, no affirmation, no certification
    — and such attempts are rejected with `ERR_CYCLE_ADMIN_SUSPENDED` (409).
    The claim also requires the course to be `APPROVED` (otherwise
    `ERR_COURSE_NOT_APPROVED`), the `completion_date` to be no later than the
    course's `expires_at` (otherwise `ERR_COURSE_APPROVAL_EXPIRED`), and the
    attorney's `status` to be `ACTIVE` or `EXEMPT` (otherwise
    `ERR_ATTORNEY_NOT_IN_GOOD_STANDING`).

    Design: Difficulty/priority_pair_validation_conflict/admin_suspended_cycle_state_check_outranks_course_standing_check_on_credit_filing
    """
    attorney, cycle = register_attorney_with_a_late_period()
    course = register_unapproved_individual_course(attorney)
    drive_cycle_to_administrative_suspension(attorney, cycle)

    # The claim breaks the cycle-suspension rule of PRD §2.8 step 9 and the
    # regulatory-standing rule of step 13 at the same time.
    response = file_claim(api, attorney, course)

    validate_error(response, "ERR_CYCLE_ADMIN_SUSPENDED")
    assert list_credit_records(
        attorney_id=attorney["id"], course_id=course["id"]
    ) == []


def test_unapproved_course_alone_reports_its_own_error_on_a_credit_claim(api):
    """The claim also requires the course to be `APPROVED` (otherwise
    `ERR_COURSE_NOT_APPROVED`), the `completion_date` to be no later than the
    course's `expires_at` (otherwise `ERR_COURSE_APPROVAL_EXPIRED`), and the
    attorney's `status` to be `ACTIVE` or `EXEMPT` (otherwise
    `ERR_ATTORNEY_NOT_IN_GOOD_STANDING`). It is `PROVIDER_ACCREDITED` when
    `provider_id` is supplied *and* that sponsor's `self_certification_enabled`
    is true at the moment of creation; in every other case — no sponsor at all,
    or a sponsor that is not fully accredited — it is `INDIVIDUAL_APPROVAL`.
    Every other course is created in `PENDING_APPROVAL` and stays there until
    an application is decided; if it names a sponsor, only that sponsor's
    `courses_total_count` rises.

    Design: Difficulty/priority_pair_validation_conflict/admin_suspended_cycle_state_check_outranks_course_standing_check_on_credit_filing
    """
    attorney, cycle = register_attorney_with_a_late_period()
    course = register_unapproved_individual_course(attorney)

    # No reporting run has been executed, so the period is still in good
    # standing and only the regulatory-standing rule is broken.
    assert read_cycle(cycle["id"])["administrative_status"] == "GOOD_STANDING"
    assert read_attorney(attorney["id"])["status"] == "ACTIVE"
    response = file_claim(api, attorney, course)

    validate_error(response, "ERR_COURSE_NOT_APPROVED")
    assert list_credit_records(
        attorney_id=attorney["id"], course_id=course["id"]
    ) == []


def test_reinstated_cycle_lets_the_unapproved_course_error_surface_on_the_same_claim(api):
    """On success the named cycle moves `administrative_status` from
    `ADMIN_SUSPENDED` to `REINSTATED` and its `delinquent_since` returns to
    null, and the attorney's `status` moves `ADMIN_SUSPENDED → ACTIVE`. A cycle
    whose `administrative_status` is `ADMIN_SUSPENDED` accepts no
    credit-bearing write at all — no credit-record creation, no affirmation, no
    certification — and such attempts are rejected with
    `ERR_CYCLE_ADMIN_SUSPENDED` (409). The claim also requires the course to be
    `APPROVED` (otherwise `ERR_COURSE_NOT_APPROVED`), the `completion_date` to
    be no later than the course's `expires_at` (otherwise
    `ERR_COURSE_APPROVAL_EXPIRED`), and the attorney's `status` to be `ACTIVE`
    or `EXEMPT` (otherwise `ERR_ATTORNEY_NOT_IN_GOOD_STANDING`).

    Design: Difficulty/priority_pair_validation_conflict/admin_suspended_cycle_state_check_outranks_course_standing_check_on_credit_filing
    """
    attorney, cycle = register_attorney_with_a_late_period()
    course = register_unapproved_individual_course(attorney)
    drive_cycle_to_administrative_suspension(attorney, cycle)
    validate_error(file_claim(api, attorney, course), "ERR_CYCLE_ADMIN_SUSPENDED")
    for assessment in list_fee_assessments(
        attorney_id=attorney["id"], status="ASSESSED"
    ):
        settle_fee(assessment["id"], "PAY", BOARD_HEADERS)
    # Reinstatement is the one action endpoint that returns the reinstated
    # Attorney rather than the cycle named in its body, so the cycle's new
    # administrative_status is read back from the cycle itself.
    reinstate_attorney(attorney["id"], cycle["id"], cure_basis="BOARD_ORDER")
    reinstated = read_cycle(cycle["id"])
    assert reinstated["administrative_status"] == "REINSTATED", reinstated
    assert read_attorney(attorney["id"])["status"] == "ACTIVE"
    assert read_attorney(attorney["id"])["outstanding_fee_cents"] == 0

    # The identical payload, now that only the course rule is still broken.
    response = file_claim(api, attorney, course)

    validate_error(response, "ERR_COURSE_NOT_APPROVED")
    assert list_credit_records(
        attorney_id=attorney["id"], course_id=course["id"]
    ) == []


def build_live_session_claimed_at_its_expiry_instant():
    """A four-hour live session whose approval covers the session and nothing
    more, and one attorney holding a verified claim for it. Returns a dict of
    the rows."""
    provider = create_accredited_provider(
        name="Riverbend Judicial College", provider_type="GOVERNMENT"
    )
    course = create_self_certified_course(
        provider,
        title="Bench-Bar Evidence Seminar",
        delivery_format="LIVE_IN_PERSON",
        total_minutes=240,
        presented_at="2026-03-01T09:00:00Z",
        attendance_verification_method="ATTENDANCE_CODE",
        credit_allocations=[credit_allocation_entry("GENERAL", 240)],
    )
    attorney = create_attorney(
        bar_number="BAR-9009",
        full_name="Gregor Lindqvist",
        admission_date="2014-02-01T00:00:00Z",
        compliance_group="GROUP_2",
        principal_office_jurisdiction="ST",
    )
    cycle = create_cycle(
        attorney["id"], "2026-01-01T00:00:00Z", "2028-01-01T00:00:00Z"
    )
    record = file_code_verified_record(
        attorney, course, attended_minutes=240,
        completion_date="2026-03-01T13:00:00Z",
    )
    # Guards on the starting position: approval ran out four hours after the
    # session began, and the first claim landed on that very instant.
    assert_same_instant(
        course["expires_at"], "2026-03-01T13:00:00Z", "course expires_at"
    )
    assert read_course(course["id"])["status"] == "APPROVED"
    assert record["status"] == "VERIFIED", record
    return {
        "provider": provider,
        "course": course,
        "attorney": attorney,
        "cycle": cycle,
        "record": record,
    }


def refile_claim(api, attorney, course, completion_date):
    payload = create_credit_record_payload(
        attorney["id"],
        course["id"],
        verification_method="ATTENDANCE_CODE",
        attendance_code=course["attendance_code"],
        attended_minutes=240,
        completion_date=completion_date,
        certificate_reference=None,
    )
    return api.create_credit_record(payload, make_attorney_headers(attorney["id"]))


def test_expired_course_window_outranks_the_duplicate_claim_on_a_refiling(api):
    """When a single request violates several rules, the response must name the
    violation that comes first in the following order. This order is normative:
    it is what makes an error response predictable, and it is why, for example,
    a request from an unauthorized role against a non-existent resource returns
    a permission error rather than a not-found error. The credit's
    `completion_date` falls inside some cycle's half-open period
    (`ERR_OUTSIDE_COMPLIANCE_PERIOD`); the credit's `completion_date` does not
    exceed the course's `expires_at` (`ERR_COURSE_APPROVAL_EXPIRED`); a new
    cycle's half-open window does not overlap another cycle of the same
    attorney (`ERR_CYCLE_PERIOD_OVERLAP`); a new audit's closed window neither
    overlaps nor abuts another audit window of the same provider
    (`ERR_AUDIT_PERIOD_OVERLAP`) and the provider holds no other non-terminal
    audit (`ERR_AUDIT_ENGAGEMENT_ACTIVE`); a new live-in-person course does not
    push its provider's concurrent session count above the capacity limit
    (`ERR_SESSION_WINDOW_CONFLICT`); a roster arrives inside its hard filing
    window (`ERR_ROSTER_WINDOW_CLOSED`) — HTTP 409. Finally, an attorney may
    hold at most one live claim per course: a second claim for the same
    attorney and course while an earlier one is still `PENDING_VERIFICATION` or
    `VERIFIED` is `ERR_DUPLICATE_CREDIT_RECORD`.

    Design: Difficulty/priority_pair_validation_conflict/expired_course_window_check_outranks_duplicate_record_constraint_on_refiling
    """
    state = build_live_session_claimed_at_its_expiry_instant()

    # The refiling breaks temporal coherence, PRD §2.8 step 15, and the
    # uniqueness constraint of step 16 at the same time.
    response = refile_claim(
        api, state["attorney"], state["course"], "2026-03-02T00:00:00Z"
    )

    validate_error(response, "ERR_COURSE_APPROVAL_EXPIRED")


def test_duplicate_claim_alone_reports_its_own_error_inside_the_approval_window(api):
    """Finally, an attorney may hold at most one live claim per course: a second
    claim for the same attorney and course while an earlier one is still
    `PENDING_VERIFICATION` or `VERIFIED` is `ERR_DUPLICATE_CREDIT_RECORD`. The
    credit's `completion_date` falls inside some cycle's half-open period
    (`ERR_OUTSIDE_COMPLIANCE_PERIOD`); the credit's `completion_date` does not
    exceed the course's `expires_at` (`ERR_COURSE_APPROVAL_EXPIRED`); a new
    cycle's half-open window does not overlap another cycle of the same
    attorney (`ERR_CYCLE_PERIOD_OVERLAP`); a new audit's closed window neither
    overlaps nor abuts another audit window of the same provider
    (`ERR_AUDIT_PERIOD_OVERLAP`) and the provider holds no other non-terminal
    audit (`ERR_AUDIT_ENGAGEMENT_ACTIVE`); a new live-in-person course does not
    push its provider's concurrent session count above the capacity limit
    (`ERR_SESSION_WINDOW_CONFLICT`); a roster arrives inside its hard filing
    window (`ERR_ROSTER_WINDOW_CLOSED`) — HTTP 409. On a course:
    `credited_minutes_total` is the sum of its allocation minutes, which must
    equal `total_minutes`, and `verified_credit_record_count` is the number of
    credit records for that course currently in the verified state — incremented
    when a record becomes verified and decremented when a verified record is
    voided.

    Design: Difficulty/priority_pair_validation_conflict/expired_course_window_check_outranks_duplicate_record_constraint_on_refiling
    """
    state = build_live_session_claimed_at_its_expiry_instant()

    # An hour before approval ran out, so only the uniqueness constraint of
    # PRD §2.8 step 16 is broken.
    response = refile_claim(
        api, state["attorney"], state["course"], "2026-03-01T12:00:00Z"
    )

    validate_error(response, "ERR_DUPLICATE_CREDIT_RECORD")
    records = list_credit_records(
        attorney_id=state["attorney"]["id"], course_id=state["course"]["id"]
    )
    assert len(records) == 1, records
    assert records[0]["id"] == state["record"]["id"], records
    course = read_course(state["course"]["id"])
    assert course["verified_credit_record_count"] == 1, course
