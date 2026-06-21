"""Difficulty Rule 2 — combinatorial_formula.

Formulas with 3+ inputs whose evaluation order is observable in the result:
the nested min() in the two-pool charge waterfall (PRD §3.6) — pfl_charge =
min(fmla_charge, pfl_remaining), where pfl_remaining depends on the state.
"""
from test_helpers import (
    record_interval,
    seed_historic_interval,
    set_clock,
    setup_approved_case,
)


class TestPoolChargeNestedMinWithStateBranch:
    """PRD §3.6: nested min — pfl_charge = min(fmla_charge, pfl_remaining).

    For an RI employee (PFL_QUOTA=200) with case pre-existing fmla=150 and pfl=150,
    a new 80-hour interval should yield fmla_charge=80 (min(80, 480-150=330)) and
    pfl_charge=50 (min(80, 200-150=50)) — the nested min produces a smaller PFL
    than FMLA charge.
    """

    def test_ri_pool_charge_with_preexisting_150_yields_fmla_80_pfl_50(self, api):
        """PRD §3.6: "First, the FMLA remaining is the larger of zero and 480 minus the case's pre-existing `fmla_hours_charged`, and the interval's FMLA charge is the smaller of `hours_taken` and that FMLA remaining."
        PRD §3.6: "the PFL remaining is the larger of zero and the employee's state-specific PFL quota — ...200 for `RI`,...— minus the case's pre-existing `pfl_hours_charged`, and the interval's PFL charge is the smaller of the FMLA charge just computed and that PFL remaining."

        Design: Difficulty/combinatorial_formula/pool_charge_three_input_nonlinear_min_with_state_branch
        """
        bundle = setup_approved_case(
            employer_state="RI",
            employee_home_state="RI",
            qualifying_reason="OWN_SERIOUS_HEALTH_CONDITION",
            leave_type="CONTINUOUS",
            requested_start_at="2026-06-01T00:00:00.000Z",
            requested_end_at="2026-08-15T00:00:00.000Z",
            cert_expected_duration_weeks=10,
        )
        # Seed 150 historic hours of FMLA and PFL onto this case.
        seed_historic_interval(
            bundle.case["id"],
            "2026-04-01T00:00:00.000Z",
            "2026-04-30T00:00:00.000Z",
            150,
            150,
            150,
        )
        set_clock("2026-06-01T00:00:00.000Z")
        interval = record_interval(
            bundle.case["id"],
            "2026-06-01T00:00:00.000Z",
            "2026-06-15T00:00:00.000Z",
            80,
        )
        # FMLA: min(80, 480-150=330) = 80.
        assert interval["fmla_hours_charged"] == 80, (
            f"FMLA charge must be min(80, 330) = 80; got {interval['fmla_hours_charged']!r}"
        )
        # PFL: min(fmla_charge=80, pfl_remaining=200-150=50) = 50.
        assert interval["pfl_hours_charged"] == 50, (
            f"PFL charge must be min(fmla_charge=80, pfl_remaining=50) = 50; got {interval['pfl_hours_charged']!r}"
        )

    def test_ri_pool_charge_subsequent_interval_pfl_zero_at_quota(self, api):
        """PRD §3.6: "the PFL remaining is the larger of zero and the employee's state-specific PFL quota — ...200 for `RI`,...— minus the case's pre-existing `pfl_hours_charged`, and the interval's PFL charge is the smaller of the FMLA charge just computed and that PFL remaining."

        Design: Difficulty/combinatorial_formula/pool_charge_three_input_nonlinear_min_with_state_branch
        """
        # After the first interval brings case pfl_hours_charged exactly to 200,
        # the next interval must charge pfl=0 since pfl_remaining=max(0, 200-200)=0.
        bundle = setup_approved_case(
            employer_state="RI",
            employee_home_state="RI",
            qualifying_reason="OWN_SERIOUS_HEALTH_CONDITION",
            leave_type="CONTINUOUS",
            requested_start_at="2026-06-01T00:00:00.000Z",
            requested_end_at="2026-08-15T00:00:00.000Z",
            cert_expected_duration_weeks=10,
        )
        seed_historic_interval(
            bundle.case["id"],
            "2026-04-01T00:00:00.000Z",
            "2026-04-30T00:00:00.000Z",
            150,
            150,
            150,
        )
        set_clock("2026-06-01T00:00:00.000Z")
        # First interval brings pfl to exactly 200.
        record_interval(
            bundle.case["id"],
            "2026-06-01T00:00:00.000Z",
            "2026-06-15T00:00:00.000Z",
            80,
        )
        second = record_interval(
            bundle.case["id"],
            "2026-06-15T00:00:00.000Z",
            "2026-06-22T00:00:00.000Z",
            40,
        )
        # FMLA: min(40, 480 - (150+80)) = min(40, 250) = 40.
        assert second["fmla_hours_charged"] == 40
        # PFL: min(40, 200 - 200) = 0.
        assert second["pfl_hours_charged"] == 0, (
            f"PFL must be 0 after RI quota of 200 is exhausted; got {second['pfl_hours_charged']!r}"
        )
