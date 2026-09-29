"""Derived money: the monthly utilization charge, the redelivery discrepancy waterfall
and the server-side substitute selector.

Every figure asserted here is reproducible from the lease's commercial terms and the
legs actually flown, exactly as the PRD's pinned rounding order and tier boundaries
require.
"""

import pytest

from test_helpers import (
    TEST_USERS,
    add_substitute_candidate,
    assert_deposit_conservation,
    cancel_leg_payload,
    complete_leg_payload,
    create_substitution_payload,
    dispatch_leg,
    fly_leg,
    get_success_data,
    inspect_return_payload,
    record_maintenance_event,
    schedule_leg,
    setup_active_lease,
    setup_terminating_lease,
    validate_paginated,
    validate_success,
)

OPS = TEST_USERS["lessor_ops_headers"]
BILLING = TEST_USERS["billing_admin_headers"]
TECH = TEST_USERS["maintenance_controller_headers"]


# --------------------------------------------------------------------------- #
# Scenario builders                                                            #
# --------------------------------------------------------------------------- #


def _september_lease_with_dispatched_revenue_leg(api) -> dict:
    """ACTIVE lease over the whole of 2026-09 carrying one DISPATCHED revenue leg.

    The leg is scheduled 06:00:00Z-08:35:30Z (155 scheduled block minutes) and went
    off-blocks ten minutes late, so closing it out on 08:35:00Z books 145 block minutes.
    """
    scenario = setup_active_lease(api)
    scenario["leg"] = schedule_leg(
        api,
        scenario,
        scheduled_out="2026-09-08T06:00:00Z",
        scheduled_in="2026-09-08T08:35:30Z",
    )
    dispatch_leg(api, scenario["leg"]["id"], "2026-09-08T06:10:00Z")
    return scenario


def _september_lease_with_completed_scheduled_and_ferry_legs(api) -> dict:
    """ACTIVE lease over 2026-09 carrying three legs with three include-set outcomes:

    a COMPLETED revenue leg billing 145 minutes, a still-SCHEDULED revenue leg carrying
    120 scheduled minutes, and a COMPLETED maintenance ferry that flew 155 block minutes.
    """
    scenario = setup_active_lease(api)
    fly_leg(
        api,
        scenario,
        scheduled_out="2026-09-08T06:00:00Z",
        scheduled_in="2026-09-08T08:35:30Z",
        actual_out="2026-09-08T06:10:00Z",
        actual_in="2026-09-08T08:35:00Z",
    )
    scenario["scheduled_leg"] = schedule_leg(
        api,
        scenario,
        scheduled_out="2026-09-12T06:00:00Z",
        scheduled_in="2026-09-12T08:00:00Z",
    )
    scenario["ferry_leg"] = fly_leg(
        api,
        scenario,
        scheduled_out="2026-09-15T06:00:00Z",
        scheduled_in="2026-09-15T08:35:30Z",
        leg_class="MAINTENANCE_FERRY",
        dest_icao="EGGW",
    )
    return scenario


def _september_lease_with_seven_hour_month(api) -> dict:
    """ACTIVE lease over 2026-09 whose single completed leg flew 420 block minutes,
    putting credited hours at exactly 7.0000 against a 5.0000-hour guarantee."""
    scenario = setup_active_lease(api)
    fly_leg(
        api,
        scenario,
        scheduled_out="2026-09-10T06:00:00Z",
        scheduled_in="2026-09-10T13:00:00Z",
    )
    return scenario


def _terminating_lease_awaiting_inspection(api) -> dict:
    """Lease driven to TERMINATING with its PENDING_INSPECTION return record, carrying
    the drafted ceilings of 300.00 hours, 120 cycles and 4,000 kg of fuel, a liability
    cap of 900,000 cents and a maintenance reserve deposit of 500,000 cents."""
    scenario = setup_terminating_lease(api)
    rows, _meta = validate_paginated(
        api.list_return_conditions(TECH, {"lease_id": scenario["lease"]["id"]})
    )
    assert len(rows) == 1, "termination opens exactly one return record on the lease"
    scenario["return_condition"] = rows[0]
    return scenario


