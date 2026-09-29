"""Intake triage scoring and the bounded reframing loop on a research request."""

import pytest

from test_helpers import (
    RESEARCH_LEAD_HEADERS,
    STAKEHOLDER_HEADERS,
    create_decision,
    create_request,
    read_request,
    resubmit_research_request_payload,
    triage_payload,
    validate_error,
    validate_success,
)

# The reframing loop of the design under test: a REVERSIBLE decision 3000 users
# wide whose deadline sits far enough out that the urgency multiplier is 1.00,
# so every score in these tests is the unmultiplied base.
LOOP_DECISION = {
    "reversibility": "REVERSIBLE",
    "decision_deadline": "2026-11-01T00:00:00Z",
    "impacted_user_count": 3000,
}


def _submit_loop_request(api):
    """A SUBMITTED DISCOVERY request with a PARTIAL evidence gap."""
    decision = create_decision(api, **LOOP_DECISION)
    return create_request(
        decision["id"],
        api,
        question="Do people want digests?",
        question_type="DISCOVERY",
        evidence_gap="PARTIAL",
    )


def _triage(api, request_id, outcome, reason=None):
    return validate_success(
        api.triage_research_request(
            request_id, triage_payload(outcome, reason), RESEARCH_LEAD_HEADERS
        )
    )


def _resubmit(api, request_id, question, evidence_gap="FULL"):
    return validate_success(
        api.resubmit_research_request(
            request_id,
            resubmit_research_request_payload(
                question=question,
                question_type="DISCOVERY",
                evidence_gap=evidence_gap,
            ),
            STAKEHOLDER_HEADERS,
        )
    )


def _loop_until_revision_limit(api):
    """Walk SUBMITTED -> NEEDS_REFRAMING -> SUBMITTED twice, then land back in
    NEEDS_REFRAMING with both permitted reframing rounds spent."""
    request = _submit_loop_request(api)
    request_id = request["id"]
    _triage(
        api,
        request_id,
        "NEEDS_REFRAMING",
        "Question is a preference poll, not a research question",
    )
    _resubmit(
        api,
        request_id,
        "How do people currently triage their notification backlog?",
    )
    _triage(api, request_id, "NEEDS_REFRAMING", "Scope still spans two decisions")
    _resubmit(
        api,
        request_id,
        "How do power users triage the notification backlog after a week away?",
    )
    _triage(api, request_id, "NEEDS_REFRAMING", "Still needs a single decision owner")
    return request_id


def test_the_loop_counter_rises_once_per_reframing_round(api):
    """Each trip back through the requester's resubmit raises revision_round by one.

    PRD 3.1: "The operator whose `X-User-ID` matches the request's
    `requester_user_id` resubmits with a fresh `question`, `question_type` and
    `evidence_gap`, carrying the request `NEEDS_REFRAMING → SUBMITTED`."

    PRD 3.1: "All three submitted values overwrite the stored ones verbatim,
    `revision_round` is incremented by 1, and `priority_score`,
    `recommended_method` and `approved_method` are all cleared back to null so
    that nothing stale survives the loop."

    Design: Difficulty/non_linear_state_machine/research_request_reframing_cycle_with_bounded_rounds
    """
    request = _submit_loop_request(api)
    request_id = request["id"]
    assert request["revision_round"] == 0, (
        f"Expected a freshly submitted request to carry revision_round 0, got "
        f"{request['revision_round']}"
    )

    _triage(
        api,
        request_id,
        "NEEDS_REFRAMING",
        "Question is a preference poll, not a research question",
    )
    first = _resubmit(
        api,
        request_id,
        "How do people currently triage their notification backlog?",
    )
    assert first["status"] == "SUBMITTED", (
        f"Expected the first resubmit to carry the request back to SUBMITTED, got "
        f"{first['status']}"
    )
    assert first["revision_round"] == 1, (
        f"Expected revision_round 1 after the first reframing round, got "
        f"{first['revision_round']}"
    )
    assert first["question"] == (
        "How do people currently triage their notification backlog?"
    ), f"Expected the resubmitted question to overwrite the stored one verbatim, got {first['question']!r}"

    _triage(api, request_id, "NEEDS_REFRAMING", "Scope still spans two decisions")
    second = _resubmit(
        api,
        request_id,
        "How do power users triage the notification backlog after a week away?",
    )
    assert second["status"] == "SUBMITTED", (
        f"Expected the second resubmit to carry the request back to SUBMITTED, got "
        f"{second['status']}"
    )
    assert second["revision_round"] == 2, (
        f"Expected revision_round 2 after the second reframing round, got "
        f"{second['revision_round']}"
    )


