"""Compliance reporting: statutory attainment (count-only vs strict spacing
variants), pinned rounding order in the overall score, exact count boundary,
period overlap semantics, staleness cascades, and posture derivation."""
import pytest

from test_helpers import (
    ApiErrorId,
    complete_drill_at,
    create_compliance_report,
    create_compliance_report_payload,
    get_compliance_report,
    get_drill,
    get_site,
    get_type_attainment,
    run_completed_drill,
    schedule_drill,
    set_clock,
    setup_active_eop_site,
    setup_site_with_requirement,
    start_drill_on,
    validate_error,
    validate_success,
)


def _two_clustered_fire_drills(ctx):
    """Two FIRE drills completed five days apart (below a 20-day spacing)."""
    site_id = ctx["site"]["id"]
    run_completed_drill(site_id, scheduled_date="2026-09-15")
    run_completed_drill(site_id, scheduled_date="2026-09-20")


class TestDualVariantAttainment:
    def test_attainment_per_type_flags(self, api):
        """PRD: "The `attainment_count_only` flag is true when the completed count is at least the required count. The `spacing_compliant` flag checks ordering: the counted drills are ordered by `scheduled_date` ascending (with ties broken by `created_at` ascending), and for every consecutive pair the number of whole calendar days between their scheduled dates must be at least the requirement's `min_spacing_days`. When fewer than 2 drills are counted, spacing compliance is vacuously true. The `attainment_strict` flag is true when both the count threshold is met and spacing is compliant."

        Design: Difficulty/dual_variant_calc/attainment_count_only_vs_count_and_spacing
        """
        ctx = setup_active_eop_site(site_name="Harborview Middle",
                                    enrollment_count=700)
        _two_clustered_fire_drills(ctx)

        report = create_compliance_report(ctx["site"]["id"])
        attainment = get_type_attainment(report, "FIRE")
        assert attainment["completed_count"] == 2
        assert attainment["required_count"] == 2
        assert attainment["spacing_compliant"] is False, (
            "5-day gap < 20-day min_spacing_days must fail spacing")
        assert attainment["attainment_count_only"] is True, (
            "2 >= 2 satisfies the count_only variant on identical data")
        assert attainment["attainment_strict"] is False

    def test_attainment_overall_flags(self, api):
        """PRD: "`overall_compliant_count_only` is the conjunction of `attainment_count_only` across all configured types — true only when every configured type meets its count threshold. `overall_compliant_strict` is the conjunction of `attainment_strict` across all configured types — true only when every type meets both count and spacing."

        Design: Difficulty/dual_variant_calc/attainment_count_only_vs_count_and_spacing
        """
        ctx = setup_active_eop_site(site_name="Harborview Middle",
                                    enrollment_count=700)
        _two_clustered_fire_drills(ctx)

        report = create_compliance_report(ctx["site"]["id"])
        assert report["overall_compliant_count_only"] is True
        assert report["overall_compliant_strict"] is False, (
            "Identical drill data yields opposite verdicts across the two "
            "variants when spacing fails")


