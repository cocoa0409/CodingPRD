"""The deadlines and the documentation policy of a dependent eligibility audit.

Each of the audit's windows is a closed interval whose final instant is still
inside it — the amnesty end, the response deadline, the thirty-day appeal
window and the sixty-day continuation election — and each closes with its own
refusal. Alongside them sit the policy gates that decide whether a program may
publish a rule, scope a population, or accept an offered document at all.
"""
from __future__ import annotations

import pytest

from prd_bench_local_runner.testing import validate_error, validate_paginated

from test_helpers import api_errors as E
from test_helpers import factories as f
from test_helpers.assertions import (
    assert_case,
    assert_dependent,
    assert_instant_equals,
    assert_notice,
    assert_page_meta,
    assert_program,
    assert_submission,
)
from test_helpers.fixtures import (
    AMNESTY_END_INSTANT,
    APPEAL_WINDOW_END_INSTANT,
    ELECTION_DEADLINE_INSTANT,
    ESCALATION_INSTANT,
    RESPONSE_DEADLINE_INSTANT,
    RESPONSE_WINDOW_INSTANT,
    announced_wave,
    escalated_wave,
    finalized_wave,
    response_window_wave,
)
from test_helpers.test_users import (
    ANALYST,
    ANALYST_USER_ID,
    PROGRAM_ADMIN,
    employee_headers,
)

# One day past each closed window.
_AFTER_AMNESTY_END_INSTANT = "2026-09-23T00:00:00Z"
_LATE_SUBMISSION_INSTANT = "2026-10-20T00:00:00Z"
_AFTER_APPEAL_WINDOW_INSTANT = "2026-11-17T00:00:00Z"
_LATE_ELECTION_INSTANT = "2026-12-17T00:00:00Z"

# The reminder cadence: three chases exactly seven whole days apart.
_FIRST_REMINDER_INSTANT = "2026-09-08T00:00:00Z"
_SECOND_REMINDER_INSTANT = "2026-09-15T00:00:00Z"
_THIRD_REMINDER_INSTANT = "2026-09-22T00:00:00Z"
_ONE_DAY_AFTER_THIRD_REMINDER = "2026-09-23T00:00:00Z"
_SEVEN_DAYS_AFTER_THIRD_REMINDER = "2026-09-29T00:00:00Z"

# The recency floor for an announcement on 1 September and 365 days of grace.
_RECENCY_FLOOR_DATE = "2025-09-01"
_ONE_DAY_STALE_DATE = "2025-08-31"
_MARRIAGE_CERTIFICATE_DATE = "2011-05-14"

_SPOUSE_AND_CHILD = ("SPOUSE", "CHILD_BIOLOGICAL")
_TWO_DOCUMENT_SPOUSE_RULE = {
    "SPOUSE": {
        "acceptable_proof_types": ["MARRIAGE_CERTIFICATE", "JOINT_TAX_RETURN"],
        "min_accepted_documents": 2,
        "requires_recency_days": 365,
    }
}


def test_an_amnesty_removal_recorded_on_the_amnesty_end_instant_is_admitted(b):
    """PRD §3.4: "Separately, the current clock instant must be no later than the
    program's `amnesty_end_at`; the boundary instant itself is inside the window,
    and anything past it is refused with `ERR_AMNESTY_WINDOW_CLOSED`." ... "Its
    `coverage_end_date` is the last calendar day of the month containing that
    instant — coverage runs out the end of the month, not the day of the
    attestation."

    Design: Corner/validations/corner_amnesty_removal_is_admitted_at_the_amnesty_end_instant_and_refused_one_day_later
    """
    ctx = announced_wave(b, relationships=_SPOUSE_AND_CHILD)
    assert_program(ctx.program, status="AMNESTY_OPEN")
    assert_instant_equals(ctx.program["amnesty_end_at"], AMNESTY_END_INSTANT)

    b.set_clock(AMNESTY_END_INSTANT)
    removal = b.amnesty_removal(
        ctx.dep1["id"],
        ctx.case["id"],
        employee_id=ctx.employee["id"],
        reason_code="DIVORCE_FINALIZED",
    )

    assert_instant_equals(removal["recorded_at"], AMNESTY_END_INSTANT)
    assert removal["coverage_end_date"] == "2026-09-30", removal
    assert removal["penalty_waived"] is True, removal
    assert removal["claims_recovery_waived"] is True, removal
    assert_dependent(
        b.read_dependent(ctx.dep1["id"]),
        coverage_status="AMNESTY_REMOVED",
        coverage_end_date="2026-09-30",
    )
    assert_case(b.read_case(ctx.case["id"]), status="IN_PROGRESS")


def test_an_amnesty_removal_one_day_late_is_refused_while_the_program_stays_open(
    b, client
):
    """PRD §3.4: "Separately, the current clock instant must be no later than the
    program's `amnesty_end_at`; the boundary instant itself is inside the window,
    and anything past it is refused with `ERR_AMNESTY_WINDOW_CLOSED`." ... "Both
    `penalty_waived` and `claims_recovery_waived` are recorded as true
    unconditionally"

    Design: Corner/validations/corner_amnesty_removal_is_admitted_at_the_amnesty_end_instant_and_refused_one_day_later
    """
    ctx = announced_wave(b, relationships=_SPOUSE_AND_CHILD)
    b.set_clock(AMNESTY_END_INSTANT)
    b.amnesty_removal(
        ctx.dep1["id"],
        ctx.case["id"],
        employee_id=ctx.employee["id"],
        reason_code="DIVORCE_FINALIZED",
    )

    b.set_clock(_AFTER_AMNESTY_END_INSTANT)
    late = client.create_amnesty_removal(
        f.amnesty_removal_payload(
            ctx.dep2["id"], ctx.case["id"], reason_code="AGE_LIMIT_EXCEEDED"
        ),
        employee_headers(ctx.employee["id"]),
    )

    validate_error(late, E.ERR_AMNESTY_WINDOW_CLOSED)
    assert_program(b.read_program(ctx.program["id"]), status="AMNESTY_OPEN")
    assert_dependent(
        b.read_dependent(ctx.dep2["id"]), coverage_status="PENDING_VERIFICATION"
    )
    assert_case(b.read_case(ctx.case["id"]), status="IN_PROGRESS")
    removals, meta = b.case_removals(ctx.case["id"])
    assert meta["total_count"] == 1, meta
    assert removals[0]["dependent_id"] == ctx.dep1["id"], removals


