"""Verification report assessment, threshold boundaries, period overlap,
and the IVT fraud cascade."""
import pytest

from test_helpers import (
    api_client, make_analyst_headers,
    validate_success, validate_error,
    assert_verification_report,
    create_verification_report_payload,
    ApiErrorId,
    create_line_item, create_creative, walk_creative_to_tagged,
    transition_line_item,
    setup_live_line_item, file_verification_report, setup_breach_report,
    get_line_item, get_creative,
)


class TestAssessmentThresholds:
    def test_threshold_equality_passes(self, api):
        """PRD §3.5: "The report's `assessment` is `BREACH` when
        `viewability_rate` falls below the parent order's
        `viewability_threshold_pct` or when `ivt_rate` exceeds the order's
        `ivt_threshold_pct`; a rate exactly equal to its threshold passes,
        and a report meeting both thresholds is assessed `PASS`."

        Design: Difficulty/boundary_precision_check/verification_threshold_equality_pass
        """
        ctx = setup_live_line_item()
        li_id = ctx["line_item"]["id"]
        report = file_verification_report(
            li_id, vendor="DOUBLEVERIFY", measured_impressions=100000,
            viewable_impressions=70000, ivt_impressions=2000)
        assert_verification_report(report)
        assert report["viewability_rate"] == pytest.approx(0.70, abs=1e-9)
        assert report["ivt_rate"] == pytest.approx(0.02, abs=1e-9)
        assert report["assessment"] == "PASS", (
            "Equality with both thresholds must pass")

        li = get_line_item(li_id)
        assert li["fraud_posture"] == "CLEAR"
        assert li["status"] == "LIVE"

    def test_ivt_strictly_above_threshold_breaches(self, api):
        """PRD §3.5: "The report's `assessment` is `BREACH` when
        `viewability_rate` falls below the parent order's
        `viewability_threshold_pct` or when `ivt_rate` exceeds the order's
        `ivt_threshold_pct`; a rate exactly equal to its threshold passes"

        Design: Difficulty/boundary_precision_check/verification_threshold_equality_pass
        """
        ctx = setup_live_line_item()
        li_id = ctx["line_item"]["id"]
        report = file_verification_report(
            li_id, vendor="DOUBLEVERIFY", measured_impressions=100000,
            viewable_impressions=80000, ivt_impressions=3000)
        assert report["viewability_rate"] == pytest.approx(0.80, abs=1e-9)
        assert report["ivt_rate"] == pytest.approx(0.03, abs=1e-9)
        assert report["assessment"] == "BREACH", (
            "ivt_rate 0.03 strictly exceeds the 0.02 threshold")

        li = get_line_item(li_id)
        assert li["fraud_posture"] == "BREACH"
        assert li["status"] == "PAUSED"


class TestFraudCascade:
    def test_ivt_breach_fraud_cascade_depth3(self, api):
        """PRD §3.5: "When — and only when — `ivt_rate` exceeds the order's
        invalid-traffic threshold, filing the report fires the fraud cascade:
        the line item's `fraud_posture` becomes `BREACH`, a `LIVE` line item
        drops to `PAUSED` automatically, and every `LIVE` creative under it
        pauses with it."

        Design: Difficulty/transitive_cascade/ivt_breach_fraud_cascade_depth3
        """
        ctx = setup_live_line_item()
        li_id = ctx["line_item"]["id"]
        cr_id = ctx["creative"]["id"]

        report = file_verification_report(
            li_id, vendor="IAS", measured_impressions=100000,
            viewable_impressions=80000, ivt_impressions=5000)
        assert report["assessment"] == "BREACH", (
            "ivt_rate 0.05 > 0.02 while viewability 0.80 passes")
        # shortfall 0 (viewability passes) + ivt 5000 -> 5000*500/1000 = 2500.
        assert report["make_good_max_credit_cents"] == 2500

        li = get_line_item(li_id)
        assert li["fraud_posture"] == "BREACH"
        assert li["status"] == "PAUSED"
        assert get_creative(cr_id)["status"] == "PAUSED", (
            "The pause cascades from the line item to its LIVE creatives")

    def test_viewability_only_breach_does_not_fire_cascade(self, api):
        """PRD §3.5: "When — and only when — `ivt_rate` exceeds the order's
        invalid-traffic threshold, filing the report fires the fraud cascade"

        Design: Difficulty/transitive_cascade/ivt_breach_fraud_cascade_depth3
        """
        ctx = setup_live_line_item()
        li_id = ctx["line_item"]["id"]
        cr_id = ctx["creative"]["id"]

        report = file_verification_report(
            li_id, vendor="IAS", measured_impressions=100000,
            viewable_impressions=60000, ivt_impressions=0)
        assert report["assessment"] == "BREACH", (
            "viewability 0.60 < 0.70 breaches even with zero IVT")
        # shortfall = 70000 - 60000 = 10000 -> 10000*500/1000 = 5000.
        assert report["make_good_max_credit_cents"] == 5000

        li = get_line_item(li_id)
        assert li["fraud_posture"] == "CLEAR", (
            "Viewability-only breach must not set the fraud hold")
        assert li["status"] == "LIVE"
        assert get_creative(cr_id)["status"] == "LIVE"


