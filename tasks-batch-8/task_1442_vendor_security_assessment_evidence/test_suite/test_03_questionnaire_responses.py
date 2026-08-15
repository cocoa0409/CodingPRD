"""Questionnaire responses: scoring variants, NA exclusion, revision loops,
response deadlines, and the expiry sweep (PRD §3.3, §3.4)."""
import pytest

from test_helpers import (
    ANALYST,
    ApiErrorId,
    assert_instant_equal,
    assert_score,
    contact_headers,
    create_and_submit_response,
    create_response_payload,
    get_cycle_response,
    get_success_data,
    issue_cycle,
    list_schedule_events,
    open_cycle,
    create_published_template,
    register_vendor,
    score_cycle,
    set_clock,
    setup_active_policy,
    setup_issued_cycle,
    setup_scored_cycle,
    TEST_USERS,
    validate_error,
    validate_success,
    yes_answers,
)

ADMIN = TEST_USERS["platform_admin_headers"]

# Four-item template with weights 1/2/3/4 used by the scoring-variant tests.
WEIGHTED_ITEMS = [
    {"item_key": "a", "prompt": "p", "weight": 1, "control_domain": "d"},
    {"item_key": "b", "prompt": "p", "weight": 2, "control_domain": "d"},
    {"item_key": "c", "prompt": "p", "weight": 3, "control_domain": "d"},
    {"item_key": "d", "prompt": "p", "weight": 4, "control_domain": "d"},
]
# earned = 1*1.0 + 2*0.5 + 3*0.0 + 4*1.0 = 6.0; possible = 10 -> raw 60.0
MIXED_ANSWERS = [
    {"item_key": "a", "answer_value": "YES"},
    {"item_key": "b", "answer_value": "PARTIAL"},
    {"item_key": "c", "answer_value": "NO"},
    {"item_key": "d", "answer_value": "YES"},
]


def _return_and_resubmit(api, ctx, response_id):
    api_resp = api.return_response(ctx["vendor"]["id"], ctx["cycle"]["id"], response_id, ANALYST)
    get_success_data(api_resp)
    return get_success_data(
        api.submit_response(ctx["vendor"]["id"], ctx["cycle"]["id"], response_id, contact_headers(ctx))
    )


class TestProvisionalVsFinalScoring:
    def test_revision_penalty_applied_at_final_scoring(self, api):
        """PRD §3.4: "The revision penalty is then the lesser of five percent of the
        raw score multiplied by `revision_count`, and 20 points; the cycle's
        `questionnaire_score` is the raw score minus that penalty, rounded half-up to
        two decimal places, while the response's `raw_score` records the pre-penalty
        value."

        One revision lap -> revision_count 1 -> penalty min(60*0.05*1, 20) = 3.0.

        Design: Difficulty/dual_variant_calc/questionnaire_provisional_vs_final_scoring
        """
        ctx = setup_issued_cycle(items=WEIGHTED_ITEMS)
        response = create_and_submit_response(
            ctx["vendor"]["id"], ctx["cycle"]["id"], contact_headers(ctx), MIXED_ANSWERS
        )
        _return_and_resubmit(api, ctx, response["id"])
        cycle = validate_success(api.score_cycle(ctx["vendor"]["id"], ctx["cycle"]["id"], ANALYST), 200)
        assert_score(cycle["questionnaire_score"], 57.0)
        scored_response = get_cycle_response(ctx["cycle"]["id"])
        assert_score(scored_response["raw_score"], 60.0)
        assert scored_response["revision_count"] == 2  # return + fail-branch increment

    def test_identical_answers_without_revisions_keep_raw_score(self, api):
        """PRD §3.4: "When `questionnaire_score` meets or exceeds the tier pass
        threshold — 60 for `TIER_1`, 70 for `TIER_2`, 80 for `TIER_3`, 90 for
        `TIER_4` — the response moves `SUBMITTED → ACCEPTED` and the cycle advances
        `RESPONSE_RECEIVED → SCORED`."
        PRD §3.4: "The revision penalty is then the lesser of five percent of the
        raw score multiplied by `revision_count`, and 20 points".

        Identical answers with revision_count 0: penalty 0, score stays 60.0 >= 60.

        Design: Difficulty/dual_variant_calc/questionnaire_provisional_vs_final_scoring
        """
        ctx = setup_issued_cycle(items=WEIGHTED_ITEMS)
        response = create_and_submit_response(
            ctx["vendor"]["id"], ctx["cycle"]["id"], contact_headers(ctx), MIXED_ANSWERS
        )
        cycle = validate_success(api.score_cycle(ctx["vendor"]["id"], ctx["cycle"]["id"], ANALYST), 200)
        assert cycle["status"] == "SCORED"
        assert_score(cycle["questionnaire_score"], 60.0)
        scored_response = get_cycle_response(ctx["cycle"]["id"])
        assert scored_response["status"] == "ACCEPTED"
        assert_score(scored_response["raw_score"], 60.0)