def test_a_proof_lodged_on_the_response_deadline_instant_is_accepted(b):
    """PRD §3.5: "Independently, the current clock instant must be no later than
    the program's `response_deadline_at` — the boundary instant is inside the
    window — and a submission after it is refused with
    `ERR_RESPONSE_WINDOW_CLOSED`." ... "Its `privacy_status` starts at `REDACTED`
    when the proof type is sensitive and `redaction_applied` was true, and at
    `NOT_REQUIRED` in every other case."

    Design: Corner/validations/corner_proof_submission_is_admitted_on_the_response_deadline_and_refused_afterwards
    """
    ctx = response_window_wave(b, relationships=_SPOUSE_AND_CHILD)
    assert_program(ctx.program, status="RESPONSE_WINDOW")
    assert_instant_equals(
        ctx.program["response_deadline_at"], RESPONSE_DEADLINE_INSTANT
    )

    b.set_clock(RESPONSE_DEADLINE_INSTANT)
    submission = b.submit_proof(
        ctx.case["id"], ctx.dep1["id"], ctx.employee["id"], "MARRIAGE_CERTIFICATE"
    )

    assert_submission(
        submission,
        review_status="SUBMITTED",
        privacy_class="STANDARD",
        privacy_status="NOT_REQUIRED",
    )
    assert_case(
        b.read_case(ctx.case["id"]), status="IN_PROGRESS", proof_submission_count=1
    )


def test_a_proof_lodged_after_the_response_deadline_is_refused_and_never_persisted(
    b, client
):
    """PRD §3.5: "Independently, the current clock instant must be no later than
    the program's `response_deadline_at` — the boundary instant is inside the
    window — and a submission after it is refused with
    `ERR_RESPONSE_WINDOW_CLOSED`." ... "The submission increments the case's
    `proof_submission_count` and, when it is the case's first response, drives the
    `NOTIFIED → IN_PROGRESS` move"

    Design: Corner/validations/corner_proof_submission_is_admitted_on_the_response_deadline_and_refused_afterwards
    """
    ctx = response_window_wave(b, relationships=_SPOUSE_AND_CHILD)
    b.set_clock(RESPONSE_DEADLINE_INSTANT)
    b.submit_proof(
        ctx.case["id"], ctx.dep1["id"], ctx.employee["id"], "MARRIAGE_CERTIFICATE"
    )

    b.set_clock(_LATE_SUBMISSION_INSTANT)
    late = client.create_proof_submission(
        f.proof_submission_payload(
            ctx.case["id"], ctx.dep2["id"], "BIRTH_CERTIFICATE"
        ),
        employee_headers(ctx.employee["id"]),
    )

    validate_error(late, E.ERR_RESPONSE_WINDOW_CLOSED)
    assert_case(
        b.read_case(ctx.case["id"]), status="IN_PROGRESS", proof_submission_count=1
    )
    assert_program(b.read_program(ctx.program["id"]), status="RESPONSE_WINDOW")
    _rows, meta = b.submissions(case_id=ctx.case["id"])
    assert meta["total_count"] == 1, meta


def test_an_appeal_filed_on_the_thirtieth_day_after_issuance_is_still_admitted(b):
    """PRD §3.8: "And the appeal must be timely: the current clock instant must be
    no later than the `issued_at` of the dependent's non-rescinded
    `TerminationNotice` advanced by thirty whole days, with a late filing refused
    with `ERR_APPEAL_WINDOW_CLOSED`." ... "A new appeal is created in `SUBMITTED`
    with `round_number` at 1 and `reviewer_user_id`, `assigned_at`, `decided_at`,
    `decision_rationale`, and `remand_reason` all null."

    Design: Corner/validations/corner_appeal_filed_after_the_thirty_day_appeal_window_is_refused
    """
    ctx = escalated_wave(b)
    notice = b.notices()[0]
    assert_instant_equals(notice["issued_at"], ESCALATION_INSTANT)

    b.set_clock(APPEAL_WINDOW_END_INSTANT)
    appeal = b.appeal(ctx.case["id"], ctx.dep["id"], ctx.employee["id"])

    assert appeal["status"] == "SUBMITTED", appeal
    assert appeal["round_number"] == 1, appeal
    assert appeal["reviewer_user_id"] is None, appeal
    assert appeal["assigned_at"] is None, appeal


def test_an_appeal_filed_the_day_after_the_window_closes_is_refused_as_untimely(
    b, client
):
    """PRD §3.8: "And the appeal must be timely: the current clock instant must be
    no later than the `issued_at` of the dependent's non-rescinded
    `TerminationNotice` advanced by thirty whole days, with a late filing refused
    with `ERR_APPEAL_WINDOW_CLOSED`." ... "That thirty-day window is the same one
    that keeps a case parked in `ESCALATED` during step four of the checkpoint."

    Design: Corner/validations/corner_appeal_filed_after_the_thirty_day_appeal_window_is_refused
    """
    ctx = escalated_wave(b)

    b.set_clock(_AFTER_APPEAL_WINDOW_INSTANT)
    late = client.create_appeal(
        f.appeal_payload(ctx.case["id"], ctx.dep["id"], "ADMINISTRATIVE_ERROR"),
        employee_headers(ctx.employee["id"]),
    )

    validate_error(late, E.ERR_APPEAL_WINDOW_CLOSED)
    rows, meta = b.appeals()
    assert meta["total_count"] == 0, meta
    assert rows == [], rows
    assert_case(b.read_case(ctx.case["id"]), status="ESCALATED")
    assert_dependent(
        b.read_dependent(ctx.dep["id"]), coverage_status="TERMINATION_PENDING"
    )


