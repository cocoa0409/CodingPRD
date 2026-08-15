"""Debris reporting: MEASURED vs ESTIMATED variants, rounding order, window,
immutability, one-report-per-event (PRD §3.6, §2.10)."""
import pytest

from test_helpers import (
    ApiErrorId,
    assert_debris_report,
    brief_event,
    create_adult_waiver,
    create_event,
    create_group,
    get_event,
    get_metrics,
    make_coordinator_headers,
    make_group_leader_headers,
    set_clock,
    setup_active_agreement,
    setup_agreement_with_waiver,
    setup_briefed_event,
    validate_error,
    validate_success,
)
from prd_bench_local_runner.testing import get_success_data

COORD = make_coordinator_headers()


class TestMeasuredVsEstimated:
    def test_debris_measured_vs_estimated_divergence(self, api):
        """PRD §3.6: "Under `MEASURED`, the crew weighed the debris on a scale
        ... The official weight is the scale reading itself. Under `ESTIMATED`,
        no scale was available, so each line's weight is its `bag_count`
        multiplied by the per-bag average for its material — 12.75 pounds for
        `GENERAL_TRASH`, 7.25 for `RECYCLABLES`, 22.4 for `METALS`, 10.6 for
        `YARD_WASTE`, and 9.85 for `OTHER` — with each line rounded half-up to
        one decimal place first and the rounded lines then summed into
        `official_weight_lbs`. The two methods legitimately produce different
        official weights for the same physical cleanup."

        Design: Difficulty/dual_variant_calc/debris_measured_vs_estimated_divergence
        """
        group, segment, agreement, waiver = setup_agreement_with_waiver(
            group_name="Clean Banks", contact_name="Sam Lead",
            contact_email="sam@cleanbanks.org",
            route_name="Hill Rd", mile_marker_start=10.0, mile_marker_end=12.0,
            segment_type="ROADWAY", water_adjacent=False,
        )
        ea = create_event(agreement["id"], group["id"],
                          scheduled_date="2026-09-10", expected_volunteers=4)
        brief_event(ea["id"], group["id"], [waiver["id"]])
        eb = create_event(agreement["id"], group["id"],
                          scheduled_date="2026-09-12", expected_volunteers=4)
        brief_event(eb["id"], group["id"], [waiver["id"]])

        set_clock("2026-09-10T10:00:00Z")
        gl = make_group_leader_headers(group["id"])
        est = get_success_data(api.submit_debris_report(
            ea["id"],
            {"weight_method": "ESTIMATED",
             "material_lines": [
                 {"material_type": "GENERAL_TRASH", "bag_count": 2},
                 {"material_type": "RECYCLABLES", "bag_count": 2}]},
            gl))
        set_clock("2026-09-12T10:00:00Z")
        meas = get_success_data(api.submit_debris_report(
            eb["id"],
            {"weight_method": "MEASURED",
             "measured_total_weight_lbs": 38.4,
             "material_lines": [
                 {"material_type": "GENERAL_TRASH", "line_weight_lbs": 24.9},
                 {"material_type": "RECYCLABLES", "line_weight_lbs": 13.5}]},
            gl))

        assert est["official_weight_lbs"] == pytest.approx(40.0, abs=1e-9)
        assert meas["official_weight_lbs"] == pytest.approx(38.4, abs=1e-9)
        assert est["official_weight_lbs"] != meas["official_weight_lbs"]

        metrics = get_metrics()
        assert metrics["total_debris_lbs"] == pytest.approx(78.4, abs=1e-9)
        assert metrics["completed_cleanups"] == 2

    def test_estimated_report_uses_per_bag_averages(self, api):
        """PRD §3.6: "each line's weight is its `bag_count` multiplied by the
        per-bag average for its material — 12.75 pounds for `GENERAL_TRASH`,
        7.25 for `RECYCLABLES`, 22.4 for `METALS`, 10.6 for `YARD_WASTE`, and
        9.85 for `OTHER`"

        Design: Difficulty/dual_variant_calc/debris_measured_vs_estimated_divergence
        """
        group, segment, agreement, waiver, event = setup_briefed_event(
            scheduled_date="2026-09-10", expected_volunteers=4,
            route_name="Hill Rd", mile_marker_start=10.0, mile_marker_end=12.0,
            segment_type="ROADWAY", water_adjacent=False,
        )
        set_clock("2026-09-10T10:00:00Z")
        gl = make_group_leader_headers(group["id"])
        report = get_success_data(api.submit_debris_report(
            event["id"],
            {"weight_method": "ESTIMATED",
             "material_lines": [
                 {"material_type": "GENERAL_TRASH", "bag_count": 2},
                 {"material_type": "RECYCLABLES", "bag_count": 2}]},
            gl))
        # 2 * 12.75 = 25.5; 2 * 7.25 = 14.5; total 40.0
        assert report["official_weight_lbs"] == pytest.approx(40.0, abs=1e-9)


