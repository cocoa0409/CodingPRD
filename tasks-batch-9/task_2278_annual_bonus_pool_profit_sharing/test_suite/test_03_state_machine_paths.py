"""Non-linear paths: loops that re-enter a state, rewinds, and parallel axes."""

from test_helpers import (
    CC_CERTIFIER,
    CC_SCORECARD,
    HRBP_USER,
    HRBP_USER_ALT,
    PAYMENT_DATE_CLOCK,
    BonusPlanScenario,
    assert_pct,
    assert_ratio,
    build_allocated_scenario,
    build_locked_scenario,
    dispute_resolution_payload,
    make_hr_headers,
    validate_success,
)


def _calibration_cycle_scenario() -> BonusPlanScenario:
    """One fully allocated pool, driven twice back to ALLOCATING and then locked."""
    scenario = build_allocated_scenario(
        units=("UNIT-L",),
        plan_overrides={"plan_name": "FY26 Calibration Cycle Plan"},
    )
    # First return leaves CALIBRATION_SUBMITTED.
    scenario.submit_calibration("UNIT-L")
    scenario.open_calibration()
    scenario.decide_calibration(
        "UNIT-L", "RETURN", decision_note="first return - differentiate more"
    )
    return scenario


class TestPoolReturnsToAllocatingTwice:
    def test_the_two_return_edges_leave_from_two_different_calibration_states(
        self, api
    ):
        """PRD §3.7: "`RETURN` reopens the pool for reallocation and can be applied both
        to a pool in `CALIBRATION_SUBMITTED` and to one already in `CALIBRATED`, in
        either case landing it back in `ALLOCATING`: it increments
        `calibration_returned_count`, demotes every award of the pool from `CALIBRATED`
        back to `PROPOSED`, and — because the pool has left the state that let the plan
        advance — sends a plan sitting in `CALIBRATION_REVIEW` back to `ALLOCATION_OPEN`
        without any separate request against the plan."

        Design: Difficulty/non_linear_state_machine/pool_returns_to_allocating_from_two_different_calibration_states
        """
        scenario = _calibration_cycle_scenario()

        first_return = scenario.pools["UNIT-L"]
        assert first_return["calibration_status"] == "ALLOCATING"
        assert first_return["calibration_returned_count"] == 1
        assert scenario.refresh_plan()["status"] == "ALLOCATION_OPEN"
        assert scenario.refresh_award("ada")["allocation_status"] == "PROPOSED"

        # Second cycle: certify first, so the return leaves CALIBRATED instead.
        scenario.submit_calibration("UNIT-L")
        scenario.open_calibration()
        certified = scenario.decide_calibration("UNIT-L", "CERTIFY", decision_note="accepted")
        assert certified["calibration_status"] == "CALIBRATED"
        assert scenario.refresh_award("ada")["allocation_status"] == "CALIBRATED"

        second_return = scenario.decide_calibration(
            "UNIT-L", "RETURN", decision_note="second return, this time out of CALIBRATED"
        )
        assert second_return["calibration_status"] == "ALLOCATING"
        assert second_return["calibration_returned_count"] == 2
        assert scenario.refresh_plan()["status"] == "ALLOCATION_OPEN"
        assert scenario.refresh_award("ada")["allocation_status"] == "PROPOSED"

    def test_the_loop_moves_no_money_and_the_third_pass_locks_cleanly(self, api):
        """PRD §3.7: "Locking moves every pool of the plan from `CALIBRATED` to `LOCKED`
        — a terminal state for a pool — and, through them, every award in `CALIBRATED`
        to `LOCKED`. The plan's `locked_total_cents` is the sum of `final_award_cents`
        over the awards now in `LOCKED`, and `locked_by_user_id` records the acting
        member."

        Design: Difficulty/non_linear_state_machine/pool_returns_to_allocating_from_two_different_calibration_states
        """
        scenario = _calibration_cycle_scenario()
        scenario.submit_calibration("UNIT-L")
        scenario.open_calibration()
        scenario.decide_calibration("UNIT-L", "CERTIFY", decision_note="accepted")
        scenario.decide_calibration(
            "UNIT-L", "RETURN", decision_note="second return, this time out of CALIBRATED"
        )
        scenario.submit_calibration("UNIT-L")
        scenario.open_calibration()
        scenario.decide_calibration("UNIT-L", "CERTIFY", decision_note="final")
        plan = scenario.lock()

        pool = scenario.pools["UNIT-L"]
        assert pool["calibration_returned_count"] == 2
        assert pool["calibration_status"] == "LOCKED"
        assert pool["allocated_cents"] == 4000000
        assert pool["available_cents"] == 0
        assert pool["distribution_status"] == "WITHIN_GUIDELINES"
        assert_pct(pool["utilization_pct"], 100.00)

        award = scenario.refresh_award("ada")
        assert award["allocation_status"] == "LOCKED"
        assert award["proposed_allocation_cents"] == 4000000
        assert award["retraction_count"] == 0

        assert plan["status"] == "LOCKED"
        assert plan["locked_total_cents"] == 4000000
        assert plan["governance_posture"] == "COMPLIANT"