def test_a_continuation_election_on_the_sixtieth_day_after_issuance_is_admitted(b):
    """PRD §3.7: "The current clock instant must be no later than
    `continuation_election_deadline` — the boundary instant is inside the window —
    and a late election is refused with
    `ERR_CONTINUATION_ELECTION_WINDOW_CLOSED`." ... "The notice's
    `continuation_start_date` is its `effective_date` advanced by one day and is
    the inclusive first day of the continuation interval."

    Design: Corner/validations/corner_continuation_election_after_the_sixty_day_deadline_is_refused
    """
    ctx = finalized_wave(b)
    assert_notice(ctx.notice, status="FINAL", effective_date="2026-10-31")
    assert_instant_equals(
        ctx.notice["continuation_election_deadline"], ELECTION_DEADLINE_INSTANT
    )

    b.set_clock(ELECTION_DEADLINE_INSTANT)
    elected = b.continuation_election(
        ctx.notice["id"], "ELECT", employee_id=ctx.employee["id"]
    )

    assert_notice(
        elected,
        continuation_election_status="ELECTED",
        continuation_start_date="2026-11-01",
        continuation_end_date="2028-05-01",
    )
    assert_instant_equals(elected["continuation_elected_at"], ELECTION_DEADLINE_INSTANT)


def test_a_continuation_election_one_day_late_leaves_the_notice_unelected(b, client):
    """PRD §3.7: "The current clock instant must be no later than
    `continuation_election_deadline` — the boundary instant is inside the window —
    and a late election is refused with
    `ERR_CONTINUATION_ELECTION_WINDOW_CLOSED`." ... "`continuation_election_deadline`
    is set to the notice's `issued_at` instant advanced by sixty whole days"

    Design: Corner/validations/corner_continuation_election_after_the_sixty_day_deadline_is_refused
    """
    ctx = finalized_wave(b)

    b.set_clock(_LATE_ELECTION_INSTANT)
    late = client.continuation_election(
        ctx.notice["id"],
        f.continuation_election_payload("ELECT"),
        employee_headers(ctx.employee["id"]),
    )

    validate_error(late, E.ERR_CONTINUATION_ELECTION_WINDOW_CLOSED)
    notice = b.read_notice(ctx.notice["id"])
    assert_notice(
        notice,
        status="FINAL",
        continuation_election_status="NOT_ELECTED",
        continuation_monthly_premium_cents=0,
        continuation_start_date=None,
        continuation_end_date=None,
    )
    assert_instant_equals(
        notice["continuation_election_deadline"], ELECTION_DEADLINE_INSTANT
    )


def _case_chased_to_its_allowance(b):
    """Announce over one household and spend all three reminders exactly on cadence."""
    ctx = announced_wave(b)
    for instant in (
        _FIRST_REMINDER_INSTANT,
        _SECOND_REMINDER_INSTANT,
        _THIRD_REMINDER_INSTANT,
    ):
        b.set_clock(instant)
        ctx.case = b.reminder(ctx.case["id"])
    return ctx


def test_a_reminder_that_breaks_both_limits_reports_the_cadence_violation(b, client):
    """PRD §2.8: "When a single request violates more than one rule, the response
    must report the violation that comes first in the following precedence order."
    ... "24. The reminder cadence gap has elapsed —
    `ERR_REMINDER_CADENCE_VIOLATION` (409), on a reminder." ... "A gap exactly
    equal to the configured minimum is therefore allowed; anything shorter is
    refused with `ERR_REMINDER_CADENCE_VIOLATION`."

    Design: Corner/validations/corner_cadence_rule_outranks_the_reminder_limit_when_both_are_violated
    """
    ctx = _case_chased_to_its_allowance(b)
    assert_case(ctx.case, reminders_sent_count=3)

    b.set_clock(_ONE_DAY_AFTER_THIRD_REMINDER)
    refused = client.send_reminder(
        ctx.case["id"], f.reminder_payload(channel="EMAIL"), ANALYST
    )

    validate_error(refused, E.ERR_REMINDER_CADENCE_VIOLATION)
    case = b.read_case(ctx.case["id"])
    assert_case(case, reminders_sent_count=3, communication_sequence_no=4)
    assert_instant_equals(case["last_reminder_at"], _THIRD_REMINDER_INSTANT)


def test_once_the_cadence_gap_has_elapsed_the_same_reminder_hits_the_volume_cap(
    b, client
):
    """PRD §3.3: "The **volume cap** requires the case's `reminders_sent_count` to
    be strictly less than the program's `max_reminders`; a case that has already
    received its full allowance is refused with `ERR_REMINDER_LIMIT_REACHED`."
    ... "The elapsed time from the anchor to the current clock instant is converted
    to whole elapsed days by discarding any partial day"

    Design: Corner/validations/corner_cadence_rule_outranks_the_reminder_limit_when_both_are_violated
    """
    ctx = _case_chased_to_its_allowance(b)

    b.set_clock(_SEVEN_DAYS_AFTER_THIRD_REMINDER)
    refused = client.send_reminder(
        ctx.case["id"], f.reminder_payload(channel="MAIL"), ANALYST
    )

    validate_error(refused, E.ERR_REMINDER_LIMIT_REACHED)
    events, meta = b.communications(ctx.case["id"])
    assert meta["total_count"] == 4, meta
    assert [row["kind"] for row in events] == [
        "ANNOUNCEMENT",
        "REMINDER",
        "REMINDER",
        "REMINDER",
    ], events
    assert_case(b.read_case(ctx.case["id"]), reminders_sent_count=3)