def test_a_third_resubmit_is_refused_once_both_reframing_rounds_are_spent(api):
    """The loop is bounded at two rounds and the third resubmit is refused.

    PRD 3.1: "At most two reframing rounds are permitted: a resubmit attempted
    while `revision_round` already stands at 2 is refused with
    `ERR_REVISION_LIMIT_REACHED`, and from that point the only way the request
    can leave `NEEDS_REFRAMING` is a triage `REJECTED`, whose `reason` lands in
    `triage_reason` as the record of why the loop was closed off."

    Design: Difficulty/non_linear_state_machine/research_request_reframing_cycle_with_bounded_rounds
    """
    request_id = _loop_until_revision_limit(api)
    before = read_request(request_id, api)
    assert before["status"] == "NEEDS_REFRAMING", (
        f"Expected the third triage to leave the request in NEEDS_REFRAMING, got "
        f"{before['status']}"
    )
    assert before["revision_round"] == 2, (
        f"Expected the third triage to leave revision_round at 2, got "
        f"{before['revision_round']}"
    )

    validate_error(
        api.resubmit_research_request(
            request_id,
            resubmit_research_request_payload(
                question="Third attempt at the same framing",
                question_type="DISCOVERY",
                evidence_gap="FULL",
            ),
            STAKEHOLDER_HEADERS,
        ),
        "ERR_REVISION_LIMIT_REACHED",
    )

    after = read_request(request_id, api)
    assert after["revision_round"] == 2, (
        f"Expected the refused resubmit to leave revision_round at 2, got "
        f"{after['revision_round']}"
    )
    assert after["status"] == "NEEDS_REFRAMING", (
        f"Expected the refused resubmit to leave the request in NEEDS_REFRAMING, got "
        f"{after['status']}"
    )
    assert after["question"] != "Third attempt at the same framing", (
        "Expected the refused resubmit to leave the stored question untouched, but "
        "the third framing was written anyway"
    )


