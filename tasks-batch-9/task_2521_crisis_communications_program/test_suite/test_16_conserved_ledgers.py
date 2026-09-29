"""Conserved ledgers: every forward action followed by its compensation leaves
the counter exactly where it started (PRD §2.7, §3.5, §3.6, §3.7, §3.8)."""

from test_helpers import (
    assert_field,
    assert_state,
    book_interview,
    confirm_interview,
    draft_statement,
    issue_correction,
    log_claim,
    read_channel,
    read_incident,
    read_interview,
    read_member,
    refresh,
    setup_activated_incident,
    setup_published_statement,
    submit_for_review,
    tasks_for_statement,
    triage_claim,
    validate_success,
)

# ---------------------------------------------------------------------------
# Incident.open_approval_task_count: submit then withdraw
# ---------------------------------------------------------------------------


def _drafted_statement_with_an_empty_task_ledger():
    """A SEV2 incident with an ACKNOWLEDGED incident-lead seat and an
    ACKNOWLEDGED privilege-cleared counsel seat — so the quorum will be 2 —
    carrying one HOLDING statement still in DRAFT."""
    scenario = setup_activated_incident(
        tier="SEV2",
        clock="2026-08-10T09:00:00Z",
        scenario_code="REGULATORY_PROBE",
        title="Investor letter leaked to press",
        seat_roles=["INCIDENT_LEAD", "LEGAL_COUNSEL"],
    )
    draft_statement(
        scenario,
        statement_type="HOLDING",
        body="We do not comment on private correspondence.",
    )
    assert_state(scenario["statement"], "DRAFT", "statement")
    assert_field(
        read_incident(scenario["incident"]["id"]), "open_approval_task_count", 0, "incident"
    )
    return scenario


def test_submitting_a_two_seat_quorum_raises_the_open_task_ledger_to_two(api):
    """PRD §3.5: "`approvals_recorded` resets to 0, `open_approval_task_count`
    rises by exactly the number of tasks created", and PRD §2.7 defines the
    quantity itself: "An incident's `open_approval_task_count` is the number of
    approval tasks in state `PENDING` whose statement belongs to that incident."

    Design: Difficulty/compensating_invariant/compensating_open_approval_task_count_submit_then_withdraw
    """
    scenario = _drafted_statement_with_an_empty_task_ledger()

    submitted = submit_for_review(scenario)

    assert_state(submitted, "IN_REVIEW", "statement")
    assert_field(submitted, "quorum_required", 2, "statement")
    assert_field(submitted, "approvals_recorded", 0, "statement")
    tasks = tasks_for_statement(scenario["statement"]["id"], state="PENDING")
    assert len(tasks) == 2, f"the SEV2 quorum must fan out two tasks, got {len(tasks)}"
    assert_field(
        read_incident(scenario["incident"]["id"]), "open_approval_task_count", 2, "incident"
    )


def test_withdrawing_from_review_returns_the_open_task_ledger_to_zero(api):
    """PRD §3.6: "Withdrawing from `IN_REVIEW` advances `IN_REVIEW → WITHDRAWN`
    and compensates the review round: every approval task of the current round
    still in `PENDING` transitions to `VOIDED`, and `open_approval_task_count` is
    recomputed back to its exact pre-submission value, preserving the
    conserved-ledger invariant."

    PRD §2.7 explains why no residue can survive the round: each conserved ledger
    "is recomputed from scratch — never incrementally patched — every time a
    transition says it changes, which guarantees that any forward action followed
    by its compensating action leaves the ledger exactly where it started."

    Design: Difficulty/compensating_invariant/compensating_open_approval_task_count_submit_then_withdraw
    """
    scenario = _drafted_statement_with_an_empty_task_ledger()
    submit_for_review(scenario)

    withdrawn = validate_success(
        api.withdraw_statement(
            scenario["statement"]["id"],
            {"withdraw_reason": "Legal asked for a different framing entirely."},
            scenario["headers"]["comms"],
        )
    )

    assert_state(withdrawn, "WITHDRAWN", "statement")
    assert_field(
        withdrawn,
        "withdraw_reason",
        "Legal asked for a different framing entirely.",
        "statement",
    )
    statement_id = scenario["statement"]["id"]
    voided = tasks_for_statement(statement_id, state="VOIDED")
    assert len(voided) == 2, f"both pending tasks must be voided, got {len(voided)}"
    for task in voided:
        assert task["decided_at"] is not None, "a voided task must stamp decided_at"
    assert tasks_for_statement(statement_id, state="PENDING") == [], (
        "no task of the collapsed round may remain pending"
    )
    assert_field(
        read_incident(scenario["incident"]["id"]), "open_approval_task_count", 0, "incident"
    )


