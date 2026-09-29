"""Driving an audit wave through its declared lifecycles.

An audit program travels from draft through scoping, announcement, the amnesty
period, the response window and escalation; alongside it a case, a dependent, a
proof submission, a termination notice and an appeal each run their own
lifecycle. This module walks the sanctioned moves, the moves that are refused
because a precondition is unmet, and the terminal states that refuse a replay.
"""
from __future__ import annotations

from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import api_errors as E
from test_helpers import factories as f
from test_helpers.assertions import (
    assert_fields,
    assert_instant_equals,
    assert_priority_score,
)
from test_helpers.fixtures import (
    ANNOUNCE_INSTANT,
    APPEAL_INSTANT,
    ELECTION_DEADLINE_INSTANT,
    RESPONSE_WINDOW_INSTANT,
    announced_wave,
    appeal_wave,
    audit_wave,
    escalated_wave,
    finalized_wave,
)
from test_helpers.test_users import (
    ANALYST_USER_ID,
    PROGRAM_ADMIN,
    REVIEWER,
    employee_headers,
)


def test_deciding_scope_moves_the_program_to_scoped_and_freezes_one_case_per_subscriber(
    b, client
):
    """On success, every selected dependent moves `ENROLLED → PENDING_VERIFICATION`,
    each affected employee's `enrolled_dependent_count` is recomputed, the program's
    `scope_type` is recorded, `status` becomes `SCOPED`, and `in_scope_case_count`,
    `in_scope_dependent_count`, and `pending_dependent_count` are refreshed. ... The
    program's `version` increments by 1.

    Design: Corner/state_machines/corner_scope_run_moves_program_to_scoped_and_creates_selected_case_with_pending_dependents
    """
    ctx = audit_wave(b, stage="DRAFT", relationships=("SPOUSE", "CHILD_BIOLOGICAL"))
    assert ctx.program["version"] == 1, ctx.program

    response = client.run_scope(
        ctx.program["id"], f.scope_payload(1, "FULL_CENSUS"), PROGRAM_ADMIN
    )
    program = validate_success(response)

    assert_fields(
        program,
        status="SCOPED",
        scope_type="FULL_CENSUS",
        version=2,
        in_scope_case_count=1,
        in_scope_dependent_count=2,
        pending_dependent_count=2,
        announcement_at=None,
    )

    cases, case_meta = validate_paginated(
        client.list_cases(PROGRAM_ADMIN, params={"program_id": ctx.program["id"]})
    )
    assert case_meta["total_count"] == 1, case_meta
    case = cases[0]
    assert_fields(
        case,
        program_id=ctx.program["id"],
        employee_id=ctx.employee["id"],
        status="SELECTED",
        in_scope_dependent_ids=[ctx.dep1["id"], ctx.dep2["id"]],
        in_scope_dependent_count=2,
        proof_submission_count=0,
        reminders_sent_count=0,
        communication_sequence_no=0,
        notified_at=None,
    )

    for dependent in (ctx.dep1, ctx.dep2):
        assert (
            b.read_dependent(dependent["id"])["coverage_status"]
            == "PENDING_VERIFICATION"
        )


def test_a_freshly_scoped_case_is_triaged_on_its_unverified_household_and_its_silence(
    b, client
):
    """A **sensitive-relationship flag** contributes 25 whenever at least one
    in-scope dependent has a `relationship_type` of `DOMESTIC_PARTNER`, `STEPCHILD`,
    or `LEGAL_GUARDIANSHIP`, and contributes nothing otherwise ... A **silence
    flag** contributes 15 when the case's `proof_submission_count` is exactly zero,
    and nothing otherwise.

    Design: Corner/state_machines/corner_scope_run_moves_program_to_scoped_and_creates_selected_case_with_pending_dependents
    """
    ctx = audit_wave(b, stage="DRAFT", relationships=("SPOUSE", "CHILD_BIOLOGICAL"))

    validate_success(
        client.run_scope(
            ctx.program["id"], f.scope_payload(1, "FULL_CENSUS"), PROGRAM_ADMIN
        )
    )

    case = b.case(ctx.program["id"])
    assert_priority_score(
        case,
        unverified=2,
        in_scope=2,
        sensitive=False,
        reminders=0,
        max_reminders=3,
        silent=True,
    )
    assert case["priority_score"] == 55, case


