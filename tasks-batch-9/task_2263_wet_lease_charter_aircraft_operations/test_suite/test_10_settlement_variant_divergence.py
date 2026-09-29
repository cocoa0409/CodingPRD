"""Divergence between the two variants each dual-variant calculation is computed under.

One unchanged set of flight legs is read twice — once under each variant rule — and the
two answers must differ exactly as the PRD's include-sets and per-leg minute figures
demand.
"""

import pytest

from test_helpers import (
    TEST_USERS,
    cancel_leg,
    create_reliability_report_payload,
    file_reliability_report,
    fly_leg,
    get_success_data,
    schedule_leg,
    setup_active_lease,
    validate_success,
)

BILLING = TEST_USERS["billing_admin_headers"]
TECH = TEST_USERS["maintenance_controller_headers"]


def _month_with_completed_scheduled_and_lessee_cancelled_legs(api) -> dict:
    """ACTIVE lease over 2026-09 carrying one COMPLETED, one SCHEDULED and one
    lessee-cancelled REVENUE leg — the leg set both charge variants are read against.

    L1 completes 330 actual block minutes, L2 stays SCHEDULED on 180 scheduled block
    minutes, L3 is cancelled by the lessee on 120 scheduled block minutes.
    """
    scenario = setup_active_lease(api)
    fly_leg(
        api,
        scenario,
        scheduled_out="2026-09-03T06:00:00Z",
        scheduled_in="2026-09-03T11:30:00Z",
        dest_icao="LEPA",
    )
    schedule_leg(
        api,
        scenario,
        scheduled_out="2026-09-05T06:00:00Z",
        scheduled_in="2026-09-05T09:00:00Z",
        dest_icao="LFPG",
    )
    cancelled = schedule_leg(
        api,
        scenario,
        scheduled_out="2026-09-07T06:00:00Z",
        scheduled_in="2026-09-07T08:00:00Z",
        dest_icao="EIDW",
    )
    cancel_leg(api, cancelled["id"], cancelling_party="LESSEE", cancel_reason="COMMERCIAL")
    return scenario


def _month_with_delayed_departure_and_technical_cancellation(api) -> dict:
    """ACTIVE lease on the DEPARTURE reliability basis carrying two completed REVENUE
    legs — one delayed 30 technical minutes — and one lessor technical cancellation.
    """
    scenario = setup_active_lease(api)
    fly_leg(
        api,
        scenario,
        scheduled_out="2026-09-03T06:00:00Z",
        scheduled_in="2026-09-03T09:00:00Z",
        actual_out="2026-09-03T06:30:00Z",
        actual_in="2026-09-03T09:30:00Z",
        technical_delay_minutes=30,
        dest_icao="LEPA",
    )
    fly_leg(
        api,
        scenario,
        scheduled_out="2026-09-05T06:00:00Z",
        scheduled_in="2026-09-05T09:00:00Z",
        technical_delay_minutes=0,
        dest_icao="LFPG",
    )
    cancelled = schedule_leg(
        api,
        scenario,
        scheduled_out="2026-09-07T06:00:00Z",
        scheduled_in="2026-09-07T08:00:00Z",
        dest_icao="EIDW",
    )
    cancel_leg(api, cancelled["id"], cancelling_party="LESSOR", cancel_reason="TECHNICAL")
    return scenario