def test_a_resubmit_clears_the_stored_score_and_the_next_triage_recomputes_it(api):
    """The score is stamped on every triage, wiped by the resubmit, and recomputed
    from the freshly submitted evidence gap.

    PRD 3.1: "Whichever outcome is chosen, the request's `priority_score` and
    `recommended_method` are recomputed against the current logical clock and
    stored, `triaged_at` is set to the clock instant, and `triage_reason` is set
    to the supplied `reason` (or to null when none was supplied)."

    PRD 3.1: "All three submitted values overwrite the stored ones verbatim,
    `revision_round` is incremented by 1, and `priority_score`,
    `recommended_method` and `approved_method` are all cleared back to null so
    that nothing stale survives the loop."

    PRD 3.1: "An `evidence_gap` of `NONE` contributes 0.0, `PARTIAL` contributes
    12.0, and `FULL` contributes 25.0."

    Design: Difficulty/non_linear_state_machine/research_request_reframing_cycle_with_bounded_rounds
    """
    request = _submit_loop_request(api)
    request_id = request["id"]
    assert request["priority_score"] is None, (
        f"Expected intake to leave priority_score null, got {request['priority_score']!r}"
    )

    first_triage = _triage(
        api,
        request_id,
        "NEEDS_REFRAMING",
        "Question is a preference poll, not a research question",
    )
    assert first_triage["priority_score"] == pytest.approx(39.00, abs=0.01), (
        f"Expected a NEEDS_REFRAMING triage to still score the request 39.00, got "
        f"{first_triage['priority_score']}"
    )
    assert first_triage["recommended_method"] == "INTERVIEW", (
        f"Expected recommended_method INTERVIEW on a DISCOVERY question, got "
        f"{first_triage['recommended_method']!r}"
    )
    assert first_triage["approved_method"] is None, (
        f"Expected a NEEDS_REFRAMING triage to leave approved_method null, got "
        f"{first_triage['approved_method']!r}"
    )

    reframed = _resubmit(
        api,
        request_id,
        "How do people currently triage their notification backlog?",
        evidence_gap="FULL",
    )
    assert reframed["priority_score"] is None, (
        f"Expected the resubmit to clear priority_score back to null, got "
        f"{reframed['priority_score']!r}"
    )
    assert reframed["recommended_method"] is None, (
        f"Expected the resubmit to clear recommended_method back to null, got "
        f"{reframed['recommended_method']!r}"
    )
    assert reframed["approved_method"] is None, (
        f"Expected the resubmit to leave approved_method null, got "
        f"{reframed['approved_method']!r}"
    )
    assert reframed["evidence_gap"] == "FULL", (
        f"Expected the resubmitted evidence_gap FULL to overwrite PARTIAL, got "
        f"{reframed['evidence_gap']!r}"
    )

    second_triage = _triage(
        api, request_id, "NEEDS_REFRAMING", "Scope still spans two decisions"
    )
    assert second_triage["priority_score"] == pytest.approx(52.00, abs=0.01), (
        f"Expected the second triage to rescore the request 52.00 now that the "
        f"resubmitted evidence_gap FULL replaced PARTIAL, got "
        f"{second_triage['priority_score']}"
    )


def test_a_needs_reframing_request_cannot_be_triaged_to_approved(api):
    """Once the loop is closed off the only outcome the state machine offers is
    REJECTED, so asking for APPROVED is refused.

    PRD 3.1: "A `NEEDS_REFRAMING` request has exactly one triage outcome
    available to it — `REJECTED`; asking for `APPROVED` on a request that is
    sitting in `NEEDS_REFRAMING` is not a transition this state machine has, and
    it is refused with `ERR_INVALID_STATE`."

    Design: Difficulty/non_linear_state_machine/research_request_reframing_cycle_with_bounded_rounds
    """
    request_id = _loop_until_revision_limit(api)

    validate_error(
        api.triage_research_request(
            request_id, triage_payload("APPROVED"), RESEARCH_LEAD_HEADERS
        ),
        "ERR_INVALID_STATE",
    )

    after = read_request(request_id, api)
    assert after["status"] == "NEEDS_REFRAMING", (
        f"Expected the refused triage to leave the request in NEEDS_REFRAMING, got "
        f"{after['status']}"
    )
    assert after["approved_method"] is None, (
        f"Expected the refused triage to leave approved_method null, got "
        f"{after['approved_method']!r}"
    )


def test_the_closing_triage_rejects_the_request_and_records_the_reason(api):
    """The one exit from the exhausted loop is a triage REJECTED whose reason is
    kept as the record of why the loop was closed off.

    PRD 3.1: "At most two reframing rounds are permitted: a resubmit attempted
    while `revision_round` already stands at 2 is refused with
    `ERR_REVISION_LIMIT_REACHED`, and from that point the only way the request
    can leave `NEEDS_REFRAMING` is a triage `REJECTED`, whose `reason` lands in
    `triage_reason` as the record of why the loop was closed off."

    Design: Difficulty/non_linear_state_machine/research_request_reframing_cycle_with_bounded_rounds
    """
    request_id = _loop_until_revision_limit(api)
    validate_error(
        api.resubmit_research_request(
            request_id,
            resubmit_research_request_payload(
                question="Third attempt at the same framing",
                question_type="DISCOVERY",
                evidence_gap="FULL",
            ),
            STAKEHOLDER_HEADERS,
        ),
        "ERR_REVISION_LIMIT_REACHED",
    )

    closed = _triage(
        api, request_id, "REJECTED", "Closing after three reframings"
    )
    assert closed["status"] == "REJECTED", (
        f"Expected the closing triage to move NEEDS_REFRAMING to REJECTED, got "
        f"{closed['status']}"
    )
    assert closed["triage_reason"] == "Closing after three reframings", (
        f"Expected the closing reason to land in triage_reason, got "
        f"{closed['triage_reason']!r}"
    )
    assert closed["approved_method"] is None, (
        f"Expected a REJECTED triage to leave approved_method null, got "
        f"{closed['approved_method']!r}"
    )
    assert closed["revision_round"] == 2, (
        f"Expected the closing triage to leave revision_round at 2, got "
        f"{closed['revision_round']}"
    )


