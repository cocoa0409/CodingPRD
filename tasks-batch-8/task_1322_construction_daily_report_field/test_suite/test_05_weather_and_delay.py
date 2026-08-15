"""Weather lost-time variants, lost-hours clipping, delay overlap and finalize."""
import pytest

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    add_crew_entry,
    add_delay_event,
    add_weather_observation,
    get_delay_event,
    get_report,
    make_active_project,
    make_classified_delay,
    make_owner_rep_headers,
    make_report,
    make_report_bundle,
    make_work_area,
    set_clock,
    validate_error,
    validate_success,
)

_ADMIN = TEST_USERS["system_admin_headers"]
_PM = TEST_USERS["project_manager_headers"]
_SUPT = TEST_USERS["superintendent_headers"]


class TestLostDayDualVariant:
    def test_below_half_shift_calendar_false_fraction_prorated(self, api):
        """PRD section 3.4: "The calendar-day variant, `weather_lost_day_calendar`,
        is a boolean that is true exactly when the lost hours reach at least half
        of the project's `scheduled_shift_hours` — at exactly half the shift, the
        day counts as lost. The prorated variant, `weather_lost_day_fraction`, is
        the lost hours divided by `scheduled_shift_hours`, capped at one, and
        rounded half-up to two decimal places."

        Design: Difficulty/dual_variant_calc/lost_day_calendar_vs_prorated
        """
        ctx = make_report_bundle(with_weather=False, with_crew=False,
                                 project_overrides={"scheduled_shift_hours": 8})
        rid, aid = ctx["report"]["id"], ctx["area"]["id"]
        add_weather_observation(rid, observed_at="2026-08-05T08:00:00Z",
                                condition="RAIN", work_impact="STOPPAGE",
                                precipitation_in=0.4)
        event = make_classified_delay(rid, aid, "EXCUSABLE_NON_COMPENSABLE",
                                      start_at="2026-08-05T07:30:00Z",
                                      end_at="2026-08-05T10:30:00Z",
                                      cause="WEATHER")
        assert event["lost_hours"] == pytest.approx(3.00, abs=1e-9)

        report = get_report(rid)
        assert report["weather_lost_hours"] == pytest.approx(3.00, abs=1e-9)
        # Same input set, two variants: 3.00 < 4.00 -> calendar False,
        # 3.00 / 8 = 0.375 -> fraction 0.38 (round half-up, 2dp).
        assert report["weather_lost_day_calendar"] is False
        assert report["weather_lost_day_fraction"] == pytest.approx(0.38, abs=1e-9)

    def test_above_half_shift_calendar_true(self, api):
        """PRD section 3.4: "The calendar-day variant, `weather_lost_day_calendar`,
        is a boolean that is true exactly when the lost hours reach at least half
        of the project's `scheduled_shift_hours`"; "The prorated variant,
        `weather_lost_day_fraction`, is the lost hours divided by
        `scheduled_shift_hours`, capped at one, and rounded half-up to two
        decimal places."

        Design: Difficulty/dual_variant_calc/lost_day_calendar_vs_prorated
        """
        ctx = make_report_bundle(with_weather=False, with_crew=False,
                                 project_overrides={"scheduled_shift_hours": 8})
        rid, aid = ctx["report"]["id"], ctx["area"]["id"]
        event = make_classified_delay(rid, aid, "EXCUSABLE_NON_COMPENSABLE",
                                      start_at="2026-08-05T07:00:00Z",
                                      end_at="2026-08-05T13:00:00Z",
                                      cause="WEATHER")
        assert event["lost_hours"] == pytest.approx(6.00, abs=1e-9)

        report = get_report(rid)
        assert report["weather_lost_hours"] == pytest.approx(6.00, abs=1e-9)
        assert report["weather_lost_day_calendar"] is True  # 6.00 >= 4.00
        assert report["weather_lost_day_fraction"] == pytest.approx(0.75, abs=1e-9)


