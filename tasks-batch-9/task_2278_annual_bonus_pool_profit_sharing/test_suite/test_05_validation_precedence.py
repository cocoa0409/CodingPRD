"""Requests that break two rules at once, where only the earlier one may surface."""

from test_helpers import (
    ApiErrorId,
    build_allocated_scenario,
    build_funded_scenario,
    discretionary_adjustment_payload,
    make_committee_headers,
    make_plan_admin_headers,
    propose_allocation_payload,
    validate_error,
    validate_success,
)

DUAL_HAT = "dual_hat"


class TestPlanPhaseWinsOverPoolFunds:
    def test_the_closed_allocation_phase_is_reported_and_not_the_pool_money(self, api):
        """PRD §3.5: "The checks are the ladder of §2.10 applied to this operation, in
        this order: the acting `X-User-ID` must equal the award's `business_unit_id`
        (`ERR_FORBIDDEN_RESOURCE_OWNERSHIP`); the plan must be in `ALLOCATION_OPEN`
        (`ERR_PLAN_NOT_IN_ALLOCATION`); the pool must be in `FUNDED` or `ALLOCATING`
        (`ERR_POOL_NOT_ALLOCATING`); the award's `allocation_status` must be
        `UNALLOCATED` or `PROPOSED` (`ERR_AWARD_STATE_INVALID`); `expected_pool_version`
        must match the pool's `version` (`ERR_STALE_POOL_VERSION`); the award's
        `eligibility_status` must be `ELIGIBLE` or `GOOD_LEAVER`, since an
        `INELIGIBLE_MIN_SERVICE` or `BAD_LEAVER` award may receive nothing
        (`ERR_AWARD_NOT_ELIGIBLE`); the guideline band must be respected; and finally the
        pool must still have the money."

        Design: Difficulty/priority_pair_validation_conflict/plan_phase_state_error_wins_over_pool_funds_exceeded
        """
        scenario = build_allocated_scenario(
            units=("UNIT-Q",), plan_overrides={"plan_name": "FY26 Priority Phase Plan"}
        )
        scenario.submit_calibration("UNIT-Q")
        scenario.open_calibration()

        response = api.propose_allocation(
            scenario.award_id("ada"),
            propose_allocation_payload(
                5000000,
                scenario.pool_version("UNIT-Q"),
                allocation_rationale="late uplift attempt",
            ),
            scenario.manager_headers("UNIT-Q"),
        )

        error = validate_error(
            response, ApiErrorId.ERR_PLAN_NOT_IN_ALLOCATION.value, expected_status=409
        )
        assert error["error_id"] != ApiErrorId.ERR_POOL_FUNDS_EXCEEDED.value
        assert error["error_id"] != ApiErrorId.ERR_POOL_NOT_ALLOCATING.value

    def test_the_refused_late_allocation_leaves_award_and_pool_exactly_as_they_were(
        self, api
    ):
        """PRD §2.10: "An incentive plan must refuse an unauthorized or out-of-sequence
        action before it ever reports a budget number, so identity comes first and money
        comes last."

        Design: Difficulty/priority_pair_validation_conflict/plan_phase_state_error_wins_over_pool_funds_exceeded
        """
        scenario = build_allocated_scenario(
            units=("UNIT-Q",), plan_overrides={"plan_name": "FY26 Priority Phase Plan"}
        )
        scenario.submit_calibration("UNIT-Q")
        scenario.open_calibration()

        api.propose_allocation(
            scenario.award_id("ada"),
            propose_allocation_payload(
                5000000,
                scenario.pool_version("UNIT-Q"),
                allocation_rationale="late uplift attempt",
            ),
            scenario.manager_headers("UNIT-Q"),
        )

        assert scenario.refresh_award("ada")["proposed_allocation_cents"] == 4000000
        assert scenario.refresh_pool("UNIT-Q")["allocated_cents"] == 4000000


