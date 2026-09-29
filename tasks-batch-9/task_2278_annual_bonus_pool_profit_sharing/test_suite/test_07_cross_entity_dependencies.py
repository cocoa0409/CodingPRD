"""Transitions guarded by the state of a neighbouring entity, not by their own row."""

from test_helpers import (
    CC_LOCKER,
    FC,
    HRBP_USER_ALT,
    PAYMENT_DATE_CLOCK,
    ApiErrorId,
    BonusPlanScenario,
    assert_pct,
    assert_settlement_closure,
    build_allocated_scenario,
    build_locked_scenario,
    dispute_resolution_payload,
    make_committee_headers,
    make_hr_headers,
    propose_allocation_payload,
    settle_payload,
    validate_error,
    validate_success,
)

_L3_TARGET = ({"job_level": "L3", "target_bonus_pct": 10.00},)
_TWO_UNIT_ROSTER = (
    {
        "label": "una",
        "unit_code": "EAST1",
        "employee_code": "E401",
        "full_name": "Una One",
        "job_level": "L3",
        "base_salary_cents": 10000000,
        "hire_date": "2025-01-01",
    },
    {
        "label": "ted",
        "unit_code": "EAST2",
        "employee_code": "E402",
        "full_name": "Ted Two",
        "job_level": "L3",
        "base_salary_cents": 10000000,
        "hire_date": "2025-01-01",
    },
)


def _half_calibrated_scenario() -> BonusPlanScenario:
    """Two fully allocated pools in calibration review, only the first one certified."""
    scenario = build_allocated_scenario(
        units=("EAST1", "EAST2"),
        plan_overrides={"plan_name": "FY26 Two Pool Plan"},
        targets=_L3_TARGET,
        participants=_TWO_UNIT_ROSTER,
    )
    scenario.submit_calibration("EAST1")
    scenario.submit_calibration("EAST2")
    scenario.open_calibration()
    scenario.decide_calibration("EAST1", "CERTIFY", decision_note="east one accepted")
    return scenario


class TestPlanLockNeedsEverySiblingPool:
    def test_the_lock_is_refused_while_one_sibling_pool_is_merely_submitted(self, api):
        """PRD §3.7: "Three conditions guard it, in ladder order: the acting `X-User-ID`
        must differ from the plan's `certified_by_user_id`, so that the member who
        certified the performance figures is not the member who freezes the money
        (`ERR_SEGREGATION_OF_DUTIES`); the plan's `governance_posture` must be
        `COMPLIANT`, which means no pool may be left over-allocated or under-utilized
        (`ERR_GOVERNANCE_POSTURE_BREACHED`); and every pool of the plan must be in
        `CALIBRATED`, not merely submitted (`ERR_POOL_CALIBRATION_PENDING`)."

        Design: Difficulty/cross_entity_state_dependency/plan_lock_requires_every_sibling_pool_calibrated
        """
        scenario = _half_calibrated_scenario()

        response = api.lock_plan(scenario.plan_id, make_committee_headers(CC_LOCKER))
        validate_error(
            response, ApiErrorId.ERR_POOL_CALIBRATION_PENDING.value, expected_status=409
        )

        assert scenario.refresh_plan()["status"] == "CALIBRATION_REVIEW"
        assert scenario.refresh_pool("EAST1")["calibration_status"] == "CALIBRATED"
        assert scenario.refresh_pool("EAST2")["calibration_status"] == "CALIBRATION_SUBMITTED"
        assert scenario.refresh_award("una")["allocation_status"] == "CALIBRATED"
        assert scenario.refresh_award("ted")["allocation_status"] == "PROPOSED"

    def test_certifying_the_second_pool_lets_the_identical_lock_request_through(
        self, api
    ):
        """PRD §3.7: "Locking moves every pool of the plan from `CALIBRATED` to `LOCKED`
        — a terminal state for a pool — and, through them, every award in `CALIBRATED` to
        `LOCKED`. The plan's `locked_total_cents` is the sum of `final_award_cents` over
        the awards now in `LOCKED`, and `locked_by_user_id` records the acting member."

        Design: Difficulty/cross_entity_state_dependency/plan_lock_requires_every_sibling_pool_calibrated
        """
        scenario = _half_calibrated_scenario()
        scenario.decide_calibration("EAST2", "CERTIFY", decision_note="east two accepted")

        plan = scenario.lock(user_id=CC_LOCKER)
        assert plan["status"] == "LOCKED"
        assert plan["locked_total_cents"] == 2000000
        assert plan["locked_by_user_id"] == CC_LOCKER
        assert_pct(plan["bu_weighted_achievement_pct"], 100.00)
        assert plan["funded_pool_cents"] == 2000000

        assert scenario.pools["EAST1"]["calibration_status"] == "LOCKED"
        assert scenario.pools["EAST2"]["calibration_status"] == "LOCKED"
        assert scenario.refresh_award("una")["allocation_status"] == "LOCKED"
        assert scenario.refresh_award("ted")["allocation_status"] == "LOCKED"