def _program_with_one_spouse_audit_rule(b):
    """A draft program already publishing a single SPOUSE audit rule."""
    program = b.program(program_name="PY2026 Documentation Policy Audit")
    rule = b.doc_rule(program["id"], "SPOUSE", "AUDIT")
    assert rule["grace_days"] is None, rule
    return program, rule


def _rules_of(b, program_id):
    data, meta = validate_paginated(
        b.client.list_documentation_rules(program_id, PROGRAM_ADMIN)
    )
    return data, meta


def test_a_second_rule_for_the_same_relationship_and_phase_is_refused(b, client, clock):
    """PRD §3.1: "The triple of program, relationship class, and phase must be
    unique; a second rule for the same triple is refused with
    `ERR_DOCUMENTATION_RULE_CONFLICT`, as is a rule that carries `grace_days` for
    the wrong phase — the field is required and must be between 1 and 180 whole
    days when the phase is `POINT_OF_ENROLLMENT`, and must be null when the phase
    is `AUDIT`."

    Design: Corner/validations/corner_documentation_rule_uniqueness_and_grace_days_phase_coupling
    """
    program, rule = _program_with_one_spouse_audit_rule(b)

    duplicate = client.create_documentation_rule(
        program["id"],
        f.documentation_rule_payload("SPOUSE", "AUDIT"),
        PROGRAM_ADMIN,
    )

    validate_error(duplicate, E.ERR_DOCUMENTATION_RULE_CONFLICT)
    rows, meta = _rules_of(b, program["id"])
    assert meta["total_count"] == 1, meta
    assert [row["id"] for row in rows] == [rule["id"]], rows


def test_an_audit_phase_rule_carrying_a_grace_period_is_refused(b, client, clock):
    """PRD §3.1: "The triple of program, relationship class, and phase must be
    unique; a second rule for the same triple is refused with
    `ERR_DOCUMENTATION_RULE_CONFLICT`, as is a rule that carries `grace_days` for
    the wrong phase — the field is required and must be between 1 and 180 whole
    days when the phase is `POINT_OF_ENROLLMENT`, and must be null when the phase
    is `AUDIT`."

    Design: Corner/validations/corner_documentation_rule_uniqueness_and_grace_days_phase_coupling
    """
    program, _rule = _program_with_one_spouse_audit_rule(b)

    misphased = client.create_documentation_rule(
        program["id"],
        f.documentation_rule_payload("CHILD_BIOLOGICAL", "AUDIT", grace_days=30),
        PROGRAM_ADMIN,
    )

    validate_error(misphased, E.ERR_DOCUMENTATION_RULE_CONFLICT)
    _rows, meta = _rules_of(b, program["id"])
    assert meta["total_count"] == 1, meta


def test_the_same_relationship_in_the_enrollment_phase_with_a_grace_period_is_admitted(
    b, clock
):
    """PRD §3.1: "The triple of program, relationship class, and phase must be
    unique; a second rule for the same triple is refused with
    `ERR_DOCUMENTATION_RULE_CONFLICT`, as is a rule that carries `grace_days` for
    the wrong phase — the field is required and must be between 1 and 180 whole
    days when the phase is `POINT_OF_ENROLLMENT`, and must be null when the phase
    is `AUDIT`."

    Design: Corner/validations/corner_documentation_rule_uniqueness_and_grace_days_phase_coupling
    """
    program, audit_rule = _program_with_one_spouse_audit_rule(b)

    enrollment_rule = b.doc_rule(program["id"], "SPOUSE", "POINT_OF_ENROLLMENT")

    assert enrollment_rule["grace_days"] == 30, enrollment_rule
    assert enrollment_rule["phase"] == "POINT_OF_ENROLLMENT", enrollment_rule
    assert enrollment_rule["relationship_type"] == "SPOUSE", enrollment_rule
    rows, meta = _rules_of(b, program["id"])
    assert meta["total_count"] == 2, meta
    assert {row["id"] for row in rows} == {audit_rule["id"], enrollment_rule["id"]}, rows


def _draft_program_over_one_long_standing_spouse(b):
    """One spouse enrolled on the origin date, and a draft program that covers her."""
    employee = b.employee()
    dependent = b.dependent(employee["id"], "SPOUSE")
    program = b.program(program_name="PY2026 Scope Shape Audit")
    b.doc_rule(program["id"], "SPOUSE", "AUDIT")
    version = b.read_program(program["id"])["version"]
    return employee, dependent, program, version


@pytest.mark.parametrize(
    "scope_type, extra",
    [
        ("TARGETED", {}),
        ("TARGETED", {"targeted_employee_ids": []}),
        ("FULL_CENSUS", {"new_dependent_since_date": "2026-09-01"}),
    ],
)
def test_a_scope_payload_that_mismatches_its_class_is_refused_before_selection_runs(
    b, client, clock, scope_type, extra
):
    """PRD §3.2: "`TARGETED` additionally requires a non-empty
    `targeted_employee_ids` list; `NEW_DEPENDENT_ONLY` additionally requires a
    `new_dependent_since_date`; `FULL_CENSUS` forbids both. A payload whose
    parameters do not match its declared scope class is refused with
    `ERR_SCOPE_PARAMETERS_INVALID`."

    Design: Corner/validations/corner_scope_parameter_shape_is_checked_before_the_candidate_set_is_evaluated
    """
    _employee, dependent, program, version = _draft_program_over_one_long_standing_spouse(b)

    refused = client.run_scope(
        program["id"],
        f.scope_payload(version, scope_type, **extra),
        PROGRAM_ADMIN,
    )

    validate_error(refused, E.ERR_SCOPE_PARAMETERS_INVALID)
    assert_program(
        b.read_program(program["id"]),
        status="DRAFT",
        scope_type=None,
        version=version,
        in_scope_case_count=0,
    )
    assert b.cases(program["id"]) == []
    assert_dependent(b.read_dependent(dependent["id"]), coverage_status="ENROLLED")


