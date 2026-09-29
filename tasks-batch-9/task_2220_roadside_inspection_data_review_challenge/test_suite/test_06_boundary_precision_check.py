"""Edges pinned on both sides: the decay bands, the two-year lookback, and the two
alert bars at exact equality.
"""

from typing import Any, Dict

from test_helpers import (
    AlertStatus,
    BasicCategory,
    InterventionStatus,
    SelectionBand,
    UnitType,
    ViolationStatus,
    assert_measure,
    assert_one_decimal,
    fixtures as fx,
)

OLD_THRESHOLD_START = "2024-01-01T00:00:00Z"


def _unsafe_driving_carrier(api) -> Dict[str, Any]:
    """A MEDIUM carrier with a weight-5 UNSAFE_DRIVING code and a threshold effective
    long before any of the inspections used here."""
    fx.set_clock(api)
    carrier = fx.create_carrier(api)
    code = fx.create_violation_code(
        api,
        code="392.2S",
        basic_category=BasicCategory.UNSAFE_DRIVING,
        severity_weight=5,
    )
    threshold = fx.create_threshold(
        api,
        basic_category=BasicCategory.UNSAFE_DRIVING,
        carrier_segment="MEDIUM",
        effective_from=OLD_THRESHOLD_START,
        measure_at_p50=0.5,
        measure_at_p65=1.0,
        measure_at_p80=2.0,
    )
    return {"carrier": carrier, "code": code, "threshold": threshold}


def _four_ages_around_the_band_edges(api) -> Dict[str, Any]:
    """One weight-5 violation at each of ages 182, 183, 365 and 366 days."""
    base = _unsafe_driving_carrier(api)
    ages = {
        182: ("OH182", "2026-01-31T00:00:00Z", "2026-01-31T01:00:00Z"),
        183: ("OH183", "2026-01-30T00:00:00Z", "2026-01-30T01:00:00Z"),
        365: ("OH365", "2025-08-01T00:00:00Z", "2025-08-01T01:00:00Z"),
        366: ("OH366", "2025-07-31T00:00:00Z", "2025-07-31T01:00:00Z"),
    }
    violations = {}
    for age, (number, start, end) in ages.items():
        _, rows = fx.build_scored_report(
            api,
            base["carrier"]["id"],
            [{"violation_code_id": base["code"]["id"], "unit_type": UnitType.VEHICLE}],
            report_number=number,
            inspection_start=start,
            inspection_end=end,
        )
        violations[age] = rows[0]
    base["violations"] = violations
    return base


class TestTimeWeightBandEdges:
    def test_both_interior_edges_of_the_decay_curve(self, api):
        """PRD 3.3: "The age then selects an integer `time_weight`: 3 for the first 26
        weeks, meaning an age of 182 days or fewer; 2 for an age from 183 through 365
        days inclusive; 1 for an age from 366 through 730 days inclusive; and 0 once the
        age reaches 731 days, so an inspection more than two years old contributes
        nothing at all."

        Design: Difficulty/boundary_precision_check/time_weight_band_edges_182_183_365_366
        """
        scenario = _four_ages_around_the_band_edges(api)
        expected = {182: (3, 15.0), 183: (2, 10.0), 365: (2, 10.0), 366: (1, 5.0)}
        for age, (time_weight, severity) in expected.items():
            violation = fx.read_violation(api, scenario["violations"][age]["id"])
            assert violation["time_weight"] == time_weight, age
            assert_one_decimal(violation["time_weighted_severity"], severity)

    def test_the_mixed_decay_rolls_up_to_one_three_decimal_measure(self, api):
        """PRD 3.4: "When it is above `measure_at_p65` but no greater than
        `measure_at_p80`, the percentile is sixty-five plus fifteen multiplied by the
        amount by which the certified measure exceeds `measure_at_p65` and divided by the
        difference between `measure_at_p80` and `measure_at_p65`."

        Design: Difficulty/boundary_precision_check/time_weight_band_edges_182_183_365_366
        """
        scenario = _four_ages_around_the_band_edges(api)
        carrier_id = scenario["carrier"]["id"]

        row = fx.read_basic_score(api, carrier_id, BasicCategory.UNSAFE_DRIVING)
        assert_one_decimal(row["total_time_weighted_severity"], 40.0)
        assert row["included_violation_count"] == 4
        assert row["relevant_inspection_count"] == 4
        assert_one_decimal(row["denominator_value"], 30.0)
        assert_measure(row["certified_measure"], 1.333)
        assert_one_decimal(row["percentile"], 70.0)
        assert row["alert_status"] == AlertStatus.ALERT

        carrier = fx.read_carrier(api, carrier_id)
        assert carrier["open_alert_count"] == 1
        assert carrier["intervention_status"] == InterventionStatus.WARNING_LETTER
        assert_one_decimal(carrier["iss_pre_credit_value"], 24.5)
        assert_one_decimal(carrier["iss_value"], 24.5)


