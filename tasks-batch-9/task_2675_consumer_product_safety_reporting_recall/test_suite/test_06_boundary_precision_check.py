"""Deadlines, travel buffers and risk thresholds checked at their exact edges."""

from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.assertions import (
    assert_decimal_equals,
    assert_field_values,
    assert_fields_null,
)
from test_helpers.test_users import AUDITOR_HEADERS

# The statutory report clock: a determination stamped at the chain's opening
# instant is due exactly ten days later.
DETERMINED_AT = "2026-03-01T00:00:00Z"
REPORT_DUE_AT = "2026-03-11T00:00:00Z"
ONE_SECOND_LATE = "2026-03-11T00:00:01Z"

# The standing audit window and the two candidate windows on either side of the
# travel-buffer edge that sits one full day past its close.
STANDING_WINDOW = {
    "window_start": "2026-03-17T09:00:00Z",
    "window_end": "2026-03-17T17:00:00Z",
}
BUFFER_EDGE_WINDOW = {
    "window_start": "2026-03-18T17:00:00Z",
    "window_end": "2026-03-19T01:00:00Z",
}
INSIDE_BUFFER_WINDOW = {
    "window_start": "2026-03-18T16:59:59Z",
    "window_end": "2026-03-19T00:59:59Z",
}

# Two models carrying the identical verified burn cluster (severity sum 42.60,
# concentration ratio 1.0000) and differing only in distribution volume, which
# lands the risk index on either side of the high-risk threshold.
MODEL_AT_THRESHOLD = {"units_distributed": 25560, "units_registered": 5000}
MODEL_BELOW_THRESHOLD = {"units_distributed": 25570, "units_registered": 5000}

EVALUATION_OPENED_AT = "2026-03-01T00:00:00Z"
SHORT_WINDOW_DUE_AT = "2026-03-03T00:00:00Z"
LONG_WINDOW_DUE_AT = "2026-03-06T00:00:00Z"


def _instant_is(actual, expected_iso8601):
    """A stored instant names exactly the expected ISO 8601 UTC second."""
    assert actual is not None, f"expected {expected_iso8601}, got null"
    assert str(actual).startswith(expected_iso8601[:19]), (
        f"expected {expected_iso8601}, got {actual}"
    )


class TestStatutoryReportLatenessBoundary:
    """The single instant at which a filing costs nothing, and the next second."""

    def test_filing_at_exactly_the_report_deadline_is_on_time(self, api):
        """A report filed on the deadline itself scores no late day and no surcharge.

        The contract states: "Filing at exactly `report_due_at` yields zero late
        seconds, a `days_late` of 0 and no surcharge — the boundary is inclusive
        and on time." It also states: "When `days_late` is 0 the
        `late_surcharge_cents` is 0; otherwise it is 250,000 cents per late day,
        capped at 5,000,000 cents in total, so the charge is the smaller of the
        per-day product and the cap."

        Design: Difficulty/boundary_precision_check/section_report_submitted_at_exactly_report_due_at_is_not_late
        """
        env = fx.draft_report_env(api)

        evaluation = fx.get_evaluation(api, env["evaluation_id"])
        _instant_is(evaluation["determined_at"], DETERMINED_AT)
        _instant_is(evaluation["report_due_at"], REPORT_DUE_AT)

        fx.set_clock(api, REPORT_DUE_AT)
        filed = fx.submit_section_report(api, env["report_id"])

        assert_field_values(
            filed, status="SUBMITTED", days_late=0, late_surcharge_cents=0
        )
        _instant_is(filed["submitted_at"], REPORT_DUE_AT)
        assert filed["late_surcharge_cents"] != 250000, (
            "an on-time filing must not be billed a late day"
        )

    def test_filing_one_second_past_the_report_deadline_costs_a_whole_day(self, api):
        """A single second of delay rounds up to one late day and one day's charge.

        The contract states: "`days_late` is that figure divided by 86,400 seconds
        and then rounded **up** to a whole number, so any part-day counts as a
        whole day: one second late is one day late, exactly 86,400 seconds late is
        still one day late, and 86,401 seconds late is two."

        Design: Difficulty/boundary_precision_check/section_report_submitted_at_exactly_report_due_at_is_not_late
        """
        env = fx.draft_report_env(api)

        evaluation = fx.get_evaluation(api, env["evaluation_id"])
        _instant_is(evaluation["report_due_at"], REPORT_DUE_AT)

        fx.set_clock(api, ONE_SECOND_LATE)
        filed = fx.submit_section_report(api, env["report_id"])

        assert_field_values(
            filed, status="SUBMITTED", days_late=1, late_surcharge_cents=250000
        )
        _instant_is(filed["submitted_at"], ONE_SECOND_LATE)