def test_a_well_shaped_scope_whose_cutoff_excludes_everyone_reports_an_empty_scope(
    b, client, clock
):
    """PRD §3.2: "If candidate selection produces no employee at all, the run is
    refused with `ERR_SCOPE_EMPTY`: no case is created and the program's `status` is
    left exactly as it was, whether that was `DRAFT` or `SCOPED`." ... "Under
    `NEW_DEPENDENT_ONLY`, an employee is a candidate when at least one of their
    enrolled dependents has an `enrolled_at` date on or after
    `new_dependent_since_date`."

    Design: Corner/validations/corner_scope_parameter_shape_is_checked_before_the_candidate_set_is_evaluated
    """
    _employee, dependent, program, version = _draft_program_over_one_long_standing_spouse(b)
    assert_dependent(b.read_dependent(dependent["id"]), enrolled_at="2026-08-01")

    refused = client.run_scope(
        program["id"],
        f.scope_payload(
            version, "NEW_DEPENDENT_ONLY", new_dependent_since_date="2026-09-01"
        ),
        PROGRAM_ADMIN,
    )

    validate_error(refused, E.ERR_SCOPE_EMPTY)
    assert_program(
        b.read_program(program["id"]), status="DRAFT", scope_type=None, version=version
    )
    assert b.cases(program["id"]) == []


def test_none_of_the_refused_scope_runs_consumes_the_program_version(b, client, clock):
    """PRD §3.2: "On success, every selected dependent moves `ENROLLED →
    PENDING_VERIFICATION`, each affected employee's `enrolled_dependent_count` is
    recomputed, the program's `scope_type` is recorded, `status` becomes `SCOPED`,
    and `in_scope_case_count`, `in_scope_dependent_count`, and
    `pending_dependent_count` are refreshed." ... "The program's `version`
    increments by 1."

    Design: Corner/validations/corner_scope_parameter_shape_is_checked_before_the_candidate_set_is_evaluated
    """
    _employee, dependent, program, version = _draft_program_over_one_long_standing_spouse(b)
    for scope_type, extra, expected_error in (
        ("TARGETED", {}, E.ERR_SCOPE_PARAMETERS_INVALID),
        ("TARGETED", {"targeted_employee_ids": []}, E.ERR_SCOPE_PARAMETERS_INVALID),
        (
            "FULL_CENSUS",
            {"new_dependent_since_date": "2026-09-01"},
            E.ERR_SCOPE_PARAMETERS_INVALID,
        ),
        (
            "NEW_DEPENDENT_ONLY",
            {"new_dependent_since_date": "2026-09-01"},
            E.ERR_SCOPE_EMPTY,
        ),
    ):
        refused = client.run_scope(
            program["id"], f.scope_payload(version, scope_type, **extra), PROGRAM_ADMIN
        )
        validate_error(refused, expected_error)

    scoped = b.scope(program["id"], "FULL_CENSUS", expected_program_version=version)

    assert_program(
        scoped,
        status="SCOPED",
        scope_type="FULL_CENSUS",
        version=version + 1,
        in_scope_case_count=1,
        in_scope_dependent_count=1,
        pending_dependent_count=1,
    )
    assert_dependent(
        b.read_dependent(dependent["id"]), coverage_status="PENDING_VERIFICATION"
    )


def _half_documented_family(b):
    """A spouse and a biological child, but only the spouse rule published."""
    employee = b.employee(coverage_tier="FAMILY")
    spouse = b.dependent(employee["id"], "SPOUSE")
    child = b.dependent(employee["id"], "CHILD_BIOLOGICAL")
    program = b.program(program_name="PY2026 Rule Coverage Audit")
    b.doc_rule(program["id"], "SPOUSE", "AUDIT")
    version = b.read_program(program["id"])["version"]
    return employee, spouse, child, program, version


def test_a_relationship_class_with_no_audit_rule_blocks_the_whole_scope_run(
    b, client, clock
):
    """PRD §3.2: "And if the selected dependent set contains any relationship class
    for which this program has published no `AUDIT`-phase documentation rule, the
    run is refused with `ERR_DOCUMENTATION_RULE_MISSING` — the audit will not ask an
    employee for documentation it has not defined."

    Design: Corner/validations/corner_scope_requires_an_audit_rule_for_every_selected_relationship_type
    """
    _employee, spouse, child, program, version = _half_documented_family(b)

    refused = client.run_scope(
        program["id"], f.scope_payload(version, "FULL_CENSUS"), PROGRAM_ADMIN
    )

    validate_error(refused, E.ERR_DOCUMENTATION_RULE_MISSING)
    assert b.cases(program["id"]) == []
    assert_program(b.read_program(program["id"]), status="DRAFT", version=version)
    assert_dependent(b.read_dependent(spouse["id"]), coverage_status="ENROLLED")
    assert_dependent(b.read_dependent(child["id"]), coverage_status="ENROLLED")


