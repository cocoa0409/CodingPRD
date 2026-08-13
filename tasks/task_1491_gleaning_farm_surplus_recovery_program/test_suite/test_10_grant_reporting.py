"""Grant reports: impact metric snapshots, truncation, and the RETURNED resubmit
cycle (PRD §3.6, §3.7)."""
import pytest

from test_helpers import (
    coordinator_headers,
    create_report_payload,
    get_offer,
    new_crew_leader,
    new_vehicle,
    new_volunteer,
    reviewer_headers,
    run_event_lifecycle,
    setup_closed_offer,
    unique_email,
    validate_success,
)

PERIOD = {"period_start": "2026-08-01T00:00:00Z", "period_end": "2026-09-01T00:00:00Z"}


def _submit(api, report_id):
    return validate_success(api.submit_report(report_id, coordinator_headers()), 200)


class TestImpactMetricsPrecision:
    def test_meals_equivalent_truncates_not_rounds(self, api):
        """PRD §3.7: "The `meals_equivalent` multiplies that total by 1.2 meals per
        pound and truncates the product down to a whole number."

        Design: Corner/calculations/impact_metrics_precision_truncation
        """
        ctx = setup_closed_offer(
            county_code="PRC",
            offer_over={"estimated_lbs": 100.0},
            lot_specs=[{"gross": 93.3, "cull": 0.0, "verify": True}],  # net 83.3
        )
        report = validate_success(
            api.create_report(create_report_payload(county_code="PRC", **PERIOD),
                              coordinator_headers()),
            201,
        )
        submitted = _submit(api, report["id"])
        assert submitted["total_gleaned_lbs"] == pytest.approx(83.3)
        assert submitted["meals_equivalent"] == 99, (
            "floor(83.3 * 1.2) = floor(99.96) = 99; round-half-up would give 100"
        )


class TestSalvageRatioVariants:
    def _salvage_setup(self, api):
        """350.0 verified pounds of APPLES (estimated 500.0) with a 40.0-lb resolved
        incident and one DELIVERED distribution; offer CLOSED; report submitted."""
        ctx = run_event_lifecycle(
            stop_at="closed",
            county_code="CCC",
            offer_over={"crop_code": "APPLES", "estimated_lbs": 500.0,
                        "perishability_class": "MEDIUM",
                        "requires_refrigeration": True,
                        "window_start": "2026-08-05T00:00:00Z",
                        "window_end": "2026-08-25T00:00:00Z"},
            event_end="2026-08-10T14:00:00Z",
            container_count=3,
            lot_specs=[{"gross": 130.0, "verify": True},
                       {"gross": 90.0, "verify": True},
                       {"gross": 160.0, "verify": True}],  # nets 120+80+150 = 350.0
            incident_specs=[{"severity": "MINOR", "condemned_lbs": 40.0,
                             "disposition": "COMPOST"}],
            agency_over={"agency_name": "AG3", "county_code": "CCC",
                         "weekly_capacity_lbs": 10000.0, "refrigeration_capable": True},
            distribution_specs=[{"planned_lbs": 300.0, "deliver": 300.0,
                                 "delivery_date": "2026-08-11T10:00:00Z"}],
        )
        report = validate_success(
            api.create_report(create_report_payload(county_code="CCC", **PERIOD),
                              coordinator_headers()),
            201,
        )
        submitted = _submit(api, report["id"])
        return ctx, submitted

    def test_offer_salvage_ratio_uses_raw_actual_pounds(self, api):
        """PRD §3.6: "The `salvage_ratio` is computed as `actual_lbs` divided by
        `estimated_lbs`, rounded half-up to four decimal places; the raw ratio always
        uses all verified pounds, including any later condemned."
        PRD §3.6: "Alongside it, grant reporting draws on a net-of-condemnation
        variant — `actual_lbs` minus the resolved incidents' condemned pounds, divided
        by `estimated_lbs`, likewise at four decimal places round half up."

        Design: Difficulty/dual_variant_calc/salvage_ratio_raw_vs_net_of_condemnation
        """
        ctx, submitted = self._salvage_setup(api)
        offer = get_offer(ctx["offer"]["id"])
        assert offer["salvage_ratio"] == pytest.approx(0.7, abs=1e-9), (
            "raw ratio 350.0/500.0; condemnation is NOT netted on the offer"
        )
        assert submitted["total_gleaned_lbs"] == pytest.approx(310.0), (
            "the grant-report variant nets out the 40.0 condemned pounds"
        )

    def test_report_meals_and_agency_count(self, api):
        """PRD §3.7: "Within that scope, `total_gleaned_lbs` is the sum of the events'
        `total_harvested_lbs` minus the `condemned_lbs` of their resolved incidents,
        expressed at one decimal place round half up."
        PRD §3.7: "The `agency_count` counts the distinct agencies that received
        `DELIVERED` distributions from the in-scope events."

        Design: Difficulty/dual_variant_calc/salvage_ratio_raw_vs_net_of_condemnation
        """
        ctx, submitted = self._salvage_setup(api)
        assert submitted["meals_equivalent"] == 372, "floor(310.0 * 1.2)"
        assert submitted["agency_count"] == 1