# The urgency boundary of the design under test: two IRREVERSIBLE decisions
# 12,000 users wide, one deadline exactly fourteen days past the clock's startup
# instant and one fifteen days past it. Both requests share the same 75.00 base
# (40.0 decision points, 25.0 gap points, 10.0 reach points), so the only thing
# that can separate their scores is the urgency tier.
BOUNDARY_DECISION = {
    "reversibility": "IRREVERSIBLE",
    "impacted_user_count": 12000,
}
DEADLINE_AT_FOURTEEN_DAYS = "2026-08-15T00:00:00Z"
DEADLINE_AT_FIFTEEN_DAYS = "2026-08-16T00:00:00Z"


def _triage_request_against_deadline(api, deadline, question):
    decision = create_decision(api, decision_deadline=deadline, **BOUNDARY_DECISION)
    request = create_request(
        decision["id"],
        api,
        question=question,
        question_type="DISCOVERY",
        evidence_gap="FULL",
    )
    return validate_success(
        api.triage_research_request(
            request["id"], triage_payload("APPROVED"), RESEARCH_LEAD_HEADERS
        )
    )


def test_a_deadline_exactly_fourteen_days_out_takes_the_nearest_urgency_tier(api):
    """A deadline exactly fourteen days past the clock is inside the nearest tier,
    so the base is multiplied by 1.30.

    PRD 2.5: "Its startup value is exactly `2026-08-01T00:00:00Z`, and it never
    falls back to the host's wall-clock time."

    PRD 3.1: "Take the difference between the decision's `decision_deadline` and
    the current logical clock, express it in whole days by flooring the number of
    86,400-second periods, and read the tier: 14 days or fewer gives a multiplier
    of 1.30; more than 14 but 45 days or fewer gives 1.15; more than 45 days
    gives 1.00."

    PRD 3.1: "Multiply the base by the multiplier, hold the product at a ceiling
    of 100.0, and round the capped value half-up to two decimal places."

    Design: Difficulty/boundary_precision_check/triage_urgency_multiplier_at_exactly_fourteen_days
    """
    triaged = _triage_request_against_deadline(
        api, DEADLINE_AT_FOURTEEN_DAYS, "What blocks activation this month?"
    )
    assert triaged["priority_score"] == pytest.approx(97.50, abs=0.01), (
        f"Expected 97.50 for a 75.00 base times the 1.30 tier at exactly 14 days "
        f"to the deadline, got {triaged['priority_score']}"
    )

    read_back = read_request(triaged["id"], api)
    assert read_back["priority_score"] == pytest.approx(97.50, abs=0.01), (
        f"Expected the stored priority_score to read back as 97.50, got "
        f"{read_back['priority_score']}"
    )


def test_a_deadline_fifteen_days_out_falls_into_the_next_urgency_tier(api):
    """One day further out crosses the boundary, so the same base is multiplied by
    1.15 instead.

    PRD 2.5: "Its startup value is exactly `2026-08-01T00:00:00Z`, and it never
    falls back to the host's wall-clock time."

    PRD 3.1: "Take the difference between the decision's `decision_deadline` and
    the current logical clock, express it in whole days by flooring the number of
    86,400-second periods, and read the tier: 14 days or fewer gives a multiplier
    of 1.30; more than 14 but 45 days or fewer gives 1.15; more than 45 days
    gives 1.00."

    PRD 3.1: "Multiply the base by the multiplier, hold the product at a ceiling
    of 100.0, and round the capped value half-up to two decimal places."

    Design: Difficulty/boundary_precision_check/triage_urgency_multiplier_at_exactly_fourteen_days
    """
    triaged = _triage_request_against_deadline(
        api, DEADLINE_AT_FIFTEEN_DAYS, "What blocks activation next month?"
    )
    assert triaged["priority_score"] == pytest.approx(86.25, abs=0.01), (
        f"Expected 86.25 for a 75.00 base times the 1.15 tier at 15 days to the "
        f"deadline, got {triaged['priority_score']}"
    )

    read_back = read_request(triaged["id"], api)
    assert read_back["priority_score"] == pytest.approx(86.25, abs=0.01), (
        f"Expected the stored priority_score to read back as 86.25, got "
        f"{read_back['priority_score']}"
    )