def _deferred_payout_scenario() -> BonusPlanScenario:
    """An executed run whose only award is held DEFERRED by a live dispute."""
    scenario = build_locked_scenario(
        units=("UNIT-V",),
        plan_overrides={
            "plan_name": "FY26 Settlement Guard Plan",
            "termination_treatment_policy": "STRICT_PAYMENT_DATE",
        },
    )
    scenario.file_dispute(
        "ada",
        dispute_reason="calibration outcome unclear",
        claimed_amount_cents=4200000,
    )
    scenario.set_clock(PAYMENT_DATE_CLOCK)
    scenario.open_payout_run(run_note="FY26 payout")
    scenario.execute_payout()
    return scenario


class TestSettlementNeedsEveryDisputeClosed:
    def test_settlement_is_refused_although_the_run_and_the_plan_are_both_ready(
        self, api
    ):
        """PRD §3.9: "The plan must be in `PAID_OUT` (`ERR_PLAN_NOT_LOCKED`) and no award
        of the plan may still be in `payment_status` `DEFERRED` — every live dispute must
        be resolved first, and an attempt while one remains is refused with
        `ERR_DEFERRED_AWARDS_PENDING`."

        Design: Difficulty/cross_entity_state_dependency/settlement_blocked_while_a_dispute_holds_an_award_deferred
        """
        scenario = _deferred_payout_scenario()

        response = api.settle_true_up(
            scenario.payout_run["id"],
            FC,
            settle_payload(settlement_note="first settlement attempt"),
        )
        validate_error(
            response, ApiErrorId.ERR_DEFERRED_AWARDS_PENDING.value, expected_status=409
        )

        run = validate_success(api.get_payout_run(scenario.payout_run["id"], FC))
        assert run["status"] == "EXECUTED"
        assert run["true_up_cents"] == 0

        plan = scenario.refresh_plan()
        assert plan["status"] == "PAID_OUT"
        assert plan["true_up_cents"] == 0
        assert scenario.refresh_award("ada")["payment_status"] == "DEFERRED"

    def test_resolving_the_dispute_releases_the_cash_and_the_true_up_then_books(
        self, api
    ):
        """PRD §3.9: "Settlement takes the plan's `paid_total_cents` — the cash actually
        paid, including awards that were deferred and later paid through dispute
        resolution, with forfeited awards contributing 0 — and computes
        `settlement_burden_cents` as `paid_total_cents` multiplied by the burden rate for
        that amount, divided by 100 and rounded half up to whole cents, using the same
        three-band table the accrual posting uses: 7.65 percent below 5,000,000 cents,
        9.25 percent below 20,000,000 cents and 10.50 percent at or above that, keyed on
        `paid_total_cents`."

        Design: Difficulty/cross_entity_state_dependency/settlement_blocked_while_a_dispute_holds_an_award_deferred
        """
        scenario = _deferred_payout_scenario()
        dispute_id = scenario.disputes[0]["id"]
        scenario.assign_dispute_review(dispute_id, reviewer_note="taking it under review")
        dispute = validate_success(
            api.resolve_dispute(
                dispute_id,
                dispute_resolution_payload(
                    "UPHOLD", resolution_note="original allocation stands"
                ),
                make_hr_headers(HRBP_USER_ALT),
            )
        )
        assert dispute["status"] == "RESOLVED_UPHELD"
        assert scenario.refresh_award("ada")["payment_status"] == "PAID"

        run = scenario.settle(settlement_note="second settlement attempt, dispute closed")
        assert run["status"] == "SETTLED"
        assert run["settlement_burden_cents"] == 306000
        assert run["true_up_cents"] == 4306000

        plan = scenario.refresh_plan()
        assert plan["status"] == "SETTLED"
        assert plan["paid_total_cents"] == 4000000
        assert plan["accrued_total_cents"] == 0
        assert plan["settlement_burden_cents"] == 306000
        assert plan["true_up_cents"] == 4306000
        assert_settlement_closure(plan)