def test_publishing_the_missing_rule_lets_the_identical_scope_run_succeed(b, clock):
    """PRD §2.8: "32. An audit-phase documentation rule exists for every relationship
    class the operation needs — `ERR_DOCUMENTATION_RULE_MISSING` (422), on the scope
    run and on proof submission." ... "That array is the frozen, authoritative
    in-scope set for the case: it holds the identifiers of the employee's enrolled
    dependents ordered by the dependents' own `created_at` ascending."

    Design: Corner/validations/corner_scope_requires_an_audit_rule_for_every_selected_relationship_type
    """
    _employee, spouse, child, program, _version = _half_documented_family(b)

    b.doc_rule(program["id"], "CHILD_BIOLOGICAL", "AUDIT")
    scoped = b.scope(program["id"], "FULL_CENSUS")

    assert_program(
        scoped,
        status="SCOPED",
        in_scope_case_count=1,
        in_scope_dependent_count=2,
        pending_dependent_count=2,
    )
    cases = b.cases(program["id"])
    assert len(cases) == 1, cases
    assert_case(
        cases[0],
        status="SELECTED",
        in_scope_dependent_ids=[spouse["id"], child["id"]],
        in_scope_dependent_count=2,
    )


_SHARED_PROGRAM_NAME = "PY2026 Dependent Eligibility Audit"


def test_a_second_program_with_the_same_name_and_plan_year_is_refused(b, client, clock):
    """PRD §3.1: "The program itself is created in `DRAFT` with a `program_name`
    between 1 and 120 characters and a `plan_year` between 2020 and 2100; the pair
    of plan year and program name must be unique across all programs, and a
    collision is refused with `ERR_DUPLICATE_PROGRAM`."

    Design: Corner/validations/corner_program_name_is_unique_only_within_a_plan_year
    """
    first = b.program(program_name=_SHARED_PROGRAM_NAME, plan_year=2026)

    collision = client.create_program(
        f.program_payload(
            program_name=_SHARED_PROGRAM_NAME,
            plan_year=2026,
            amnesty_days=30,
            response_days=60,
            reminder_min_gap_days=10,
            max_reminders=2,
        ),
        PROGRAM_ADMIN,
    )

    validate_error(collision, E.ERR_DUPLICATE_PROGRAM)
    rows, meta = validate_paginated(
        client.list_programs(PROGRAM_ADMIN, params={"limit": 10, "offset": 0})
    )
    assert_page_meta(meta, limit=10, offset=0, total_count=1, has_more=False)
    assert [row["id"] for row in rows] == [first["id"]], rows
    assert_program(b.read_program(first["id"]), amnesty_days=21, response_days=45)


def test_the_same_program_name_in_the_next_plan_year_is_created(b, client, clock):
    """PRD §3.1: "the pair of plan year and program name must be unique across all
    programs, and a collision is refused with `ERR_DUPLICATE_PROGRAM`." ... "A
    freshly created program has `scope_type` null, `announcement_at`,
    `amnesty_end_at`, `response_deadline_at`, and `last_savings_variant` all null,
    `sweep_epoch` at zero"

    Design: Corner/validations/corner_program_name_is_unique_only_within_a_plan_year
    """
    b.program(program_name=_SHARED_PROGRAM_NAME, plan_year=2026)

    next_year = b.program(program_name=_SHARED_PROGRAM_NAME, plan_year=2027)

    assert_program(
        next_year,
        program_name=_SHARED_PROGRAM_NAME,
        plan_year=2027,
        status="DRAFT",
        version=1,
        scope_type=None,
        announcement_at=None,
        amnesty_end_at=None,
        response_deadline_at=None,
        last_savings_variant=None,
        sweep_epoch=0,
    )
    _rows, meta = validate_paginated(
        client.list_programs(PROGRAM_ADMIN, params={"limit": 10, "offset": 0})
    )
    assert_page_meta(meta, limit=10, offset=0, total_count=2, has_more=False)


_AMNESTY_SUBMISSION_INSTANT = "2026-09-05T00:00:00Z"


def test_a_document_outside_the_relationship_rule_is_refused_and_never_persisted(
    b, client
):
    """PRD §3.5: "Third, acceptability: the offered `proof_type` must be a member of
    that rule's `acceptable_proof_types`, and anything else is refused with
    `ERR_PROOF_TYPE_NOT_ACCEPTED` — a birth certificate proves nothing about a
    marriage."

    Design: Corner/validations/corner_proof_type_outside_the_relationship_rule_is_refused
    """
    ctx = announced_wave(b)
    assert_case(ctx.case, status="NOTIFIED", proof_submission_count=0)

    b.set_clock(_AMNESTY_SUBMISSION_INSTANT)
    refused = client.create_proof_submission(
        f.proof_submission_payload(ctx.case["id"], ctx.dep["id"], "BIRTH_CERTIFICATE"),
        employee_headers(ctx.employee["id"]),
    )

    validate_error(refused, E.ERR_PROOF_TYPE_NOT_ACCEPTED)
    _rows, meta = b.submissions(case_id=ctx.case["id"])
    assert meta["total_count"] == 0, meta
    assert_case(
        b.read_case(ctx.case["id"]), status="NOTIFIED", proof_submission_count=0
    )
    assert_dependent(
        b.read_dependent(ctx.dep["id"]),
        coverage_status="PENDING_VERIFICATION",
        accepted_proof_type_count=0,
        documentation_complete=False,
    )


def test_the_one_document_the_spouse_rule_names_is_admitted(b):
    """PRD §3.5: "Third, acceptability: the offered `proof_type` must be a member of
    that rule's `acceptable_proof_types`, and anything else is refused with
    `ERR_PROOF_TYPE_NOT_ACCEPTED` — a birth certificate proves nothing about a
    marriage." ... "A newly created submission starts with `review_status`
    `SUBMITTED`."

    Design: Corner/validations/corner_proof_type_outside_the_relationship_rule_is_refused
    """
    ctx = announced_wave(b)

    b.set_clock(_AMNESTY_SUBMISSION_INSTANT)
    submission = b.submit_proof(
        ctx.case["id"], ctx.dep["id"], ctx.employee["id"], "MARRIAGE_CERTIFICATE"
    )

    assert_submission(
        submission,
        proof_type="MARRIAGE_CERTIFICATE",
        review_status="SUBMITTED",
        privacy_status="NOT_REQUIRED",
        reviewed_by_user_id=None,
        decision_reason_code=None,
        decided_at=None,
        redacted_document_reference=None,
    )
    rows, meta = b.submissions(case_id=ctx.case["id"])
    assert meta["total_count"] == 1, meta
    assert [row["id"] for row in rows] == [submission["id"]], rows
    assert_case(
        b.read_case(ctx.case["id"]), status="IN_PROGRESS", proof_submission_count=1
    )