class TestRoundingOrder:
    def test_estimated_weight_per_line_rounding_order(self, api):
        """PRD §3.6: "with each line rounded half-up to one decimal place first
        and the rounded lines then summed into `official_weight_lbs`."
        PRD §2.10: "for estimated debris reports, each material line is rounded
        first and the rounded lines are then summed — the rounding-precedes-
        summation order is pinned."

        Design: Difficulty/combinatorial_formula/estimated_weight_per_line_rounding_order
        """
        group, segment, agreement, waiver, event = setup_briefed_event(
            scheduled_date="2026-09-10", expected_volunteers=2,
            route_name="Hill Rd", mile_marker_start=1.0, mile_marker_end=2.0,
            segment_type="ROADWAY", water_adjacent=False,
        )
        set_clock("2026-09-10T10:00:00Z")
        gl = make_group_leader_headers(group["id"])
        report = get_success_data(api.submit_debris_report(
            event["id"],
            {"weight_method": "ESTIMATED",
             "material_lines": [
                 {"material_type": "GENERAL_TRASH", "bag_count": 1},
                 {"material_type": "RECYCLABLES", "bag_count": 1}]},
            gl))
        # Per-line: 12.75 -> 12.8; 7.25 -> 7.3; sum 20.1 (NOT 20.0).
        assert report["official_weight_lbs"] == pytest.approx(20.1, abs=1e-9)
        breakdown = {l["material_type"]: l["line_weight_lbs"]
                     for l in report["material_breakdown"]}
        assert breakdown["GENERAL_TRASH"] == pytest.approx(12.8, abs=1e-9)
        assert breakdown["RECYCLABLES"] == pytest.approx(7.3, abs=1e-9)

    def test_rounding_precedes_summation_order_pinned(self, api):
        """PRD §2.10: "for estimated debris reports, each material line is
        rounded first and the rounded lines are then summed — the
        rounding-precedes-summation order is pinned."

        Design: Difficulty/combinatorial_formula/estimated_weight_per_line_rounding_order
        """
        group, segment, agreement, waiver, event = setup_briefed_event(
            scheduled_date="2026-09-10", expected_volunteers=2,
            route_name="Hill Rd", mile_marker_start=1.0, mile_marker_end=2.0,
            segment_type="ROADWAY", water_adjacent=False,
        )
        set_clock("2026-09-10T10:00:00Z")
        gl = make_group_leader_headers(group["id"])
        # 1 GENERAL_TRASH (12.75 -> 12.8) + 1 OTHER (9.85 -> 9.9): per-line
        # rounding then summation gives 22.7; summing raw products
        # (12.75 + 9.85 = 22.6) then rounding would give 22.6.
        report = get_success_data(api.submit_debris_report(
            event["id"],
            {"weight_method": "ESTIMATED",
             "material_lines": [
                 {"material_type": "GENERAL_TRASH", "bag_count": 1},
                 {"material_type": "OTHER", "bag_count": 1}]},
            gl))
        assert report["official_weight_lbs"] == pytest.approx(22.7, abs=1e-9)

    def test_estimated_weight_per_bag_constants_applied(self, api):
        """PRD §3.6: "each line's weight is its `bag_count` multiplied by the
        per-bag average for its material — 12.75 pounds for `GENERAL_TRASH`,
        7.25 for `RECYCLABLES`, 22.4 for `METALS`, 10.6 for `YARD_WASTE`, and
        9.85 for `OTHER`"

        Design: Corner/calculations/estimated_weight_per_bag_constants_applied
        """
        group, segment, agreement, waiver, event = setup_briefed_event(
            scheduled_date="2026-09-10", expected_volunteers=2,
        )
        set_clock("2026-09-10T10:00:00Z")
        gl = make_group_leader_headers(group["id"])
        report = get_success_data(api.submit_debris_report(
            event["id"],
            {"weight_method": "ESTIMATED",
             "material_lines": [
                 {"material_type": "METALS", "bag_count": 3},
                 {"material_type": "YARD_WASTE", "bag_count": 2}]},
            gl))
        # 3 * 22.4 = 67.2; 2 * 10.6 = 21.2; total 88.4
        assert report["official_weight_lbs"] == pytest.approx(88.4, abs=1e-9)
        breakdown = {l["material_type"]: l["line_weight_lbs"]
                     for l in report["material_breakdown"]}
        assert breakdown["METALS"] == pytest.approx(67.2, abs=1e-9)
        assert breakdown["YARD_WASTE"] == pytest.approx(21.2, abs=1e-9)