class TestUtilizationChargeVariantDivergence:
    def test_settlement_preview_credits_different_hours_under_each_variant(self, api):
        """PRD §3.8: `mgh_effective_hours` is the lease's `min_guaranteed_block_hours_per_month` multiplied by the number of covered days and divided by the number of calendar days in `period_month`, rounded half up to four decimal places.
        PRD §3.8: Under the `PROVISIONAL` variant the include-set is every leg of the lease whose `scheduled_out` falls inside `period_month` and whose `status` is `SCHEDULED`, `DISPATCHED` or `COMPLETED`.
        PRD §3.8: A leg not yet completed contributes its `scheduled_block_minutes`, with the same one-hour minimum billable floor applied when its `leg_class` is `REVENUE` and with 0 contributed when its `leg_class` is `MAINTENANCE_FERRY`.
        PRD §3.8: Cancelled and diverted legs contribute nothing at all, so no lessee-cancellation credit ever appears in a provisional figure.
        PRD §3.8: Only legs whose `status` is `COMPLETED` count from the operational side, each contributing its `billable_block_minutes`.
        PRD §3.8: To that is added, for every leg whose `status` is `CANCELLED_LESSEE`, a contribution of half its `scheduled_block_minutes` — the lessee pays for half of what it cancelled.
        PRD §3.8: Otherwise `shortfall_hours` is 0 and `overrun_hours` is `credited_hours` less `mgh_effective_hours`, rounded half up to four decimal places — so a month landing exactly on the guarantee produces neither.

        Design: Difficulty/dual_variant_calc/utilization_charge_provisional_vs_final_diverge_on_identical_legs
        """
        scenario = _month_with_completed_scheduled_and_lessee_cancelled_legs(api)

        preview = validate_success(
            api.get_settlement_preview(scenario["period"]["id"], BILLING), 200
        )

        assert preview["mgh_effective_hours"] == pytest.approx(5.0000, abs=0.0001), (
            "a lease covering the whole of 2026-09 carries its full 5-hour guarantee"
        )
        assert preview["provisional_credited_hours"] == pytest.approx(
            8.5000, abs=0.0001
        ), (
            "the provisional variant credits the completed leg's 330 billable minutes plus "
            "the still-SCHEDULED leg's 180 scheduled minutes and nothing for the "
            "lessee-cancelled leg, giving 8.5000 hours"
        )
        assert preview["final_credited_hours"] == pytest.approx(6.5000, abs=0.0001), (
            "the final variant drops the SCHEDULED leg entirely and credits half of the "
            "lessee-cancelled leg's 120 scheduled minutes, giving 6.5000 hours"
        )
        assert preview["final_overrun_hours"] == pytest.approx(1.5000, abs=0.0001), (
            "final credited hours of 6.5000 exceed the 5.0000-hour guarantee by 1.5000"
        )

    def test_settlement_preview_prices_the_variant_gap_without_persisting_it(self, api):
        """PRD §3.8: Each tier's hours are multiplied by the block-hour rate and by that tier's multiplier — 1.00 for the first tier, 1.15 for the second, and 1.35 for the third — and each of the three products is rounded half up to whole cents *individually*; `overrun_charge_cents` is the sum of those three rounded figures.
        PRD §3.8: `gross_charge_cents` is `base_charge_cents` less `shortfall_credit_cents` plus `overrun_charge_cents`.
        PRD §3.8: `reliability_penalty_cents` is derived as described below, and the net charge is `gross_charge_cents` less `reliability_penalty_cents`.
        PRD §3.8: Under the `PROVISIONAL` variant that net figure is written to `provisional_charge_cents`; under the `FINAL` variant it is written to `final_charge_cents`.
        PRD §3.8: If no accepted report exists for the month, `reliability_penalty_cents` is 0 and no penalty applies.
        PRD §3.8: A non-mutating computed read evaluates both variants side by side without persisting anything.
        PRD §3.8: It returns `period_id`, `period_month`, `mgh_effective_hours`, `provisional_credited_hours`, `provisional_gross_charge_cents`, `final_credited_hours`, `final_shortfall_hours`, `final_overrun_hours`, `final_gross_charge_cents`, `reliability_penalty_cents` and `projected_final_charge_cents`.
        PRD §2.4: `version` (integer): an integer that starts at 1 and increments by 1 on every mutation of the resource.
        PRD §2.11: Whichever variant most recently wrote a period's credited and shortfall/overrun fields is recorded in `variant_applied`, which holds either `PROVISIONAL` or `FINAL`.

        Design: Difficulty/dual_variant_calc/utilization_charge_provisional_vs_final_diverge_on_identical_legs
        """
        scenario = _month_with_completed_scheduled_and_lessee_cancelled_legs(api)
        period_id = scenario["period"]["id"]
        before = get_success_data(api.get_utilization_period(period_id, BILLING))

        preview = validate_success(api.get_settlement_preview(period_id, BILLING), 200)

        assert preview["provisional_gross_charge_cents"] == 4512000, (
            "the provisional gross charge is the 2,400,000-cent base guarantee plus the "
            "three overrun tiers on 3.5000 overrun hours"
        )
        assert preview["final_gross_charge_cents"] == 3216000, (
            "the final gross charge is the 2,400,000-cent base guarantee plus the three "
            "overrun tiers on 1.5000 overrun hours"
        )
        assert preview["reliability_penalty_cents"] == 0, (
            "no reliability report has been accepted for the month, so no penalty applies"
        )
        assert preview["projected_final_charge_cents"] == 3216000, (
            "the projected final charge is the final gross charge less a zero penalty"
        )
        assert (
            preview["provisional_gross_charge_cents"]
            - preview["final_gross_charge_cents"]
            == 1296000
        ), "the variant switch must move the charge by exactly 1,296,000 cents"

        after = get_success_data(api.get_utilization_period(period_id, BILLING))
        assert after["status"] == "OPEN", (
            "the preview persists nothing, so the period is still OPEN"
        )
        assert after["version"] == before["version"], (
            "the preview mutates nothing, so the period's version must not advance"
        )
        assert after["variant_applied"] == "PROVISIONAL", (
            "the last write to the period's credited fields was the provisional "
            "recomputation triggered by the leg mutations, not the preview"
        )
        assert after["credited_hours"] == pytest.approx(8.5000, abs=0.0001), (
            "the persisted period keeps its provisional credited hours of 8.5000"
        )
        assert after["gross_charge_cents"] == 4512000, (
            "the persisted period keeps its provisional gross charge of 4,512,000 cents"
        )
        assert after["provisional_charge_cents"] == 4512000, (
            "the provisional net charge is the provisional gross charge less a zero penalty"
        )


