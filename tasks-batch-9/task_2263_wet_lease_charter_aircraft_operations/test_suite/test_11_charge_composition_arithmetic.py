"""Composition arithmetic: nesting order, rounding order and which figure keys a tier.

Each scenario below is built so that only one composition of the PRD's min/max, cap,
floor, per-leg rounding and tier-selection rules reproduces every figure at once.
"""

import pytest

from test_helpers import (
    TEST_USERS,
    assert_deposit_conservation,
    assert_gross_charge_composition,
    cancel_leg,
    file_reliability_report,
    fly_leg,
    get_success_data,
    inspect_return_payload,
    schedule_leg,
    setup_active_lease,
    setup_terminating_lease,
    validate_success,
)

OPS = TEST_USERS["lessor_ops_headers"]
BILLING = TEST_USERS["billing_admin_headers"]
TECH = TEST_USERS["maintenance_controller_headers"]


def _terminating_lease_with_tight_liability_cap(api) -> dict:
    """TERMINATING lease whose redelivery bargain caps discrepancy liability at
    400,000 cents while holding a 500,000-cent maintenance reserve deposit.
    """
    return setup_terminating_lease(
        api, lease_overrides={"return_liability_cap_cents": 400000}
    )


def _inspect_over_returned_airframe(api, return_id: str):
    """Record a redelivery inspection 55.50 hours over, 18 cycles over and 400 kg short,
    with one discrepancy code noted on the airframe.
    """
    return api.inspect_return_condition(
        return_id,
        inspect_return_payload(355.50, 138, 3600, ["AIRFRAME_HOURS_OVER"]),
        TECH,
    )


def _month_of_three_hundred_minutes_flown_in_three_legs(api) -> dict:
    """ACTIVE lease over 2026-09 with three completed 100-minute REVENUE legs."""
    scenario = setup_active_lease(api)
    for scheduled_out, scheduled_in, dest in (
        ("2026-09-10T06:00:00Z", "2026-09-10T07:40:00Z", "LEPA"),
        ("2026-09-11T06:00:00Z", "2026-09-11T07:40:00Z", "LFPG"),
        ("2026-09-12T06:00:00Z", "2026-09-12T07:40:00Z", "EIDW"),
    ):
        fly_leg(
            api,
            scenario,
            scheduled_out=scheduled_out,
            scheduled_in=scheduled_in,
            technical_delay_minutes=0,
            dest_icao=dest,
        )
    return scenario


def _month_landing_exactly_on_the_penalty_tier_boundary(api) -> dict:
    """ACTIVE lease on the SCHEDULED reliability basis whose month grosses exactly
    5,000,000 cents, with an ACCEPTED report reporting 50.00 percent reliability.

    One completed 600-minute REVENUE leg meets the ten-hour guarantee exactly; one
    lessor technical cancellation halves the scheduled-basis reliability figure.
    """
    scenario = setup_active_lease(
        api,
        lease_overrides={
            "block_hour_rate_usd_cents": 500000,
            "min_guaranteed_block_hours_per_month": 10,
            "reliability_basis": "SCHEDULED",
        },
    )
    fly_leg(
        api,
        scenario,
        scheduled_out="2026-09-14T06:00:00Z",
        scheduled_in="2026-09-14T16:00:00Z",
        technical_delay_minutes=0,
        dest_icao="LEPA",
    )
    cancelled = schedule_leg(
        api,
        scenario,
        scheduled_out="2026-09-16T06:00:00Z",
        scheduled_in="2026-09-16T08:00:00Z",
        dest_icao="EIDW",
    )
    cancel_leg(api, cancelled["id"], cancelling_party="LESSOR", cancel_reason="TECHNICAL")
    scenario["report"] = file_reliability_report(
        api, scenario, period_month="2026-09", decision="ACCEPT"
    )
    return scenario