class TestMeasuredReconciliation:
    def test_measured_weight_lines_must_sum_to_total(self, api):
        """PRD §3.6: "the supplied line weights must sum to the measured total
        exactly at one decimal place — any discrepancy is rejected with
        `ERR_WEIGHT_MISMATCH`."

        Design: Corner/calculations/measured_weight_lines_must_sum_to_total
        """
        group, segment, agreement, waiver, event = setup_briefed_event(
            scheduled_date="2026-09-10", expected_volunteers=2,
        )
        set_clock("2026-09-10T10:00:00Z")
        gl = make_group_leader_headers(group["id"])
        bad = api.submit_debris_report(
            event["id"],
            {"weight_method": "MEASURED",
             "measured_total_weight_lbs": 20.0,
             "material_lines": [
                 {"material_type": "GENERAL_TRASH", "line_weight_lbs": 12.8},
                 {"material_type": "RECYCLABLES", "line_weight_lbs": 7.3}]},
            gl)
        validate_error(bad, ApiErrorId.ERR_WEIGHT_MISMATCH)

        good = get_success_data(api.submit_debris_report(
            event["id"],
            {"weight_method": "MEASURED",
             "measured_total_weight_lbs": 20.1,
             "material_lines": [
                 {"material_type": "GENERAL_TRASH", "line_weight_lbs": 12.8},
                 {"material_type": "RECYCLABLES", "line_weight_lbs": 7.3}]},
            gl))
        assert good["official_weight_lbs"] == pytest.approx(20.1, abs=1e-9)

    def test_measured_report_missing_total_returns_invalid_request(self, api):
        """PRD §3.6: "Under `MEASURED`, the crew weighed the debris on a scale:
        `measured_total_weight_lbs` is required (and it is forbidden under
        `ESTIMATED`)"
        PRD §2.11 family 5: "Request shape — required fields present, types and
        enum values valid, ranges respected ... (`ERR_INVALID_REQUEST`)."

        Design: Corner/validations/measured_report_missing_total_returns_invalid_request
        """
        group, segment, agreement, waiver, event = setup_briefed_event(
            scheduled_date="2026-09-10", expected_volunteers=2,
        )
        set_clock("2026-09-10T10:00:00Z")
        gl = make_group_leader_headers(group["id"])
        resp = api.submit_debris_report(
            event["id"],
            {"weight_method": "MEASURED",
             "material_lines": [
                 {"material_type": "GENERAL_TRASH", "line_weight_lbs": 12.8}]},
            gl)
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)


class TestOneReportPerEvent:
    def test_second_report_on_completed_event_hits_state_guard(self, api):
        """PRD §3.6: "The event must be in `BRIEFING_DONE`, else
        `ERR_EVENT_NOT_BRIEFED`, and because completion moves the event out of
        `BRIEFING_DONE`, that single state guard also enforces the rule of at
        most one debris report per event."

        Design: Corner/validations/second_report_on_completed_event_hits_state_guard
        """
        group, segment, agreement, waiver, event = setup_briefed_event(
            scheduled_date="2026-09-10", expected_volunteers=2,
        )
        set_clock("2026-09-10T10:00:00Z")
        gl = make_group_leader_headers(group["id"])
        get_success_data(api.submit_debris_report(
            event["id"],
            {"weight_method": "ESTIMATED",
             "material_lines": [{"material_type": "GENERAL_TRASH", "bag_count": 2}]},
            gl))
        resp = api.submit_debris_report(
            event["id"],
            {"weight_method": "ESTIMATED",
             "material_lines": [{"material_type": "GENERAL_TRASH", "bag_count": 1}]},
            gl)
        validate_error(resp, ApiErrorId.ERR_EVENT_NOT_BRIEFED)

    def test_report_on_unbriefed_event_rejected(self, api):
        """PRD §3.6: "The event must be in `BRIEFING_DONE`, else
        `ERR_EVENT_NOT_BRIEFED`"

        Design: Corner/validations/second_report_on_completed_event_hits_state_guard
        """
        group, segment, agreement = setup_active_agreement()
        event = create_event(agreement["id"], group["id"],
                             scheduled_date="2026-09-10")
        set_clock("2026-09-10T10:00:00Z")
        gl = make_group_leader_headers(group["id"])
        resp = api.submit_debris_report(
            event["id"],
            {"weight_method": "ESTIMATED",
             "material_lines": [{"material_type": "GENERAL_TRASH", "bag_count": 1}]},
            gl)
        validate_error(resp, ApiErrorId.ERR_EVENT_NOT_BRIEFED)


