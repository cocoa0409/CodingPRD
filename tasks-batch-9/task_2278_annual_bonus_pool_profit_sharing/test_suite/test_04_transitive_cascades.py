"""One write, four levels of consequence: award, pool, plan, governance."""

from test_helpers import (
    CC_ADJUDICATOR,
    PA,
    BonusPlanScenario,
    assert_pct,
    build_allocated_scenario,
    validate_success,
)

_TWO_LEVEL_TARGETS = (
    {"job_level": "L3", "target_bonus_pct": 10.00},
    {"job_level": "L5", "target_bonus_pct": 20.00},
)
_TWO_METRICS = (
    {
        "metric_code": "REVENUE",
        "weight_pct": 60.00,
        "threshold_value": 900,
        "target_value": 1000,
        "max_value": 1200,
    },
    {
        "metric_code": "EBITDA",
        "weight_pct": 40.00,
        "threshold_value": 90,
        "target_value": 100,
        "max_value": 130,
    },
)
_ADA_AND_BEN = (
    {
        "label": "ada",
        "employee_code": "E001",
        "full_name": "Ada Long",
        "job_level": "L5",
        "base_salary_cents": 20000000,
        "hire_date": "2025-03-01",
    },
    {
        "label": "ben",
        "employee_code": "E002",
        "full_name": "Ben Short",
        "job_level": "L3",
        "base_salary_cents": 10000000,
        "hire_date": "2026-07-01",
    },
)


def _pending_adjustment_scenario(unit_code: str):
    """A fully allocated pool with one filed adjustment worth the whole plan budget."""
    scenario = build_allocated_scenario(
        units=(unit_code,),
        plan_overrides={
            "plan_name": "FY26 Adjustment Cascade Plan",
            "discretionary_budget_pct": 10.00,
        },
        targets=_TWO_LEVEL_TARGETS,
        metrics=_TWO_METRICS,
        metric_actuals={"REVENUE": 900, "EBITDA": 95},
        participants=_ADA_AND_BEN,
        allocations={"ada": 2000000, "ben": 252055},
    )
    adjustment = scenario.file_adjustment(
        "ada",
        225206,
        headers=PA,
        justification="retention risk, committee-sponsored uplift",
        documentation_ref="GOV-2026-014",
    )
    return scenario, adjustment


class TestAdjustmentApprovalCascade:
    def test_approval_loads_the_award_and_records_the_frozen_per_award_cap(self, api):
        """PRD §3.6: "`per_award_cap_cents` is the greater of 50000 cents and a quarter
        of the award's `prorated_target_cents` — the latter computed as
        `prorated_target_cents` multiplied by 25, divided by 100 and rounded half up to
        whole cents — read at creation time and never moved afterwards, so a later
        re-proration that changes `prorated_target_cents` leaves an existing
        adjustment's frozen cap exactly as it was."

        Design: Difficulty/transitive_cascade/adjustment_approval_propagates_award_pool_plan_governance
        """
        scenario, adjustment = _pending_adjustment_scenario("EAST-C")
        decided = scenario.decide_adjustment(
            adjustment["id"], "APPROVE", user_id=CC_ADJUDICATOR,
            decision_note="approved at committee",
        )

        assert decided["status"] == "APPROVED"
        assert decided["per_award_cap_cents"] == 1000000
        assert decided["decided_by_user_id"] == CC_ADJUDICATOR

        ada = scenario.refresh_award("ada")
        assert ada["adjustment_total_cents"] == 225206
        assert ada["final_award_cents"] == 2225206
        assert scenario.refresh_award("ben")["final_award_cents"] == 252055

    def test_the_same_approval_tips_the_pool_into_over_allocated(self, api):
        """PRD §3.5: "Finally the pool's `distribution_status` is decided in this order:
        `NO_ELIGIBLE_PARTICIPANTS` when `eligible_headcount` is 0; otherwise
        `OVER_ALLOCATED` when `allocated_cents` is strictly greater than `funded_cents`;
        otherwise `UNDER_UTILIZED` when `allocated_cents` is strictly less than
        `min_utilization_cents`; otherwise `WITHIN_GUIDELINES`."

        Design: Difficulty/transitive_cascade/adjustment_approval_propagates_award_pool_plan_governance
        """
        scenario, adjustment = _pending_adjustment_scenario("EAST-C")
        before = scenario.refresh_pool("EAST-C")
        assert before["distribution_status"] == "WITHIN_GUIDELINES"

        scenario.decide_adjustment(
            adjustment["id"], "APPROVE", user_id=CC_ADJUDICATOR,
            decision_note="approved at committee",
        )
        pool = scenario.refresh_pool("EAST-C")

        assert pool["allocated_cents"] == 2477261
        assert pool["available_cents"] == -225206
        assert_pct(pool["utilization_pct"], 110.00)
        assert pool["distribution_status"] == "OVER_ALLOCATED"

    def test_the_cascade_reaches_the_plan_governance_posture(self, api):
        """PRD §3.5: "The plan then re-derives its governance view:
        `over_allocated_pool_count` is the number of its pools in `OVER_ALLOCATED`,
        `under_utilized_pool_count` the number in `UNDER_UTILIZED`, and
        `governance_posture` is `BREACHED` when two or more pools are over-allocated,
        otherwise `FLAGGED` when exactly one pool is over-allocated or at least one pool
        is under-utilized, otherwise `COMPLIANT`."

        Design: Difficulty/transitive_cascade/adjustment_approval_propagates_award_pool_plan_governance
        """
        scenario, adjustment = _pending_adjustment_scenario("EAST-C")
        assert scenario.refresh_plan()["governance_posture"] == "COMPLIANT"

        scenario.decide_adjustment(
            adjustment["id"], "APPROVE", user_id=CC_ADJUDICATOR,
            decision_note="approved at committee",
        )
        plan = scenario.refresh_plan()

        assert plan["discretionary_used_cents"] == 225206
        assert plan["over_allocated_pool_count"] == 1
        assert plan["under_utilized_pool_count"] == 0
        assert plan["governance_posture"] == "FLAGGED"