def _active_lease_with_eight_substitute_candidates(api) -> dict:
    """ACTIVE lease on the 189-seat B738 G-ACMI, plus nine further airframes registered
    in a fixed order so that only one of them can win the ranking.

    G-SUBY and G-SUBW tie on both the seat-delta and the hours-since-check keys and are
    separated only by registration order; the last five candidates each fail exactly one
    eligibility test.
    """
    scenario = setup_active_lease(api)
    scenario["subx"] = add_substitute_candidate(
        api,
        tail_number="G-SUBX",
        airframe_hours_total=30000.00,
        hours_since_last_check=150.00,
        cycles_since_last_check=50,
    )
    scenario["subz"] = add_substitute_candidate(
        api,
        tail_number="G-SUBZ",
        type_designator="B737",
        seat_count=186,
        mtow_kg=70000,
        airframe_hours_total=31000.00,
        hours_since_last_check=10.00,
        cycles_since_last_check=4,
    )
    scenario["suby"] = add_substitute_candidate(
        api,
        tail_number="G-SUBY",
        type_designator="B739",
        mtow_kg=85000,
        airframe_hours_total=12000.00,
        hours_since_last_check=90.00,
        cycles_since_last_check=20,
    )
    scenario["subw"] = add_substitute_candidate(
        api,
        tail_number="G-SUBW",
        airframe_hours_total=15000.00,
        hours_since_last_check=90.00,
        cycles_since_last_check=20,
    )
    scenario["subv"] = add_substitute_candidate(
        api,
        tail_number="G-SUBV",
        airframe_hours_total=40000.00,
        hours_since_last_check=420.00,
        cycles_since_last_check=130,
    )
    scenario["subu"] = add_substitute_candidate(
        api,
        tail_number="G-SUBU",
        type_designator="B737",
        seat_count=183,
        mtow_kg=66000,
        airframe_hours_total=9000.00,
        hours_since_last_check=5.00,
        cycles_since_last_check=2,
    )
    scenario["subm"] = add_substitute_candidate(
        api,
        tail_number="G-SUBM",
        maintenance_program_ref="MP-B738-REV11",
        airframe_hours_total=8000.00,
        hours_since_last_check=5.00,
        cycles_since_last_check=2,
    )
    scenario["subi"] = add_substitute_candidate(
        api,
        tail_number="G-SUBI",
        airframe_hours_total=7000.00,
        hours_since_last_check=5.00,
        cycles_since_last_check=2,
    )
    scenario["suba"] = add_substitute_candidate(
        api,
        tail_number="G-SUBA",
        type_designator="A321",
        type_family="A320",
        seat_count=220,
        mtow_kg=93000,
        airframe_hours_total=6000.00,
        hours_since_last_check=5.00,
        cycles_since_last_check=2,
    )
    record_maintenance_event(
        api, scenario["subi"]["id"], "GROUND_SCHEDULED", note="C-check"
    )
    scenario["lease"] = get_success_data(api.get_lease(scenario["lease"]["id"], OPS))
    return scenario


