"""Drill execution and evacuation timing assessment: provisional vs official
seconds, standard vs unannounced-adjusted met-target flags, exact boundary
behavior, and the roster-completeness completion gate."""
from test_helpers import (
    ApiErrorId,
    add_roster_entry,
    get_drill,
    schedule_drill,
    set_clock,
    setup_active_eop_site,
    setup_site_with_requirement,
    start_drill_on,
    validate_error,
    validate_success,
)


def _run_unannounced_drill_360(ctx):
    """UNANNOUNCED FIRE drill on 2026-09-15: start 09:00, sole roster student
    accounted at 09:06:00, all-clear at 09:06:00."""
    site_id = ctx["site"]["id"]
    drill = schedule_drill(site_id, scheduled_date="2026-09-15",
                           announcement_mode="UNANNOUNCED")
    start_drill_on(drill["id"], "2026-09-15", "09:00")
    entry = add_roster_entry(drill["id"], student_ref="stu-1")
    set_clock("2026-09-15T09:06:00Z")
    return drill, entry


class TestDualVariantEvacTiming:
    def test_evac_timing_seconds_and_completion(self, api, officer_headers):
        """PRD: "First, `provisional_evac_seconds` is the raw wall-clock elapsed time from `actual_start_at` to `all_clear_at` in integer seconds. Second, the system determines `last_accountability_at` — the maximum timestamp across all roster entries, using each entry's `released_at` if the entry is `RELEASED` and its `accounted_at` otherwise."
        PRD: "The `official_evac_seconds` is then the elapsed time from `actual_start_at` to `last_accountability_at` in integer seconds; when the roster is empty it equals `provisional_evac_seconds`."

        Design: Difficulty/dual_variant_calc/evac_timing_standard_vs_unannounced_adjusted
        """
        ctx = setup_active_eop_site(
            requirement_overrides={"required_per_year": 2,
                                   "min_spacing_days": 20,
                                   "target_evac_seconds": 300})
        drill, entry = _run_unannounced_drill_360(ctx)
        api.account_roster_entry(entry["id"], officer_headers)

        completed = validate_success(
            api.complete_drill(drill["id"], {}, officer_headers), 200)
        assert completed["status"] == "COMPLETED"
        assert completed["provisional_evac_seconds"] == 360, (
            f"09:00:00 -> 09:06:00 all-clear is 360s, "
            f"got {completed['provisional_evac_seconds']}")
        assert completed["official_evac_seconds"] == 360, (
            f"last accountability at 09:06:00 gives 360s, "
            f"got {completed['official_evac_seconds']}")

    def test_evac_timing_standard_vs_adjusted_flags(self, api, officer_headers):
        """PRD: "The standard flag, `met_target_standard`, is true when `official_evac_seconds` is less than or equal to the `target_evac_seconds` from the DrillTypeRequirement matching the drill's site and type. The adjusted flag, `met_target_adjusted`, applies only when the drill's `announcement_mode` is `UNANNOUNCED`: in that case the target is increased by a 25 percent allowance — computed as `target_evac_seconds` multiplied by 0.25, with the result rounded up to the nearest whole second — and `met_target_adjusted` is true when `official_evac_seconds` is less than or equal to the adjusted target. When `announcement_mode` is `ANNOUNCED`, `met_target_adjusted` mirrors `met_target_standard` exactly."

        Design: Difficulty/dual_variant_calc/evac_timing_standard_vs_unannounced_adjusted
        """
        ctx = setup_active_eop_site(
            requirement_overrides={"required_per_year": 2,
                                   "min_spacing_days": 20,
                                   "target_evac_seconds": 300})
        drill, entry = _run_unannounced_drill_360(ctx)
        api.account_roster_entry(entry["id"], officer_headers)

        completed = validate_success(
            api.complete_drill(drill["id"], {}, officer_headers), 200)
        # official 360 vs target 300: standard fails; adjusted target is
        # 300 + ceil(300 * 0.25) = 375, so the adjusted variant passes on
        # identical timing data.
        assert completed["met_target_standard"] is False
        assert completed["met_target_adjusted"] is True