class TestReturnDiscrepancyNesting:
    def test_inspection_caps_the_raw_exposure_before_the_minimum_fee_floor(self, api):
        """PRD §3.10: The hours overrun is the amount by which `hours_since_check_at_return` exceeds the lease's `return_hours_since_check_max`, floored at zero.
        PRD §3.10: The airframe component is the hours overrun multiplied by a rate of 2,500 cents (USD 25.00) per hour over, rounded half up to whole cents — this being the only one of the three that needs rounding, since the other two multiply integers.
        PRD §3.10: The cycles component is the cycles overrun multiplied by a rate of 18,000 cents (USD 180.00) per cycle over.
        PRD §3.10: The fuel component is the fuel shortfall multiplied by a rate of 95 cents per kilogram short.
        PRD §3.10: Their raw sum is then capped at the lease's `return_liability_cap_cents`.
        PRD §3.10: Otherwise `discrepancy_cost_cents` is the greater of the capped sum and a minimum discrepancy fee of 250,000 cents (USD 2,500.00) — a recorded discrepancy code always attracts at least that minimum, even when nothing measurable was over.
        PRD §3.10: `return_deposit_applied_cents` on the lease becomes the lesser of `discrepancy_cost_cents` and the lease's full `return_deposit_cents`; `return_deposit_remaining_cents` becomes `return_deposit_cents` less that applied figure; and `billed_to_lessee_cents` on the return record becomes `discrepancy_cost_cents` less the applied figure.

        Design: Difficulty/combinatorial_formula/return_discrepancy_nested_cap_then_minimum_fee
        """
        scenario = _terminating_lease_with_tight_liability_cap(api)

        record = validate_success(
            _inspect_over_returned_airframe(api, scenario["return_condition"]["id"]), 200
        )

        assert record["discrepancy_cost_cents"] == 400000, (
            "the 500,750-cent raw sum of the airframe, cycles and fuel components is "
            "capped at the 400,000-cent liability cap, and the 250,000-cent minimum fee "
            "floor then applies to that capped figure"
        )
        assert record["billed_to_lessee_cents"] == 0, (
            "the 500,000-cent deposit fully absorbs a 400,000-cent discrepancy cost, so "
            "nothing is billed onward to the lessee"
        )

    def test_inspection_draws_the_deposit_waterfall_from_the_full_original_deposit(
        self, api
    ):
        """PRD §3.10: A first inspection producing a non-empty `discrepancy_codes` array moves the record from `PENDING_INSPECTION` to `DISCREPANCIES_OPEN`.
        PRD §3.10: The waterfall always starts from the full original `return_deposit_cents` and never from the surviving remainder of an earlier inspection, which is what makes re-inspection safe and keeps the deposit invariant of §2.9 true at every step.
        PRD §2.9: On every lease, `return_deposit_applied_cents` plus `return_deposit_remaining_cents` equals `return_deposit_cents` at all times.
        PRD §3.10: Closure stores `repositioning_leg_id`, moves the record from `CLEARED` to the terminal `CLOSED`, and drives the lease from `TERMINATING` to the terminal `RETURNED`.

        Design: Difficulty/combinatorial_formula/return_discrepancy_nested_cap_then_minimum_fee
        """
        scenario = _terminating_lease_with_tight_liability_cap(api)

        record = validate_success(
            _inspect_over_returned_airframe(api, scenario["return_condition"]["id"]), 200
        )

        assert record["status"] == "DISCREPANCIES_OPEN", (
            "a first inspection recording a discrepancy code opens the discrepancies"
        )

        lease = get_success_data(api.get_lease(scenario["lease"]["id"], OPS))
        assert lease["return_deposit_applied_cents"] == 400000, (
            "the applied deposit is the lesser of the 400,000-cent discrepancy cost and "
            "the full 500,000-cent deposit"
        )
        assert lease["return_deposit_remaining_cents"] == 100000, (
            "the remaining deposit is the full 500,000-cent deposit less the 400,000 applied"
        )
        assert_deposit_conservation(lease)
        assert lease["status"] == "TERMINATING", (
            "only closure of the return record moves the lease out of TERMINATING"
        )


