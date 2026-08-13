"""Risk scoring, re-survey intervals, and overdue-leak boundaries (PRD §3.1, §3.8, §3.9)."""
import pytest

from test_helpers import (
    ApiErrorId,
    assert_timestamp_eq,
    get_success_data,
    make_leak,
    set_clock,
    setup_accepted_run,
    setup_completed_route,
    setup_verifiable_leak,
    validate_success,
)
from test_helpers.factories import create_cp_reading_payload, create_schedule_repair_payload


class TestResurveyInterval:
    def test_resurvey_on_demand_clean_distribution_segment(self, api):
        """PRD §3.9: "365 days for `DISTRIBUTION` outside an HCA" with "A
        multiplicative adjustment factor, starting at 1.0" unchanged on a clean
        segment, and "`next_survey_due_at` is the route's completion timestamp
        plus that many days."
        PRD §3.1: the on-demand capability returns "the recomputed
        `next_survey_due_at` and the `interval_days` that produced it".

        Design: Corner/calculations/resurvey_on_demand_clean_distribution_segment
        """
        ctx = setup_completed_route(route_code="R-RSO")
        segment = ctx["segments"][0]
        data = validate_success(api.get_next_survey_due(segment["id"], ctx["ia_h"]))
        assert data["interval_days"] == 365
        assert_timestamp_eq(data["next_survey_due_at"], "2027-08-01T00:00:00Z",
                            "next_survey_due_at")

    def test_resurvey_interval_multifactor_nonlinear(self, api):
        """PRD §3.9: "90 days for `TRANSMISSION` in an HCA"; "otherwise, if it has
        any open Grade 2 leak, the factor drops to 0.5 (semiannual)";
        "Independently, if the segment has any cathodic-protection reading with
        `anomaly_status` of `OPEN` or `ACKNOWLEDGED`, the factor is multiplied by
        0.5. The interval in days is the base multiplied by the factor, truncated
        down to a whole number of days" — floor(90 * 0.5 * 0.5) = 22 days after
        the 2026-08-01 completion.

        Design: Difficulty/combinatorial_formula/resurvey_interval_multifactor_nonlinear
        """
        def add_g2_leak_and_cp_anomaly(ctx):
            segment, run = ctx["segments"][0], ctx["run"]
            make_leak(ctx, segment["id"], run["id"])  # default payload grades G2
            get_success_data(api.create_cp_reading(
                create_cp_reading_payload(segment["id"]),  # instant_off -800: anomalous
                ctx["ft_h"],
            ))

        ctx = setup_completed_route(
            route_code="R-RS",
            segment_overrides={
                "segment_code": "SEG-RS",
                "install_year": 2015,
                "diameter_inches": 24.0,
                "length_feet": 5000.0,
                "operating_pressure_psi": 800.0,
                "pressure_class": "TRANSMISSION",
                "is_high_consequence_area": True,
            },
            distance_covered_feet=5000.0,
            pre_complete=add_g2_leak_and_cp_anomaly,
        )
        segment = ctx["segments"][0]
        after = get_success_data(api.get_pipe_segment(segment["id"], ctx["ia_h"]))
        assert_timestamp_eq(after["next_survey_due_at"], "2026-08-23T00:00:00Z",
                            "next_survey_due_at")

    def test_resurvey_interval_g2_factor_without_cp_anomaly(self, api):
        """PRD §3.9: "90 days for `TRANSMISSION` in an HCA" tightened only by
        "otherwise, if it has any open Grade 2 leak, the factor drops to 0.5
        (semiannual)" — floor(90 * 0.5) = 45 days when no CP anomaly is open.

        Design: Difficulty/combinatorial_formula/resurvey_interval_multifactor_nonlinear
        """
        def add_g2_leak(ctx):
            make_leak(ctx, ctx["segments"][0]["id"], ctx["run"]["id"])

        ctx = setup_completed_route(
            route_code="R-RS2",
            segment_overrides={
                "segment_code": "SEG-RS2",
                "install_year": 2015,
                "diameter_inches": 24.0,
                "length_feet": 5000.0,
                "operating_pressure_psi": 800.0,
                "pressure_class": "TRANSMISSION",
                "is_high_consequence_area": True,
            },
            distance_covered_feet=5000.0,
            pre_complete=add_g2_leak,
        )
        segment = ctx["segments"][0]
        after = get_success_data(api.get_pipe_segment(segment["id"], ctx["ia_h"]))
        assert_timestamp_eq(after["next_survey_due_at"], "2026-09-15T00:00:00Z",
                            "next_survey_due_at")