def test_announcing_a_program_that_has_not_been_scoped_is_refused_on_its_phase(
    b, client, clock
):
    """The program must be in `SCOPED` and at least one of its cases must still be in
    `SELECTED`; otherwise the request is refused with `ERR_PROGRAM_PHASE_INVALID`.

    Design: Corner/state_machines/corner_communicate_on_a_draft_program_is_rejected_before_any_case_is_notified
    """
    program = b.program()
    b.doc_rule(program["id"], "SPOUSE")

    response = client.communicate(
        program["id"], f.communicate_payload(), PROGRAM_ADMIN
    )

    validate_error(response, E.ERR_PROGRAM_PHASE_INVALID, expected_status=409)
    assert_fields(
        b.read_program(program["id"]),
        status="DRAFT",
        announcement_at=None,
        amnesty_end_at=None,
        response_deadline_at=None,
        version=1,
    )


def test_a_marriage_certificate_submission_is_standard_and_needs_no_redaction(b, client):
    """A submission's `privacy_class` is computed from this designation alone and is
    never supplied by the caller: it is `SENSITIVE` when the offered `proof_type` is
    one of those four, and `STANDARD` for every other proof type. ... Its
    `privacy_status` starts at `REDACTED` when the proof type is sensitive and
    `redaction_applied` was true, and at `NOT_REQUIRED` in every other case.

    Design: Corner/state_machines/corner_new_proof_submission_starts_submitted_with_standard_privacy_class
    """
    ctx = announced_wave(b)
    b.set_clock("2026-09-05T00:00:00Z")

    response = client.create_proof_submission(
        f.proof_submission_payload(
            ctx.case["id"], ctx.dep["id"], "MARRIAGE_CERTIFICATE"
        ),
        employee_headers(ctx.employee["id"]),
    )
    submission = validate_success(response, expected_status=201)

    assert_fields(submission, privacy_class="STANDARD", privacy_status="NOT_REQUIRED")


def test_a_newly_lodged_submission_is_unreviewed_with_every_decision_stamp_still_empty(
    b, client
):
    """A newly created submission starts with `review_status` `SUBMITTED`. ... Its
    `reviewed_by_user_id`, `decision_reason_code`, `decided_at`, and
    `redacted_document_reference` all start null.

    Design: Corner/state_machines/corner_new_proof_submission_starts_submitted_with_standard_privacy_class
    """
    ctx = announced_wave(b)
    b.set_clock("2026-09-05T00:00:00Z")

    response = client.create_proof_submission(
        f.proof_submission_payload(
            ctx.case["id"], ctx.dep["id"], "MARRIAGE_CERTIFICATE"
        ),
        employee_headers(ctx.employee["id"]),
    )
    submission = validate_success(response, expected_status=201)

    assert_fields(
        submission,
        case_id=ctx.case["id"],
        dependent_id=ctx.dep["id"],
        review_status="SUBMITTED",
        reviewed_by_user_id=None,
        decision_reason_code=None,
        decided_at=None,
        redacted_document_reference=None,
    )


def test_the_first_document_offered_on_a_notified_case_puts_that_case_in_progress(
    b, client
):
    """Throughout the amnesty and response windows, the first response of any kind on
    a notified case moves it `NOTIFIED → IN_PROGRESS`, which requires the program to
    be in either `AMNESTY_OPEN` or `RESPONSE_WINDOW`; the case's
    `proof_submission_count`, `unverified_dependent_count`, and `priority_score` are
    recomputed

    Design: Corner/state_machines/corner_new_proof_submission_starts_submitted_with_standard_privacy_class
    """
    ctx = announced_wave(b)
    assert ctx.case["status"] == "NOTIFIED", ctx.case
    b.set_clock("2026-09-05T00:00:00Z")

    validate_success(
        client.create_proof_submission(
            f.proof_submission_payload(
                ctx.case["id"], ctx.dep["id"], "MARRIAGE_CERTIFICATE"
            ),
            employee_headers(ctx.employee["id"]),
        ),
        expected_status=201,
    )

    assert_fields(
        b.read_case(ctx.case["id"]),
        status="IN_PROGRESS",
        proof_submission_count=1,
        unverified_dependent_count=1,
    )


