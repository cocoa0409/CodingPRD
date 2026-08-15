"""State-machine claims: invalid transitions, terminal lockdowns, and the
close-registration cascade (PRD 3.1, 3.4, 3.5, 3.8)."""
from test_helpers import (
    CLOCK_AFTER_HS_WITHDRAW,
    CLOCK_BEFORE_COLLEGE_END,
    ApiErrorId,
    assert_invoice,
    close_term,
    confirm_enrollment,
    confirm_enrollment_raw,
    create_credential_application,
    create_college_term,
    create_course,
    create_high_school,
    create_instructor,
    drop_enrollment,
    finalize_offering,
    first_invoice_for_enrollment,
    get_credential_application,
    get_enrollment,
    get_invoice,
    get_offering,
    get_student,
    list_transcript_entries_for_enrollment,
    move_offering_to_grading,
    open_term,
    register_and_confirm,
    register_student,
    set_clock,
    setup_base,
    setup_graded_scenario,
    setup_mixed_enrollment_scenario,
    start_session,
    submit_grade,
    validate_error,
    validate_success,
)
import pytest


def test_term_close_from_closed_rejected(api, admin_headers):
    """PRD 3.1: "The administrator moves a term from `SCHEDULED` to `OPEN` via
    open-registration (invalid in any other state, rejected with
    `ERR_TERM_INVALID_STATE`, HTTP 409), and from `OPEN` to `CLOSED` via
    close-registration (same error on a state mismatch)."

    Design: Corner/state_machines/term_close_from_closed_rejected
    """
    term = create_college_term()
    open_term(term["id"])
    close_term(term["id"])

    response = api.close_term_registration(term["id"], admin_headers)
    validate_error(response, ApiErrorId.ERR_TERM_INVALID_STATE.value)
    term_after = validate_success(api.get_term(term["id"], admin_headers))
    assert term_after["status"] == "CLOSED", (
        f"A rejected second close must leave the term CLOSED, got {term_after['status']}"
    )


def test_offering_finalize_from_draft_rejected(api, registrar_headers):
    """PRD 3.8: "A `CollegeRegistrar` finalizes the offering, moving it from
    `GRADING` to the terminal `FINALIZED` state (any other origin state is
    `ERR_OFFERING_INVALID_STATE`)."

    Design: Corner/state_machines/offering_finalize_from_draft_rejected
    """
    ctx = setup_base(approve_credential=False, open_offering_flag=False)
    assert ctx["offering"]["status"] == "DRAFT"

    response = api.finalize_offering(ctx["offering"]["id"], registrar_headers)
    validate_error(response, ApiErrorId.ERR_OFFERING_INVALID_STATE.value)


def test_confirm_dropped_enrollment_terminal_lockdown(api):
    """PRD 3.5: "The request carries `expected_offering_version` per §2.8, and the
    checks run in this order: the enrollment is in `PENDING_VERIFICATION` (else
    `ERR_ENROLLMENT_INVALID_STATE`, HTTP 409); the offering's current `version`
    matches `expected_offering_version` (else `ERR_STALE_VERSION`, HTTP 412); the
    offering is `OPEN` (else `ERR_OFFERING_INVALID_STATE`); the student is
    `ELIGIBLE` and has `grade_level` at least 11 (else `ERR_STUDENT_NOT_ELIGIBLE`);
    the student's school is `ACTIVE` (else `ERR_SCHOOL_SUSPENDED`); the logical
    clock reads at or before the earlier of the two terms' `add_deadline` values
    (else `ERR_ADD_WINDOW_CLOSED`, HTTP 409); both terms are `OPEN` (else
    `ERR_TERM_NOT_OPEN`); every prerequisite of the offering's course is satisfied
    (else `ERR_PREREQUISITE_NOT_MET`, HTTP 409); placement requirements are met
    (else `ERR_PLACEMENT_MISSING` or `ERR_PLACEMENT_SCORE_INSUFFICIENT`, HTTP 409);
    and a `FundingAgreement` exists for the offering's `high_school_id` and
    `college_term_id` pair (else `ERR_NO_FUNDING_AGREEMENT`, HTTP 409)."
    PRD 3.5: "Drop moves the enrollment to `DROPPED`, decrements `seats_taken` by 1,
    and increments the offering's `version`."

    Design: Corner/state_machines/confirm_dropped_enrollment_terminal_lockdown
    """
    ctx = setup_base()
    pair = register_and_confirm(ctx)
    enrollment_id = pair["enrollment"]["id"]
    drop_enrollment(enrollment_id)
    assert get_enrollment(enrollment_id)["status"] == "DROPPED"

    response = confirm_enrollment_raw(ctx["offering"]["id"], enrollment_id)
    validate_error(response, ApiErrorId.ERR_ENROLLMENT_INVALID_STATE.value)
    assert get_enrollment(enrollment_id)["status"] == "DROPPED", (
        "DROPPED is terminal: a failed confirm must not move the enrollment"
    )