class TestMonthlyUtilizationCharge:
    def test_completed_revenue_leg_credits_the_open_month_at_four_decimal_hours(self, api):
        """PRD §3.6: It advances `status` from `DISPATCHED` to `COMPLETED`, stores `actual_in` and the optionally supplied `technical_delay_minutes` (a non-negative count of departure-delay minutes attributable to a technical defect, defaulting to 0), and writes `block_minutes` as the whole number of minutes between `actual_out` and `actual_in` with the remaining seconds discarded.
        PRD §3.6: A `REVENUE` leg is subject to a minimum billable block of one hour: if `block_minutes` is at least 60 the billable figure is `block_minutes` itself, and otherwise it is 60.
        PRD §3.8: `mgh_effective_hours` is the lease's `min_guaranteed_block_hours_per_month` multiplied by the number of covered days and divided by the number of calendar days in `period_month`, rounded half up to four decimal places.
        PRD §3.8: Each included leg's minute contribution is divided by 60 and rounded half up to four decimal places *first*; `credited_hours` is the sum of those rounded per-leg figures.
        PRD §3.8: `credited_block_minutes` is separately the plain sum of the same per-leg minute contributions, in whole minutes.
        PRD §3.8: When `credited_hours` is strictly less than `mgh_effective_hours`, `shortfall_hours` is their difference rounded half up to four decimal places and `overrun_hours` is 0.
        PRD §3.8: Separately, the lessor-cancelled hours of the month are the sum of `scheduled_block_minutes` over every leg of the month whose `status` is `CANCELLED_LESSOR`, divided by 60 and rounded half up to four decimal places; `lessor_attributable_shortfall_hours` is the lesser of `shortfall_hours` and that figure.
        PRD §3.8: `base_charge_cents` is `mgh_effective_hours` multiplied by the lease's `block_hour_rate_usd_cents`, rounded half up to whole cents.
        PRD §3.8: `shortfall_credit_cents` is `lessor_attributable_shortfall_hours` multiplied by that same rate and by the lease's `shortfall_credit_pct`, rounded half up to whole cents.
        PRD §3.8: `gross_charge_cents` is `base_charge_cents` less `shortfall_credit_cents` plus `overrun_charge_cents`.
        PRD §3.8: If no accepted report exists for the month, `reliability_penalty_cents` is 0 and no penalty applies.

        Design: Corner/calculations/completed_revenue_leg_credits_the_period_at_four_decimal_hours
        """
        scenario = _september_lease_with_dispatched_revenue_leg(api)

        completed = validate_success(
            api.complete_flight_leg(
                scenario["leg"]["id"],
                complete_leg_payload("2026-09-08T08:35:00Z"),
                OPS,
            ),
            200,
        )

        assert completed["status"] == "COMPLETED", (
            "closing out a DISPATCHED leg must advance its status to COMPLETED"
        )
        assert completed["block_minutes"] == 145, (
            "06:10:00Z to 08:35:00Z is 145 whole minutes of block time"
        )
        assert completed["billable_block_minutes"] == 145, (
            "a revenue leg above the one-hour floor bills its own 145 block minutes"
        )

        period = validate_success(
            api.get_utilization_period(scenario["period"]["id"], BILLING), 200
        )

        assert period["mgh_effective_hours"] == pytest.approx(5.0000, abs=0.0001), (
            "the lease term covers all 30 days of 2026-09, so the full 5-hour guarantee "
            "applies without proration"
        )
        assert period["credited_block_minutes"] == 145, (
            "credited_block_minutes is the plain sum of the per-leg minute contributions"
        )
        assert period["credited_hours"] == pytest.approx(2.4167, abs=0.0001), (
            "145 minutes divided by 60 rounds half up to 2.4167 hours, not 2.4166 and "
            "not 2.42"
        )
        assert period["shortfall_hours"] == pytest.approx(2.5833, abs=0.0001), (
            "credited hours of 2.4167 fall short of the 5.0000-hour guarantee by 2.5833"
        )
        assert period["lessor_attributable_shortfall_hours"] == pytest.approx(
            0.0000, abs=0.0001
        ), (
            "no leg of the month was cancelled by the lessor, so none of the shortfall "
            "hours are lessor-attributable"
        )
        assert period["overrun_hours"] == pytest.approx(0.0000, abs=0.0001), (
            "a month below its guarantee produces shortfall hours and no overrun"
        )
        assert period["base_charge_cents"] == 2400000, (
            "the base guarantee charge is 5.0000 hours at 480,000 cents per block hour"
        )
        assert period["shortfall_credit_cents"] == 0, (
            "the credit is priced on lessor-attributable shortfall hours only, which "
            "are 0 here, so the lessee still pays the full guarantee"
        )
        assert period["overrun_charge_cents"] == 0, (
            "there are no overrun hours to charge in any tier"
        )
        assert period["gross_charge_cents"] == 2400000, (
            "the gross charge is 2,400,000 cents of base guarantee less a zero credit "
            "plus a zero overrun charge"
        )
        assert period["reliability_penalty_cents"] == 0, (
            "no reliability report has been accepted for the month, so no penalty applies"
        )
        assert period["provisional_charge_cents"] == 2400000, (
            "the provisional net charge is the gross charge less a zero penalty"
        )
        assert period["variant_applied"] == "PROVISIONAL", (
            "the leg completion recomputed the open month under the provisional variant"
        )

    def test_settlement_preview_reports_both_variants_without_touching_the_period(self, api):
        """PRD §3.8: A non-mutating computed read evaluates both variants side by side without persisting anything.
        PRD §3.8: It returns `period_id`, `period_month`, `mgh_effective_hours`, `provisional_credited_hours`, `provisional_gross_charge_cents`, `final_credited_hours`, `final_shortfall_hours`, `final_overrun_hours`, `final_gross_charge_cents`, `reliability_penalty_cents` and `projected_final_charge_cents`.
        PRD §3.8: Under the `FINAL` variant the include-set is narrower in one respect and wider in another.
        PRD §3.8: Only legs whose `status` is `COMPLETED` count from the operational side, each contributing its `billable_block_minutes`.
        PRD §3.8: When `credited_hours` is strictly less than `mgh_effective_hours`, `shortfall_hours` is their difference rounded half up to four decimal places and `overrun_hours` is 0.
        PRD §2.4: `version` (integer): an integer that starts at 1 and increments by 1 on every mutation of the resource.

        Design: Corner/calculations/completed_revenue_leg_credits_the_period_at_four_decimal_hours
        """
        scenario = _september_lease_with_dispatched_revenue_leg(api)
        get_success_data(
            api.complete_flight_leg(
                scenario["leg"]["id"],
                complete_leg_payload("2026-09-08T08:35:00Z"),
                OPS,
            )
        )
        period_id = scenario["period"]["id"]
        before = get_success_data(api.get_utilization_period(period_id, BILLING))

        preview = validate_success(api.get_settlement_preview(period_id, BILLING), 200)

        assert preview["mgh_effective_hours"] == pytest.approx(5.0000, abs=0.0001), (
            "the preview prorates the guarantee over the same fully covered month"
        )
        assert preview["provisional_credited_hours"] == pytest.approx(
            2.4167, abs=0.0001
        ), "the provisional variant credits the completed leg's 145 billable minutes"
        assert preview["provisional_gross_charge_cents"] == 2400000, (
            "the provisional gross charge is the bare 2,400,000-cent guarantee"
        )
        assert preview["final_credited_hours"] == pytest.approx(2.4167, abs=0.0001), (
            "the final variant counts the same completed leg's billable_block_minutes"
        )
        assert preview["final_shortfall_hours"] == pytest.approx(2.5833, abs=0.0001), (
            "the final variant is also 2.5833 hours short of the guarantee"
        )
        assert preview["final_overrun_hours"] == pytest.approx(0.0000, abs=0.0001), (
            "neither variant exceeds the guarantee, so there is no overrun"
        )
        assert preview["final_gross_charge_cents"] == 2400000, (
            "the final gross charge is the bare 2,400,000-cent guarantee"
        )
        assert preview["reliability_penalty_cents"] == 0, (
            "no accepted reliability report exists for the month"
        )
        assert preview["projected_final_charge_cents"] == 2400000, (
            "the projected final charge is the final gross charge less a zero penalty"
        )

        after = get_success_data(api.get_utilization_period(period_id, BILLING))
        assert after["status"] == "OPEN", (
            "the preview persists nothing, so the period is still OPEN"
        )
        assert after["version"] == before["version"], (
            "the preview is non-mutating, so the period's version must not advance"
        )
        assert after["variant_applied"] == "PROVISIONAL", (
            "evaluating the final variant inside a preview must not rewrite "
            "variant_applied"
        )

    def test_ferry_and_scheduled_legs_are_filtered_by_class_not_by_state(self, api):
        """PRD §3.6: A `MAINTENANCE_FERRY` leg is never billable and takes 0.
        PRD §3.8: Under the `PROVISIONAL` variant the include-set is every leg of the lease whose `scheduled_out` falls inside `period_month` and whose `status` is `SCHEDULED`, `DISPATCHED` or `COMPLETED`.
        PRD §3.8: A `COMPLETED` leg contributes its `billable_block_minutes`.
        PRD §3.8: A leg not yet completed contributes its `scheduled_block_minutes`, with the same one-hour minimum billable floor applied when its `leg_class` is `REVENUE` and with 0 contributed when its `leg_class` is `MAINTENANCE_FERRY`.
        PRD §3.8: Each included leg's minute contribution is divided by 60 and rounded half up to four decimal places *first*; `credited_hours` is the sum of those rounded per-leg figures.
        PRD §3.8: Separately, the lessor-cancelled hours of the month are the sum of `scheduled_block_minutes` over every leg of the month whose `status` is `CANCELLED_LESSOR`, divided by 60 and rounded half up to four decimal places; `lessor_attributable_shortfall_hours` is the lesser of `shortfall_hours` and that figure.

        Design: Corner/calculations/cancelled_lessor_and_ferry_legs_leave_the_credited_hour_include_set
        """
        scenario = _september_lease_with_completed_scheduled_and_ferry_legs(api)

        period = validate_success(
            api.get_utilization_period(scenario["period"]["id"], BILLING), 200
        )

        assert period["credited_block_minutes"] == 265, (
            "the month credits the completed leg's 145 billable minutes plus the "
            "still-SCHEDULED revenue leg's 120 scheduled minutes, and nothing at all "
            "for the maintenance ferry"
        )
        assert period["credited_hours"] == pytest.approx(4.4167, abs=0.0001), (
            "2.4167 hours from the completed leg plus 2.0000 from the scheduled leg, "
            "each rounded before they are added"
        )
        assert period["shortfall_hours"] == pytest.approx(0.5833, abs=0.0001), (
            "4.4167 credited hours fall 0.5833 short of the 5.0000-hour guarantee"
        )
        assert period["lessor_attributable_shortfall_hours"] == pytest.approx(
            0.0000, abs=0.0001
        ), "no leg of the month is CANCELLED_LESSOR yet"
        assert period["shortfall_credit_cents"] == 0, (
            "with no lessor-attributable shortfall hours the credit is zero"
        )
        assert period["gross_charge_cents"] == 2400000, (
            "the gross charge is the bare 2,400,000-cent guarantee"
        )

        ferry = validate_success(
            api.get_flight_leg(scenario["ferry_leg"]["id"], OPS), 200
        )
        assert ferry["block_minutes"] == 155, (
            "the ferry really flew 155 whole minutes of block time"
        )
        assert ferry["billable_block_minutes"] == 0, (
            "a MAINTENANCE_FERRY leg is never billable whatever it flew"
        )

    def test_lessor_cancellation_removes_credited_hours_and_raises_the_credit(self, api):
        """PRD §3.6: A `SCHEDULED` leg cancelled by the lessee moves to `CANCELLED_LESSEE`; cancelled by the lessor it moves to `CANCELLED_LESSOR`.
        PRD §3.6: A lessor cancellation additionally raises the month's lessor-attributable shortfall.
        PRD §3.8: Cancelled and diverted legs contribute nothing at all, so no lessee-cancellation credit ever appears in a provisional figure.
        PRD §3.8: Separately, the lessor-cancelled hours of the month are the sum of `scheduled_block_minutes` over every leg of the month whose `status` is `CANCELLED_LESSOR`, divided by 60 and rounded half up to four decimal places; `lessor_attributable_shortfall_hours` is the lesser of `shortfall_hours` and that figure.
        PRD §3.8: `shortfall_credit_cents` is `lessor_attributable_shortfall_hours` multiplied by that same rate and by the lease's `shortfall_credit_pct`, rounded half up to whole cents.
        PRD §3.8: `gross_charge_cents` is `base_charge_cents` less `shortfall_credit_cents` plus `overrun_charge_cents`.

        Design: Corner/calculations/cancelled_lessor_and_ferry_legs_leave_the_credited_hour_include_set
        """
        scenario = _september_lease_with_completed_scheduled_and_ferry_legs(api)

        cancelled = validate_success(
            api.cancel_flight_leg(
                scenario["scheduled_leg"]["id"],
                cancel_leg_payload("LESSOR", "TECHNICAL"),
                OPS,
            ),
            200,
        )

        assert cancelled["status"] == "CANCELLED_LESSOR", (
            "a SCHEDULED leg cancelled by the lessor lands in CANCELLED_LESSOR"
        )
        assert cancelled["cancel_reason"] == "TECHNICAL", (
            "the supplied cancel_reason must be recorded on the leg"
        )

        period = validate_success(
            api.get_utilization_period(scenario["period"]["id"], BILLING), 200
        )

        assert period["credited_block_minutes"] == 145, (
            "the cancelled leg's 120 minutes leave the include-set entirely"
        )
        assert period["credited_hours"] == pytest.approx(2.4167, abs=0.0001), (
            "only the completed leg's 145 billable minutes remain credited"
        )
        assert period["shortfall_hours"] == pytest.approx(2.5833, abs=0.0001), (
            "credited hours of 2.4167 are 2.5833 short of the 5.0000-hour guarantee"
        )
        assert period["lessor_attributable_shortfall_hours"] == pytest.approx(
            2.0000, abs=0.0001
        ), (
            "the lessor cancelled 120 scheduled minutes, so 2.0000 of the 2.5833 "
            "shortfall hours are lessor-attributable"
        )
        assert period["base_charge_cents"] == 2400000, (
            "the base guarantee charge is unaffected by the cancellation"
        )
        assert period["shortfall_credit_cents"] == 576000, (
            "2.0000 lessor-attributable hours at 480,000 cents and a 0.60 credit share "
            "give a 576,000-cent credit"
        )
        assert period["overrun_charge_cents"] == 0, (
            "a month below its guarantee has no overrun to charge"
        )
        assert period["gross_charge_cents"] == 1824000, (
            "the gross charge is 2,400,000 less the 576,000-cent credit"
        )
        assert period["provisional_charge_cents"] == 1824000, (
            "the provisional net charge is the gross charge less a zero penalty"
        )

    def test_overrun_charge_walks_all_three_tier_multipliers_on_close(self, api):
        """PRD §3.8: Otherwise `shortfall_hours` is 0 and `overrun_hours` is `credited_hours` less `mgh_effective_hours`, rounded half up to four decimal places — so a month landing exactly on the guarantee produces neither.
        PRD §3.8: The first tier is 10 percent of `mgh_effective_hours`, rounded half up to four decimal places; the second tier is 15 percent of `mgh_effective_hours`, likewise rounded to four decimal places.
        PRD §3.8: The first tier's hours are the lesser of `overrun_hours` and the first tier width.
        PRD §3.8: The second tier's hours are the lesser of the second tier width and whatever remains of `overrun_hours` after the first tier width is removed, floored at zero.
        PRD §3.8: The third tier's hours are whatever remains of `overrun_hours` after both tier widths are removed, floored at zero.
        PRD §3.8: Each tier's hours are multiplied by the block-hour rate and by that tier's multiplier — 1.00 for the first tier, 1.15 for the second, and 1.35 for the third — and each of the three products is rounded half up to whole cents *individually*; `overrun_charge_cents` is the sum of those three rounded figures.
        PRD §3.8: Closing recomputes every charge field under the `FINAL` variant, sets `variant_applied` to `FINAL`, writes `final_charge_cents`, and increments the period's `version`.

        Design: Corner/calculations/overrun_charge_walks_all_three_tier_multipliers
        """
        scenario = _september_lease_with_seven_hour_month(api)
        period_id = scenario["period"]["id"]
        before = get_success_data(api.get_utilization_period(period_id, BILLING))

        closed = validate_success(api.close_utilization_period(period_id, BILLING), 200)

        assert closed["status"] == "PENDING_SETTLEMENT", (
            "closing an OPEN month moves it to PENDING_SETTLEMENT"
        )
        assert closed["variant_applied"] == "FINAL", (
            "the close rewrites the charge fields under the final variant"
        )
        assert closed["mgh_effective_hours"] == pytest.approx(5.0000, abs=0.0001), (
            "the lease covers the whole month, so the guarantee is not prorated"
        )
        assert closed["credited_block_minutes"] == 420, (
            "the single completed leg contributes all 420 of its billable minutes"
        )
        assert closed["credited_hours"] == pytest.approx(7.0000, abs=0.0001), (
            "420 minutes divided by 60 is exactly 7.0000 hours"
        )
        assert closed["shortfall_hours"] == pytest.approx(0.0000, abs=0.0001), (
            "credited hours above the guarantee produce no shortfall"
        )
        assert closed["overrun_hours"] == pytest.approx(2.0000, abs=0.0001), (
            "7.0000 credited hours exceed the 5.0000-hour guarantee by 2.0000"
        )
        assert closed["base_charge_cents"] == 2400000, (
            "the base guarantee charge is 5.0000 hours at 480,000 cents"
        )
        assert closed["shortfall_credit_cents"] == 0, (
            "an overrun month has no shortfall to credit"
        )
        assert closed["overrun_charge_cents"] == 1140000, (
            "0.5000 hours at 1.00 gives 240,000, the 0.7500-hour second tier at 1.15 "
            "gives 414,000 and the remaining 0.7500 hours at 1.35 give 486,000, each "
            "rounded individually before they are summed"
        )
        assert closed["gross_charge_cents"] == 3540000, (
            "the gross charge is the 2,400,000-cent base plus 1,140,000 of overrun"
        )
        assert closed["reliability_penalty_cents"] == 0, (
            "no reliability report exists for the month, so no penalty applies"
        )
        assert closed["final_charge_cents"] == 3540000, (
            "the final net charge is the gross charge less a zero penalty"
        )
        assert closed["version"] == before["version"] + 1, (
            "closing the month increments the period's version by exactly one"
        )


