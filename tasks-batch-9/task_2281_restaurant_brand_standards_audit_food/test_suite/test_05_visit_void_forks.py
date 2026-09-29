"""Voiding a visit: the reversal set depends entirely on the originating state."""
import pytest

from test_helpers import (
    ADMIN_HEADERS,
    FIRST_VISIT_END,
    SECOND_VISIT_END,
    SECOND_VISIT_START,
    api_client,
    finalize_visit,
    schedule_visit,
    setup_finalized_visit,
    setup_submitted_visit,
    validate_paginated,
    validate_success,
    void_payload,
)


class TestVoidForkBySourceState:
    def test_voiding_a_scheduled_visit_moves_nothing_but_the_visit(self):
        """From SCHEDULED the void records its reason and stops there.

        PRD: "Voiding from `SCHEDULED` records the `void_reason` and does nothing else,
        because nothing was ever scored."

        Design: Difficulty/non_linear_state_machine/void_fork_side_effects_diverge_by_originating_state
        """
        program = setup_finalized_visit()
        assert program["visit"]["composite_score"] == pytest.approx(90.70, abs=0.01)
        assert program["visit"]["grade"] == "PASS"
        second = schedule_visit(program, SECOND_VISIT_START, SECOND_VISIT_END)
        assert second["status"] == "SCHEDULED"

        voided = validate_success(
            api_client.void_audit_visit(
                second["id"], void_payload("SCHEDULING_ERROR"), ADMIN_HEADERS,
            )
        )
        assert voided["status"] == "VOIDED"
        assert voided["void_reason"] == "SCHEDULING_ERROR"
        assert voided["composite_score"] is None
        assert voided["grade"] is None

        location = validate_success(
            api_client.get_location(program["location"]["id"], ADMIN_HEADERS)
        )
        assert location["standing_score"] == pytest.approx(90.70, abs=0.01), \
            "the finalized visit's standing is untouched"
        assert location["latest_grade"] == "PASS"
        assert location["open_corrective_action_count"] == 3

        auditor = validate_success(
            api_client.get_auditor(program["auditor"]["id"], ADMIN_HEADERS)
        )
        assert auditor["finalized_visit_count"] == 1

    def test_voiding_a_finalized_visit_compensates_its_whole_side_effect_set(self):
        """From FINALIZED the void is the compensating branch and does the most work.

        PRD: "When permitted, the void records the `void_reason` and clears
        `composite_score`, `composite_variant`, `grade`, and `health_component_percent` to
        null; lowers the scoring auditor's `finalized_visit_count` by one; drives every
        non-terminal corrective action created by this visit to `VOIDED`, each of which
        lowers the location's `open_corrective_action_count` by one; appends exactly one
        `VOID_REVERSAL` ledger entry for each escalation entry this visit had itself
        appended, each of which lowers `escalation_level` by one and re-derives
        `franchise_agreement_status`; and finally recomputes the location's
        `standing_score`, `latest_grade`, and `repeat_violation_count`, and then the
        brand's `brand_risk_index`."

        Design: Difficulty/non_linear_state_machine/void_fork_side_effects_diverge_by_originating_state
        """
        program = setup_finalized_visit()
        visit_id = program["visit"]["id"]

        voided = validate_success(
            api_client.void_audit_visit(
                visit_id, void_payload("RUBRIC_DEFECT"), ADMIN_HEADERS,
            )
        )
        assert voided["status"] == "VOIDED"
        assert voided["void_reason"] == "RUBRIC_DEFECT"
        assert voided["composite_score"] is None
        assert voided["composite_variant"] is None
        assert voided["grade"] is None
        assert voided["health_component_percent"] is None

        location = validate_success(
            api_client.get_location(program["location"]["id"], ADMIN_HEADERS)
        )
        assert location["standing_score"] == pytest.approx(0.00, abs=0.01), \
            "with no finalized visit left the standing falls back to 0.00"
        assert location["latest_grade"] is None
        assert location["open_corrective_action_count"] == 0

        actions, meta = validate_paginated(
            api_client.list_corrective_actions(
                ADMIN_HEADERS, params={"location_id": program["location"]["id"]}
            )
        )
        assert meta["total_count"] == 3, "the actions are voided, not deleted"
        assert all(action["status"] == "VOIDED" for action in actions)

        auditor = validate_success(
            api_client.get_auditor(program["auditor"]["id"], ADMIN_HEADERS)
        )
        assert auditor["finalized_visit_count"] == 0

        risk = validate_success(
            api_client.get_brand_risk_index(program["brand"]["id"], ADMIN_HEADERS)
        )
        assert risk["rated_location_count"] == 0
        assert risk["brand_risk_index"] == pytest.approx(0.00, abs=0.01)
        assert risk["brand_risk_tier"] == "BASELINE"