class TestReportFilingValidation:
    def test_measured_zero_rejected(self, api, analyst_headers):
        """PRD §2.8: "Third, request-body schema: required fields present,
        types correct, enum members valid, and cross-field consistency —
        `viewable_impressions` not exceeding `measured_impressions`,
        `ivt_impressions` not exceeding `measured_impressions`, `clicks` not
        exceeding `impressions`, `end_date` on or after `start_date`,
        `flight_end` on or after `flight_start`, `period_end` strictly after
        `period_start`, `measured_impressions` greater than zero, and
        positive amounts wherever an amount is required
        (`ERR_INVALID_REQUEST`)."

        Design: Corner/validations/verification_measured_zero_rejected
        """
        ctx = setup_live_line_item()
        res = api.create_verification_report(
            create_verification_report_payload(
                ctx["line_item"]["id"], vendor="IAS",
                measured_impressions=0, viewable_impressions=0,
                ivt_impressions=0),
            analyst_headers)
        validate_error(res, ApiErrorId.ERR_INVALID_REQUEST.value, 400)

    def test_schema_beats_temporal_on_report_filing(self, api,
                                                    analyst_headers):
        """PRD §2.8: "Every request is evaluated against a fixed pipeline,
        and a request that would trip several checks is rejected with the
        error belonging to the earliest one."
        PRD §2.8: "Third, request-body schema: required fields present, types
        correct, enum members valid, and cross-field consistency —
        `viewable_impressions` not exceeding `measured_impressions`,
        `ivt_impressions` not exceeding `measured_impressions`, `clicks` not
        exceeding `impressions`, `end_date` on or after `start_date`,
        `flight_end` on or after `flight_start`, `period_end` strictly after
        `period_start`, `measured_impressions` greater than zero, and
        positive amounts wherever an amount is required
        (`ERR_INVALID_REQUEST`)."

        Design: Difficulty/priority_pair_validation_conflict/schema_beats_temporal_on_report_filing
        """
        ctx = setup_live_line_item()
        li_id = ctx["line_item"]["id"]
        file_verification_report(li_id, vendor="MOAT",
                                 period_start="2026-08-01",
                                 period_end="2026-08-05",
                                 measured_impressions=1000,
                                 viewable_impressions=800, ivt_impressions=0)

        # Overlapping period AND internally inconsistent body.
        res = api.create_verification_report(
            create_verification_report_payload(
                li_id, vendor="MOAT", period_start="2026-08-03",
                period_end="2026-08-08", measured_impressions=100,
                viewable_impressions=200, ivt_impressions=0),
            analyst_headers)
        validate_error(res, ApiErrorId.ERR_INVALID_REQUEST.value, 400)

    def test_schema_violation_alone_on_non_overlapping_period(
            self, api, analyst_headers):
        """PRD §2.8: "Third, request-body schema: required fields present,
        types correct, enum members valid, and cross-field consistency —
        `viewable_impressions` not exceeding `measured_impressions`,
        `ivt_impressions` not exceeding `measured_impressions`, `clicks` not
        exceeding `impressions`, `end_date` on or after `start_date`,
        `flight_end` on or after `flight_start`, `period_end` strictly after
        `period_start`, `measured_impressions` greater than zero, and
        positive amounts wherever an amount is required
        (`ERR_INVALID_REQUEST`)."

        Design: Difficulty/priority_pair_validation_conflict/schema_beats_temporal_on_report_filing
        """
        ctx = setup_live_line_item()
        li_id = ctx["line_item"]["id"]
        file_verification_report(li_id, vendor="MOAT",
                                 period_start="2026-08-01",
                                 period_end="2026-08-05",
                                 measured_impressions=1000,
                                 viewable_impressions=800, ivt_impressions=0)

        res = api.create_verification_report(
            create_verification_report_payload(
                li_id, vendor="MOAT", period_start="2026-08-10",
                period_end="2026-08-15", measured_impressions=100,
                viewable_impressions=200, ivt_impressions=0),
            analyst_headers)
        validate_error(res, ApiErrorId.ERR_INVALID_REQUEST.value, 400)