class TestSpacingBranchPersistence:
    def test_clustered_pair_persists_despite_third_spaced_drill(self, api):
        """PRD: "The `spacing_compliant` flag checks ordering: the counted drills are ordered by `scheduled_date` ascending (with ties broken by `created_at` ascending), and for every consecutive pair the number of whole calendar days between their scheduled dates must be at least the requirement's `min_spacing_days`. When fewer than 2 drills are counted, spacing compliance is vacuously true."

        Design: Difficulty/combinatorial_formula/strict_attainment_spacing_branch_persistence
        """
        ctx = setup_active_eop_site(site_name="Cedar Grove High",
                                    enrollment_count=1200)
        site_id = ctx["site"]["id"]
        run_completed_drill(site_id, scheduled_date="2026-09-15")
        run_completed_drill(site_id, scheduled_date="2026-09-17")  # gap 2 < 20
        run_completed_drill(site_id, scheduled_date="2026-10-20")  # gap 33

        report = create_compliance_report(site_id)
        attainment = get_type_attainment(report, "FIRE")
        assert attainment["completed_count"] == 3
        assert attainment["spacing_compliant"] is False, (
            "The 2-day clustered pair persists; a third well-spaced drill "
            "does not wash it out")

    def test_clustered_pair_count_variant_still_satisfied(self, api):
        """PRD: "The `attainment_count_only` flag is true when the completed count is at least the required count."
        PRD: "The `attainment_strict` flag is true when both the count threshold is met and spacing is compliant."

        Design: Difficulty/combinatorial_formula/strict_attainment_spacing_branch_persistence
        """
        ctx = setup_active_eop_site(site_name="Cedar Grove High",
                                    enrollment_count=1200)
        site_id = ctx["site"]["id"]
        run_completed_drill(site_id, scheduled_date="2026-09-15")
        run_completed_drill(site_id, scheduled_date="2026-09-17")
        run_completed_drill(site_id, scheduled_date="2026-10-20")

        report = create_compliance_report(site_id)
        attainment = get_type_attainment(report, "FIRE")
        assert attainment["attainment_count_only"] is True, (
            "3 >= 2 satisfies the count_only variant")
        assert attainment["attainment_strict"] is False, (
            "strict requires BOTH count and spacing; spacing fails")


class TestOverallScoreRoundingOrder:
    def _build_three_type_scenario(self):
        """FIRE 3/4, EVACUATION 1/7, EARTHQUAKE 3/7 completed drills."""
        ctx = setup_active_eop_site(
            site_name="Maplewood K-8", enrollment_count=850,
            requirement_overrides={"drill_type": "FIRE", "required_per_year": 4,
                                   "min_spacing_days": 0,
                                   "target_evac_seconds": 300},
            extra_requirements=[
                {"drill_type": "EVACUATION", "required_per_year": 7,
                 "min_spacing_days": 0, "target_evac_seconds": 240},
                {"drill_type": "EARTHQUAKE", "required_per_year": 7,
                 "min_spacing_days": 0, "target_evac_seconds": 300},
            ])
        site_id = ctx["site"]["id"]
        run_completed_drill(site_id, drill_type="FIRE",
                            scheduled_date="2026-09-01")
        run_completed_drill(site_id, drill_type="EVACUATION",
                            scheduled_date="2026-09-02")
        run_completed_drill(site_id, drill_type="EARTHQUAKE",
                            scheduled_date="2026-09-03")
        run_completed_drill(site_id, drill_type="FIRE",
                            scheduled_date="2026-09-08")
        run_completed_drill(site_id, drill_type="EARTHQUAKE",
                            scheduled_date="2026-09-10")
        run_completed_drill(site_id, drill_type="FIRE",
                            scheduled_date="2026-09-15")
        run_completed_drill(site_id, drill_type="EARTHQUAKE",
                            scheduled_date="2026-09-17")
        return ctx

    def test_overall_score_per_type_counts(self, api):
        """PRD: "The system computes the statutory attainment snapshot: for each DrillTypeRequirement configured at the site, it counts the drills with matching `drill_type`, in `COMPLETED` or `CLOSED` status, whose `scheduled_date` falls within the closed interval from `period_start` through `period_end`."

        Design: Difficulty/combinatorial_formula/overall_score_rounding_order_pinned
        """
        ctx = self._build_three_type_scenario()
        report = create_compliance_report(ctx["site"]["id"])
        assert get_type_attainment(report, "FIRE")["completed_count"] == 3
        assert get_type_attainment(report, "EVACUATION")["completed_count"] == 1
        assert get_type_attainment(report, "EARTHQUAKE")["completed_count"] == 3

    def test_overall_score_rounding_order_pinned(self, api):
        """PRD: "For each configured type, a per-type ratio is computed as the lesser of 1.0 and the quotient of completed count divided by required count, rounded half-up to 4 decimal places. These rounded ratios are then summed and divided by the number of configured types, the result multiplied by 100, and the product rounded half-up to 1 decimal place. The per-type ratios must be rounded to 4 decimal places before averaging; averaging raw ratios and rounding once at the end produces a different, non-compliant result."

        Design: Difficulty/combinatorial_formula/overall_score_rounding_order_pinned
        """
        ctx = self._build_three_type_scenario()
        report = create_compliance_report(ctx["site"]["id"])
        # Pinned order: round4(3/4)=0.7500, round4(1/7)=0.1429,
        # round4(3/7)=0.4286; sum 1.3215; /3 = 0.4405; x100 = 44.05 -> 44.1.
        assert report["overall_score_pct"] == pytest.approx(44.1, abs=0.01), (
            f"Pinned rounding order must publish 44.1, "
            f"got {report['overall_score_pct']}")