def _two_ages_around_the_lookback_edge(api) -> Dict[str, Any]:
    """One violation at age 730 days and one at age 731, both on SCORED reports."""
    base = _unsafe_driving_carrier(api)
    _, inside_rows = fx.build_scored_report(
        api,
        base["carrier"]["id"],
        [{"violation_code_id": base["code"]["id"], "unit_type": UnitType.VEHICLE}],
        report_number="OH730",
        inspection_start="2024-08-01T00:00:00Z",
        inspection_end="2024-08-01T01:00:00Z",
    )
    _, outside_rows = fx.build_scored_report(
        api,
        base["carrier"]["id"],
        [{"violation_code_id": base["code"]["id"], "unit_type": UnitType.VEHICLE}],
        report_number="OH731",
        inspection_start="2024-07-31T00:00:00Z",
        inspection_end="2024-07-31T01:00:00Z",
    )
    base["inside"] = inside_rows[0]
    base["outside"] = outside_rows[0]
    return base


class TestLookbackWindowEdge:
    def test_day_730_still_weighs_and_day_731_does_not(self, api):
        """PRD 3.3: "Finally, `time_weighted_severity` is computed as the sum of
        `code_weight_snapshot` and `oos_add_on_snapshot`, multiplied by `time_weight`."

        Design: Difficulty/boundary_precision_check/lookback_edge_730_included_731_excluded
        """
        scenario = _two_ages_around_the_lookback_edge(api)

        inside = fx.read_violation(api, scenario["inside"]["id"])
        assert inside["time_weight"] == 1
        assert_one_decimal(inside["time_weighted_severity"], 5.0)

        outside = fx.read_violation(api, scenario["outside"]["id"])
        assert outside["time_weight"] == 0
        assert_one_decimal(outside["time_weighted_severity"], 0.0)
        assert outside["status"] == ViolationStatus.ACTIVE

    def test_the_zero_weight_violation_leaves_both_counts(self, api):
        """PRD 3.4: "A violation is *included* in a category row when its `status` is
        `ACTIVE` or `RECODED`, its owning report's `status` is `SCORED`, that report's
        `attributed_carrier_id` is this carrier, its `time_weight` is greater than 0, and
        its `basic_category` matches the row's category."

        Design: Difficulty/boundary_precision_check/lookback_edge_730_included_731_excluded
        """
        scenario = _two_ages_around_the_lookback_edge(api)
        carrier_id = scenario["carrier"]["id"]

        row = fx.read_basic_score(api, carrier_id, BasicCategory.UNSAFE_DRIVING)
        assert_one_decimal(row["total_time_weighted_severity"], 5.0)
        assert row["included_violation_count"] == 1
        assert row["relevant_inspection_count"] == 1
        assert_measure(row["certified_measure"], 0.167)
        assert_one_decimal(row["percentile"], 16.7)
        assert row["alert_status"] == AlertStatus.CLEAR

        carrier = fx.read_carrier(api, carrier_id)
        assert_one_decimal(carrier["iss_pre_credit_value"], 5.9)
        assert_one_decimal(carrier["iss_value"], 5.9)
        assert carrier["selection_band"] == SelectionBand.PASS