class TestLostHoursClipping:
    def test_lost_hours_clipped_to_shift_window(self, api):
        """PRD section 3.4: "The lost hours are the length of the intersection
        of the two windows, in hours, rounded half-up to two decimal places. A
        delay lying entirely outside the shift yields exactly zero, and a delay
        that merely touches the shift boundary contributes zero as well."

        Design: Corner/calculations/lost_hours_clipped_to_shift_window
        """
        project = make_active_project(scheduled_shift_hours=8)
        area = make_work_area(project["id"])
        report = make_report(project["id"])

        d1 = make_classified_delay(report["id"], area["id"], "NON_EXCUSABLE",
                                   start_at="2026-08-05T13:00:00Z",
                                   end_at="2026-08-05T18:00:00Z",
                                   cause="MATERIAL")
        assert d1["lost_hours"] == pytest.approx(2.00, abs=1e-9), \
            "13:00-18:00 clips at the 15:00 shift end (07:00 + 8h)"

        d2 = make_classified_delay(report["id"], area["id"], "NON_EXCUSABLE",
                                   start_at="2026-08-05T18:00:00Z",
                                   end_at="2026-08-05T19:00:00Z",
                                   cause="MATERIAL")
        assert d2["lost_hours"] == pytest.approx(0.00, abs=1e-9), \
            "a delay lying entirely outside the shift yields exactly zero"


class TestWeatherTotalsInputSet:
    def test_disputed_events_drop_out_of_weather_totals(self, api):
        """PRD section 3.4: "`weather_lost_hours` sums `lost_hours` across the
        report's delay events whose `cause` is `WEATHER`, whose status is
        `CLASSIFIED` or `FINAL`, and whose `classification` is one of the two
        excusable values; `RECORDED` and `DISPUTED` events never contribute."

        Design: Corner/calculations/weather_totals_exclude_disputed_events
        """
        project = make_active_project(scheduled_shift_hours=8)
        area = make_work_area(project["id"])
        report = make_report(project["id"])
        event = make_classified_delay(report["id"], area["id"],
                                      "EXCUSABLE_NON_COMPENSABLE",
                                      start_at="2026-08-05T07:30:00Z",
                                      end_at="2026-08-05T10:30:00Z",
                                      cause="WEATHER")

        r1 = get_report(report["id"])
        assert r1["weather_lost_hours"] == pytest.approx(3.00, abs=1e-9)

        disputed = validate_success(api.dispute_delay_event(
            event["id"], {"reason": "Owner contests"}, make_owner_rep_headers("owner-1")))
        assert disputed["status"] == "DISPUTED"
        r2 = get_report(report["id"])
        assert r2["weather_lost_hours"] == pytest.approx(0.00, abs=1e-9), \
            "DISPUTED events never contribute to weather totals"

        reclassified = validate_success(api.classify_delay_event(
            event["id"], {"classification": "EXCUSABLE_NON_COMPENSABLE"}, _PM))
        assert reclassified["status"] == "CLASSIFIED"
        r3 = get_report(report["id"])
        assert r3["weather_lost_hours"] == pytest.approx(3.00, abs=1e-9)

    def test_lost_day_threshold_exactly_half_shift(self, api):
        """PRD section 3.4: "at exactly half the shift, the day counts as lost"
        (the boolean uses reach-at-least-half semantics); "The prorated variant,
        `weather_lost_day_fraction`, is the lost hours divided by
        `scheduled_shift_hours`, capped at one, and rounded half-up to two
        decimal places."

        Design: Corner/calculations/lost_day_threshold_exactly_half_shift
        """
        project = make_active_project(scheduled_shift_hours=8)
        area = make_work_area(project["id"])
        report = make_report(project["id"])
        make_classified_delay(report["id"], area["id"], "EXCUSABLE_COMPENSABLE",
                              start_at="2026-08-05T07:00:00Z",
                              end_at="2026-08-05T11:00:00Z",
                              cause="WEATHER")

        r = get_report(report["id"])
        assert r["weather_lost_hours"] == pytest.approx(4.00, abs=1e-9)
        assert r["weather_lost_day_calendar"] is True, "4.00 >= 0.5 * 8 boundary counts"
        assert r["weather_lost_day_fraction"] == pytest.approx(0.50, abs=1e-9)