class TestAuditWindowTravelBufferBoundary:
    """The first inspection instant a second team can legally take at one store."""

    def _store_under_stop_sale_with_a_standing_visit(self, api):
        """An issued stop-sale plus one scheduled visit closing mid-afternoon."""
        env = fx.approved_recall_env(api)
        assert_field_values(
            fx.get_notification(api, env["notification_id"]), status="ISSUED"
        )
        assert_field_values(
            fx.get_retailer(api, env["retailer_id"]),
            compliance_posture="STOP_SALE_ACTIVE",
        )
        env["visit"] = fx.create_audit_visit(
            api, env["notification_id"], **STANDING_WINDOW
        )
        return env

    def test_window_starting_exactly_at_the_travel_buffer_edge_is_scheduled(self, api):
        """A window opening one full day after the standing close does not conflict.

        The contract states: "Each window is widened by a travel buffer of 24 hours
        on each side, and the new visit conflicts with an existing one when the new
        `window_start` falls before the existing `window_end` plus 24 hours **and**
        the existing `window_start` falls before the new `window_end` plus 24
        hours." It also states: "Because the interval is half-open, a new window
        starting at exactly the existing `window_end` plus 24 hours does not
        conflict."

        Design: Difficulty/boundary_precision_check/audit_window_starting_exactly_at_the_24h_buffer_edge_is_accepted
        """
        env = self._store_under_stop_sale_with_a_standing_visit(api)

        second = validate_success(
            api.create_audit_visit(
                f.audit_visit_payload(env["notification_id"], **BUFFER_EDGE_WINDOW),
                headers=AUDITOR_HEADERS,
            ),
            201,
        )

        assert_field_values(
            second,
            status="SCHEDULED",
            verdict="PENDING",
            retailer_notification_id=env["notification_id"],
        )
        assert_fields_null(second, "shelf_units_found", "completed_at")
        _instant_is(second["window_start"], BUFFER_EDGE_WINDOW["window_start"])
        _instant_is(second["window_end"], BUFFER_EDGE_WINDOW["window_end"])

        assert_field_values(
            fx.get_audit_visit(api, env["visit"]["id"]),
            status="SCHEDULED",
            verdict="PENDING",
        )
        rows, meta = validate_paginated(
            api.list_audit_visits(
                {"retailer_notification_id": env["notification_id"]},
                headers=AUDITOR_HEADERS,
            )
        )
        assert meta["total_count"] == 2, meta
        assert [row["id"] for row in rows] == [env["visit"]["id"], second["id"]], rows

    def test_window_starting_one_second_inside_the_travel_buffer_is_refused(self, api):
        """One second earlier the two visits collide inside the travel buffer.

        The contract states: "Each window is widened by a travel buffer of 24 hours
        on each side, and the new visit conflicts with an existing one when the new
        `window_start` falls before the existing `window_end` plus 24 hours **and**
        the existing `window_start` falls before the new `window_end` plus 24
        hours." A conflict "is refused with `ERR_AUDIT_WINDOW_CONFLICT` (HTTP
        409)".

        Design: Difficulty/boundary_precision_check/audit_window_starting_exactly_at_the_24h_buffer_edge_is_accepted
        """
        env = self._store_under_stop_sale_with_a_standing_visit(api)

        response = api.create_audit_visit(
            f.audit_visit_payload(env["notification_id"], **INSIDE_BUFFER_WINDOW),
            headers=AUDITOR_HEADERS,
        )
        validate_error(response, "ERR_AUDIT_WINDOW_CONFLICT", 409)

        rows, meta = validate_paginated(
            api.list_audit_visits(
                {"retailer_notification_id": env["notification_id"]},
                headers=AUDITOR_HEADERS,
            )
        )
        assert meta["total_count"] == 1, meta
        assert [row["id"] for row in rows] == [env["visit"]["id"]], rows