class TestReportWindow:
    def test_report_window_thirty_days_inclusive(self, api):
        """PRD §3.6: "the group has from the `scheduled_date` through 30 days
        after it — both endpoints included — to file the debris report; outside
        that window the submission is refused with `ERR_REPORT_WINDOW_CLOSED`."

        Design: Corner/validations/report_window_thirty_days_inclusive
        """
        group, segment, agreement, waiver = setup_agreement_with_waiver()
        e1 = create_event(agreement["id"], group["id"],
                          scheduled_date="2026-09-10")
        brief_event(e1["id"], group["id"], [waiver["id"]])
        e2 = create_event(agreement["id"], group["id"],
                          scheduled_date="2026-09-11")
        brief_event(e2["id"], group["id"], [waiver["id"]])

        gl = make_group_leader_headers(group["id"])
        # Exactly +30 days after 2026-09-10: inside the window.
        set_clock("2026-10-10T09:00:00Z")
        ok = get_success_data(api.submit_debris_report(
            e1["id"],
            {"weight_method": "ESTIMATED",
             "material_lines": [{"material_type": "GENERAL_TRASH", "bag_count": 2}]},
            gl))
        assert ok["official_weight_lbs"] == pytest.approx(25.5, abs=1e-9)

        # 2026-10-12 is +31 days after 2026-09-11: outside the window.
        set_clock("2026-10-12T09:00:00Z")
        resp = api.submit_debris_report(
            e2["id"],
            {"weight_method": "ESTIMATED",
             "material_lines": [{"material_type": "GENERAL_TRASH", "bag_count": 2}]},
            gl)
        validate_error(resp, ApiErrorId.ERR_REPORT_WINDOW_CLOSED)

    def test_report_before_scheduled_date_rejected(self, api):
        """PRD §3.6: "the group has from the `scheduled_date` through 30 days
        after it — both endpoints included — to file the debris report; outside
        that window the submission is refused with `ERR_REPORT_WINDOW_CLOSED`."

        Design: Corner/validations/report_window_thirty_days_inclusive
        """
        group, segment, agreement, waiver, event = setup_briefed_event(
            scheduled_date="2026-09-10", expected_volunteers=2,
        )
        # Clock is still 2026-08-01, before the scheduled date.
        gl = make_group_leader_headers(group["id"])
        resp = api.submit_debris_report(
            event["id"],
            {"weight_method": "ESTIMATED",
             "material_lines": [{"material_type": "GENERAL_TRASH", "bag_count": 2}]},
            gl)
        validate_error(resp, ApiErrorId.ERR_REPORT_WINDOW_CLOSED)


class TestDebrisReportImmutability:
    def test_debris_report_immutable_shape(self, api):
        """PRD §2.4: "A `DebrisReport` carries only `id` and `created_at`;
        `updated_at` and `version` are both absent, because debris reports are
        immutable once created."

        Design: Corner/entities/debris_report_immutable_shape
        """
        group, segment, agreement, waiver, event = setup_briefed_event(
            scheduled_date="2026-09-10", expected_volunteers=2,
        )
        set_clock("2026-09-10T10:00:00Z")
        gl = make_group_leader_headers(group["id"])
        report = get_success_data(api.submit_debris_report(
            event["id"],
            {"weight_method": "ESTIMATED",
             "material_lines": [{"material_type": "GENERAL_TRASH", "bag_count": 2}]},
            gl))
        assert_debris_report(report)
        assert report["created_at"] == "2026-09-10T10:00:00Z"

        listed = validate_success(
            api.list_event_debris_reports(event["id"], gl), 200)
        assert len(listed) == 1
        assert listed[0]["id"] == report["id"]

    def test_debris_report_collection_is_zero_or_one(self, api):
        """PRD §3.6: "Reading the event's report collection therefore yields an
        array of zero or one entries."

        Design: Corner/entities/debris_report_immutable_shape
        """
        group, segment, agreement = setup_active_agreement()
        event = create_event(agreement["id"], group["id"],
                             scheduled_date="2026-09-10")
        gl = make_group_leader_headers(group["id"])
        listed = validate_success(
            api.list_event_debris_reports(event["id"], gl), 200)
        assert listed == []