def test_offering_proof_for_a_dependent_already_surrendered_under_amnesty_is_refused(
    b, client
):
    """the dependent's `coverage_status` must be exactly `PENDING_VERIFICATION` and its
    identifier must appear in the case's `in_scope_dependent_ids`, since a submission
    for someone outside the frozen scope set is meaningless. ... Dependent coverage
    status and scope membership admit the operation — `ERR_DEPENDENT_STATE_INVALID`
    (409), on proof submission, amnesty removal, appeal filing, and claim recovery
    creation.

    Design: Corner/state_machines/corner_proof_submission_for_an_amnesty_removed_dependent_is_rejected
    """
    ctx = announced_wave(b, relationships=("SPOUSE", "CHILD_BIOLOGICAL"))
    b.set_clock("2026-09-10T00:00:00Z")
    b.amnesty_removal(
        ctx.dep2["id"],
        ctx.case["id"],
        employee_id=ctx.employee["id"],
        reason_code="AGE_LIMIT_EXCEEDED",
    )

    response = client.create_proof_submission(
        f.proof_submission_payload(
            ctx.case["id"], ctx.dep2["id"], "BIRTH_CERTIFICATE"
        ),
        employee_headers(ctx.employee["id"]),
    )

    validate_error(response, E.ERR_DEPENDENT_STATE_INVALID, expected_status=409)
    assert_fields(b.read_dependent(ctx.dep2["id"]), coverage_status="AMNESTY_REMOVED")
    sibling = b.submit_proof(
        ctx.case["id"],
        ctx.dep1["id"],
        employee_id=ctx.employee["id"],
        proof_type="MARRIAGE_CERTIFICATE",
    )
    assert_fields(sibling, review_status="SUBMITTED", dependent_id=ctx.dep1["id"])


def test_publishing_the_announcement_a_second_time_is_refused_on_the_programs_phase(
    b, client
):
    """The program must be in `SCOPED` and at least one of its cases must still be in
    `SELECTED`; otherwise the request is refused with `ERR_PROGRAM_PHASE_INVALID`. ...
    one `CommunicationEvent` is appended per case with `kind` `ANNOUNCEMENT` and
    `sequence_no` 1, and each case's `communication_sequence_no` becomes 1

    Design: Corner/state_machines/corner_second_communicate_on_an_announced_program_is_rejected
    """
    ctx = announced_wave(b)

    response = client.communicate(
        ctx.program["id"], f.communicate_payload(channel="MAIL"), PROGRAM_ADMIN
    )

    validate_error(response, E.ERR_PROGRAM_PHASE_INVALID, expected_status=409)
    events, meta = b.communications(ctx.case["id"], limit=10, offset=0)
    assert meta["total_count"] == 1, meta
    assert_fields(events[0], kind="ANNOUNCEMENT", sequence_no=1, channel="EMAIL")
    program = b.read_program(ctx.program["id"])
    assert_fields(program, status="AMNESTY_OPEN")
    assert_instant_equals(program["announcement_at"], ANNOUNCE_INSTANT)
    assert_fields(b.read_case(ctx.case["id"]), communication_sequence_no=1)