def _wave_wanting_two_spouse_documents(b):
    """An announced wave whose spouse rule wants a certificate and a tax return."""
    ctx = announced_wave(b, rule_overrides=_TWO_DOCUMENT_SPOUSE_RULE)
    b.set_clock(_AMNESTY_SUBMISSION_INSTANT)
    return ctx


def test_a_joint_tax_return_one_day_older_than_the_floor_is_refused_as_stale(b, client):
    """PRD §3.5: "For those two only, the `document_date` must fall on or after the
    calendar date of the program's `announcement_at` moved backwards by the governing
    rule's `requires_recency_days` whole days; an older document is refused with
    `ERR_PROOF_STALE_DOCUMENT`."

    Design: Corner/validations/corner_recency_floor_applies_only_to_recency_scoped_proof_types
    """
    ctx = _wave_wanting_two_spouse_documents(b)

    stale = client.create_proof_submission(
        f.proof_submission_payload(
            ctx.case["id"],
            ctx.dep["id"],
            "JOINT_TAX_RETURN",
            document_date=_ONE_DAY_STALE_DATE,
            redaction_applied=True,
        ),
        employee_headers(ctx.employee["id"]),
    )

    validate_error(stale, E.ERR_PROOF_STALE_DOCUMENT)
    _rows, meta = b.submissions(case_id=ctx.case["id"])
    assert meta["total_count"] == 0, meta
    assert_case(
        b.read_case(ctx.case["id"]), status="NOTIFIED", proof_submission_count=0
    )


def test_a_joint_tax_return_dated_exactly_on_the_floor_is_admitted_as_sensitive(b):
    """PRD §3.5: "Fourth, recency: exactly two document classes are recency-scoped,
    `JOINT_TAX_RETURN` and `JOINT_ACCOUNT_STATEMENT`, because both are evidence of an
    ongoing shared financial life rather than of a one-time event." ... "Its
    `privacy_status` starts at `REDACTED` when the proof type is sensitive and
    `redaction_applied` was true, and at `NOT_REQUIRED` in every other case."

    Design: Corner/validations/corner_recency_floor_applies_only_to_recency_scoped_proof_types
    """
    ctx = _wave_wanting_two_spouse_documents(b)

    submission = b.submit_proof(
        ctx.case["id"],
        ctx.dep["id"],
        ctx.employee["id"],
        "JOINT_TAX_RETURN",
        document_date=_RECENCY_FLOOR_DATE,
        redaction_applied=True,
    )

    assert_submission(
        submission,
        proof_type="JOINT_TAX_RETURN",
        document_date=_RECENCY_FLOOR_DATE,
        privacy_class="SENSITIVE",
        privacy_status="REDACTED",
        review_status="SUBMITTED",
    )


def test_a_fifteen_year_old_marriage_certificate_is_never_checked_for_recency(b):
    """PRD §3.5: "The remaining eight document classes are never checked for recency
    at all — a birth certificate does not go stale." ... "The dependent's
    `documentation_complete` becomes true when `accepted_proof_type_count` is greater
    than or equal to the governing rule's `min_accepted_documents` — exactly the
    minimum is sufficient."

    Design: Corner/validations/corner_recency_floor_applies_only_to_recency_scoped_proof_types
    """
    ctx = _wave_wanting_two_spouse_documents(b)
    b.submit_proof(
        ctx.case["id"],
        ctx.dep["id"],
        ctx.employee["id"],
        "JOINT_TAX_RETURN",
        document_date=_RECENCY_FLOOR_DATE,
        redaction_applied=True,
    )

    certificate = b.submit_proof(
        ctx.case["id"],
        ctx.dep["id"],
        ctx.employee["id"],
        "MARRIAGE_CERTIFICATE",
        document_date=_MARRIAGE_CERTIFICATE_DATE,
    )

    assert_submission(
        certificate,
        document_date=_MARRIAGE_CERTIFICATE_DATE,
        privacy_class="STANDARD",
        privacy_status="NOT_REQUIRED",
        review_status="SUBMITTED",
    )
    _rows, meta = b.submissions(case_id=ctx.case["id"])
    assert meta["total_count"] == 2, meta
    assert_case(b.read_case(ctx.case["id"]), proof_submission_count=2)
    assert_dependent(
        b.read_dependent(ctx.dep["id"]),
        coverage_status="PENDING_VERIFICATION",
        accepted_proof_type_count=0,
        documentation_complete=False,
    )


_MASKED_REFERENCE = "s3://redacted/doc-mc-001-masked.pdf"


def _submission_awaiting_review(b):
    """One spouse certificate lodged during amnesty, reviewable after the sweep."""
    ctx = announced_wave(b)
    b.set_clock(_AMNESTY_SUBMISSION_INSTANT)
    submission = b.submit_proof(
        ctx.case["id"],
        ctx.dep["id"],
        ctx.employee["id"],
        "MARRIAGE_CERTIFICATE",
        document_date=_MARRIAGE_CERTIFICATE_DATE,
    )
    b.set_clock(RESPONSE_WINDOW_INSTANT)
    ctx.program = b.sweep(ctx.program["id"])
    assert_program(ctx.program, status="RESPONSE_WINDOW")
    return ctx, submission