class TestNaExclusionOrdering:
    def test_na_items_excluded_from_numerator_and_denominator(self, api):
        """PRD §3.4: "Each item earns its `weight` multiplied by the answer's score:
        1.0 for `YES`, 0.5 for `PARTIAL`, and 0.0 for `NO`, while items answered `NA`
        are excluded from both the earned total and the possible total."
        PRD §3.4: "The raw score is one hundred times the earned total divided by
        the possible total, rounded half-up to two decimal places, with per-item
        products left unrounded until the final sum".

        earned = 1 + 1.5 + 4 = 6.5 over possible 1+3+4 = 8 -> 81.25; including the
        NA item's weight 2 in the denominator would give 65.0.

        Design: Difficulty/combinatorial_formula/questionnaire_score_na_exclusion_ordering_mode_b
        """
        ctx = setup_issued_cycle(items=WEIGHTED_ITEMS)
        answers = [
            {"item_key": "a", "answer_value": "YES"},
            {"item_key": "b", "answer_value": "NA", "na_justification": "no such system"},
            {"item_key": "c", "answer_value": "PARTIAL"},
            {"item_key": "d", "answer_value": "YES"},
        ]
        create_and_submit_response(ctx["vendor"]["id"], ctx["cycle"]["id"], contact_headers(ctx), answers)
        cycle = validate_success(api.score_cycle(ctx["vendor"]["id"], ctx["cycle"]["id"], ANALYST), 200)
        assert_score(cycle["questionnaire_score"], 81.25)
        scored_response = get_cycle_response(ctx["cycle"]["id"])
        assert_score(scored_response["raw_score"], 81.25)
        assert scored_response["status"] == "ACCEPTED"

    def test_all_na_answers_yield_zero_raw_and_fail_branch(self, api):
        """PRD §3.4: "if every item was answered `NA`, the possible total is zero and
        the raw score is 0.0."
        PRD §3.4: "When it falls short, the fail branch fires instead: the response
        moves to `RETURNED` with `revision_count` incremented, and the cycle remains
        `RESPONSE_RECEIVED` awaiting a revised submission — a below-threshold score
        here is a workflow outcome, not an error."

        Design: Difficulty/combinatorial_formula/questionnaire_score_na_exclusion_ordering_mode_b
        """
        ctx = setup_issued_cycle()
        answers = [{"item_key": "a", "answer_value": "NA", "na_justification": "not applicable"}]
        create_and_submit_response(ctx["vendor"]["id"], ctx["cycle"]["id"], contact_headers(ctx), answers)
        cycle = validate_success(api.score_cycle(ctx["vendor"]["id"], ctx["cycle"]["id"], ANALYST), 200)
        assert cycle["status"] == "RESPONSE_RECEIVED"
        assert_score(cycle["questionnaire_score"], 0.0)
        scored_response = get_cycle_response(ctx["cycle"]["id"])
        assert_score(scored_response["raw_score"], 0.0)
        assert scored_response["status"] == "RETURNED"
        assert scored_response["revision_count"] == 1