class TestSegregationOfDutiesWinsOverBudget:
    def _scenario_with_self_filed_adjustment(self, api):
        scenario = build_allocated_scenario(
            units=("UNIT-R",),
            plan_overrides={
                "plan_name": "FY26 Duties Plan",
                "discretionary_budget_pct": 10.00,
            },
        )
        # 500,000 sits under the frozen 1,000,000 per-award cap but over the
        # plan's 400,000 discretionary budget.
        adjustment = validate_success(
            api.create_discretionary_adjustment(
                discretionary_adjustment_payload(
                    scenario.plan_id,
                    scenario.award_id("ada"),
                    500000,
                    scenario.plan_version(),
                    justification="market correction",
                    documentation_ref="GOV-2026-021",
                ),
                make_plan_admin_headers(DUAL_HAT),
            ),
            expected_status=201,
        )
        return scenario, adjustment

    def test_the_self_approval_is_refused_before_the_budget_is_ever_consulted(self, api):
        """PRD §3.6: "Either verdict requires the plan to be in `ALLOCATION_OPEN` or
        `CALIBRATION_REVIEW` (`ERR_PLAN_NOT_IN_ALLOCATION`), the adjustment to be in
        `PENDING_APPROVAL` (`ERR_ADJUSTMENT_NOT_PENDING`) and the acting `X-User-ID` to
        differ from the adjustment's `submitted_by_user_id`
        (`ERR_SEGREGATION_OF_DUTIES`)."

        Design: Difficulty/priority_pair_validation_conflict/segregation_of_duties_wins_over_discretionary_budget_exceeded
        """
        scenario, adjustment = self._scenario_with_self_filed_adjustment(api)
        assert adjustment["per_award_cap_cents"] == 1000000

        response = api.decide_discretionary_adjustment(
            adjustment["id"],
            {"decision": "APPROVE", "decision_note": "self-approval attempt"},
            make_committee_headers(DUAL_HAT),
        )

        error = validate_error(
            response, ApiErrorId.ERR_SEGREGATION_OF_DUTIES.value, expected_status=403
        )
        assert error["error_id"] != ApiErrorId.ERR_DISCRETIONARY_BUDGET_EXCEEDED.value
        assert error["error_id"] != ApiErrorId.ERR_ADJUSTMENT_EXCEEDS_PER_AWARD_LIMIT.value

    def test_the_refused_decision_leaves_the_adjustment_pending_and_the_ledger_at_zero(
        self, api
    ):
        """PRD §2.11: "For every plan, `discretionary_used_cents` always equals the sum
        of the absolute values of `adjustment_cents` over the plan's discretionary
        adjustments that are currently `APPROVED`."

        Design: Difficulty/priority_pair_validation_conflict/segregation_of_duties_wins_over_discretionary_budget_exceeded
        """
        scenario, adjustment = self._scenario_with_self_filed_adjustment(api)
        api.decide_discretionary_adjustment(
            adjustment["id"],
            {"decision": "APPROVE", "decision_note": "self-approval attempt"},
            make_committee_headers(DUAL_HAT),
        )

        stored = validate_success(
            api.get_discretionary_adjustment(
                adjustment["id"], make_plan_admin_headers(DUAL_HAT)
            )
        )
        assert stored["status"] == "PENDING_APPROVAL"
        assert stored["decided_by_user_id"] is None
        assert scenario.refresh_plan()["discretionary_used_cents"] == 0


class TestGuidelineRatioWinsOverPoolFunds:
    def test_the_band_breach_is_reported_although_the_pool_is_also_short(self, api):
        """PRD §3.5: "For a non-zero amount, that ratio must be at least the
        `guideline_min_ratio` and at most the `guideline_max_ratio` of the job-level
        target row for the award's level; a ratio outside the band is
        `ERR_GUIDELINE_RATIO_BREACH`."

        Design: Difficulty/priority_pair_validation_conflict/guideline_ratio_breach_wins_over_pool_funds_exceeded
        """
        scenario = build_funded_scenario(
            units=("UNIT-S",), plan_overrides={"plan_name": "FY26 Guideline Plan"}
        )
        # 10,000,000 is ratio 2.5000 against a 4,000,000 target and also exceeds
        # the 4,000,000 the pool holds.
        response = api.propose_allocation(
            scenario.award_id("ada"),
            propose_allocation_payload(
                10000000,
                scenario.pool_version("UNIT-S"),
                allocation_rationale="star performer, 2.5x target",
            ),
            scenario.manager_headers("UNIT-S"),
        )

        error = validate_error(
            response, ApiErrorId.ERR_GUIDELINE_RATIO_BREACH.value, expected_status=422
        )
        assert error["error_id"] != ApiErrorId.ERR_POOL_FUNDS_EXCEEDED.value

    def test_the_refused_proposal_leaves_the_award_unallocated_in_a_funded_pool(
        self, api
    ):
        """PRD §3.5: "The **pool money check** is the last gate to run. The pool's
        `allocated_cents`, evaluated after this award's previous proposed amount has been
        removed and the new one added, must not exceed the pool's frozen `funded_cents`;
        if it would, the request is refused with `ERR_POOL_FUNDS_EXCEEDED`."

        Design: Difficulty/priority_pair_validation_conflict/guideline_ratio_breach_wins_over_pool_funds_exceeded
        """
        scenario = build_funded_scenario(
            units=("UNIT-S",), plan_overrides={"plan_name": "FY26 Guideline Plan"}
        )
        api.propose_allocation(
            scenario.award_id("ada"),
            propose_allocation_payload(
                10000000,
                scenario.pool_version("UNIT-S"),
                allocation_rationale="star performer, 2.5x target",
            ),
            scenario.manager_headers("UNIT-S"),
        )

        award = scenario.refresh_award("ada")
        assert award["allocation_status"] == "UNALLOCATED"
        assert award["proposed_allocation_cents"] == 0

        pool = scenario.refresh_pool("UNIT-S")
        assert pool["allocated_cents"] == 0
        assert pool["calibration_status"] == "FUNDED"