class TestEvacSecondsBoundary:
    def test_official_seconds_exactly_target_meets(self, api, officer_headers):
        """PRD: "The standard flag, `met_target_standard`, is true when `official_evac_seconds` is less than or equal to the `target_evac_seconds` from the DrillTypeRequirement matching the drill's site and type."

        Design: Difficulty/boundary_precision_check/evac_seconds_exactly_target_boundary
        """
        ctx = setup_active_eop_site(
            requirement_overrides={"required_per_year": 2,
                                   "min_spacing_days": 0,
                                   "target_evac_seconds": 300})
        site_id = ctx["site"]["id"]
        drill = schedule_drill(site_id, scheduled_date="2026-09-15")
        start_drill_on(drill["id"], "2026-09-15", "09:00")
        entry = add_roster_entry(drill["id"], student_ref="stu-1")
        set_clock("2026-09-15T09:05:00Z")
        api.account_roster_entry(entry["id"], officer_headers)

        completed = validate_success(
            api.complete_drill(drill["id"], {}, officer_headers), 200)
        assert completed["official_evac_seconds"] == 300
        assert completed["met_target_standard"] is True, (
            "official_evac_seconds == target_evac_seconds meets the target (<=)")

    def test_official_seconds_one_over_target_misses(self, api,
                                                     officer_headers):
        """PRD: "The standard flag, `met_target_standard`, is true when `official_evac_seconds` is less than or equal to the `target_evac_seconds` from the DrillTypeRequirement matching the drill's site and type."

        Design: Difficulty/boundary_precision_check/evac_seconds_exactly_target_boundary
        """
        ctx = setup_active_eop_site(
            requirement_overrides={"required_per_year": 2,
                                   "min_spacing_days": 0,
                                   "target_evac_seconds": 300})
        site_id = ctx["site"]["id"]
        drill_a = schedule_drill(site_id, scheduled_date="2026-09-15")
        start_drill_on(drill_a["id"], "2026-09-15", "09:00")
        entry_a = add_roster_entry(drill_a["id"], student_ref="stu-1")
        set_clock("2026-09-15T09:05:00Z")
        api.account_roster_entry(entry_a["id"], officer_headers)
        validate_success(api.complete_drill(drill_a["id"], {}, officer_headers),
                         200)

        drill_b = schedule_drill(site_id, scheduled_date="2026-09-16")
        start_drill_on(drill_b["id"], "2026-09-16", "09:00")
        entry_b = add_roster_entry(drill_b["id"], student_ref="stu-1")
        set_clock("2026-09-16T09:05:01Z")
        api.account_roster_entry(entry_b["id"], officer_headers)

        completed_b = validate_success(
            api.complete_drill(drill_b["id"], {}, officer_headers), 200)
        assert completed_b["official_evac_seconds"] == 301
        assert completed_b["met_target_standard"] is False, (
            "official_evac_seconds == target + 1 must NOT meet the target")


class TestOfficialVsProvisional:
    def test_official_seconds_differ_from_provisional(self, api,
                                                      officer_headers):
        """PRD: "First, `provisional_evac_seconds` is the raw wall-clock elapsed time from `actual_start_at` to `all_clear_at` in integer seconds. Second, the system determines `last_accountability_at` — the maximum timestamp across all roster entries, using each entry's `released_at` if the entry is `RELEASED` and its `accounted_at` otherwise. When the roster is empty, `last_accountability_at` is set equal to `all_clear_at`. The `official_evac_seconds` is then the elapsed time from `actual_start_at` to `last_accountability_at` in integer seconds; when the roster is empty it equals `provisional_evac_seconds`."

        Design: Corner/calculations/official_seconds_differ_from_provisional
        """
        ctx = setup_active_eop_site()
        site_id = ctx["site"]["id"]
        drill = schedule_drill(site_id, scheduled_date="2026-09-15")
        start_drill_on(drill["id"], "2026-09-15", "09:00")
        entry = add_roster_entry(drill["id"], student_ref="stu-1")
        set_clock("2026-09-15T09:04:00Z")
        api.account_roster_entry(entry["id"], officer_headers)
        set_clock("2026-09-15T09:05:00Z")

        completed = validate_success(
            api.complete_drill(drill["id"], {}, officer_headers), 200)
        assert completed["provisional_evac_seconds"] == 300, (
            "all-clear at 09:05 gives 300s provisional")
        assert completed["official_evac_seconds"] == 240, (
            "accountability completed at 09:04 gives 240s official")
        assert completed["met_target_standard"] is True, (
            "240 <= 300 meets the standard target")