class TestVerificationPeriodOverlap:
    def test_closed_interval_touch_conflicts(self, api):
        """PRD §3.5: "The new period must not overlap an existing report for
        the same line item and vendor — because the interval is closed,
        periods that merely touch at a boundary date already conflict, and
        the filing is rejected with `ERR_VERIFICATION_PERIOD_OVERLAP`."

        Design: Difficulty/resource_temporal_overlap/verification_periods_closed_touch_conflict
        """
        ctx = setup_live_line_item()
        li_id = ctx["line_item"]["id"]
        file_verification_report(li_id, vendor="MOAT",
                                 period_start="2026-08-01",
                                 period_end="2026-08-05",
                                 measured_impressions=1000,
                                 viewable_impressions=800, ivt_impressions=0)

        # Clear of the closed interval: starts the day after it ends.
        report2 = file_verification_report(
            li_id, vendor="MOAT", period_start="2026-08-06",
            period_end="2026-08-08", measured_impressions=1000,
            viewable_impressions=800, ivt_impressions=0)
        assert report2["status"] == "OPEN"

        # Touching at the boundary date conflicts under closed semantics.
        res = api_client.create_verification_report(
            create_verification_report_payload(
                li_id, vendor="MOAT", period_start="2026-08-05",
                period_end="2026-08-07", measured_impressions=1000,
                viewable_impressions=800, ivt_impressions=0),
            make_analyst_headers("va-1"))
        validate_error(
            res, ApiErrorId.ERR_VERIFICATION_PERIOD_OVERLAP.value, 409)

        # Same dates under a different vendor are an independent stream.
        report3 = file_verification_report(
            li_id, vendor="IAS", period_start="2026-08-03",
            period_end="2026-08-06", measured_impressions=1000,
            viewable_impressions=800, ivt_impressions=0)
        assert report3["status"] == "OPEN"

    def test_overlap_is_scoped_per_line_item_and_vendor(self, api):
        """PRD §3.5: "The new period must not overlap an existing report for
        the same line item and vendor — because the interval is closed,
        periods that merely touch at a boundary date already conflict, and
        the filing is rejected with `ERR_VERIFICATION_PERIOD_OVERLAP`."

        Design: Difficulty/resource_temporal_overlap/verification_periods_closed_touch_conflict
        """
        ctx = setup_live_line_item()
        li1_id = ctx["line_item"]["id"]
        # Second LIVE line item under the same order.
        li2 = create_line_item(ctx["io"]["id"], name="LI2",
                               goal_impressions=1000)
        cr2 = create_creative(li2["id"], name="CR2")
        walk_creative_to_tagged(cr2["id"], ad_tag="<script>2</script>")
        transition_line_item(li2["id"], "TRAFFIC")
        transition_line_item(li2["id"], "LAUNCH")

        file_verification_report(li1_id, vendor="MOAT",
                                 period_start="2026-08-01",
                                 period_end="2026-08-05",
                                 measured_impressions=1000,
                                 viewable_impressions=800, ivt_impressions=0)

        # Same vendor, same dates, different line item -> independent.
        other = file_verification_report(
            li2["id"], vendor="MOAT", period_start="2026-08-01",
            period_end="2026-08-05", measured_impressions=1000,
            viewable_impressions=800, ivt_impressions=0)
        assert other["status"] == "OPEN"

        # Same line item + vendor, strictly contained period -> conflict.
        res = api_client.create_verification_report(
            create_verification_report_payload(
                li1_id, vendor="MOAT", period_start="2026-08-02",
                period_end="2026-08-04", measured_impressions=1000,
                viewable_impressions=800, ivt_impressions=0),
            make_analyst_headers("va-1"))
        validate_error(
            res, ApiErrorId.ERR_VERIFICATION_PERIOD_OVERLAP.value, 409)