class TestRedeliveryDiscrepancyPricing:
    def test_discrepancy_cost_prices_each_overrun_component_and_fills_the_deposit_first(
        self, api
    ):
        """PRD §3.10: The hours overrun is the amount by which `hours_since_check_at_return` exceeds the lease's `return_hours_since_check_max`, floored at zero.
        PRD §3.10: The airframe component is the hours overrun multiplied by a rate of 2,500 cents (USD 25.00) per hour over, rounded half up to whole cents — this being the only one of the three that needs rounding, since the other two multiply integers.
        PRD §3.10: The cycles component is the cycles overrun multiplied by a rate of 18,000 cents (USD 180.00) per cycle over.
        PRD §3.10: The fuel component is the fuel shortfall multiplied by a rate of 95 cents per kilogram short.
        PRD §3.10: Their raw sum is then capped at the lease's `return_liability_cap_cents`.
        PRD §3.10: `return_deposit_applied_cents` on the lease becomes the lesser of `discrepancy_cost_cents` and the lease's full `return_deposit_cents`; `return_deposit_remaining_cents` becomes `return_deposit_cents` less that applied figure; and `billed_to_lessee_cents` on the return record becomes `discrepancy_cost_cents` less the applied figure.
        PRD §3.10: A first inspection producing a non-empty `discrepancy_codes` array moves the record from `PENDING_INSPECTION` to `DISCREPANCIES_OPEN`.
        PRD §2.9: On every lease, `return_deposit_applied_cents` plus `return_deposit_remaining_cents` equals `return_deposit_cents` at all times.

        Design: Corner/calculations/return_deposit_absorbs_the_discrepancy_before_the_lessee_is_billed
        """
        scenario = _terminating_lease_awaiting_inspection(api)

        inspected = validate_success(
            api.inspect_return_condition(
                scenario["return_condition"]["id"],
                inspect_return_payload(355.50, 138, 3600, ["CABIN_TRIM_DAMAGE"]),
                TECH,
            ),
            200,
        )

        assert inspected["status"] == "DISCREPANCIES_OPEN", (
            "a first inspection recording a discrepancy code opens the discrepancies"
        )
        assert inspected["discrepancy_cost_cents"] == 500750, (
            "55.50 hours over at 2,500 cents is 138,750, 18 cycles over at 18,000 cents "
            "is 324,000 and 400 kg short at 95 cents is 38,000, summing to 500,750 "
            "under the 900,000-cent liability cap"
        )
        assert inspected["billed_to_lessee_cents"] == 750, (
            "the 500,000-cent deposit absorbs all but 750 cents of the discrepancy"
        )

        lease = validate_success(api.get_lease(scenario["lease"]["id"], OPS), 200)
        assert lease["return_deposit_applied_cents"] == 500000, (
            "the applied figure is the lesser of the 500,750-cent cost and the full "
            "500,000-cent deposit"
        )
        assert lease["return_deposit_remaining_cents"] == 0, (
            "the deposit is exhausted by a cost larger than the deposit itself"
        )
        assert_deposit_conservation(lease)

    def test_re_inspection_redraws_the_waterfall_from_the_full_original_deposit(self, api):
        """PRD §3.10: Inspection is admissible while the record is `PENDING_INSPECTION` or `DISCREPANCIES_OPEN` — a re-inspection is expected and supported — and, on a first inspection, requires the lease to be `TERMINATING`.
        PRD §3.10: The waterfall always starts from the full original `return_deposit_cents` and never from the surviving remainder of an earlier inspection, which is what makes re-inspection safe and keeps the deposit invariant of §2.9 true at every step.
        PRD §2.9: A re-inspection recomputes the split from the full original deposit rather than from the surviving remainder, so re-inspecting can never double-draw.
        PRD §2.9: On every lease, `return_deposit_applied_cents` plus `return_deposit_remaining_cents` equals `return_deposit_cents` at all times.

        Design: Corner/calculations/return_deposit_absorbs_the_discrepancy_before_the_lessee_is_billed
        """
        scenario = _terminating_lease_awaiting_inspection(api)
        return_id = scenario["return_condition"]["id"]
        get_success_data(
            api.inspect_return_condition(
                return_id,
                inspect_return_payload(355.50, 138, 3600, ["CABIN_TRIM_DAMAGE"]),
                TECH,
            )
        )

        re_inspected = validate_success(
            api.inspect_return_condition(
                return_id,
                inspect_return_payload(355.50, 138, 3600, ["CABIN_TRIM_DAMAGE"]),
                TECH,
            ),
            200,
        )

        assert re_inspected["discrepancy_cost_cents"] == 500750, (
            "identical readings must price identically on a second inspection"
        )
        assert re_inspected["billed_to_lessee_cents"] == 750, (
            "the second draw starts from the full deposit again, so only 750 cents "
            "reach the lessee a second time"
        )

        lease = validate_success(api.get_lease(scenario["lease"]["id"], OPS), 200)
        assert lease["return_deposit_applied_cents"] == 500000, (
            "the applied figure is recomputed from the full 500,000-cent deposit and "
            "never double-drawn"
        )
        assert lease["return_deposit_remaining_cents"] == 0, (
            "the remainder after re-inspection is still the deposit less the applied "
            "figure"
        )
        assert_deposit_conservation(lease)

    def test_recorded_code_with_nothing_measurable_over_attracts_the_minimum_fee(self, api):
        """PRD §3.10: The hours overrun is the amount by which `hours_since_check_at_return` exceeds the lease's `return_hours_since_check_max`, floored at zero.
        PRD §3.10: The fuel shortfall is the amount by which `fuel_on_board_kg` falls below `return_fuel_kg_required`, floored at zero.
        PRD §3.10: Otherwise `discrepancy_cost_cents` is the greater of the capped sum and a minimum discrepancy fee of 250,000 cents (USD 2,500.00) — a recorded discrepancy code always attracts at least that minimum, even when nothing measurable was over.
        PRD §3.10: A first inspection producing a non-empty `discrepancy_codes` array moves the record from `PENDING_INSPECTION` to `DISCREPANCIES_OPEN`.
        PRD §3.10: `return_deposit_applied_cents` on the lease becomes the lesser of `discrepancy_cost_cents` and the lease's full `return_deposit_cents`; `return_deposit_remaining_cents` becomes `return_deposit_cents` less that applied figure; and `billed_to_lessee_cents` on the return record becomes `discrepancy_cost_cents` less the applied figure.

        Design: Corner/calculations/minimum_discrepancy_fee_floors_a_zero_raw_cost_only_when_a_code_is_recorded
        """
        scenario = _terminating_lease_awaiting_inspection(api)

        inspected = validate_success(
            api.inspect_return_condition(
                scenario["return_condition"]["id"],
                inspect_return_payload(280.00, 100, 4200, ["GALLEY_INSERT_MISSING"]),
                TECH,
            ),
            200,
        )

        assert inspected["status"] == "DISCREPANCIES_OPEN", (
            "a recorded discrepancy code opens the discrepancies even when every "
            "reading is inside its ceiling"
        )
        assert inspected["discrepancy_cost_cents"] == 250000, (
            "280.00 hours, 100 cycles and 4,200 kg are all inside their ceilings, so "
            "the raw sum is 0 and the 250,000-cent minimum fee applies"
        )
        assert inspected["billed_to_lessee_cents"] == 0, (
            "the 500,000-cent deposit absorbs the whole minimum fee"
        )

    def test_clearing_the_code_list_prices_the_same_readings_at_zero_and_restores_the_deposit(
        self, api
    ):
        """PRD §3.10: If the raw sum is 0 *and* `discrepancy_codes` is empty, `discrepancy_cost_cents` is 0.
        PRD §3.10: A re-inspection with an empty `discrepancy_codes` array moves the record from `DISCREPANCIES_OPEN` to `CLEARED`, recomputing the cost and re-applying the waterfall from the original deposit balance.
        PRD §3.10: `return_deposit_applied_cents` on the lease becomes the lesser of `discrepancy_cost_cents` and the lease's full `return_deposit_cents`; `return_deposit_remaining_cents` becomes `return_deposit_cents` less that applied figure; and `billed_to_lessee_cents` on the return record becomes `discrepancy_cost_cents` less the applied figure.
        PRD §2.9: On every lease, `return_deposit_applied_cents` plus `return_deposit_remaining_cents` equals `return_deposit_cents` at all times.

        Design: Corner/calculations/minimum_discrepancy_fee_floors_a_zero_raw_cost_only_when_a_code_is_recorded
        """
        scenario = _terminating_lease_awaiting_inspection(api)
        return_id = scenario["return_condition"]["id"]
        get_success_data(
            api.inspect_return_condition(
                return_id,
                inspect_return_payload(280.00, 100, 4200, ["GALLEY_INSERT_MISSING"]),
                TECH,
            )
        )

        re_inspected = validate_success(
            api.inspect_return_condition(
                return_id, inspect_return_payload(280.00, 100, 4200, []), TECH
            ),
            200,
        )

        assert re_inspected["status"] == "CLEARED", (
            "a re-inspection with an empty code list clears the record"
        )
        assert re_inspected["discrepancy_cost_cents"] == 0, (
            "the same readings cost nothing once no discrepancy code is recorded"
        )
        assert re_inspected["billed_to_lessee_cents"] == 0, (
            "a zero cost bills the lessee nothing"
        )
        assert re_inspected["discrepancy_codes"] == [], (
            "the emptied code list must be stored as recorded"
        )

        lease = validate_success(api.get_lease(scenario["lease"]["id"], OPS), 200)
        assert lease["return_deposit_applied_cents"] == 0, (
            "a zero cost draws nothing from the deposit"
        )
        assert lease["return_deposit_remaining_cents"] == 500000, (
            "the waterfall restarts from the full deposit, restoring all 500,000 cents"
        )
        assert_deposit_conservation(lease)