def test_attesting_twice_to_the_same_dependents_ineligibility_reports_the_prior_record(
    b, client
):
    """The already-removed status is deliberately admitted at that gate precisely so
    that a duplicate removal falls through to the last gate and reports the specific
    `ERR_AMNESTY_ALREADY_RECORDED` — at most one amnesty removal may ever exist for a
    given dependent.

    Design: Corner/state_machines/corner_second_amnesty_removal_for_the_same_dependent_returns_already_recorded
    """
    ctx = announced_wave(b, relationships=("SPOUSE", "CHILD_BIOLOGICAL"))
    b.set_clock("2026-09-10T00:00:00Z")
    b.amnesty_removal(
        ctx.dep1["id"],
        ctx.case["id"],
        employee_id=ctx.employee["id"],
        reason_code="DIVORCE_FINALIZED",
    )

    response = client.create_amnesty_removal(
        f.amnesty_removal_payload(ctx.dep1["id"], ctx.case["id"]),
        employee_headers(ctx.employee["id"]),
    )

    validate_error(response, E.ERR_AMNESTY_ALREADY_RECORDED, expected_status=409)
    _rows, meta = b.dependent_removals(ctx.dep1["id"], limit=10, offset=0)
    assert meta["total_count"] == 1, meta
    assert_fields(b.read_program(ctx.program["id"]), amnesty_removed_count=1)
    assert_fields(b.read_case(ctx.case["id"]), status="IN_PROGRESS")


def test_accepting_the_last_outstanding_document_verifies_the_dependent_and_closes_out_the_case(
    b, client
):
    """The moment the test flips to true for a dependent under audit, the dependent
    moves `PENDING_VERIFICATION → VERIFIED` with `documentation_complete` set to true.
    That resolution ripples upward: the owning case recomputes
    `unverified_dependent_count` and `priority_score`, the program recomputes
    `verified_dependent_count` and `pending_dependent_count`, and if this was the
    case's last unresolved in-scope dependent the case moves to `COMPLETE` with
    `completed_at` set to the current clock instant.

    Design: Corner/state_machines/corner_accepting_the_last_dependents_proof_bubbles_the_case_to_complete
    """
    ctx = announced_wave(b)
    b.set_clock("2026-09-05T00:00:00Z")
    submission = b.submit_proof(
        ctx.case["id"],
        ctx.dep["id"],
        employee_id=ctx.employee["id"],
        proof_type="MARRIAGE_CERTIFICATE",
    )
    b.set_clock(RESPONSE_WINDOW_INSTANT)
    b.sweep(ctx.program["id"])

    decided = b.accept_proof(submission["id"])

    assert_fields(
        decided,
        review_status="ACCEPTED",
        reviewed_by_user_id=ANALYST_USER_ID,
        decision_reason_code="VERIFIED_MATCH",
    )
    assert_instant_equals(decided["decided_at"], RESPONSE_WINDOW_INSTANT)
    assert_fields(
        b.read_dependent(ctx.dep["id"]),
        coverage_status="VERIFIED",
        accepted_proof_type_count=1,
        documentation_complete=True,
    )
    case = b.read_case(ctx.case["id"])
    assert_fields(case, status="COMPLETE", unverified_dependent_count=0)
    assert_instant_equals(case["completed_at"], RESPONSE_WINDOW_INSTANT)
    assert_fields(
        b.read_program(ctx.program["id"]),
        verified_dependent_count=1,
        pending_dependent_count=0,
        responded_case_count=1,
    )


def test_the_checkpoint_expires_a_continuation_window_nobody_answered(b, client):
    """Every `TerminationNotice` whose `status` is `ISSUED` or `FINAL`, whose
    `continuation_election_status` is still `NOT_ELECTED`, and whose
    `continuation_election_deadline` is strictly earlier than the current clock
    instant, moves its `continuation_election_status` to `WINDOW_EXPIRED`.

    Design: Corner/state_machines/corner_sweep_step_s6_expires_the_unelected_continuation_window_and_blocks_later_election
    """
    ctx = finalized_wave(b)
    notice = b.notice_for(ctx.dep["id"])
    assert_fields(
        notice, status="FINAL", continuation_election_status="NOT_ELECTED"
    )
    assert_instant_equals(
        notice["continuation_election_deadline"], ELECTION_DEADLINE_INSTANT
    )

    b.set_clock("2026-12-17T00:00:00Z")
    b.sweep(ctx.program["id"])

    assert_fields(
        b.read_notice(notice["id"]),
        status="FINAL",
        continuation_election_status="WINDOW_EXPIRED",
        continuation_elected_at=None,
        continuation_monthly_premium_cents=0,
        continuation_start_date=None,
        continuation_end_date=None,
    )