class TestReliabilityBasisVariantDivergence:
    def test_filed_report_stores_both_bases_and_binds_the_contractual_one(self, api):
        """PRD §3.8: `tdr_departure_basis_pct` is 100 multiplied by `revenue_departures` less `technical_delay_events`, divided by `revenue_departures`; when `revenue_departures` is 0 the figure is 100.00.
        PRD §3.8: `tdr_scheduled_basis_pct` is 100 multiplied by `scheduled_revenue_legs` less `technical_delay_events` less `technical_cancellations`, divided by `scheduled_revenue_legs`; when `scheduled_revenue_legs` is 0 the figure is 100.00.
        PRD §3.8: `technical_dispatch_reliability_pct` is then set to `tdr_departure_basis_pct` when the lease's `reliability_basis` is `DEPARTURE`, and to `tdr_scheduled_basis_pct` when it is `SCHEDULED`.
        PRD §2.11: Both are always computed and both are always stored on the report, as `tdr_departure_basis_pct` and `tdr_scheduled_basis_pct`; the lease's contractual `reliability_basis` then selects which of the two becomes the binding headline figure in `technical_dispatch_reliability_pct`.

        Design: Difficulty/dual_variant_calc/tdr_departure_basis_vs_scheduled_basis_diverge_on_identical_legs
        """
        scenario = _month_with_delayed_departure_and_technical_cancellation(api)

        report = file_reliability_report(
            api, scenario, period_month="2026-09", decision=None
        )

        assert report["tdr_departure_basis_pct"] == pytest.approx(50.00, abs=0.01), (
            "the departure basis divides one undelayed departure by two departures"
        )
        assert report["tdr_scheduled_basis_pct"] == pytest.approx(33.33, abs=0.01), (
            "the scheduled basis subtracts both the delay event and the technical "
            "cancellation from a denominator of three published legs"
        )
        assert report[
            "technical_dispatch_reliability_pct"
        ] == pytest.approx(50.00, abs=0.01), (
            "the lease's reliability_basis of DEPARTURE makes the departure basis binding"
        )

    def test_filed_report_counts_only_the_declared_leg_statuses_per_basis(self, api):
        """PRD §3.8: Technical control files the monthly report by supplying `lease_id`, `aircraft_id` and `period_month`; the report is created with `status` `SUBMITTED` and its `period_month` is unique per lease-and-airframe pair among reports that are not `REJECTED`.
        PRD §3.8: `revenue_departures` counts those whose `status` is `DISPATCHED` or `COMPLETED`.
        PRD §3.8: `scheduled_revenue_legs` counts those whose `status` is `SCHEDULED`, `DISPATCHED`, `COMPLETED` or `CANCELLED_LESSOR`.
        PRD §3.8: `technical_delay_events` counts those whose `technical_delay_minutes` is strictly greater than 15.
        PRD §3.8: `technical_cancellations` counts those whose `status` is `CANCELLED_LESSOR` and whose `cancel_reason` is `TECHNICAL`.

        Design: Difficulty/dual_variant_calc/tdr_departure_basis_vs_scheduled_basis_diverge_on_identical_legs
        """
        scenario = _month_with_delayed_departure_and_technical_cancellation(api)

        report = validate_success(
            api.create_reliability_report(
                create_reliability_report_payload(
                    scenario["lease"]["id"], scenario["aircraft"]["id"], "2026-09"
                ),
                TECH,
            ),
            201,
        )

        assert report["revenue_departures"] == 2, (
            "only the two completed legs actually went off-blocks"
        )
        assert report["scheduled_revenue_legs"] == 3, (
            "the lessor technical cancellation stays in the published-programme denominator"
        )
        assert report["technical_delay_events"] == 1, (
            "only the 30-minute technical delay exceeds the 15-minute threshold"
        )
        assert report["technical_cancellations"] == 1, (
            "the single CANCELLED_LESSOR leg carries cancel_reason TECHNICAL"
        )
        assert report["status"] == "SUBMITTED", (
            "a freshly filed reliability report is created SUBMITTED"
        )