class TestReportReturnedResubmitCycle:
    def _cycle_setup(self, api):
        """County GGG: farm A offer closed at 200.0 lbs; report submitted then
        returned; farm B offer (same county) closed at 160.0 lbs afterwards."""
        vehicle = new_vehicle()
        lead = new_crew_leader()
        coord = new_volunteer(full_name="Coord G", email=unique_email("coord"))
        shared = {"vehicle": vehicle, "lead": lead, "coord": coord}
        ctx_a = run_event_lifecycle(
            stop_at="closed", shared=shared, county_code="GGG",
            farm_over={"farm_name": "FGA"},
            offer_over={"crop_code": "SWEET_CORN", "estimated_lbs": 250.0},
            lot_specs=[{"gross": 210.0, "verify": True}],  # net 200.0
        )
        assert ctx_a["farm"]["county_code"] == "GGG"
        report = validate_success(
            api.create_report(create_report_payload(county_code="GGG", **PERIOD),
                              coordinator_headers()),
            201,
        )
        return {"shared": shared, "ctx_a": ctx_a, "report": report}

    def test_first_submit_snapshots_then_return(self, api):
        """PRD §3.7: "Submission freezes the numbers. Both the initial submission and
        any resubmission recompute the report's three metrics at that instant, and the
        frozen snapshot never changes afterward, no matter what later happens to
        farms, agencies, lots, or incidents."
        PRD §3.7: "a `GrantReviewer` then accepts it (`SUBMITTED` → `ACCEPTED`,
        terminal) or returns it (`SUBMITTED` → `RETURNED`), and a returned report may
        be resubmitted, moving `RETURNED` → `SUBMITTED`."

        Design: Difficulty/non_linear_state_machine/grant_report_returned_resubmit_cycle
        """
        ctx = self._cycle_setup(api)
        first = _submit(api, ctx["report"]["id"])
        assert first["total_gleaned_lbs"] == pytest.approx(200.0)
        returned = validate_success(
            api.return_report(ctx["report"]["id"], reviewer_headers()), 200
        )
        assert returned["status"] == "RETURNED"

    def test_resubmit_recomputes_metrics_snapshot(self, api):
        """PRD §3.7: "Submission freezes the numbers. Both the initial submission and
        any resubmission recompute the report's three metrics at that instant"
        PRD §3.7: "The scope is the set of glean events whose offer's farm
        `county_code` equals the report's county, whose offer has reached `CLOSED`,
        and whose offer's close timestamp — its `updated_at` at the moment of the
        `CLOSED` transition — falls within the half-open period from `period_start`
        inclusive to `period_end` exclusive."

        Design: Difficulty/non_linear_state_machine/grant_report_returned_resubmit_cycle
        """
        ctx = self._cycle_setup(api)
        first = _submit(api, ctx["report"]["id"])
        assert first["total_gleaned_lbs"] == pytest.approx(200.0)
        api.return_report(ctx["report"]["id"], reviewer_headers())

        # A second farm in the same county closes another offer inside the period.
        run_event_lifecycle(
            stop_at="closed", shared=ctx["shared"], county_code="GGG",
            farm_over={"farm_name": "FGB"},
            offer_over={"crop_code": "APPLES", "estimated_lbs": 200.0,
                        "window_start": "2026-08-06T00:00:00Z",
                        "window_end": "2026-08-21T00:00:00Z"},
            event_start="2026-08-11T08:00:00Z", event_end="2026-08-11T12:00:00Z",
            clock_iso="2026-08-11T09:00:00Z",
            lot_specs=[{"gross": 170.0, "verify": True}],  # net 160.0
        )
        second = _submit(api, ctx["report"]["id"])
        assert second["status"] == "SUBMITTED"
        assert second["total_gleaned_lbs"] == pytest.approx(360.0), (
            "resubmit recomputes: 200.0 + 160.0"
        )
        assert second["meals_equivalent"] == 432, "floor(360.0 * 1.2)"