class TestAttainmentCountBoundary:
    def test_one_below_required_count_fails_attainment(self, api):
        """PRD: "The `attainment_count_only` flag is true when the completed count is at least the required count."

        Design: Difficulty/boundary_precision_check/attainment_count_exactly_required_boundary
        """
        ctx = setup_active_eop_site(site_name="Harborview Middle",
                                    enrollment_count=700)
        site_id = ctx["site"]["id"]
        run_completed_drill(site_id, scheduled_date="2026-09-15")

        report = create_compliance_report(site_id)
        attainment = get_type_attainment(report, "FIRE")
        assert attainment["completed_count"] == 1
        assert attainment["attainment_count_only"] is False, (
            "1 completed of 2 required is one below the >= boundary")
        assert report["overall_compliant_count_only"] is False

    def test_exactly_required_count_satisfies_attainment(self, api,
                                                         coordinator_headers):
        """PRD: "The `attainment_count_only` flag is true when the completed count is at least the required count."
        PRD: "A report in `DRAFT` transitions to `STALE` whenever any drill at the same site whose `scheduled_date` lies within the report's period is created or changes status after `snapshot_generated_at`, or whenever any DrillTypeRequirement at the site is created or updated."
        PRD: "Regeneration is available from either `STALE` or `REJECTED`: the coordinator regenerates the report, which recomputes the full snapshot (statutory attainment and overall score), stamps `snapshot_generated_at` anew, and moves the report back to `DRAFT`."

        Design: Difficulty/boundary_precision_check/attainment_count_exactly_required_boundary
        """
        ctx = setup_active_eop_site(site_name="Harborview Middle",
                                    enrollment_count=700)
        site_id = ctx["site"]["id"]
        run_completed_drill(site_id, scheduled_date="2026-09-15")
        report = create_compliance_report(site_id)

        # Scheduling the second drill stales the covering DRAFT report.
        drill_two = schedule_drill(site_id, scheduled_date="2026-10-10")
        stale = get_compliance_report(site_id, report["id"])
        assert stale["status"] == "STALE", (
            "Creating a drill inside the report period must stale the DRAFT")

        start_drill_on(drill_two["id"], "2026-10-10", "09:00")
        complete_drill_at(drill_two["id"], "2026-10-10", "09:04")

        regenerated = api.regenerate_compliance_report(report["id"],
                                                       coordinator_headers)
        data = validate_success(regenerated, 200)
        assert data["status"] == "DRAFT"
        attainment = get_type_attainment(data, "FIRE")
        assert attainment["completed_count"] == 2
        assert attainment["attainment_count_only"] is True, (
            "2 == 2 satisfies the >= boundary exactly")
        assert attainment["attainment_strict"] is True, (
            "25-day gap >= 20-day min_spacing_days keeps strict compliant")
        assert data["overall_score_pct"] == pytest.approx(100.0, abs=0.01)