class TestCompletionGates:
    def test_complete_from_scheduled_returns_invalid_state(self, api,
                                                           officer_headers):
        """PRD: "Completing a drill — moving it from `IN_PROGRESS` to `COMPLETED` — requires every roster entry to be resolved: each must be in `ACCOUNTED` or `RELEASED` status."
        PRD: "(5) state validity — the target resource must be in a state from which the requested transition exists, else `ERR_INVALID_STATE`"

        Design: Corner/state_machines/complete_from_scheduled_returns_invalid_state
        """
        ctx = setup_site_with_requirement(site_name="Cedar Grove High",
                                          enrollment_count=1200)
        drill = schedule_drill(ctx["site"]["id"], scheduled_date="2026-09-15")
        set_clock("2026-09-15T09:00:00Z")

        resp = api.complete_drill(drill["id"], {}, officer_headers)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

        current = get_drill(drill["id"])
        assert current["status"] == "SCHEDULED"

    def test_completion_blocked_while_roster_unresolved(self, api,
                                                        officer_headers):
        """PRD: "Completing a drill — moving it from `IN_PROGRESS` to `COMPLETED` — requires every roster entry to be resolved: each must be in `ACCOUNTED` or `RELEASED` status. If any entry remains `UNACCOUNTED`, the completion is rejected with `ERR_ROSTER_INCOMPLETE`. This check is vacuously satisfied when the roster is empty."

        Design: Difficulty/cross_entity_state_dependency/drill_completion_requires_roster_resolved
        """
        ctx = setup_active_eop_site()
        drill = schedule_drill(ctx["site"]["id"], scheduled_date="2026-09-15")
        start_drill_on(drill["id"], "2026-09-15", "09:00")
        add_roster_entry(drill["id"], student_ref="stu-1")

        resp = api.complete_drill(drill["id"], {}, officer_headers)
        validate_error(resp, ApiErrorId.ERR_ROSTER_INCOMPLETE)

        current = get_drill(drill["id"])
        assert current["status"] == "IN_PROGRESS", (
            "A rejected completion must leave the drill IN_PROGRESS")
        assert current["unaccounted_count"] == 1

    def test_completion_succeeds_after_roster_resolved(self, api,
                                                       officer_headers):
        """PRD: "Completing a drill — moving it from `IN_PROGRESS` to `COMPLETED` — requires every roster entry to be resolved: each must be in `ACCOUNTED` or `RELEASED` status. If any entry remains `UNACCOUNTED`, the completion is rejected with `ERR_ROSTER_INCOMPLETE`. This check is vacuously satisfied when the roster is empty."

        Design: Difficulty/cross_entity_state_dependency/drill_completion_requires_roster_resolved
        """
        ctx = setup_active_eop_site()
        drill = schedule_drill(ctx["site"]["id"], scheduled_date="2026-09-15")
        start_drill_on(drill["id"], "2026-09-15", "09:00")
        entry = add_roster_entry(drill["id"], student_ref="stu-1")

        blocked = api.complete_drill(drill["id"], {}, officer_headers)
        validate_error(blocked, ApiErrorId.ERR_ROSTER_INCOMPLETE)

        api.account_roster_entry(entry["id"], officer_headers)
        completed = validate_success(
            api.complete_drill(drill["id"], {}, officer_headers), 200)
        assert completed["status"] == "COMPLETED"
        assert completed["accounted_count"] == 1
        assert completed["unaccounted_count"] == 0