def test_a_redaction_request_parks_the_review_and_raises_the_privacy_obligation(b):
    """PRD §3.5: "A **redaction request** leaves the review dimension parked at
    `UNDER_REVIEW` — moving it `SUBMITTED → UNDER_REVIEW` — while advancing the
    privacy dimension to `REDACTION_REQUIRED`; this is the clearest illustration of
    the two dimensions moving independently, and `reviewed_by_user_id` is stamped
    here too."

    Design: Corner/validations/corner_privacy_hold_blocks_acceptance_until_the_redacted_copy_is_uploaded
    """
    _ctx, submission = _submission_awaiting_review(b)

    parked = b.request_redaction(submission["id"])

    assert_submission(
        parked,
        review_status="UNDER_REVIEW",
        privacy_status="REDACTION_REQUIRED",
        reviewed_by_user_id=ANALYST_USER_ID,
        redacted_document_reference=None,
    )
    assert_instant_equals(parked["decided_at"], RESPONSE_WINDOW_INSTANT)


def test_an_acceptance_under_an_outstanding_privacy_hold_is_refused(b, client):
    """PRD §3.5: "An **accept** moves the review dimension `SUBMITTED → ACCEPTED`, or
    `UNDER_REVIEW → ACCEPTED` for a submission that had been parked, and it is
    permitted only when the submission's `privacy_status` is `NOT_REQUIRED` or
    `REDACTED`; a submission still sitting at `REDACTION_REQUIRED`, or one already
    `PURGED`, cannot be accepted and the attempt is refused with `ERR_PRIVACY_HOLD`."

    Design: Corner/validations/corner_privacy_hold_blocks_acceptance_until_the_redacted_copy_is_uploaded
    """
    ctx, submission = _submission_awaiting_review(b)
    b.request_redaction(submission["id"])

    held = client.decide_proof_submission(
        submission["id"], f.decision_payload("ACCEPT", "VERIFIED_MATCH"), ANALYST
    )

    validate_error(held, E.ERR_PRIVACY_HOLD)
    assert_submission(
        b.read_submission(submission["id"]),
        review_status="UNDER_REVIEW",
        privacy_status="REDACTION_REQUIRED",
    )
    assert_dependent(
        b.read_dependent(ctx.dep["id"]),
        coverage_status="PENDING_VERIFICATION",
        accepted_proof_type_count=0,
        documentation_complete=False,
    )
    assert_case(b.read_case(ctx.case["id"]), status="IN_PROGRESS")


def test_uploading_the_masked_copy_cures_the_hold_and_lets_the_acceptance_through(b):
    """PRD §3.5: "Crucially, `review_status` is left exactly as it was: the upload
    cures the privacy obligation and nothing else, and the analyst must still come
    back and decide the document on its merits." ... "The moment the test flips to
    true for a dependent under audit, the dependent moves `PENDING_VERIFICATION →
    VERIFIED` with `documentation_complete` set to true."

    Design: Corner/validations/corner_privacy_hold_blocks_acceptance_until_the_redacted_copy_is_uploaded
    """
    ctx, submission = _submission_awaiting_review(b)
    b.request_redaction(submission["id"])

    cured = b.upload_redaction(
        submission["id"],
        employee_id=ctx.employee["id"],
        redacted_document_reference=_MASKED_REFERENCE,
    )
    assert_submission(
        cured,
        privacy_status="REDACTED",
        review_status="UNDER_REVIEW",
        redacted_document_reference=_MASKED_REFERENCE,
    )

    accepted = b.accept_proof(submission["id"])

    assert_submission(
        accepted,
        review_status="ACCEPTED",
        privacy_status="REDACTED",
        decision_reason_code="VERIFIED_MATCH",
    )
    assert_instant_equals(accepted["decided_at"], RESPONSE_WINDOW_INSTANT)
    assert_dependent(
        b.read_dependent(ctx.dep["id"]),
        coverage_status="VERIFIED",
        accepted_proof_type_count=1,
        documentation_complete=True,
    )
    assert_case(b.read_case(ctx.case["id"]), status="COMPLETE")


def test_neither_a_further_decision_nor_a_further_upload_touches_an_accepted_document(
    b, client
):
    """PRD §3.5: "The submission's `review_status` must be `SUBMITTED` or
    `UNDER_REVIEW`; a decision against an already-terminal submission is refused with
    `ERR_SUBMISSION_STATE_INVALID`." ... "An upload is legal only when the
    submission's `privacy_status` is exactly `REDACTION_REQUIRED` and its
    `review_status` is `SUBMITTED` or `UNDER_REVIEW`; otherwise it is refused with
    `ERR_SUBMISSION_STATE_INVALID`."

    Design: Corner/validations/corner_privacy_hold_blocks_acceptance_until_the_redacted_copy_is_uploaded
    """
    ctx, submission = _submission_awaiting_review(b)
    b.request_redaction(submission["id"])
    b.upload_redaction(
        submission["id"],
        employee_id=ctx.employee["id"],
        redacted_document_reference=_MASKED_REFERENCE,
    )
    b.accept_proof(submission["id"])

    late_decision = client.decide_proof_submission(
        submission["id"], f.decision_payload("REJECT", "INSUFFICIENT_PROOF"), ANALYST
    )
    late_upload = client.upload_redaction(
        submission["id"],
        f.redaction_payload("s3://redacted/doc-mc-001-masked-again.pdf"),
        employee_headers(ctx.employee["id"]),
    )

    validate_error(late_decision, E.ERR_SUBMISSION_STATE_INVALID)
    validate_error(late_upload, E.ERR_SUBMISSION_STATE_INVALID)
    assert_submission(
        b.read_submission(submission["id"]),
        review_status="ACCEPTED",
        privacy_status="REDACTED",
        decision_reason_code="VERIFIED_MATCH",
        redacted_document_reference=_MASKED_REFERENCE,
    )
    assert_dependent(b.read_dependent(ctx.dep["id"]), coverage_status="VERIFIED")