def _pending_certification_scenario() -> BonusPlanScenario:
    """Two metrics actualized, one scorecard certified, plan PENDING_CERTIFICATION."""
    scenario = BonusPlanScenario()
    scenario.add_unit("EAST-B", name="East Region B")
    scenario.create_plan(plan_name="FY26 Return Cycle Plan")
    scenario.add_target("L3", target_bonus_pct=10.00)
    scenario.add_target("L5", target_bonus_pct=20.00)
    scenario.add_metric(
        "REVENUE", weight_pct=60.00, threshold_value=900, target_value=1000, max_value=1200
    )
    scenario.add_metric(
        "EBITDA", weight_pct=40.00, threshold_value=90, target_value=100, max_value=130
    )
    scenario.add_pool("EAST-B")
    scenario.add_participant(
        "ada",
        "EAST-B",
        employee_code="E001",
        full_name="Ada Long",
        job_level="L5",
        base_salary_cents=20000000,
        hire_date="2025-03-01",
    )
    scenario.add_participant(
        "ben",
        "EAST-B",
        employee_code="E002",
        full_name="Ben Short",
        job_level="L3",
        base_salary_cents=10000000,
        hire_date="2026-07-01",
    )
    scenario.file_actual("REVENUE", 900, source_note="audited")
    scenario.file_actual("EBITDA", 95, source_note="audited")
    scenario.submit_scorecard("EAST-B", 100.00, scorecard_narrative="first submission")
    scenario.decide_scorecard("EAST-B", "CERTIFY")
    scenario.assign_targets()
    scenario.submit_for_certification()
    return scenario


class TestCertificationReturnRewind:
    def test_return_drags_every_certified_scorecard_back_to_draft_and_zeroes_the_curve(
        self, api
    ):
        """PRD §3.4: "The plan goes from `PENDING_CERTIFICATION` back to `TARGETS_SET`;
        every pool of the plan that stood in `SCORECARD_CERTIFIED` is pushed back to
        `DRAFT` with its `scorecard_certified_by_user_id` cleared; and because the
        certified-pool input set is now empty, `bu_weighted_achievement_pct` and
        `blended_achievement_pct` reset to 0.00 and `funding_multiplier` resets to
        0.0000."

        Design: Difficulty/non_linear_state_machine/certification_return_rewinds_scorecards_and_zeroes_the_multiplier
        """
        scenario = _pending_certification_scenario()
        plan = scenario.decide_certification(
            "RETURN", decision_note="committee wants the BU scorecard re-evidenced"
        )

        assert plan["status"] == "TARGETS_SET"
        assert_pct(plan["bu_weighted_achievement_pct"], 0.00)
        assert_pct(plan["blended_achievement_pct"], 0.00)
        assert_ratio(plan["funding_multiplier"], 0.0000)
        assert plan["certified_by_user_id"] is None

        pool = scenario.refresh_pool("EAST-B")
        assert pool["calibration_status"] == "DRAFT"
        assert pool["scorecard_certified_by_user_id"] is None

    def test_only_the_second_pass_through_pending_certification_mints_the_multiplier(
        self, api
    ):
        """PRD §3.4: "Every scorecard must then be resubmitted and re-certified before
        the plan can be submitted again."

        Design: Difficulty/non_linear_state_machine/certification_return_rewinds_scorecards_and_zeroes_the_multiplier
        """
        scenario = _pending_certification_scenario()
        scenario.decide_certification(
            "RETURN", decision_note="committee wants the BU scorecard re-evidenced"
        )
        scenario.submit_scorecard(
            "EAST-B", 100.00, scorecard_narrative="re-evidenced, unchanged"
        )
        scenario.decide_scorecard("EAST-B", "CERTIFY", user_id=CC_SCORECARD)
        scenario.submit_for_certification()
        plan = scenario.decide_certification(
            "CERTIFY", user_id=CC_CERTIFIER, decision_note="second pass accepted"
        )

        assert plan["status"] == "CERTIFIED"
        assert_pct(plan["company_achievement_pct"], 60.00)
        assert_pct(plan["bu_weighted_achievement_pct"], 100.00)
        assert_pct(plan["blended_achievement_pct"], 80.00)
        assert_ratio(plan["funding_multiplier"], 0.5000)
        assert plan["total_target_cents"] == 4504110
        assert plan["certified_by_user_id"] == CC_CERTIFIER

        pool = scenario.refresh_pool("EAST-B")
        assert pool["calibration_status"] == "SCORECARD_CERTIFIED"
        assert pool["scorecard_certified_by_user_id"] == CC_SCORECARD


