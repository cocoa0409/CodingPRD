"""Clock-driven query escalation, NO_RESPONSE closure, and education cascades."""
import pytest

from test_helpers import (
    ApiErrorId,
    advance_clock,
    get_case,
    respond_to_query,
    setup_sent_query,
    validate_error,
    validate_success,
)


class TestEscalatedRespondedBranching:
    def test_escalated_query_still_accepts_response(self, api, cdi_specialist_headers):
        """PRD §3.6: "Only a query in `SENT` or `ESCALATED` status accepts a
        response (`ERR_INVALID_STATE` otherwise)"
        PRD §3.5: "the query moves from `SENT` to `ESCALATED` (or from `ESCALATED`
        to a further `ESCALATED` stage): `escalation_stage` increments by 1"

        Design: Difficulty/non_linear_state_machine/cdi_query_escalated_responded_branching_and_no_response_terminal
        """
        # due=2, stage_periods=2, max_stage=2; send at period 0 -> due_period=2
        scenario = setup_sent_query(
            response_due_periods=2, escalation_stage_periods=2, max_escalation_stage=2,
        )
        query = scenario["query"]
        assert query["due_period"] == 2
        # period 3 > due 2 + stage 0 * 2 -> stage 1 (ESCALATED)
        advance_clock(scenario["program"]["id"], 3)
        # period 5 > due 2 + stage 1 * 2 = 4 -> stage 2 (ESCALATED loop)
        advance_clock(scenario["program"]["id"], 2)
        respond_to_query(query["id"], scenario["provider"]["id"], response_type="AGREE")
        after = validate_success(api.get_cdi_query(query["id"], cdi_specialist_headers))
        assert after["status"] == "RESPONDED"
        assert after["escalation_stage"] == 2
        assert after["due_period"] == 2

    def test_query_reaching_max_stage_closes_no_response(self, api, cdi_specialist_headers):
        """PRD §3.5: "When a query has already reached the policy's
        `max_escalation_stage` and the clock advances past the final threshold —
        `due_period` plus `max_escalation_stage` multiplied by
        `escalation_stage_periods` — the query closes as `NO_RESPONSE`."

        Design: Difficulty/non_linear_state_machine/cdi_query_escalated_responded_branching_and_no_response_terminal
        """
        scenario = setup_sent_query(
            response_due_periods=2, escalation_stage_periods=2, max_escalation_stage=2,
        )
        query = scenario["query"]
        advance_clock(scenario["program"]["id"], 3)  # period 3 -> stage 1
        advance_clock(scenario["program"]["id"], 2)  # period 5 -> stage 2
        # period 7 > due 2 + max 2 * 2 = 6 -> NO_RESPONSE
        advance_clock(scenario["program"]["id"], 2)
        after = validate_success(api.get_cdi_query(query["id"], cdi_specialist_headers))
        assert after["status"] == "NO_RESPONSE"
        assert after["escalation_stage"] == 2


class TestAutoEscalationEducationCascade:
    def test_no_response_path_records_education_events(self, api, cdi_manager_headers):
        """PRD §3.5: "the query moves from `SENT` to `ESCALATED` ... a
        `ProviderEducationEvent` with `pattern_tag` `NO_RESPONSE_PATTERN` and
        `points_deducted` 3 is recorded against the addressed provider."
        PRD §3.5: "Terminal closure records a harsher education event:
        `pattern_tag` `NO_RESPONSE_PATTERN` with `points_deducted` 6 against the
        addressed provider."
        PRD §3.8: "The score is 100 minus the total points deducted across all of
        the provider's education events regardless of age, floored at zero."

        Design: Difficulty/transitive_cascade/auto_escalation_cascade_clock_to_query_to_provider
        """
        scenario = setup_sent_query(
            response_due_periods=1, escalation_stage_periods=1, max_escalation_stage=1,
        )
        query = scenario["query"]
        provider_id = scenario["provider"]["id"]
        # period 2 > due 1 + stage 0 * 1 -> ESCALATED, stage 1, -3
        advance_clock(scenario["program"]["id"], 2)
        # period 3 > due 1 + max 1 * 1 = 2 -> NO_RESPONSE, -6
        advance_clock(scenario["program"]["id"], 1)
        query_after = validate_success(api.get_cdi_query(query["id"], cdi_manager_headers))
        assert query_after["status"] == "NO_RESPONSE"
        assert query_after["escalation_stage"] == 1
        provider = validate_success(api.get_provider(provider_id, cdi_manager_headers))
        assert provider["education_score"] == 100 - 3 - 6
        assert provider["education_flag"] == "NONE"
        assert provider["pattern_tally_json"]["NO_RESPONSE_PATTERN"] == 2

    def test_intermediate_escalation_records_three_point_event(self, api, cdi_manager_headers):
        """PRD §3.5: "`escalation_stage` increments by 1, `last_escalated_period`
        records the current period, and a `ProviderEducationEvent` with
        `pattern_tag` `NO_RESPONSE_PATTERN` and `points_deducted` 3 is recorded
        against the addressed provider."

        Design: Difficulty/transitive_cascade/auto_escalation_cascade_clock_to_query_to_provider
        """
        scenario = setup_sent_query(
            response_due_periods=1, escalation_stage_periods=1, max_escalation_stage=2,
        )
        query = scenario["query"]
        provider_id = scenario["provider"]["id"]
        advance_clock(scenario["program"]["id"], 2)  # -> stage 1 only
        query_after = validate_success(api.get_cdi_query(query["id"], cdi_manager_headers))
        assert query_after["status"] == "ESCALATED"
        assert query_after["escalation_stage"] == 1
        assert query_after["last_escalated_period"] == 2
        provider = validate_success(api.get_provider(provider_id, cdi_manager_headers))
        assert provider["education_score"] == 100 - 3
        assert provider["pattern_tally_json"]["NO_RESPONSE_PATTERN"] == 1