def _two_validated_reports_at_the_bars(api) -> Dict[str, Any]:
    """Two identical VALIDATED inspections, neither scored yet, against a threshold
    carrying the default alert bars."""
    fx.set_clock(api)
    carrier = fx.create_carrier(api)
    code = fx.create_violation_code(
        api,
        code="392.2S",
        basic_category=BasicCategory.UNSAFE_DRIVING,
        severity_weight=5,
    )
    fx.create_threshold(
        api,
        basic_category=BasicCategory.UNSAFE_DRIVING,
        carrier_segment="MEDIUM",
        measure_at_p50=0.5,
        measure_at_p65=1.0,
        measure_at_p80=2.0,
        monitor_percentile=50.0,
        intervention_percentile=65.0,
        investigation_percentile=85.0,
    )
    reports = []
    for number in ("OH2026070112", "OH2026070113"):
        report, _ = fx.build_validated_report(
            api,
            carrier["id"],
            [{"violation_code_id": code["id"], "unit_type": UnitType.VEHICLE}],
            report_number=number,
            inspection_start="2026-07-01T14:00:00Z",
            inspection_end="2026-07-01T15:00:00Z",
        )
        reports.append(report)
    return {"carrier": carrier, "code": code, "reports": reports}


class TestAlertBarsAtExactEquality:
    def test_percentile_exactly_on_the_monitor_bar_monitors(self, api):
        """PRD 3.4: "Otherwise it is `ALERT` when `percentile` is at or above the
        reference row's `intervention_percentile`, `MONITOR` when `percentile` is at or
        above `monitor_percentile` but below the intervention bar, and `CLEAR` in all
        remaining cases."

        Design: Difficulty/boundary_precision_check/alert_status_exactly_at_monitor_then_intervention_percentile
        """
        scenario = _two_validated_reports_at_the_bars(api)
        carrier_id = scenario["carrier"]["id"]
        fx.score_report(api, scenario["reports"][0]["id"])

        row = fx.read_basic_score(api, carrier_id, BasicCategory.UNSAFE_DRIVING)
        assert_measure(row["certified_measure"], 0.500)
        assert_one_decimal(row["percentile"], 50.0)
        assert row["alert_status"] == AlertStatus.MONITOR
        assert row["relevant_inspection_count"] == 1

        carrier = fx.read_carrier(api, carrier_id)
        assert carrier["open_alert_count"] == 0
        assert carrier["intervention_status"] == InterventionStatus.NONE
        assert_one_decimal(carrier["iss_value"], 17.5)

    def test_percentile_exactly_on_the_intervention_bar_alerts(self, api):
        """PRD 3.4: "`open_alert_count` is the number of the carrier's score rows whose
        `alert_status` is `ALERT`."

        Design: Difficulty/boundary_precision_check/alert_status_exactly_at_monitor_then_intervention_percentile
        """
        scenario = _two_validated_reports_at_the_bars(api)
        carrier_id = scenario["carrier"]["id"]
        fx.score_report(api, scenario["reports"][0]["id"])
        fx.score_report(api, scenario["reports"][1]["id"])

        row = fx.read_basic_score(api, carrier_id, BasicCategory.UNSAFE_DRIVING)
        assert_one_decimal(row["total_time_weighted_severity"], 30.0)
        assert_measure(row["certified_measure"], 1.000)
        assert_one_decimal(row["percentile"], 65.0)
        assert row["alert_status"] == AlertStatus.ALERT
        assert row["relevant_inspection_count"] == 2

        carrier = fx.read_carrier(api, carrier_id)
        assert carrier["open_alert_count"] == 1
        assert_one_decimal(carrier["max_percentile"], 65.0)
        assert carrier["intervention_status"] == InterventionStatus.WARNING_LETTER
        assert_one_decimal(carrier["iss_pre_credit_value"], 22.8)
        assert_one_decimal(carrier["iss_value"], 22.8)
        assert carrier["selection_band"] == SelectionBand.PASS