class TestSubstituteAircraftSelection:
    def test_server_ranks_seat_delta_then_hours_then_registration_order(self, api):
        """PRD §3.7: When `substitute_aircraft_id` is omitted, the server picks one and records `selection_basis` as `SERVER_SELECTED`.
        PRD §3.7: The eligible pool is every airframe other than the original whose `status` is `AVAILABLE`, whose `assigned_lease_id` is null, whose `type_family` equals the original's `type_family`, whose `maintenance_program_ref` equals the lease's `required_maintenance_program_ref`, whose `seat_count` is at least the original's `seat_count` less five, and whose `hours_since_last_check` is not more than 400.00 hours — the boundary being inclusive, so an airframe at exactly 400.00 hours remains eligible.
        PRD §3.7: `RETIRED`, `IN_MAINTENANCE`, `AOG` and already-assigned airframes are therefore all excluded.
        PRD §3.7: Because eligibility turns on the family rather than the variant, a different-variant airframe of the same family is a lawful substitute even when the rostered crew are not rated on that variant.
        PRD §3.7: The pool is then ranked by three keys, each ascending and applied in order: first the absolute difference between the candidate's `seat_count` and the original's `seat_count`, so the closest-gauge airframe wins; then the candidate's `hours_since_last_check`, so the freshest airframe wins a seat tie; and finally the candidate's `created_at`, so the longest-registered airframe wins any remaining tie.
        PRD §3.7: The row identifier is never used as a tie-break.
        PRD §3.7: The first-ranked candidate becomes the substitute.
        PRD §3.7: Either way the request records `seat_delta` as the substitute's `seat_count` less the original's `seat_count` — a figure the lessee needs for its consent decision — and `repointed_leg_count` as 0 at creation, and the lease's `version` increments by 1.
        PRD §3.7: On a lease whose rights are `LESSOR_UNILATERAL` the request lands directly in `APPROVED`, `seat_delta` is written, no airframe is touched yet, and — this is the branch's extra effect — every other substitution on the same lease whose `status` is `REQUESTED`, `LESSEE_CONSENT_PENDING` or `APPROVED` is moved to the terminal `WITHDRAWN`, without touching any airframe.
        PRD §2.5: Ranking keys used by the substitute selector are compared exactly, with no rounding.

        Design: Corner/calculations/substitute_selector_ranks_seat_delta_then_hours_then_created_at
        """
        scenario = _active_lease_with_eight_substitute_candidates(api)

        substitution = validate_success(
            api.create_substitution(
                create_substitution_payload(
                    scenario["lease"]["id"],
                    scenario["aircraft"]["id"],
                    scenario["lease"]["version"],
                    reason="SCHEDULED_MAINTENANCE",
                    effective_from="2026-09-20T00:00:00Z",
                ),
                OPS,
            ),
            201,
        )

        assert substitution["selection_basis"] == "SERVER_SELECTED", (
            "omitting substitute_aircraft_id makes the server pick the substitute"
        )
        assert substitution["substitute_aircraft_id"] == scenario["suby"]["id"], (
            "G-SUBY wins on a zero seat delta, the freshest 90.00 hours since check and "
            "the earlier registration of the two airframes tied on both keys"
        )
        assert substitution["substitute_aircraft_id"] != scenario["subw"]["id"], (
            "G-SUBW ties G-SUBY on seats and hours but was registered later, so the "
            "created_at tie-break must exclude it"
        )
        assert substitution["substitute_aircraft_id"] != scenario["subz"]["id"], (
            "G-SUBZ is the freshest airframe of all but loses on the first ranking key, "
            "its seat delta of three"
        )
        assert substitution["substitute_aircraft_id"] != scenario["subi"]["id"], (
            "G-SUBI is IN_MAINTENANCE and therefore not in the eligible pool at all"
        )
        assert substitution["seat_delta"] == 0, (
            "the substitute's 189 seats less the original's 189 seats is 0"
        )
        assert substitution["status"] == "APPROVED", (
            "a request on a LESSOR_UNILATERAL lease lands directly in APPROVED"
        )
        assert substitution["repointed_leg_count"] == 0, (
            "no leg is re-pointed until the substitution is effectuated"
        )
        assert substitution["original_aircraft_id"] == scenario["aircraft"]["id"], (
            "the request records the airframe being replaced"
        )

        chosen = validate_success(api.get_aircraft(scenario["suby"]["id"], TECH), 200)
        assert chosen["status"] == "AVAILABLE", (
            "selection alone touches no airframe, so the chosen substitute is still "
            "AVAILABLE"
        )
        assert chosen["assigned_lease_id"] is None, (
            "the substitute is not assigned to the lease until effectuation"
        )