def _targets_set_two_participant_scenario() -> BonusPlanScenario:
    """Awards of 4,000,000 and 504,110 in one pool, before any HR event lands."""
    scenario = BonusPlanScenario()
    scenario.add_unit("EAST-D", name="East Region D")
    scenario.create_plan(
        plan_name="FY26 Termination Cascade Plan",
        termination_treatment_policy="GOOD_LEAVER_PRORATION",
    )
    for target in _TWO_LEVEL_TARGETS:
        scenario.add_target(**target)
    scenario.add_pool("EAST-D")
    for spec in _ADA_AND_BEN:
        details = dict(spec)
        scenario.add_participant(details.pop("label"), "EAST-D", **details)
    scenario.assign_targets()
    return scenario


class TestTerminationEventCascade:
    def test_the_event_terminates_the_participant_and_truncates_the_window(self, api):
        """PRD §3.3: "**The participation window** is half-open: it starts on the later
        of the plan's `plan_period_start` and the participant's `hire_date`, and it ends,
        exclusively, at the plan's `plan_period_end` — except that for a participant
        whose `employment_status` is `TERMINATED`, the window ends at the earlier of
        `plan_period_end` and the day after `termination_date`."

        Design: Difficulty/transitive_cascade/termination_event_reprorates_award_pool_and_plan_targets
        """
        scenario = _targets_set_two_participant_scenario()
        assert scenario.awards["ada"]["prorated_target_cents"] == 4000000

        event = scenario.add_termination(
            "ada",
            "2026-09-30",
            "RETIREMENT",
            note="retirement, last day worked 30 September",
        )

        participant = validate_success(
            api.get_participant(scenario.participant_id("ada"), PA)
        )
        assert participant["employment_status"] == "TERMINATED"
        assert participant["termination_date"] == "2026-09-30"
        assert participant["termination_reason"] == "RETIREMENT"

        award = scenario.refresh_award("ada")
        assert award["credited_days"] == 273
        assert award["segment_count"] == 1
        assert award["prorated_target_cents"] == 2991781
        assert award["eligibility_status"] == "GOOD_LEAVER"
        assert event["superseded"] is False

    def test_the_re_proration_is_per_award_and_rolls_up_to_pool_and_plan(self, api):
        """PRD §3.2: "Once awards exist, an event does more than update a personnel
        record: it re-prorates the affected award, re-resolves which pool the award draws
        from, recomputes the distribution state of both the old and the new pool, and
        rolls the result up to the plan — the full chain of §2.7 in one request."

        Design: Difficulty/transitive_cascade/termination_event_reprorates_award_pool_and_plan_targets
        """
        scenario = _targets_set_two_participant_scenario()
        scenario.add_termination(
            "ada",
            "2026-09-30",
            "RETIREMENT",
            note="retirement, last day worked 30 September",
        )

        ben = scenario.refresh_award("ben")
        assert ben["prorated_target_cents"] == 504110
        assert ben["eligibility_status"] == "ELIGIBLE"

        pool = scenario.refresh_pool("EAST-D")
        assert pool["eligible_target_cents"] == 3495891
        assert pool["eligible_headcount"] == 2
        assert scenario.refresh_plan()["total_target_cents"] == 3495891