# ---------------------------------------------------------------------------
# MonitoredChannel.reserved_correction_minutes: issue then close
# ---------------------------------------------------------------------------


def _triaged_claim_with_an_empty_airtime_ledger():
    """A SEV2 incident on a SOCIAL surface whose ``reserved_correction_minutes``
    is 0, carrying a PUBLISHED CORRECTION statement and one TRIAGED claim."""
    scenario = setup_activated_incident(
        tier="SEV2",
        clock="2026-08-10T09:00:00Z",
        scenario_code="PRODUCT_RECALL",
        channel_type="SOCIAL",
        title="Doctored screenshot of an email",
    )
    assert_field(
        read_channel(scenario["channel"]["id"]), "reserved_correction_minutes", 0,
        "channel",
    )
    setup_published_statement(
        scenario,
        statement_type="CORRECTION",
        body="The screenshot is not authentic; here is the original message.",
    )
    log_claim(
        scenario,
        virality_score=45.00,
        claim_text="An internal email admits fault.",
    )
    triage_claim(scenario)
    return scenario


def test_issuing_a_thirty_minute_correction_reserves_exactly_thirty_minutes(api):
    """PRD §3.8: "`correction_window_minutes` is derived as the whole number of
    complete minutes between the window's start and end with any remainder
    discarded, the channel's `reserved_correction_minutes` increases by exactly
    that many minutes, and the channel's `version` is incremented by 1."

    PRD §2.7 pins the ledger's definition: "A channel's
    `reserved_correction_minutes` is the sum of `correction_window_minutes` over
    that channel's claims in state `CORRECTION_ISSUED`."

    Design: Difficulty/compensating_invariant/compensating_reserved_correction_minutes_issue_then_close
    """
    scenario = _triaged_claim_with_an_empty_airtime_ledger()
    before = read_channel(scenario["channel"]["id"])

    issued = issue_correction(
        scenario, "2026-08-10T11:00:00Z", "2026-08-10T11:30:00Z"
    )

    assert_state(issued, "CORRECTION_ISSUED", "claim")
    assert_field(issued, "correction_window_minutes", 30, "claim")
    assert_field(issued, "corrected", False, "claim")
    after = read_channel(scenario["channel"]["id"])
    assert_field(after, "reserved_correction_minutes", 30, "channel")
    assert after["version"] == before["version"] + 1, (
        "issuing a correction must increment the channel version by exactly 1, "
        f"got {before['version']} then {after['version']}"
    )


def test_closing_the_corrected_claim_gives_the_whole_airtime_back(api):
    """PRD §3.8: "Closing from `CORRECTION_ISSUED` sets `resolution_branch` to
    `CORRECTION`, sets `corrected` to true ... and compensates the airtime ledger
    by decreasing the channel's `reserved_correction_minutes` by exactly this
    claim's `correction_window_minutes`, restoring it to its pre-correction value,
    again incrementing the channel's `version` by 1."

    The ledger therefore reads 0 both before the reservation and after the close,
    even though the channel's `version` has advanced twice in between.

    Design: Difficulty/compensating_invariant/compensating_reserved_correction_minutes_issue_then_close
    """
    scenario = _triaged_claim_with_an_empty_airtime_ledger()
    baseline = read_channel(scenario["channel"]["id"])
    issue_correction(scenario, "2026-08-10T11:00:00Z", "2026-08-10T11:30:00Z")

    closed = validate_success(
        api.close_misinformation_claim(
            scenario["claim"]["id"],
            {"outcome_note": "Correction published and the original post was edited."},
            scenario["headers"]["comms"],
        )
    )

    assert_state(closed, "CLOSED", "claim")
    assert_field(closed, "resolution_branch", "CORRECTION", "claim")
    assert_field(closed, "corrected", True, "claim")
    assert_field(closed, "correction_window_minutes", 30, "claim")
    channel = read_channel(scenario["channel"]["id"])
    assert_field(channel, "reserved_correction_minutes", 0, "channel")
    assert channel["version"] == baseline["version"] + 2, (
        "the two airtime writes must each advance the channel version, got "
        f"{baseline['version']} then {channel['version']}"
    )
    assert_field(refresh(scenario), "open_claim_count", 0, "incident")