def test_the_fourteen_day_request_outscores_the_fifteen_day_request(api):
    """The tier test is inclusive at fourteen days, so two requests with identical
    bases separate on that single day.

    PRD 3.1: "Take the difference between the decision's `decision_deadline` and
    the current logical clock, express it in whole days by flooring the number of
    86,400-second periods, and read the tier: 14 days or fewer gives a multiplier
    of 1.30; more than 14 but 45 days or fewer gives 1.15; more than 45 days
    gives 1.00."

    PRD 3.1: "An `IRREVERSIBLE` decision contributes 40.0 points; a `REVERSIBLE`
    one contributes 22.0."

    Design: Difficulty/boundary_precision_check/triage_urgency_multiplier_at_exactly_fourteen_days
    """
    near = _triage_request_against_deadline(
        api, DEADLINE_AT_FOURTEEN_DAYS, "What blocks activation this month?"
    )
    further = _triage_request_against_deadline(
        api, DEADLINE_AT_FIFTEEN_DAYS, "What blocks activation next month?"
    )

    assert near["priority_score"] == pytest.approx(97.50, abs=0.01), (
        f"Expected 97.50 at exactly 14 days to the deadline, got "
        f"{near['priority_score']}"
    )
    assert further["priority_score"] == pytest.approx(86.25, abs=0.01), (
        f"Expected 86.25 at 15 days to the deadline, got {further['priority_score']}"
    )
    assert near["priority_score"] > further["priority_score"], (
        f"Expected the 14-day request to score strictly higher than the 15-day "
        f"request, got {near['priority_score']} against {further['priority_score']}"
    )


def test_the_triage_stamps_the_recommended_method_on_both_urgency_tiers(api):
    """Whatever the urgency tier, a DISCOVERY question recommends INTERVIEW and an
    approving triage with no override stamps that method as the approved one.

    PRD 3.1: "The method recommendation runs in the same triage call and is a
    small decision table over `question_type`: a `DISCOVERY` question recommends
    `INTERVIEW`, an `EVALUATIVE` question recommends `USABILITY_TEST`, a
    `BEHAVIORAL_LONGITUDINAL` question recommends `DIARY_STUDY`, and a
    `MEASUREMENT` question recommends `SURVEY`."

    PRD 3.1: "On the `SUBMITTED → APPROVED` transition, and only there,
    `approved_method` is stamped: it takes the value of `method_override` when
    triage supplied one, and otherwise the freshly computed `recommended_method`."

    Design: Difficulty/boundary_precision_check/triage_urgency_multiplier_at_exactly_fourteen_days
    """
    for deadline, question in (
        (DEADLINE_AT_FOURTEEN_DAYS, "What blocks activation this month?"),
        (DEADLINE_AT_FIFTEEN_DAYS, "What blocks activation next month?"),
    ):
        triaged = _triage_request_against_deadline(api, deadline, question)
        assert triaged["recommended_method"] == "INTERVIEW", (
            f"Expected recommended_method INTERVIEW for a DISCOVERY question with "
            f"deadline {deadline}, got {triaged['recommended_method']!r}"
        )
        assert triaged["approved_method"] == "INTERVIEW", (
            f"Expected approved_method to take the freshly computed INTERVIEW for "
            f"deadline {deadline}, got {triaged['approved_method']!r}"
        )
