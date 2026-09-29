"""Undo operations measured against the quantities they are required to restore."""

from test_helpers import (
    CC_ADJUDICATOR,
    FC,
    PA,
    BonusPlanScenario,
    assert_accrual_ledger_conservation,
    assert_discretionary_ledger_conservation,
    assert_pct,
    assert_pool_conservation,
    assert_ratio,
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


def _retracted_scenario() -> BonusPlanScenario:
    """A fully allocated award taken straight back off the table."""
    scenario = build_allocated_scenario(
        units=("UNIT-R",), plan_overrides={"plan_name": "FY26 Retraction Plan"}
    )
    scenario.retract(
        "ada", retraction_reason="manager reopens calibration for this employee"
    )
    return scenario


class TestRetractionRestoresPoolCents:
    def test_the_retraction_zeroes_the_award_and_is_audited_rather_than_silent(self, api):
        """PRD §3.5: "It sets `proposed_allocation_cents` to 0, `allocation_ratio` to
        0.0000 and `final_award_cents` to 0, increments `retraction_count`, and then runs
        the same pool recomputation and plan governance roll-up, incrementing the pool's
        `version`."

        Design: Difficulty/compensating_invariant/retract_allocation_restores_pool_cent_conservation
        """
        scenario = _retracted_scenario()
        award = scenario.refresh_award("ada")

        assert award["allocation_status"] == "UNALLOCATED"
        assert award["proposed_allocation_cents"] == 0
        assert_ratio(award["allocation_ratio"], 0.0000)
        assert award["final_award_cents"] == 0
        assert award["retraction_count"] == 1
        # The target itself is untouched by the undo.
        assert award["prorated_target_cents"] == 4000000

    def test_every_pool_and_plan_figure_returns_to_where_it_started(self, api):
        """PRD §3.5: "Allocate then retract the same award and the pool's
        `allocated_cents` and `available_cents` are back exactly where they started."

        Design: Difficulty/compensating_invariant/retract_allocation_restores_pool_cent_conservation
        """
        scenario = _retracted_scenario()
        pool = scenario.refresh_pool("UNIT-R")

        assert pool["funded_cents"] == 4000000
        assert pool["allocated_cents"] == 0
        assert pool["available_cents"] == 4000000
        assert_pct(pool["utilization_pct"], 0.00)
        assert pool["top_tier_award_count"] == 0
        assert pool["distribution_status"] == "UNDER_UTILIZED"
        assert pool["calibration_status"] == "ALLOCATING"
        assert_pool_conservation(pool)

        plan = scenario.refresh_plan()
        assert plan["under_utilized_pool_count"] == 1
        assert plan["over_allocated_pool_count"] == 0
        assert plan["governance_posture"] == "FLAGGED"


def _reversed_adjustment_scenario():
    """An approved adjustment worth the whole plan budget, then reversed."""
    scenario = build_allocated_scenario(
        units=("EAST-V",),
        plan_overrides={
            "plan_name": "FY26 Adjustment Reversal Plan",
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
    scenario.decide_adjustment(
        adjustment["id"], "APPROVE", user_id=CC_ADJUDICATOR,
        decision_note="approved at committee",
    )
    reversed_row = scenario.reverse_adjustment(
        adjustment["id"],
        decision_note="reversed after audit query; uplift withdrawn",
    )
    return scenario, reversed_row


class TestAdjustmentReversalRestoresTheBudgetLedger:
    def test_the_reversal_frees_the_whole_discretionary_budget_again(self, api):
        """PRD §2.11: "For every plan, `discretionary_used_cents` always equals the sum of
        the absolute values of `adjustment_cents` over the plan's discretionary
        adjustments that are currently `APPROVED`."

        Design: Difficulty/compensating_invariant/adjustment_reversal_restores_the_discretionary_budget_ledger
        """
        scenario, reversed_row = _reversed_adjustment_scenario()

        assert reversed_row["status"] == "REVERSED"
        assert reversed_row["adjustment_cents"] == 225206

        plan = scenario.refresh_plan()
        assert plan["discretionary_used_cents"] == 0
        assert plan["discretionary_budget_cents"] == 225206
        assert_discretionary_ledger_conservation(plan, [reversed_row])

    def test_the_award_pool_and_governance_land_on_their_pre_approval_values(self, api):
        """PRD §3.6: "It is an exact inverse of approval: the plan's
        `discretionary_used_cents` decreases by the absolute value of `adjustment_cents`,
        the award's `adjustment_total_cents` decreases by the signed `adjustment_cents`
        and its `final_award_cents` is recomputed, the pool's `allocated_cents`,
        `available_cents`, `utilization_pct` and `distribution_status` are recomputed, and
        the plan's `over_allocated_pool_count` and `governance_posture` follow — landing
        every one of those figures back on its pre-approval value, as §2.11 requires."

        Design: Difficulty/compensating_invariant/adjustment_reversal_restores_the_discretionary_budget_ledger
        """
        scenario, _ = _reversed_adjustment_scenario()

        ada = scenario.refresh_award("ada")
        assert ada["adjustment_total_cents"] == 0
        assert ada["final_award_cents"] == 2000000
        assert ada["proposed_allocation_cents"] == 2000000
        assert scenario.refresh_award("ben")["final_award_cents"] == 252055

        pool = scenario.refresh_pool("EAST-V")
        assert pool["allocated_cents"] == 2252055
        assert pool["available_cents"] == 0
        assert_pct(pool["utilization_pct"], 100.00)
        assert pool["distribution_status"] == "WITHIN_GUIDELINES"
        assert_pool_conservation(pool)

        plan = scenario.refresh_plan()
        assert plan["over_allocated_pool_count"] == 0
        assert plan["governance_posture"] == "COMPLIANT"


def _two_period_accrual_scenario() -> BonusPlanScenario:
    """Two posted half-year periods on a plan that never assigned targets."""
    scenario = BonusPlanScenario()
    scenario.add_unit("EAST-W", name="East Region W")
    scenario.create_plan(
        plan_name="FY26 Accrual Reversal Plan", discretionary_budget_pct=10.00
    )
    for target in _TWO_LEVEL_TARGETS:
        scenario.add_target(**target)
    for metric in _TWO_METRICS:
        scenario.add_metric(**metric)
    scenario.add_pool("EAST-W")
    for spec in _ADA_AND_BEN:
        details = dict(spec)
        scenario.add_participant(details.pop("label"), "EAST-W", **details)
    first = scenario.open_accrual_period("2026-01-01", "2026-06-30", 60.00)
    scenario.post_accrual_period(first["id"], posting_note="H1 provisional accrual")
    second = scenario.open_accrual_period("2026-07-01", "2026-12-31", 60.00)
    scenario.post_accrual_period(second["id"], posting_note="H2 provisional accrual")
    return scenario


class TestAccrualReversalRestoresTheLedger:
    def test_the_second_period_books_only_the_cumulative_delta(self, api):
        """PRD §3.8: "Third, `period_accrual_cents` is `cumulative_accrual_target_cents`
        minus the plan's `accrued_base_cents` as it stands before this posting; it may be
        negative, which is how a downgraded forecast claws back a previous
        over-accrual."

        Design: Difficulty/compensating_invariant/accrual_reversal_restores_the_ledger_to_the_prior_period_balance
        """
        scenario = _two_period_accrual_scenario()
        second = scenario.accrual_periods[1]

        assert second["elapsed_days"] == 365
        assert second["cumulative_accrual_target_cents"] == 2500000
        assert second["period_accrual_cents"] == 1260274
        assert second["burden_cents"] == 96411
        assert second["total_period_cents"] == 1356685

        plan = scenario.refresh_plan()
        assert plan["accrued_base_cents"] == 2500000
        assert plan["accrued_total_cents"] == 2691250

    def test_reversing_it_returns_the_ledger_to_the_first_periods_balance(self, api):
        """PRD §3.8: "It subtracts `period_accrual_cents` from the plan's
        `accrued_base_cents` and `total_period_cents` from its `accrued_total_cents` —
        exact compensation — while the period keeps every computed amount it holds for
        audit."

        Design: Difficulty/compensating_invariant/accrual_reversal_restores_the_ledger_to_the_prior_period_balance
        """
        scenario = _two_period_accrual_scenario()
        reversed_period = scenario.reverse_accrual_period(
            scenario.accrual_periods[1]["id"],
            reversal_reason="H2 forecast withdrawn pending committee certification",
        )

        assert reversed_period["status"] == "REVERSED"
        assert reversed_period["period_accrual_cents"] == 1260274
        assert reversed_period["total_period_cents"] == 1356685

        first = validate_success(
            api.get_accrual_period(scenario.accrual_periods[0]["id"], FC)
        )
        assert first["status"] == "POSTED"
        assert first["cumulative_accrual_target_cents"] == 1239726
        assert first["total_period_cents"] == 1334565

        plan = scenario.refresh_plan()
        assert plan["accrued_base_cents"] == 1239726
        assert plan["accrued_total_cents"] == 1334565
        assert plan["true_up_cents"] == 0
        assert_accrual_ledger_conservation(plan, scenario.refresh_accrual_periods())