def _disputed_payout_scenario() -> BonusPlanScenario:
    """A locked award carrying a live dispute, with the payout run already executed."""
    scenario = build_locked_scenario(
        units=("UNIT-P",),
        plan_overrides={
            "plan_name": "FY26 Parallel Axis Plan",
            "termination_treatment_policy": "STRICT_PAYMENT_DATE",
        },
    )
    scenario.file_dispute(
        "ada",
        dispute_reason="expected a higher individual multiple",
        claimed_amount_cents=4400000,
    )
    scenario.set_clock(PAYMENT_DATE_CLOCK)
    scenario.open_payout_run(run_note="FY26 payout")
    scenario.execute_payout()
    return scenario


class TestAwardParallelAxes:
    def test_execute_defers_the_payment_axis_and_leaves_the_allocation_axis_locked(
        self, api
    ):
        """PRD §3.9: "If any dispute of the award is in `OPEN` or `UNDER_REVIEW`, the
        award moves from `payment_status` `PENDING` to `DEFERRED`: its
        `payout_amount_cents` is written to the verdict amount but the cash is held, and
        the award counts only toward `deferred_award_count`."

        Design: Difficulty/non_linear_state_machine/award_allocation_axis_locks_while_payment_axis_defers_then_pays
        """
        scenario = _disputed_payout_scenario()
        award = scenario.refresh_award("ada")

        assert award["allocation_status"] == "LOCKED"
        assert award["payment_status"] == "DEFERRED"
        assert award["payout_amount_cents"] == 4000000

        run = scenario.payout_run
        assert run["deferred_award_count"] == 1
        assert run["paid_award_count"] == 0
        assert run["total_paid_cents"] == 0

        plan = scenario.refresh_plan()
        assert plan["paid_total_cents"] == 0
        assert plan["status"] == "PAID_OUT"

    def test_upholding_the_dispute_releases_the_payment_without_moving_the_allocation(
        self, api
    ):
        """PRD §3.9: "If the award was left `DEFERRED` by the run, upholding releases
        it: an award whose `payout_amount_cents` is greater than 0 moves from `DEFERRED`
        to `PAID`, and an award whose `payout_amount_cents` is 0 — the run's verdict was
        forfeiture — moves from `DEFERRED` to `FORFEITED`, with its `final_award_cents`
        added to the plan's `forfeited_total_cents`."

        Design: Difficulty/non_linear_state_machine/award_allocation_axis_locks_while_payment_axis_defers_then_pays
        """
        scenario = _disputed_payout_scenario()
        dispute_id = scenario.disputes[0]["id"]
        scenario.assign_dispute_review(
            dispute_id, reviewer_note="reviewing calibration notes"
        )
        # A different HR operator resolves, so both recorded identities are visible.
        dispute = validate_success(
            api.resolve_dispute(
                dispute_id,
                dispute_resolution_payload(
                    "UPHOLD",
                    resolution_note="allocation confirmed, release the held payment",
                ),
                make_hr_headers(HRBP_USER_ALT),
            )
        )

        award = scenario.refresh_award("ada")
        assert award["allocation_status"] == "LOCKED"
        assert award["payment_status"] == "PAID"
        assert award["payout_amount_cents"] == 4000000

        assert dispute["status"] == "RESOLVED_UPHELD"
        assert dispute["assigned_by_user_id"] == HRBP_USER
        assert dispute["resolved_by_user_id"] == HRBP_USER_ALT

        plan = scenario.refresh_plan()
        assert plan["paid_total_cents"] == 4000000
        assert plan["dispute_adjustment_cents"] == 0