def _bad_leaver_scenario() -> BonusPlanScenario:
    """A fully allocated award whose holder then resigns mid-year."""
    scenario = build_allocated_scenario(
        units=("UNIT-U",),
        plan_overrides={
            "plan_name": "FY26 Bad Leaver Plan",
            "termination_treatment_policy": "GOOD_LEAVER_PRORATION",
        },
    )
    scenario.add_termination(
        "ada",
        "2026-06-30",
        "VOLUNTARY_RESIGNATION",
        note="resigned to join a competitor",
    )
    return scenario


class TestAllocationRefusedForABadLeaver:
    def test_the_resignation_compensates_the_standing_proposal_and_re_prorates(self, api):
        """PRD §3.2: "One cascade is worth calling out here because it moves money: a
        termination whose recomputed classification is `BAD_LEAVER` zeroes a `PROPOSED`
        allocation, returning the award's `allocation_status` from `PROPOSED` to
        `UNALLOCATED` with `proposed_allocation_cents` set to 0, `allocation_ratio` to
        0.0000 and `final_award_cents` to 0."

        Design: Difficulty/cross_entity_state_dependency/allocation_refused_because_participant_left_as_bad_leaver
        """
        scenario = _bad_leaver_scenario()

        award = scenario.refresh_award("ada")
        assert award["eligibility_status"] == "BAD_LEAVER"
        assert award["credited_days"] == 181
        assert award["prorated_target_cents"] == 1983562
        assert award["allocation_status"] == "UNALLOCATED"
        assert award["proposed_allocation_cents"] == 0
        assert award["final_award_cents"] == 0

        pool = scenario.refresh_pool("UNIT-U")
        assert pool["allocated_cents"] == 0
        assert pool["available_cents"] == 4000000
        assert pool["eligible_target_cents"] == 1983562
        assert pool["distribution_status"] == "UNDER_UTILIZED"
        assert scenario.refresh_plan()["governance_posture"] == "FLAGGED"

    def test_the_allocatable_award_in_a_funded_pool_is_still_refused_the_money(self, api):
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

        Design: Difficulty/cross_entity_state_dependency/allocation_refused_because_participant_left_as_bad_leaver
        """
        scenario = _bad_leaver_scenario()

        response = api.propose_allocation(
            scenario.award_id("ada"),
            propose_allocation_payload(
                1983562,
                scenario.pool_version("UNIT-U"),
                allocation_rationale="pay the pro-rated portion anyway",
            ),
            scenario.manager_headers("UNIT-U"),
        )
        validate_error(
            response, ApiErrorId.ERR_AWARD_NOT_ELIGIBLE.value, expected_status=422
        )

        assert scenario.refresh_award("ada")["proposed_allocation_cents"] == 0
        assert scenario.refresh_pool("UNIT-U")["allocated_cents"] == 0