class TestRiskScoreVariants:
    def test_provisional_risk_score_at_route_completion(self, api):
        """PRD §3.8: "The score computed at route completion is provisional — it
        snapshots the open-grade counters as they stood at completion time and
        does not reflect leaks verified cleared after the route completed."
        CAST_IRON 1980 (age 46) DISTRIBUTION non-HCA with one open G2 leak:
        46/50*0.20 + 1.0*0.15 + min(1.5, 1)*0.30 = 0.184 + 0.15 + 0.30 = 0.634.

        Design: Difficulty/dual_variant_calc/risk_score_provisional_vs_final
        """
        ctx = _setup_provisional_scenario(api)
        segment = ctx["segments"][0]
        provisional = get_success_data(api.get_pipe_segment(segment["id"], ctx["ia_h"]))
        assert provisional["risk_score"] == pytest.approx(63.4, abs=0.01)
        assert provisional["open_grade2_count"] == 1

    def test_final_risk_score_after_verify_clear(self, api):
        """PRD §3.8: "The score recomputed when a leak is verified cleared or an
        anomaly resolves is the final score — it uses post-event counters and may
        differ from the provisional value by a cent or more for the same
        segment." After the only open G2 leak clears: 0.184 + 0.15 = 0.334.

        Design: Difficulty/dual_variant_calc/risk_score_provisional_vs_final
        """
        ctx = _setup_provisional_scenario(api)
        segment = ctx["segments"][0]
        provisional = get_success_data(api.get_pipe_segment(segment["id"], ctx["ia_h"]))["risk_score"]

        # Repair the leak to REPAIRED_PENDING_VERIFICATION.
        order = get_success_data(api.schedule_repair(
            ctx["leak"]["id"],
            create_schedule_repair_payload(ctx["leak"]["version"]),
            ctx["dc_h"],
        ))
        from test_helpers import make_crew
        crew = make_crew(ctx, crew_code="CR-P1")
        get_success_data(api.dispatch_repair_order(order["id"], {"crew_id": crew["id"]}, ctx["dc_h"]))
        get_success_data(api.arrive_on_site(order["id"], ctx["dc_h"]))
        get_success_data(api.mark_work_complete(order["id"], ctx["dc_h"]))

        # Post-repair leak-free accepted survey satisfies the §3.7 gate.
        from test_helpers import add_post_repair_survey
        add_post_repair_survey(ctx)
        validate_success(api.verify_clear_leak(ctx["leak"]["id"], ctx["co_h"]))

        final = get_success_data(api.get_pipe_segment(segment["id"], ctx["ia_h"]))
        assert final["risk_score"] == pytest.approx(33.4, abs=0.01)
        assert final["risk_score"] < provisional
        assert final["open_grade2_count"] == 0
        leak = get_success_data(api.get_leak(ctx["leak"]["id"], ctx["ia_h"]))
        assert leak["status"] == "VERIFIED_CLEARED"


def _setup_provisional_scenario(api):
    """CAST_IRON/1980/DISTRIBUTION segment; accepted run; one open G2 leak;
    route completed at the 2026-08-01 logical clock (provisional score live)."""
    def add_g2_leak(ctx):
        make_leak(ctx, ctx["segments"][0]["id"], ctx["run"]["id"])

    ctx = setup_completed_route(
        route_code="R-P1",
        segment_overrides={
            "segment_code": "SEG-P1",
            "install_year": 1980,
            "material": "CAST_IRON",
            "diameter_inches": 8.0,
            "length_feet": 2000.0,
            "operating_pressure_psi": 30.0,
        },
        distance_covered_feet=2000.0,
        pre_complete=add_g2_leak,
    )
    ctx["leak"] = ctx["leaks"][-1]
    return ctx