# ---------------------------------------------------------------------------
# TeamMember.scheduled_interview_minutes: confirm then cancel
# ---------------------------------------------------------------------------


def _scheduled_interview_with_an_empty_load_ledger():
    """A SEV2 incident whose trained spokesperson holds one SCHEDULED interview of
    exactly sixty minutes and a ``scheduled_interview_minutes`` of 0."""
    scenario = setup_activated_incident(
        tier="SEV2",
        clock="2026-08-10T09:00:00Z",
        scenario_code="PRODUCT_RECALL",
        title="Recall coverage interview requests",
    )
    book_interview(
        scenario,
        "2026-08-12T14:00:00Z",
        "2026-08-12T15:00:00Z",
        anticipated_question_count=8,
        outlet_name="Wire Afternoon",
    )
    assert_field(scenario["interview"], "duration_minutes", 60, "interview")
    return scenario


def test_a_merely_scheduled_booking_leaves_the_load_ledger_until_confirmation(api):
    """PRD §2.7: "A member's `scheduled_interview_minutes` is the sum of
    `duration_minutes` over interviews where that member is the spokesperson and
    the interview is in state `CONFIRMED`."

    So the ledger stays 0 while the booking is only `SCHEDULED`, and PRD §3.7 then
    charges it on confirmation: "the spokesperson's `scheduled_interview_minutes`
    increases by exactly this interview's `duration_minutes`, the incident's
    `confirmed_interview_count` is recomputed".

    Design: Difficulty/compensating_invariant/compensating_scheduled_interview_minutes_confirm_then_cancel
    """
    scenario = _scheduled_interview_with_an_empty_load_ledger()
    assert_field(
        read_member(scenario["ids"]["spox"]), "scheduled_interview_minutes", 0,
        "spokesperson",
    )
    assert_field(refresh(scenario), "confirmed_interview_count", 0, "incident")

    confirmed = confirm_interview(scenario, high_risk_answers_approved_count=3)

    assert_state(confirmed, "CONFIRMED", "interview")
    assert_field(
        read_member(scenario["ids"]["spox"]), "scheduled_interview_minutes", 60,
        "spokesperson",
    )
    assert_field(refresh(scenario), "confirmed_interview_count", 1, "incident")


def test_cancelling_a_confirmed_booking_restores_the_load_ledger(api):
    """PRD §3.7: "Cancelling from `CONFIRMED` advances `CONFIRMED → CANCELLED`,
    decreases the spokesperson's `scheduled_interview_minutes` by exactly this
    interview's `duration_minutes` — restoring the spokesperson-load ledger to
    where it stood before confirmation — recomputes the incident's
    `confirmed_interview_count`, and increments the incident's `version` by 1."

    Cancellation "may be initiated either by the communications lead or by the
    spokesperson standing themselves down", so the spokesperson issues it here.

    Design: Difficulty/compensating_invariant/compensating_scheduled_interview_minutes_confirm_then_cancel
    """
    scenario = _scheduled_interview_with_an_empty_load_ledger()
    confirm_interview(scenario, high_risk_answers_approved_count=3)
    assert_field(
        read_member(scenario["ids"]["spox"]), "scheduled_interview_minutes", 60,
        "spokesperson",
    )

    cancelled = validate_success(
        api.cancel_media_interview(
            scenario["interview"]["id"],
            {"cancel_reason": "The outlet pulled the segment."},
            scenario["headers"]["spox"],
        )
    )

    assert_state(cancelled, "CANCELLED", "interview")
    assert_field(
        cancelled, "cancel_reason", "The outlet pulled the segment.", "interview"
    )
    assert_field(cancelled, "duration_minutes", 60, "interview")
    assert_field(
        read_member(scenario["ids"]["spox"]), "scheduled_interview_minutes", 0,
        "spokesperson",
    )
    assert_field(refresh(scenario), "confirmed_interview_count", 0, "incident")
    assert_state(read_interview(scenario["interview"]["id"]), "CANCELLED", "interview")