class TestRevisionLoop:
    def test_single_return_increments_revision_count(self, api):
        """PRD §3.4: "A `RiskAnalyst` may return a `SUBMITTED` response, moving it to
        `RETURNED` and incrementing its `revision_count` by one while the cycle stays
        `RESPONSE_RECEIVED` awaiting resubmission; the vendor then resubmits, moving
        the response `RETURNED → SUBMITTED`."

        Design: Difficulty/non_linear_state_machine/questionnaire_response_revision_loop
        """
        ctx = setup_issued_cycle()
        response = create_and_submit_response(
            ctx["vendor"]["id"], ctx["cycle"]["id"], contact_headers(ctx), yes_answers(ctx["template"])
        )
        returned = validate_success(
            api.return_response(ctx["vendor"]["id"], ctx["cycle"]["id"], response["id"], ANALYST), 200
        )
        assert returned["status"] == "RETURNED"
        assert returned["revision_count"] == 1
        cycle = get_success_data(api.get_cycle(ctx["cycle"]["id"], ANALYST))
        assert cycle["status"] == "RESPONSE_RECEIVED"

    def test_two_laps_leave_cycle_awaiting_resubmission(self, api):
        """PRD §3.4: "A `RiskAnalyst` may return a `SUBMITTED` response, moving it to
        `RETURNED` and incrementing its `revision_count` by one while the cycle stays
        `RESPONSE_RECEIVED` awaiting resubmission; the vendor then resubmits, moving
        the response `RETURNED → SUBMITTED`."

        Design: Difficulty/non_linear_state_machine/questionnaire_response_revision_loop
        """
        ctx = setup_issued_cycle()
        response = create_and_submit_response(
            ctx["vendor"]["id"], ctx["cycle"]["id"], contact_headers(ctx), yes_answers(ctx["template"])
        )
        _return_and_resubmit(api, ctx, response["id"])
        returned = validate_success(
            api.return_response(ctx["vendor"]["id"], ctx["cycle"]["id"], response["id"], ANALYST), 200
        )
        assert returned["status"] == "RETURNED"
        assert returned["revision_count"] == 2
        cycle = get_success_data(api.get_cycle(ctx["cycle"]["id"], ANALYST))
        assert cycle["status"] == "RESPONSE_RECEIVED"


class TestRevisionPenaltyCap:
    def test_revision_penalty_capped_at_twenty(self, api):
        """PRD §3.4: "The revision penalty is then the lesser of five percent of the
        raw score multiplied by `revision_count`, and 20 points; the cycle's
        `questionnaire_score` is the raw score minus that penalty, rounded half-up to
        two decimal places, while the response's `raw_score` records the pre-penalty
        value."

        Ten laps on a raw score of 100: min(100*0.05*10, 20) = 20, not 50 -> 80.0.

        Design: Corner/calculations/questionnaire_revision_penalty_capped
        """
        ctx = setup_issued_cycle()
        response = create_and_submit_response(
            ctx["vendor"]["id"], ctx["cycle"]["id"], contact_headers(ctx), yes_answers(ctx["template"])
        )
        for _ in range(10):
            _return_and_resubmit(api, ctx, response["id"])
        cycle = validate_success(api.score_cycle(ctx["vendor"]["id"], ctx["cycle"]["id"], ANALYST), 200)
        assert_score(cycle["questionnaire_score"], 80.0)
        scored_response = get_cycle_response(ctx["cycle"]["id"])
        assert scored_response["revision_count"] == 10
        assert scored_response["status"] == "ACCEPTED"
        assert cycle["status"] == "SCORED"


class TestResponseCompleteness:
    def test_submit_missing_answer_rejected(self, api):
        """PRD §3.4: "Submitting requires every item in the pinned template to be
        answered or carried by an `na_justification` — a gap is rejected with
        `ERR_RESPONSE_INCOMPLETE` (HTTP 422)".

        Design: Corner/validations/response_submit_incomplete_answers_rejected
        """
        items = [
            {"item_key": "a", "prompt": "p", "weight": 1, "control_domain": "d"},
            {"item_key": "b", "prompt": "p", "weight": 2, "control_domain": "d"},
        ]
        ctx = setup_issued_cycle(items=items)
        response = get_success_data(
            api.create_response(
                ctx["vendor"]["id"], ctx["cycle"]["id"],
                create_response_payload(answers=[{"item_key": "a", "answer_value": "YES"}]),
                contact_headers(ctx),
            )
        )
        res = api.submit_response(ctx["vendor"]["id"], ctx["cycle"]["id"], response["id"], contact_headers(ctx))
        validate_error(res, ApiErrorId.ERR_RESPONSE_INCOMPLETE)