class TestCompensableOverlap:
    def test_half_open_adjacency_allowed_true_overlap_rejected(self, api):
        """PRD section 3.4: "an event may not be classified
        `EXCUSABLE_COMPENSABLE` when another event on the same `work_area_id`,
        itself classified `EXCUSABLE_COMPENSABLE` and sitting in `CLASSIFIED` or
        `FINAL` status, has a window overlapping this one. Because both windows
        are half-open, adjacency is not overlap — one window ending exactly where
        the other begins is permitted. A violating classification is rejected
        with `ERR_DELAY_OVERLAP_COMPENSABLE`."

        Design: Difficulty/resource_temporal_overlap/delay_compensable_overlap_half_open_adjacency
        """
        project = make_active_project(scheduled_shift_hours=8)
        area = make_work_area(project["id"])
        report = make_report(project["id"])

        a = make_classified_delay(report["id"], area["id"], "EXCUSABLE_COMPENSABLE",
                                  start_at="2026-08-05T09:00:00Z",
                                  end_at="2026-08-05T11:00:00Z")
        assert a["lost_hours"] == pytest.approx(2.00, abs=1e-9)

        # B starts exactly where A ends: half-open adjacency is NOT overlap.
        b = add_delay_event(report["id"], area["id"],
                            start_at="2026-08-05T11:00:00Z",
                            end_at="2026-08-05T12:30:00Z")
        b_classified = validate_success(api.classify_delay_event(
            b["id"], {"classification": "EXCUSABLE_COMPENSABLE"}, _PM))
        assert b_classified["status"] == "CLASSIFIED"
        assert b_classified["lost_hours"] == pytest.approx(1.50, abs=1e-9)

        # C [10:30, 12:00) truly overlaps A's [09:00, 11:00).
        c = add_delay_event(report["id"], area["id"],
                            start_at="2026-08-05T10:30:00Z",
                            end_at="2026-08-05T12:00:00Z")
        err = api.classify_delay_event(
            c["id"], {"classification": "EXCUSABLE_COMPENSABLE"}, _PM)
        validate_error(err, ApiErrorId.ERR_DELAY_OVERLAP_COMPENSABLE)
        assert err.status_code == 409
        assert get_delay_event(c["id"])["status"] == "RECORDED"

    def test_prohibition_scoped_to_compensable_and_same_area(self, api):
        """PRD section 3.4: "an event may not be classified
        `EXCUSABLE_COMPENSABLE` when another event on the same `work_area_id`,
        itself classified `EXCUSABLE_COMPENSABLE` and sitting in `CLASSIFIED` or
        `FINAL` status, has a window overlapping this one." — overlap with a
        different area, or a non-compensable classification, is not prohibited.

        Design: Difficulty/resource_temporal_overlap/delay_compensable_overlap_half_open_adjacency
        """
        project = make_active_project(scheduled_shift_hours=8)
        area1 = make_work_area(project["id"])
        area2 = make_work_area(project["id"])
        report = make_report(project["id"])

        make_classified_delay(report["id"], area1["id"], "EXCUSABLE_COMPENSABLE",
                              start_at="2026-08-05T09:00:00Z",
                              end_at="2026-08-05T11:00:00Z")

        other_area = add_delay_event(report["id"], area2["id"],
                                     start_at="2026-08-05T10:00:00Z",
                                     end_at="2026-08-05T12:00:00Z")
        ok1 = validate_success(api.classify_delay_event(
            other_area["id"], {"classification": "EXCUSABLE_COMPENSABLE"}, _PM))
        assert ok1["status"] == "CLASSIFIED", \
            "the prohibition is scoped to the same work_area_id"

        non_compensable = add_delay_event(report["id"], area1["id"],
                                          start_at="2026-08-05T10:30:00Z",
                                          end_at="2026-08-05T12:00:00Z")
        ok2 = validate_success(api.classify_delay_event(
            non_compensable["id"], {"classification": "NON_EXCUSABLE"}, _PM))
        assert ok2["status"] == "CLASSIFIED", \
            "only EXCUSABLE_COMPENSABLE classifications are overlap-protected"