class TestCreditedHoursRoundingOrder:
    def test_close_rounds_each_leg_to_four_decimals_before_summing_them(self, api):
        """PRD §2.5: **Round per leg, then sum.** When a month's credited hours are built from individual legs, each leg's minute contribution is converted to hours and rounded to four decimal places *first*, and the rounded per-leg figures are then added together.
        PRD §2.5: This is deliberately not "add the minutes, then divide once": three legs of 100 minutes each yield 1.6667 hours apiece and 5.0001 hours in total, where a single division would have yielded 5.0000 hours.
        PRD §3.8: Each included leg's minute contribution is divided by 60 and rounded half up to four decimal places *first*; `credited_hours` is the sum of those rounded per-leg figures.
        PRD §3.8: `credited_block_minutes` is separately the plain sum of the same per-leg minute contributions, in whole minutes.
        PRD §3.8: Otherwise `shortfall_hours` is 0 and `overrun_hours` is `credited_hours` less `mgh_effective_hours`, rounded half up to four decimal places — so a month landing exactly on the guarantee produces neither.

        Design: Difficulty/combinatorial_formula/credited_hours_rounded_per_leg_then_summed
        """
        scenario = _month_of_three_hundred_minutes_flown_in_three_legs(api)

        period = validate_success(
            api.close_utilization_period(scenario["period"]["id"], BILLING), 200
        )

        assert period["credited_block_minutes"] == 300, (
            "the plain minute sum of three 100-minute legs is 300 whole minutes"
        )
        assert period["credited_hours"] == pytest.approx(5.0001, abs=0.0001), (
            "each leg rounds to 1.6667 hours before summation, so the month credits 5.0001 "
            "hours rather than the 5.0000 a single division would have produced"
        )
        assert period["mgh_effective_hours"] == pytest.approx(5.0000, abs=0.0001), (
            "a lease covering the whole of 2026-09 carries its full 5-hour guarantee"
        )
        assert period["shortfall_hours"] == pytest.approx(0.0000, abs=0.0001), (
            "credited hours are not strictly less than the guarantee, so there is no shortfall"
        )
        assert period["overrun_hours"] == pytest.approx(0.0001, abs=0.0001), (
            "the per-leg rounding residue leaves 0.0001 hours of overrun above the guarantee"
        )

    def test_close_charges_the_rounding_residue_as_tier_one_overrun(self, api):
        """PRD §3.8: `base_charge_cents` is `mgh_effective_hours` multiplied by the lease's `block_hour_rate_usd_cents`, rounded half up to whole cents.
        PRD §3.8: The first tier's hours are the lesser of `overrun_hours` and the first tier width.
        PRD §3.8: Each tier's hours are multiplied by the block-hour rate and by that tier's multiplier — 1.00 for the first tier, 1.15 for the second, and 1.35 for the third — and each of the three products is rounded half up to whole cents *individually*; `overrun_charge_cents` is the sum of those three rounded figures.
        PRD §2.5: **Round each cents component, then sum.** The base guarantee charge, the shortfall credit, and each of the three overrun tier components are each rounded to whole cents *before* they are added together.
        PRD §3.8: `gross_charge_cents` is `base_charge_cents` less `shortfall_credit_cents` plus `overrun_charge_cents`.
        PRD §3.8: `reliability_penalty_cents` is derived as described below, and the net charge is `gross_charge_cents` less `reliability_penalty_cents`.
        PRD §3.8: Under the `PROVISIONAL` variant that net figure is written to `provisional_charge_cents`; under the `FINAL` variant it is written to `final_charge_cents`.
        PRD §3.8: If no accepted report exists for the month, `reliability_penalty_cents` is 0 and no penalty applies.
        PRD §3.8: Closing recomputes every charge field under the `FINAL` variant, sets `variant_applied` to `FINAL`, writes `final_charge_cents`, and increments the period's `version`.
        PRD §3.8: The final variant runs when a period moves from `OPEN` to `PENDING_SETTLEMENT` and again when it moves from `REOPENED` to `PENDING_SETTLEMENT`, and is what a `FINAL` invoice draws on.

        Design: Difficulty/combinatorial_formula/credited_hours_rounded_per_leg_then_summed
        """
        scenario = _month_of_three_hundred_minutes_flown_in_three_legs(api)

        period = validate_success(
            api.close_utilization_period(scenario["period"]["id"], BILLING), 200
        )

        assert period["base_charge_cents"] == 2400000, (
            "the base guarantee charge is 5.0000 hours at 480,000 cents per block hour"
        )
        assert period["shortfall_credit_cents"] == 0, (
            "there is no shortfall, so no shortfall credit is due"
        )
        assert period["overrun_charge_cents"] == 48, (
            "0.0001 overrun hours fall wholly in the first tier at a 1.00 multiplier, "
            "giving 48 cents"
        )
        assert period["gross_charge_cents"] == 2400048, (
            "the gross charge is the base guarantee less no credit plus the 48-cent overrun"
        )
        assert_gross_charge_composition(period)
        assert period["reliability_penalty_cents"] == 0, (
            "no reliability report has been accepted for the month, so no penalty applies"
        )
        assert period["final_charge_cents"] == 2400048, (
            "the final net charge is the gross charge less a zero reliability penalty"
        )
        assert period["variant_applied"] == "FINAL", (
            "closing the month rewrites every charge field under the FINAL variant"
        )
        assert period["status"] == "PENDING_SETTLEMENT", (
            "a closed month awaits settlement"
        )