def test_credential_approve_from_submitted_rejected(api, reviewer_headers):
    """PRD 3.3: "The application's `status` starts at `SUBMITTED` with `reviewed_by`
    null."
    PRD 3.3: "From `UNDER_REVIEW`, three decisions are possible, each restricted to
    the review owner — the caller's `X-User-ID` must equal `reviewed_by`, else
    `ERR_NOT_RESOURCE_OWNER` — and each subject to segregation of duties, so the
    caller's `X-User-ID` must differ from `instructor_id`, else
    `ERR_CREDENTIAL_SELF_APPROVAL`."
    PRD 2.10: "The auth checks come first: presence and validity of `X-User-ID` and
    `X-User-Role` (priority 1), then role authorization (priority 2), then
    entity-backed ownership and segregation-of-duties (priority 3)."

    A SUBMITTED application has `reviewed_by` null, so any reviewer calling
    approve fails the priority-3 ownership check — which surfaces before the
    priority-6 state precondition per PRD 2.10.

    Design: Corner/state_machines/credential_approve_from_submitted_rejected
    """
    school = create_high_school()
    course = create_course(
        course_code="MATH151",
        title="College Algebra",
        placement_exam_code="MATH",
        min_placement_score=70,
    )
    instructor = create_instructor(school["id"])
    application = create_credential_application(instructor["id"], course["id"])
    assert application["status"] == "SUBMITTED"

    response = api.approve_credential_application(application["id"], {}, reviewer_headers)
    validate_error(response, ApiErrorId.ERR_NOT_RESOURCE_OWNER.value)
    assert get_credential_application(application["id"])["status"] == "SUBMITTED", (
        "A rejected approve must not move the application out of SUBMITTED"
    )


def test_withdraw_during_drop_window_rejected(api, coordinator_headers):
    """PRD 3.5: "The coordinator may withdraw a `REGISTERED` enrollment only when
    the logical clock reads strictly after the earlier of the two `drop_deadline`
    values — a withdraw attempted while the drop window is still open is rejected
    with `ERR_ENROLLMENT_INVALID_STATE`, because drop must be used instead — and at
    or before the earlier of the two `withdraw_deadline` values (else
    `ERR_WITHDRAW_WINDOW_CLOSED`, HTTP 409)."
    PRD 3.10: "The clock's startup default is exactly `2026-08-01T00:00:00Z`, and
    before any set call it reads that default."

    Design: Corner/state_machines/withdraw_during_drop_window_rejected
    """
    ctx = setup_base()
    pair = register_and_confirm(ctx)
    enrollment_id = pair["enrollment"]["id"]

    response = api.withdraw_enrollment(enrollment_id, coordinator_headers)
    validate_error(response, ApiErrorId.ERR_ENROLLMENT_INVALID_STATE.value)
    assert get_enrollment(enrollment_id)["status"] == "REGISTERED", (
        "A refused withdraw must leave the enrollment REGISTERED"
    )