class TestFinalizeVoidConservation:
    def test_finalize_then_void_restores_every_counter_it_moved(self):
        """Every consequence finalization emits has a defined compensating entry.

        PRD: "Second, **reversibility**: because a scored item can be amended on appeal and
        an entire visit can be voided after finalization, every consequence the system
        emits must have a defined compensating entry."

        Design: Difficulty/compensating_invariant/finalize_then_void_conserves_open_action_count_and_standing
        """
        program = setup_submitted_visit()
        visit_id = program["visit"]["id"]
        location_id = program["location"]["id"]
        auditor_id = program["auditor"]["id"]

        before = validate_success(api_client.get_location(location_id, ADMIN_HEADERS))
        assert before["open_corrective_action_count"] == 0
        assert before["standing_score"] == pytest.approx(0.00, abs=0.01)
        assert before["latest_grade"] is None
        auditor_before = validate_success(api_client.get_auditor(auditor_id, ADMIN_HEADERS))
        assert auditor_before["finalized_visit_count"] == 0

        finalized = finalize_visit(program, visit_id, at=FIRST_VISIT_END)
        assert finalized["composite_score"] == pytest.approx(90.70, abs=0.01)
        assert finalized["grade"] == "PASS"
        during = validate_success(api_client.get_location(location_id, ADMIN_HEADERS))
        assert during["open_corrective_action_count"] == 3
        assert during["standing_score"] == pytest.approx(90.70, abs=0.01)
        assert during["latest_grade"] == "PASS"
        auditor_during = validate_success(api_client.get_auditor(auditor_id, ADMIN_HEADERS))
        assert auditor_during["finalized_visit_count"] == 1

        voided = validate_success(
            api_client.void_audit_visit(
                visit_id, void_payload("SCHEDULING_ERROR"), ADMIN_HEADERS,
            )
        )
        assert voided["status"] == "VOIDED"
        assert voided["composite_score"] is None

        after = validate_success(api_client.get_location(location_id, ADMIN_HEADERS))
        assert after["open_corrective_action_count"] == before["open_corrective_action_count"]
        assert after["standing_score"] == pytest.approx(before["standing_score"], abs=0.01)
        assert after["latest_grade"] == before["latest_grade"]
        auditor_after = validate_success(api_client.get_auditor(auditor_id, ADMIN_HEADERS))
        assert auditor_after["finalized_visit_count"] == \
            auditor_before["finalized_visit_count"]

    def test_the_conservation_leaves_the_voided_actions_readable(self):
        """The compensation voids the actions rather than erasing the audit trail.

        PRD: "An action in `ASSIGNED` is driven `ASSIGNED → VOIDED` as a system cascade
        when its originating scored item is amended out of violation or when its
        originating visit is voided, and that void lowers the location's
        `open_corrective_action_count` by one."

        Design: Difficulty/compensating_invariant/finalize_then_void_conserves_open_action_count_and_standing
        """
        program = setup_finalized_visit()
        visit_id = program["visit"]["id"]
        assert len(program["actions"]) == 3

        validate_success(
            api_client.void_audit_visit(
                visit_id, void_payload("SCHEDULING_ERROR"), ADMIN_HEADERS,
            )
        )

        for code, action in program["actions"].items():
            reread = validate_success(
                api_client.get_corrective_action(action["id"], ADMIN_HEADERS)
            )
            assert reread["status"] == "VOIDED", f"the action for {code} must be voided"

        risk = validate_success(
            api_client.get_brand_risk_index(program["brand"]["id"], ADMIN_HEADERS)
        )
        assert risk["open_critical_action_count"] == 0, \
            "a voided action is no longer an open critical action"
        assert risk["brand_risk_index"] == pytest.approx(0.00, abs=0.01)
