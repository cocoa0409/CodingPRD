"""Leak repair prioritization: multi-input score, pressure-project bonus,
rework-cycle penalty, and verify-repair segregation of duties (PRD §3.4)."""
import pytest

from test_helpers import (
    ApiErrorId,
    PINNED_LEAK,
    TEST_DEFAULTS,
    api_client,
    assert_leak,
    create_dma,
    create_in_field_survey,
    create_in_field_survey_with_active_project,
    create_repaired_leak,
    get_dma,
    make_field_supervisor_headers,
    report_leak,
    validate_error,
    validate_success,
)

FS = TEST_DEFAULTS["FIELD_SUPERVISOR"]
FS2 = TEST_DEFAULTS["FIELD_SUPERVISOR_ALT"]


class TestPriorityScoreInputs:
    def _setup_pair(self):
        """DMA-A without any pressure project; DMA-B with an IN_FIELD survey
        plus an ACTIVE project (survey started first: starting field work
        requires posture OPEN, which the ACTIVE project would revoke)."""
        dma_a = create_dma(code="DMA-CF1A", connection_count=1000,
                           mains_length_km=30.0, target_nrw_pct=15.0)
        dma_b = create_dma(code="DMA-CF1B", connection_count=1000,
                           mains_length_km=30.0, target_nrw_pct=15.0)
        survey_a = create_in_field_survey(dma_a["id"])
        _, survey_b = create_in_field_survey_with_active_project(
            dma_b["id"], project_overrides={"name": "PRV B"}
        )
        return dma_a, dma_b, survey_a, survey_b

    def test_score_without_pressure_project(self, api):
        """PRD §3.4: "`annualized_loss_m3` is the estimated loss rate multiplied
        by 86400 seconds per day and 365 days per year, divided by 1000 to
        convert litres to cubic metres" and "The annual value of the loss is the
        `annualized_loss_m3` multiplied by the program water value of 1.20
        currency units per cubic metre. The cost ratio is that annual value
        divided by the larger of the `repair_cost_estimate` and a cost floor of
        1.0. The base score is the cost ratio scaled by 2.0, capped at 100." and
        "The `priority_band` then buckets the score: `P1` when the score is 50.0
        or more, `P2` when it is 20.0 or more but below 50.0, and `P3` below
        20.0; band boundaries are inclusive."

        Design: Difficulty/combinatorial_formula/leak_priority_multi_input_conditional_branch
        """
        _, _, survey_a, _ = self._setup_pair()
        leak = report_leak(
            survey_a["id"],
            location_description="Main & 1st",
            estimated_loss_lps=2.0,
            repair_cost_estimate=8000,
        )
        assert_leak(leak)
        # annualized = 2.0 * 86400 * 365 / 1000 = 63072; value = 75686.4;
        # ratio = 9.4608; base = 18.9216 -> 18.92
        assert leak["annualized_loss_m3"] == pytest.approx(
            PINNED_LEAK["ANNUALIZED_LOSS_M3"], abs=0.01
        )
        assert leak["repair_priority_score"] == pytest.approx(
            PINNED_LEAK["SCORE_NO_PROJECT"], abs=0.01
        )
        assert leak["priority_band"] == "P3"

    def test_active_pressure_project_applies_bonus_multiplier(self, api):
        """PRD §3.4: "When the leak's DMA has a pressure project in `ACTIVE`
        status, a pressure-management bonus multiplies the score by 1.25,
        reflecting that reduced zone pressure will make the repair partly
        self-funding. The resulting `repair_priority_score` is rounded half-up
        to 2 decimal places."

        Design: Difficulty/combinatorial_formula/leak_priority_multi_input_conditional_branch
        """
        _, _, _, survey_b = self._setup_pair()
        leak = report_leak(
            survey_b["id"],
            location_description="Main & 2nd",
            estimated_loss_lps=2.0,
            repair_cost_estimate=8000,
        )
        # 18.9216 * 1.25 = 23.652 -> 23.65, which crosses into P2
        assert leak["repair_priority_score"] == pytest.approx(
            PINNED_LEAK["SCORE_WITH_PROJECT"], abs=0.01
        )
        assert leak["priority_band"] == "P2"