def test_withdraw_after_window_closed_rejected(api, coordinator_headers):
    """PRD 3.5: "The coordinator may withdraw a `REGISTERED` enrollment only when
    the logical clock reads strictly after the earlier of the two `drop_deadline`
    values — a withdraw attempted while the drop window is still open is rejected
    with `ERR_ENROLLMENT_INVALID_STATE`, because drop must be used instead — and at
    or before the earlier of the two `withdraw_deadline` values (else
    `ERR_WITHDRAW_WINDOW_CLOSED`, HTTP 409)."
    PRD 2.4: "Three effective deadlines are derived from the pair by taking the
    earlier instant in each case: the effective add deadline is the earlier of
    `college_term.add_deadline` and `hs_term.add_deadline`; the effective drop
    deadline is the earlier of `college_term.drop_deadline` and
    `hs_term.drop_deadline`; the effective withdraw deadline is the earlier of
    `college_term.withdraw_deadline` and `hs_term.withdraw_deadline`."

    Design: Corner/state_machines/withdraw_after_window_closed_rejected
    """
    ctx = setup_base()
    pair = register_and_confirm(ctx)
    enrollment_id = pair["enrollment"]["id"]
    # Past the earlier of (college withdraw 2026-11-01, HS withdraw 2026-10-25).
    set_clock(CLOCK_AFTER_HS_WITHDRAW)

    response = api.withdraw_enrollment(enrollment_id, coordinator_headers)
    validate_error(response, ApiErrorId.ERR_WITHDRAW_WINDOW_CLOSED.value)


def test_close_registration_expires_waitlisted(api, admin_headers):
    """PRD 3.1: "Closing a term has a cascade: every `WAITLISTED` enrollment whose
    offering is tied to this term — through either its `college_term_id` or its
    `hs_term_id` — transitions to `EXPIRED`, retaining its `waitlist_seq`, which is
    never reused."

    Design: Corner/state_machines/close_registration_expires_waitlisted
    """
    ctx = setup_mixed_enrollment_scenario(capacity=1, num_students=2)
    registered = ctx["enrollments"][0]
    waitlisted = ctx["enrollments"][1]
    assert registered["status"] == "REGISTERED"
    assert waitlisted["status"] == "WAITLISTED"
    assert waitlisted["waitlist_seq"] == 1

    response = api.close_term_registration(ctx["hs_term"]["id"], admin_headers)
    term = validate_success(response)
    assert term["status"] == "CLOSED"

    expired = get_enrollment(waitlisted["id"])
    assert expired["status"] == "EXPIRED", (
        f"WAITLISTED enrollment of an offering tied to the closed HS term must be "
        f"EXPIRED, got {expired['status']}"
    )
    assert expired["waitlist_seq"] == 1, "waitlist_seq is retained as audit"
    untouched = get_enrollment(registered["id"])
    assert untouched["status"] == "REGISTERED", (
        f"The REGISTERED enrollment must be unaffected, got {untouched['status']}"
    )


def test_confirm_after_term_close_returns_term_not_open(api):
    """PRD 3.1: "`PENDING_VERIFICATION` enrollments are not cancelled by
    close-registration; they remain, but any later confirm attempt against them
    fails the terms-OPEN check with `ERR_TERM_NOT_OPEN`."

    Design: Corner/state_machines/confirm_after_term_close_returns_term_not_open
    """
    ctx = setup_base()
    pair = register_student(ctx)
    enrollment_id = pair["enrollment"]["id"]
    close_term(ctx["college_term"]["id"])

    response = confirm_enrollment_raw(ctx["offering"]["id"], enrollment_id)
    validate_error(response, ApiErrorId.ERR_TERM_NOT_OPEN.value)
    assert get_enrollment(enrollment_id)["status"] == "PENDING_VERIFICATION", (
        "A failed confirm must leave the enrollment PENDING_VERIFICATION"
    )


def test_begin_grading_before_term_end_rejected(api, admin_headers):
    """PRD 3.4: "From `IN_SESSION`, the administrator begins grading, moving to
    `GRADING`; this requires the logical clock to read at or after the college
    term's `end_date`, and is rejected with `ERR_TERM_NOT_ENDED` (HTTP 409) when the
    college term has not yet ended."

    Design: Corner/state_machines/begin_grading_before_term_end_rejected
    """
    ctx = setup_base()
    start_session(ctx["offering"]["id"])
    set_clock(CLOCK_BEFORE_COLLEGE_END)  # 2026-12-01 < college end 2026-12-15

    response = api.begin_offering_grading(ctx["offering"]["id"], admin_headers)
    validate_error(response, ApiErrorId.ERR_TERM_NOT_ENDED.value)
    assert get_offering(ctx["offering"]["id"])["status"] == "IN_SESSION", (
        "A rejected begin-grading must leave the offering IN_SESSION"
    )