class TestOverdueLeakBoundary:
    def test_overdue_leak_at_exact_due_at_not_overdue(self, api):
        """PRD §3.1: "A leak counts toward `overdue_leak_count` when its status is
        one of `OPEN`, `REPAIR_SCHEDULED`, `UNDER_REPAIR`, or
        `REPAIRED_PENDING_VERIFICATION` and the current logical clock is strictly
        later than the leak's `repair_due_at`; a leak whose `repair_due_at` equals
        the current logical clock exactly is not yet overdue."

        Design: Difficulty/boundary_precision_check/overdue_leak_at_exact_due_at_not_overdue
        """
        ctx = setup_accepted_run(route_code="R-B1")
        segment = ctx["segments"][0]
        make_leak(ctx, segment["id"], ctx["run"]["id"])  # G2 -> due 2026-08-31T00:00:00Z

        set_clock(ctx, "2026-08-31T00:00:00Z")
        at_due = get_success_data(api.get_compliance_summary(segment["id"], ctx["ia_h"]))
        assert at_due["overdue_leak_count"] == 0

        set_clock(ctx, "2026-08-31T00:00:01Z")
        past_due = get_success_data(api.get_compliance_summary(segment["id"], ctx["ia_h"]))
        assert past_due["overdue_leak_count"] == 1

    def test_overdue_g1_leak_boundary_one_day_clock(self, api):
        """PRD §3.1: "the current logical clock is strictly later than the leak's
        `repair_due_at`; a leak whose `repair_due_at` equals the current logical
        clock exactly is not yet overdue" — same strict-greater boundary on the
        1-day G1 repair clock (PRD §3.5: "plus 1 day for `G1`").

        Design: Difficulty/boundary_precision_check/overdue_leak_at_exact_due_at_not_overdue
        """
        ctx = setup_accepted_run(route_code="R-B2")
        segment = ctx["segments"][0]
        make_leak(
            ctx, segment["id"], ctx["run"]["id"],
            concentration_ppm=30000.0, distance_to_building_feet=2.0,
            bar_hole_reading_pct_lel=40.0, is_migration_evidence=True,
        )  # G1 -> due 2026-08-02T00:00:00Z

        set_clock(ctx, "2026-08-02T00:00:00Z")
        at_due = get_success_data(api.get_compliance_summary(segment["id"], ctx["ia_h"]))
        assert at_due["overdue_leak_count"] == 0

        set_clock(ctx, "2026-08-02T00:00:01Z")
        past_due = get_success_data(api.get_compliance_summary(segment["id"], ctx["ia_h"]))
        assert past_due["overdue_leak_count"] == 1

    def test_compliance_summary_returns_derived_fields(self, api):
        """PRD §3.1: "a derived compliance summary exposing the segment's
        `overdue_leak_count`, current `posture`, `next_survey_due_at`, the three
        open-grade counters, and the current `risk_score`." With one open G2 leak
        at the discovery instant: overdue 0, `posture` `ELEVATED` (PRD §2.8:
        "Otherwise, if it has exactly one open Grade 2 leak, or at least one
        cathodic-protection anomaly in `OPEN` or `ACKNOWLEDGED` status, posture is
        `ELEVATED`.").

        Design: Corner/endpoints/compliance_summary_returns_derived_fields
        """
        ctx = setup_accepted_run(route_code="R-CS")
        segment = ctx["segments"][0]
        make_leak(ctx, segment["id"], ctx["run"]["id"])
        data = get_success_data(api.get_compliance_summary(segment["id"], ctx["ia_h"]))
        assert data["overdue_leak_count"] == 0
        assert data["posture"] == "ELEVATED"
        assert data["open_grade2_count"] == 1