class TestDelayFinalizeGate:
    def test_finalize_blocked_on_draft_then_succeeds_after_submit(self, api):
        """PRD section 3.4: "Finalization requires the parent report to have
        been submitted — the report must be in `SUBMITTED`, `UNDER_REVIEW`, or
        `APPROVED`, else `ERR_DELAY_FINALIZE_REQUIRES_SUBMITTED_REPORT`."

        Design: Difficulty/cross_entity_state_dependency/delay_finalize_blocked_on_draft_report
        """
        project = make_active_project(scheduled_shift_hours=8)
        area = make_work_area(project["id"])
        report = make_report(project["id"])
        event = make_classified_delay(report["id"], area["id"],
                                      "EXCUSABLE_COMPENSABLE",
                                      start_at="2026-08-05T09:00:00Z",
                                      end_at="2026-08-05T10:00:00Z")

        err = api.finalize_delay_event(event["id"], _PM)
        validate_error(err, ApiErrorId.ERR_DELAY_FINALIZE_REQUIRES_SUBMITTED_REPORT)
        assert err.status_code == 409

        add_weather_observation(report["id"])
        add_crew_entry(report["id"], area["id"])
        set_clock("2026-08-05T17:00:00Z")
        validate_success(api.submit_report(report["id"], _SUPT))

        finalized = validate_success(api.finalize_delay_event(event["id"], _PM))
        assert finalized["status"] == "FINAL"

    def test_finalize_blocked_in_revision_requested_allowed_under_review(self, api):
        """PRD section 3.4: "Finalization requires the parent report to have
        been submitted — the report must be in `SUBMITTED`, `UNDER_REVIEW`, or
        `APPROVED`, else `ERR_DELAY_FINALIZE_REQUIRES_SUBMITTED_REPORT`."

        Design: Difficulty/cross_entity_state_dependency/delay_finalize_blocked_on_draft_report
        """
        project = make_active_project(scheduled_shift_hours=8)
        area = make_work_area(project["id"])
        report = make_report(project["id"])
        event = make_classified_delay(report["id"], area["id"],
                                      "EXCUSABLE_NON_COMPENSABLE",
                                      start_at="2026-08-05T09:00:00Z",
                                      end_at="2026-08-05T10:00:00Z",
                                      cause="WEATHER")
        add_weather_observation(report["id"])
        add_crew_entry(report["id"], area["id"])
        set_clock("2026-08-05T17:00:00Z")
        validate_success(api.submit_report(report["id"], _SUPT))
        validate_success(api.start_review_report(report["id"], _PM))

        # UNDER_REVIEW -> REVISION_REQUESTED drops the report out of the
        # finalize-eligible set.
        validate_success(api.request_revision_report(
            report["id"], {"reason": "recheck"}, _PM))
        err = api.finalize_delay_event(event["id"], _PM)
        validate_error(err, ApiErrorId.ERR_DELAY_FINALIZE_REQUIRES_SUBMITTED_REPORT)

        validate_success(api.return_to_draft_report(report["id"], _SUPT))
        validate_success(api.submit_report(report["id"], _SUPT))
        validate_success(api.start_review_report(report["id"], _PM))
        finalized = validate_success(api.finalize_delay_event(event["id"], _PM))
        assert finalized["status"] == "FINAL"