class TestEscalationWindowRiskThreshold:
    """One hundredth of risk index decides between a two-day and a five-day clock."""

    def test_risk_index_exactly_at_the_high_risk_threshold_buys_the_short_window(
        self, api
    ):
        """A pattern landing exactly on the high-risk threshold gets two days only.

        The contract states: "It is `opened_at` plus a window whose length depends
        on how dangerous the underlying pattern is: when the pattern's `risk_index`
        is at least 25.00 the office gives itself only 48 hours (two days), and
        otherwise it allows 120 hours (five days)." It also states: "The threshold
        is non-strict, so a `risk_index` of exactly 25.00 buys the shorter window."

        Design: Difficulty/boundary_precision_check/risk_index_exactly_at_high_threshold_25_selects_the_48h_escalation_window
        """
        env = fx.confirmed_pattern_env(api, model=MODEL_AT_THRESHOLD)

        pattern = fx.get_pattern(api, env["pattern_id"])
        assert_field_values(
            pattern, incident_count=3, dominant_hazard_code="BURN", pattern_confirmed=True
        )
        assert_decimal_equals(pattern["severity_sum"], "42.60")
        assert_decimal_equals(pattern["concentration_ratio"], "1.0000", places=4)
        assert_decimal_equals(pattern["exposure_per_10k"], "2.5560", places=4)
        assert_decimal_equals(pattern["risk_index"], "25.00")

        evaluation = fx.create_evaluation(api, env["pattern_id"])

        assert_field_values(
            evaluation,
            status="OPEN",
            standard_basis="DEFECT",
            escalation_breached=False,
            product_model_id=env["model_id"],
        )
        _instant_is(evaluation["opened_at"], EVALUATION_OPENED_AT)
        _instant_is(evaluation["internal_escalation_due_at"], SHORT_WINDOW_DUE_AT)
        assert_fields_null(
            evaluation, "review_started_at", "determined_at", "report_due_at"
        )

    def test_risk_index_one_hundredth_below_the_threshold_buys_the_long_window(
        self, api
    ):
        """The same cluster over a slightly larger distribution gets five days.

        The contract states: "It is `opened_at` plus a window whose length depends
        on how dangerous the underlying pattern is: when the pattern's `risk_index`
        is at least 25.00 the office gives itself only 48 hours (two days), and
        otherwise it allows 120 hours (five days)."

        Design: Difficulty/boundary_precision_check/risk_index_exactly_at_high_threshold_25_selects_the_48h_escalation_window
        """
        env = fx.confirmed_pattern_env(api, model=MODEL_BELOW_THRESHOLD)

        pattern = fx.get_pattern(api, env["pattern_id"])
        assert_decimal_equals(pattern["severity_sum"], "42.60")
        assert_decimal_equals(pattern["concentration_ratio"], "1.0000", places=4)
        assert_decimal_equals(pattern["exposure_per_10k"], "2.5570", places=4)
        assert_decimal_equals(pattern["risk_index"], "24.99")

        evaluation = fx.create_evaluation(api, env["pattern_id"])

        assert_field_values(
            evaluation, status="OPEN", escalation_breached=False
        )
        _instant_is(evaluation["opened_at"], EVALUATION_OPENED_AT)
        _instant_is(evaluation["internal_escalation_due_at"], LONG_WINDOW_DUE_AT)