class TestReliabilityPenaltyTierKeying:
    def test_close_keys_the_penalty_tier_on_the_gross_charge_at_the_boundary(self, api):
        """PRD §3.8: The deficit factor is the amount by which the reliability figure falls short of 99.00, divided by 5.0, floored at zero and capped at 10.0, rounded half up to four decimal places — so every five percentage points of shortfall contributes one whole unit of deficit factor, and a report at or above 99.00 percent yields a factor of zero.
        PRD §3.8: The penalty rate is then chosen by tier on the **gross** charge, evaluated with strict comparisons: a `gross_charge_cents` below 5,000,000 cents (USD 50,000) attracts 2 percent, a gross charge below 25,000,000 cents (USD 250,000) attracts 3.5 percent, and anything at or above that attracts 5 percent.
        PRD §3.8: `reliability_penalty_cents` is `gross_charge_cents` multiplied by that rate and by the deficit factor, rounded half up to whole cents.
        PRD §3.8: The evaluation order here is contractual: the tier is keyed on `gross_charge_cents` as computed in step five, *before* any penalty is subtracted.
        PRD §3.8: The tier is never re-derived from the net figure and no fixed-point iteration is performed, even where subtracting the penalty would have pushed the net charge into a lower tier.
        PRD §3.8: `reliability_penalty_cents` is derived as described below, and the net charge is `gross_charge_cents` less `reliability_penalty_cents`.
        PRD §3.8: Under the `PROVISIONAL` variant that net figure is written to `provisional_charge_cents`; under the `FINAL` variant it is written to `final_charge_cents`.

        Design: Difficulty/combinatorial_formula/reliability_penalty_tier_keyed_on_gross_not_net
        """
        scenario = _month_landing_exactly_on_the_penalty_tier_boundary(api)

        period = validate_success(
            api.close_utilization_period(scenario["period"]["id"], BILLING), 200
        )

        assert period["gross_charge_cents"] == 5000000, (
            "ten credited hours at 500,000 cents each gross exactly 5,000,000 cents"
        )
        assert period["reliability_penalty_cents"] == 1715000, (
            "a gross charge of exactly 5,000,000 cents is not below the 5,000,000-cent "
            "boundary, so the 3.5 percent rate applies to a deficit factor of 9.8"
        )
        assert period["final_charge_cents"] == 3285000, (
            "the net charge is the 5,000,000-cent gross charge less the 1,715,000-cent penalty"
        )

    def test_close_prices_the_guarantee_and_report_that_feed_the_penalty(self, api):
        """PRD §3.8: `mgh_effective_hours` is the lease's `min_guaranteed_block_hours_per_month` multiplied by the number of covered days and divided by the number of calendar days in `period_month`, rounded half up to four decimal places.
        PRD §3.8: `base_charge_cents` is `mgh_effective_hours` multiplied by the lease's `block_hour_rate_usd_cents`, rounded half up to whole cents.
        PRD §3.8: Only legs whose `status` is `COMPLETED` count from the operational side, each contributing its `billable_block_minutes`.
        PRD §3.8: Separately, the lessor-cancelled hours of the month are the sum of `scheduled_block_minutes` over every leg of the month whose `status` is `CANCELLED_LESSOR`, divided by 60 and rounded half up to four decimal places; `lessor_attributable_shortfall_hours` is the lesser of `shortfall_hours` and that figure.
        PRD §3.8: `technical_dispatch_reliability_pct` is then set to `tdr_departure_basis_pct` when the lease's `reliability_basis` is `DEPARTURE`, and to `tdr_scheduled_basis_pct` when it is `SCHEDULED`.
        PRD §3.8: Acceptance moves the report from `SUBMITTED` to the terminal `ACCEPTED`, which both unblocks invoice approval for the same lease and month and feeds `technical_dispatch_reliability_pct` into the penalty on the next close.
        PRD §3.8: The penalty consumes the single `ReliabilityReport` for this lease and `period_month` whose `status` is `ACCEPTED`; when more than one such report exists, the one with the greatest `created_at` is used, and reports still `SUBMITTED` or already `REJECTED` are ignored entirely.

        Design: Difficulty/combinatorial_formula/reliability_penalty_tier_keyed_on_gross_not_net
        """
        scenario = _month_landing_exactly_on_the_penalty_tier_boundary(api)

        report = get_success_data(
            api.get_reliability_report(scenario["report"]["id"], TECH)
        )
        assert report["status"] == "ACCEPTED", (
            "the lessee accepted the report, so it feeds the penalty on the next close"
        )
        assert report["tdr_departure_basis_pct"] == pytest.approx(100.00, abs=0.01), (
            "the single departure carried no technical delay, so the departure basis is 100.00"
        )
        assert report["tdr_scheduled_basis_pct"] == pytest.approx(50.00, abs=0.01), (
            "one technical cancellation out of two published legs halves the scheduled basis"
        )
        assert report[
            "technical_dispatch_reliability_pct"
        ] == pytest.approx(50.00, abs=0.01), (
            "the lease's reliability_basis of SCHEDULED makes the scheduled basis binding"
        )

        period = validate_success(
            api.close_utilization_period(scenario["period"]["id"], BILLING), 200
        )

        assert period["credited_hours"] == pytest.approx(10.0000, abs=0.0001), (
            "the completed 600-minute leg credits ten hours and the lessor cancellation "
            "credits nothing"
        )
        assert period["mgh_effective_hours"] == pytest.approx(10.0000, abs=0.0001), (
            "a lease covering the whole of 2026-09 carries its full ten-hour guarantee"
        )
        assert period["shortfall_hours"] == pytest.approx(0.0000, abs=0.0001), (
            "a month landing exactly on the guarantee produces no shortfall"
        )
        assert period["overrun_hours"] == pytest.approx(0.0000, abs=0.0001), (
            "a month landing exactly on the guarantee produces no overrun"
        )
        assert period["base_charge_cents"] == 5000000, (
            "the base guarantee charge is 10.0000 hours at 500,000 cents per block hour"
        )
        assert period["variant_applied"] == "FINAL", (
            "closing the month rewrites every charge field under the FINAL variant"
        )