class TestMissedDrillExclusion:
    def test_missed_drill_excluded_from_attainment(self, api):
        """PRD: "The system computes the statutory attainment snapshot: for each DrillTypeRequirement configured at the site, it counts the drills with matching `drill_type`, in `COMPLETED` or `CLOSED` status, whose `scheduled_date` falls within the closed interval from `period_start` through `period_end`."

        Design: Corner/calculations/missed_drill_excluded_from_attainment
        """
        ctx = setup_active_eop_site(
            site_name="Harborview Middle", enrollment_count=700,
            requirement_overrides={"min_spacing_days": 0})
        site_id = ctx["site"]["id"]
        run_completed_drill(site_id, scheduled_date="2026-09-15")
        drill_b = schedule_drill(site_id, scheduled_date="2026-09-20")
        set_clock("2026-09-21T00:00:00Z")

        missed = get_drill(drill_b["id"])
        assert missed["status"] == "MISSED"

        report = create_compliance_report(site_id)
        attainment = get_type_attainment(report, "FIRE")
        assert attainment["completed_count"] == 1, (
            "The MISSED drill is excluded from the attainment input set")
        assert attainment["attainment_count_only"] is False
        assert report["overall_compliant_count_only"] is False


class TestReportPeriodOverlap:
    def test_touching_boundary_period_rejected(self, api, coordinator_headers):
        """PRD: "Report periods may not overlap: the closed interval from `period_start` through `period_end` must not intersect any other report at the same site that is in `DRAFT`, `STALE`, `SUBMITTED`, or `ACCEPTED` status. Two periods sharing even a single boundary date do overlap. A violation is rejected with `ERR_REPORT_PERIOD_OVERLAP`."

        Design: Difficulty/resource_temporal_overlap/report_period_closed_interval_touch
        """
        ctx = setup_site_with_requirement(site_name="Harborview Middle",
                                          enrollment_count=700)
        site_id = ctx["site"]["id"]
        report_a = create_compliance_report(site_id, period_start="2026-08-01",
                                            period_end="2026-12-31")

        # Report B shares the boundary date 2026-12-31 — closed-interval overlap.
        touching = api.create_compliance_report(
            create_compliance_report_payload(site_id=site_id,
                                             period_start="2026-12-31",
                                             period_end="2027-06-30"),
            coordinator_headers,
        )
        validate_error(touching, ApiErrorId.ERR_REPORT_PERIOD_OVERLAP)

        unchanged = get_compliance_report(site_id, report_a["id"])
        assert unchanged["status"] == "DRAFT"

    def test_gap_starting_period_allowed(self, api, coordinator_headers):
        """PRD: "Report periods may not overlap: the closed interval from `period_start` through `period_end` must not intersect any other report at the same site that is in `DRAFT`, `STALE`, `SUBMITTED`, or `ACCEPTED` status. Two periods sharing even a single boundary date do overlap. A violation is rejected with `ERR_REPORT_PERIOD_OVERLAP`."

        Design: Difficulty/resource_temporal_overlap/report_period_closed_interval_touch
        """
        ctx = setup_site_with_requirement(site_name="Harborview Middle",
                                          enrollment_count=700)
        site_id = ctx["site"]["id"]
        create_compliance_report(site_id, period_start="2026-08-01",
                                 period_end="2026-12-31")

        # Report C starts the day AFTER report A's period ends — no overlap.
        created = api.create_compliance_report(
            create_compliance_report_payload(site_id=site_id,
                                             period_start="2027-01-01",
                                             period_end="2027-06-30"),
            coordinator_headers,
        )
        report_c = validate_success(created, 201)
        assert report_c["status"] == "DRAFT"
        assert report_c["period_start"] == "2027-01-01"