class TestResponseDeadline:
    def test_response_due_at_is_issued_plus_tier_window(self, api):
        """PRD §3.3: "The cycle's `issued_at` is set to the current clock, and
        `response_due_at` is computed as `issued_at` plus the tier's response
        window — 45 days for `TIER_1`, 30 days for `TIER_2`, 21 days for `TIER_3`,
        and 14 days for `TIER_4`."

        TIER_1 issued at the 2026-08-01 default clock -> due 2026-09-15.

        Design: Difficulty/boundary_precision_check/response_due_at_exact_boundary
        """
        ctx = setup_issued_cycle()
        assert_instant_equal(ctx["cycle"]["issued_at"], "2026-08-01T00:00:00Z")
        assert_instant_equal(ctx["cycle"]["response_due_at"], "2026-09-15T00:00:00Z")

    def test_submission_at_exact_deadline_succeeds(self, api):
        """PRD §3.4: "it must reach the server on or before `response_due_at`: an
        overdue submission against a still-`ISSUED` cycle is rejected with
        `ERR_DEADLINE_PASSED` (HTTP 422), while a cycle the expiry sweep has already
        moved to `EXPIRED` rejects the submission at the earlier state check with
        `ERR_INVALID_STATE` (HTTP 409)."

        "on or before" makes the boundary instant inclusive.

        Design: Difficulty/boundary_precision_check/response_due_at_exact_boundary
        """
        ctx = setup_issued_cycle()
        response = get_success_data(
            api.create_response(
                ctx["vendor"]["id"], ctx["cycle"]["id"],
                create_response_payload(answers=yes_answers(ctx["template"])),
                contact_headers(ctx),
            )
        )
        set_clock("2026-09-15T00:00:00Z")  # exactly response_due_at
        submitted = validate_success(
            api.submit_response(ctx["vendor"]["id"], ctx["cycle"]["id"], response["id"], contact_headers(ctx)),
            200,
        )
        assert submitted["status"] == "SUBMITTED"
        cycle = get_success_data(api.get_cycle(ctx["cycle"]["id"], ANALYST))
        assert cycle["status"] == "RESPONSE_RECEIVED"


class TestOverdueSubmissionAndSweep:
    def test_submit_after_sweep_expired_cycle_rejected_invalid_state(self, api):
        """PRD §2.6: "Advancing the clock fires any auto-transitions that have become
        due — specifically the cycle expiry sweep and the risk-acceptance expiry
        sweep described in §3.3 and §3.6 — so clients can deterministically drive
        time-dependent behavior."
        PRD §3.4: "it must reach the server on or before `response_due_at`: an
        overdue submission against a still-`ISSUED` cycle is rejected with
        `ERR_DEADLINE_PASSED` (HTTP 422), while a cycle the expiry sweep has already
        moved to `EXPIRED` rejects the submission at the earlier state check with
        `ERR_INVALID_STATE` (HTTP 409)."

        TIER_4 due 2026-08-15; the clock advance to 2026-08-15T00:00:01Z fires the
        sweep first, so the submission meets an EXPIRED cycle.

        Design: Corner/validations/response_submit_after_deadline_returns_deadline_passed
        """
        ctx = setup_issued_cycle(tier="TIER_4")
        response = get_success_data(
            api.create_response(
                ctx["vendor"]["id"], ctx["cycle"]["id"],
                create_response_payload(answers=yes_answers(ctx["template"])),
                contact_headers(ctx),
            )
        )
        assert_instant_equal(ctx["cycle"]["response_due_at"], "2026-08-15T00:00:00Z")
        set_clock("2026-08-15T00:00:01Z")
        res = api.submit_response(ctx["vendor"]["id"], ctx["cycle"]["id"], response["id"], contact_headers(ctx))
        validate_error(res, ApiErrorId.ERR_INVALID_STATE)
        cycle = get_success_data(api.get_cycle(ctx["cycle"]["id"], ANALYST))
        assert cycle["status"] == "EXPIRED"

    def test_clock_sweep_past_due_expires_cycle_and_suspends_vendor(self, api):
        """PRD §3.3: "If the logical clock passes `response_due_at` without any
        `SUBMITTED` response on the cycle, the expiry sweep moves the cycle
        `ISSUED → EXPIRED`. The vendor's posture falls to `SUSPENDED`, its
        `active_cycle_id` clears to null, and its reassessment horizon is recomputed:
        `next_reassessment_due` moves to the current clock plus the active policy's
        `tier4_reassessment_months` months, and a `ReassessmentSchedule` event of
        kind `ALERT_ESCALATION` records the `previous_due` and `new_due` values."

        Design: Corner/state_machines/cycle_auto_expiry_on_clock_sweep
        """
        ctx = setup_issued_cycle(tier="TIER_4")  # issued 2026-08-01, due 2026-08-15
        set_clock("2026-08-16T00:00:00Z")
        cycle = get_success_data(api.get_cycle(ctx["cycle"]["id"], ANALYST))
        assert cycle["status"] == "EXPIRED"
        vendor = get_success_data(api.get_vendor(ctx["vendor"]["id"], ANALYST))
        assert vendor["posture"] == "SUSPENDED"
        assert vendor["active_cycle_id"] is None
        assert_instant_equal(vendor["next_reassessment_due"], "2027-02-16T00:00:00Z")
        events = list_schedule_events(ctx["vendor"]["id"], kind="ALERT_ESCALATION")
        assert len(events) >= 1, "Sweep must journal an ALERT_ESCALATION schedule event"