class TestReworkCycle:
    def _setup_repaired_leak(self):
        dma = create_dma(code="DMA-NL1", connection_count=1000,
                         mains_length_km=30.0, target_nrw_pct=15.0)
        # Survey started while posture is OPEN; the project then goes ACTIVE so
        # the leak's score carries the pressure-management bonus.
        _, survey = create_in_field_survey_with_active_project(
            dma["id"], project_overrides={"name": "PRV NL1"}
        )
        leak = report_leak(
            survey["id"],
            location_description="Valve 9",
            estimated_loss_lps=2.0,
            detected_at="2026-08-02T02:00:00Z",
            repair_cost_estimate=8000,
        )
        headers = make_field_supervisor_headers(FS)
        validate_success(api_client.verify_leak(leak["id"], headers), 200)
        validate_success(api_client.schedule_leak_repair(leak["id"], headers), 200)
        repaired = validate_success(
            api_client.complete_leak_repair(
                leak["id"], {"actual_repair_cost": 7500}, headers
            ),
            200,
        )
        return dma, survey, repaired

    def test_reopen_recomputes_score_with_rework_penalty(self, api,
                                                         field_supervisor_headers):
        """PRD §3.4: "Alternatively, a repair that fails inspection is reopened:
        the leak moves from `REPAIRED` to `REOPENED`, its score is recomputed
        from the same formula with an additional rework penalty multiplying the
        result by 1.10, and `open_leak_count` is recomputed."

        Design: Difficulty/non_linear_state_machine/leak_repair_rework_cycle
        """
        dma, survey, repaired = self._setup_repaired_leak()
        assert repaired["status"] == "REPAIRED"
        # A repaired-but-not-yet-verified leak has already left the open set.
        assert get_dma(dma["id"])["open_leak_count"] == 0

        reopened = validate_success(
            api.reopen_leak(repaired["id"], field_supervisor_headers), 200
        )
        assert reopened["status"] == "REOPENED"
        # 18.9216 * 1.25 * 1.10 = 26.0172 -> 26.02
        assert reopened["repair_priority_score"] == pytest.approx(
            PINNED_LEAK["SCORE_REOPENED_WITH_PROJECT"], abs=0.01
        )
        assert get_dma(dma["id"])["open_leak_count"] == 1

    def test_reopened_leak_reenters_scheduling_retaining_actual_cost(
        self, api, field_supervisor_headers
    ):
        """PRD §3.4: "A reopened leak re-enters scheduling — `REOPENED` to
        `REPAIR_SCHEDULED` — and proceeds through the repair cycle again." and
        "The supplied cost is stored, the DMA's `open_leak_count` is recomputed,
        and an audit event is appended."

        Design: Difficulty/non_linear_state_machine/leak_repair_rework_cycle
        """
        dma, survey, repaired = self._setup_repaired_leak()
        validate_success(
            api.reopen_leak(repaired["id"], field_supervisor_headers), 200
        )
        rescheduled = validate_success(
            api.schedule_leak_repair(repaired["id"], field_supervisor_headers), 200
        )
        assert rescheduled["status"] == "REPAIR_SCHEDULED"
        assert rescheduled["actual_repair_cost"] == pytest.approx(7500, abs=0.01)
        assert rescheduled["repair_priority_score"] == pytest.approx(
            PINNED_LEAK["SCORE_REOPENED_WITH_PROJECT"], abs=0.01
        )


class TestVerifyRepairSegregation:
    def test_reporter_cannot_verify_own_repair_but_peer_can(self, api):
        """PRD §3.4: "Verification of the repair — which must be performed by a
        supervisor whose `X-User-ID` differs from the leak's
        `reported_by_user_id`, with violations rejected as
        `ERR_SEGREGATION_OF_DUTIES` per §2.11 — moves it to the terminal
        `VERIFIED_REPAIR` state, recomputing `open_leak_count`"

        Design: Corner/rbac/verify_repair_segregation_from_reporter
        """
        dma = create_dma(code="DMA-RB3", connection_count=1000,
                         mains_length_km=30.0, target_nrw_pct=15.0)
        survey, repaired = create_repaired_leak(
            dma["id"],
            actual_repair_cost=3800,
            leak_overrides={"location_description": "Main & 9th"},
        )
        assert repaired["reported_by_user_id"] == FS

        own = api.verify_leak_repair(
            repaired["id"], make_field_supervisor_headers(FS)
        )
        validate_error(own, ApiErrorId.ERR_SEGREGATION_OF_DUTIES,
                       expected_status=403)

        verified = validate_success(
            api.verify_leak_repair(
                repaired["id"], make_field_supervisor_headers(FS2)
            ),
            200,
        )
        assert verified["status"] == "VERIFIED_REPAIR"