class TestStalenessCascade:
    def test_missed_drill_cascade_drill_and_counters(self, api,
                                                     coordinator_headers):
        """PRD: "if logical today passes a drill's `scheduled_date` while the drill is still `SCHEDULED` or `IN_PROGRESS`, the drill transitions to `MISSED`. Both variants — never started, or started but never completed — produce the same side effects: site drill counters recompute, `compliance_posture` recomputes (a `MISSED` drill in the current academic year forces at least `AT_RISK`), and covering `DRAFT` reports transition to `STALE`."

        Design: Difficulty/transitive_cascade/missed_drill_cascade_marks_report_stale
        """
        ctx = setup_site_with_requirement(site_name="Cedar Grove High",
                                          enrollment_count=1200)
        site_id = ctx["site"]["id"]
        drill = schedule_drill(site_id, scheduled_date="2026-09-10")
        create_compliance_report(site_id)

        set_clock("2026-09-11T00:00:00Z")

        current = get_drill(drill["id"])
        assert current["status"] == "MISSED", (
            "The sweep must flip the never-started drill to MISSED")
        site = get_site(site_id)
        assert site["drills_missed_count"] == 1
        assert site["drills_scheduled_count"] == 0

    def test_missed_drill_cascade_posture_and_report(self, api):
        """PRD: "if logical today passes a drill's `scheduled_date` while the drill is still `SCHEDULED` or `IN_PROGRESS`, the drill transitions to `MISSED`. Both variants — never started, or started but never completed — produce the same side effects: site drill counters recompute, `compliance_posture` recomputes (a `MISSED` drill in the current academic year forces at least `AT_RISK`), and covering `DRAFT` reports transition to `STALE`."

        Design: Difficulty/transitive_cascade/missed_drill_cascade_marks_report_stale
        """
        ctx = setup_site_with_requirement(site_name="Cedar Grove High",
                                          enrollment_count=1200)
        site_id = ctx["site"]["id"]
        schedule_drill(site_id, scheduled_date="2026-09-10")
        report = create_compliance_report(site_id)
        assert report["status"] == "DRAFT"

        set_clock("2026-09-11T00:00:00Z")

        site = get_site(site_id)
        assert site["compliance_posture"] == "AT_RISK", (
            "A MISSED drill in the current academic year forces at least AT_RISK")
        stale = get_compliance_report(site_id, report["id"])
        assert stale["status"] == "STALE", (
            "The covering DRAFT report must transition to STALE")

    def test_submit_stale_report_returns_invalid_state(self, api,
                                                       coordinator_headers):
        """PRD: "A `DistrictSafetyCoordinator` submits a `DRAFT` report to the state, moving it to `SUBMITTED` and stamping `submitted_at` with the logical timestamp."
        PRD: "Regeneration is available from either `STALE` or `REJECTED`: the coordinator regenerates the report, which recomputes the full snapshot (statutory attainment and overall score), stamps `snapshot_generated_at` anew, and moves the report back to `DRAFT`."

        Design: Corner/state_machines/submit_stale_report_returns_invalid_state
        """
        ctx = setup_site_with_requirement(site_name="Cedar Grove High",
                                          enrollment_count=1200)
        site_id = ctx["site"]["id"]
        schedule_drill(site_id, scheduled_date="2026-09-10")
        report = create_compliance_report(site_id)
        set_clock("2026-09-11T00:00:00Z")

        stale = get_compliance_report(site_id, report["id"])
        assert stale["status"] == "STALE"

        blocked = api.submit_compliance_report(report["id"],
                                               coordinator_headers)
        validate_error(blocked, ApiErrorId.ERR_INVALID_STATE)

        regenerated = api.regenerate_compliance_report(report["id"],
                                                       coordinator_headers)
        assert validate_success(regenerated, 200)["status"] == "DRAFT"

        submitted = api.submit_compliance_report(report["id"],
                                                 coordinator_headers)
        assert validate_success(submitted, 200)["status"] == "SUBMITTED", (
            "After regeneration the report is submittable again")


class TestPostureDerivation:
    def test_posture_non_compliant_after_year_end(self, api):
        """PRD: "The posture is `NON_COMPLIANT` when either of two conditions holds: logical today has passed the site's `academic_year_end` and any configured requirement's completed-drill count for the current academic year (drills in `COMPLETED` or `CLOSED` status with `scheduled_date` inside the academic year) falls below that requirement's `required_per_year`; or the number of overdue corrective actions reaches 3 or more."

        Design: Corner/calculations/posture_non_compliant_after_year_end
        """
        ctx = setup_site_with_requirement(site_name="Maplewood K-8",
                                          enrollment_count=850)
        site_id = ctx["site"]["id"]

        set_clock("2027-07-01T00:00:00Z")

        site = get_site(site_id)
        assert site["compliance_posture"] == "NON_COMPLIANT", (
            "Year end passed with 0 of 2 required drills completed must yield "
            "NON_COMPLIANT")