def test_electing_continuation_after_the_window_expired_is_refused_on_the_notice_state(
    b, client
):
    """The notice's `status` must be `ISSUED` or `FINAL` and its
    `continuation_election_status` must still be `NOT_ELECTED`; a notice that is
    already rescinded, already elected, already waived, or already expired is refused
    with `ERR_NOTICE_STATE_INVALID`.

    Design: Corner/state_machines/corner_sweep_step_s6_expires_the_unelected_continuation_window_and_blocks_later_election
    """
    ctx = finalized_wave(b)
    notice = b.notice_for(ctx.dep["id"])
    b.set_clock("2026-12-17T00:00:00Z")
    b.sweep(ctx.program["id"])

    response = client.continuation_election(
        notice["id"],
        f.continuation_election_payload("ELECT"),
        employee_headers(ctx.employee["id"]),
    )

    validate_error(response, E.ERR_NOTICE_STATE_INVALID, expected_status=409)
    assert_fields(
        b.read_notice(notice["id"]),
        continuation_election_status="WINDOW_EXPIRED",
        continuation_elected_at=None,
        continuation_monthly_premium_cents=0,
    )


def test_waiving_continuation_records_the_choice_and_prices_nothing(b, client):
    """A waiver moves `continuation_election_status` from `NOT_ELECTED` to `WAIVED`,
    leaves `continuation_monthly_premium_cents` at zero, and leaves both continuation
    dates null.

    Design: Corner/state_machines/corner_continuation_waive_records_the_election_without_pricing_a_premium
    """
    ctx = escalated_wave(b)
    notice = b.notice_for(ctx.dep["id"])
    assert_fields(notice, status="ISSUED", origin="AUDIT_ESCALATION")
    b.set_clock("2026-10-20T00:00:00Z")

    waived = b.continuation_election(
        notice["id"], "WAIVE", employee_id=ctx.employee["id"]
    )

    assert_fields(
        waived,
        status="ISSUED",
        continuation_election_status="WAIVED",
        continuation_monthly_premium_cents=0,
        continuation_start_date=None,
        continuation_end_date=None,
    )
    assert_instant_equals(waived["continuation_elected_at"], "2026-10-20T00:00:00Z")


def test_a_second_ruling_on_an_already_denied_appeal_is_refused(b, client):
    """Only the assigned reviewer may then decide, and only while the appeal is
    `UNDER_REVIEW`; a decision from anyone else is refused with
    `ERR_APPEAL_REVIEWER_MISMATCH` and a decision against an appeal in any other
    status is refused with `ERR_APPEAL_STATE_INVALID`. ... The dependent's
    `TerminationNotice` proceeds entirely unchanged

    Design: Corner/state_machines/corner_second_decision_on_a_denied_appeal_is_rejected
    """
    ctx = appeal_wave(b, grounds="DOCUMENT_UNAVAILABLE")
    denied = b.decide_appeal(ctx.appeal["id"], "DENY", REVIEWER)
    assert_fields(denied, status="DENIED", round_number=1)
    assert_instant_equals(denied["decided_at"], APPEAL_INSTANT)

    response = client.decide_appeal(
        ctx.appeal["id"], f.appeal_decision_payload("GRANT"), REVIEWER
    )

    validate_error(response, E.ERR_APPEAL_STATE_INVALID, expected_status=409)
    assert_fields(b.read_appeal(ctx.appeal["id"]), status="DENIED", round_number=1)
    assert_fields(
        b.read_dependent(ctx.dep["id"]),
        coverage_status="TERMINATED",
        reinstated_at=None,
    )
    assert_fields(
        b.notice_for(ctx.dep["id"]),
        status="FINAL",
        rescinded_at=None,
        rescission_reason=None,
    )