def test_finalize_with_ungraded_enrollment_rejected(api, registrar_headers):
    """PRD 3.8: "Finalize requires every `REGISTERED` enrollment on the offering to
    carry a non-null `grade`; if any is ungraded the request fails with
    `ERR_GRADES_MISSING` (HTTP 409)."

    Design: Corner/state_machines/finalize_with_ungraded_enrollment_rejected
    """
    ctx = setup_base()
    pair = register_and_confirm(ctx)
    enrollment_id = pair["enrollment"]["id"]
    move_offering_to_grading(ctx["offering"]["id"])

    response = api.finalize_offering(ctx["offering"]["id"], registrar_headers)
    validate_error(response, ApiErrorId.ERR_GRADES_MISSING.value)
    assert get_offering(ctx["offering"]["id"])["status"] == "GRADING", (
        "A rejected finalize must leave the offering GRADING"
    )
    entries = list_transcript_entries_for_enrollment(enrollment_id)
    assert entries == [], f"No transcript entries may be created, got {len(entries)}"


def test_transcript_post_twice_rejected(api, registrar_headers):
    """PRD 3.8: "The registrar posts an entry, moving it from `PENDING` to `POSTED`
    (any other origin state is `ERR_TRANSCRIPT_ENTRY_INVALID_STATE`, HTTP 409), and
    the student's GPA for that entry's institution is recomputed."
    PRD 3.8: "The college GPA is the sum of `grade_points` over `POSTED` `COLLEGE`
    entries with grades `A` through `F`, divided by the sum of those entries'
    `credit_value`."

    Design: Corner/state_machines/transcript_post_twice_rejected
    """
    ctx = setup_graded_scenario(grade="A")
    college_entry = list_transcript_entries_for_enrollment(
        ctx["enrollment"]["id"], institution="COLLEGE"
    )[0]
    posted = validate_success(api.post_transcript_entry(college_entry["id"], registrar_headers))
    assert posted["status"] == "POSTED"

    response = api.post_transcript_entry(college_entry["id"], registrar_headers)
    validate_error(response, ApiErrorId.ERR_TRANSCRIPT_ENTRY_INVALID_STATE.value)

    student = get_student(ctx["student"]["id"])
    assert student["college_gpa"] == pytest.approx(4.0, abs=1e-9), (
        f"A 3-credit A posted once must yield college_gpa 4.000 (12 points / 3 "
        f"hours), got {student['college_gpa']} — double-posting must not double-count"
    )


def test_payment_on_voided_invoice_rejected(api, bursar_headers):
    """PRD 3.7: "The payment is rejected with `ERR_INVOICE_INVALID_STATE` (HTTP 409)
    when the invoice is not in `ISSUED` or `PARTIALLY_PAID` — a `VOIDED` invoice
    cannot take payments — and with `ERR_OVERPAYMENT` (HTTP 409) when the payment
    would push the payer's running paid total above that payer's billed share."
    PRD 3.5: "It also settles the enrollment's invoice per §3.7 with `refund_pct`
    set to 100."

    Design: Corner/state_machines/payment_on_voided_invoice_rejected
    """
    ctx = setup_base()
    pair = register_and_confirm(ctx)
    invoice = first_invoice_for_enrollment(pair["enrollment"]["id"])
    drop_enrollment(pair["enrollment"]["id"])
    voided = get_invoice(invoice["id"])
    assert voided["status"] == "VOIDED"

    response = api.create_payment(
        invoice["id"], {"payer": "FAMILY", "amount_cents": 30000}, bursar_headers
    )
    validate_error(response, ApiErrorId.ERR_INVOICE_INVALID_STATE.value)
    after = get_invoice(invoice["id"])
    assert_invoice(after)
    assert after["status"] == "VOIDED"
    assert after["paid_family_cents"] == 0, (
        f"A rejected payment must not partially apply; paid_family_cents == "
        f"{after['paid_family_cents']}"
    )
