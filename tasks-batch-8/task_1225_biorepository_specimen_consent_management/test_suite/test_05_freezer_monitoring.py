"""Freezer temperature surveillance: excursion variants, warn boundary, plausibility."""
import pytest

from test_helpers import (
    validate_error,
    ApiErrorId,
    create_unit_with_slot,
    ingest_reading,
    get_unit,
    LAB_HEADERS,
)


class TestFreezerExcursionPeakVsCumulative:
    """Dual variants of the excursion assessment over identical readings."""

    def _run_readings(self, api, unit_id):
        ingest_reading(unit_id, "2026-05-01T00:00:00Z", -80.0)
        ingest_reading(unit_id, "2026-05-01T01:00:00Z", -65.0)
        ingest_reading(unit_id, "2026-05-01T02:00:00Z", -66.0)
        ingest_reading(unit_id, "2026-05-01T03:00:00Z", -80.0)

    def test_peak_variant_reports_worst_single_deviation(self, api):
        """PRD §3.4: "The **peak** variant, `peak_excursion_c`, is the largest excess
        any single reading has registered over the `warn_threshold_c`, floored at zero
        — it reports the single worst deviation regardless of duration, so a unit that
        touched -65 °C once and a unit that sat at -66 °C for hours can share the same
        peak."

        Design: Difficulty/dual_variant_calc/freezer_excursion_peak_vs_cumulative
        """
        unit, _ = create_unit_with_slot(unit_code="FRZ-EXC-A", warn_threshold_c=-70.0,
                                        fail_threshold_c=-60.0)
        self._run_readings(api, unit["id"])
        unit = get_unit(unit["id"])
        assert unit["peak_excursion_c"] == pytest.approx(5.0, abs=0.001), (
            f"peak must be max deviation -65.0 - -70.0 = 5.0, got {unit['peak_excursion_c']}")

    def test_cumulative_variant_time_weights_deviations(self, api):
        """PRD §3.4: "The **cumulative** variant, `cumulative_degree_minutes`,
        time-weights the deviations: for every reading strictly above
        `warn_threshold_c`, the excess of its `temp_c` over the threshold is multiplied
        by the whole minutes elapsed since the previous reading, and the product is
        added to the running total. Readings at or below the warn threshold accrue zero
        and end any excursion posture; a unit's very first reading has no predecessor
        and likewise accrues zero."

        Design: Difficulty/dual_variant_calc/freezer_excursion_peak_vs_cumulative
        """
        unit, _ = create_unit_with_slot(unit_code="FRZ-EXC-B", warn_threshold_c=-70.0,
                                        fail_threshold_c=-60.0)
        self._run_readings(api, unit["id"])
        unit = get_unit(unit["id"])
        # 5.0 * 60 + 4.0 * 60 = 540.0; first and final readings accrue 0.
        assert unit["cumulative_degree_minutes"] == pytest.approx(540.0, abs=0.001), (
            f"cumulative must be 540.0 degree-minutes, got {unit['cumulative_degree_minutes']}")
        assert unit["posture"] == "OPERATIONAL", (
            "final reading at/below the warn threshold ends the excursion posture")


class TestTemperatureWarningBoundaryExact:
    """Strictly-greater rule at the warn threshold."""

    def test_reading_exactly_at_threshold_stays_operational(self, api):
        """PRD §3.4: "A reading strictly above the unit's `warn_threshold_c` but at or
        below its `fail_threshold_c` moves an `OPERATIONAL` unit to `WARNING`."

        Design: Difficulty/boundary_precision_check/temperature_warning_boundary_exact
        """
        unit, _ = create_unit_with_slot(unit_code="FRZ-BND-A", warn_threshold_c=-70.0,
                                        fail_threshold_c=-60.0)
        ingest_reading(unit["id"], "2026-05-01T00:00:00Z", -70.0)
        unit = get_unit(unit["id"])
        assert unit["posture"] == "OPERATIONAL", (
            "exactly -70.0 is not strictly above the threshold; strict > must not fire")

    def test_reading_one_tenth_above_threshold_warns(self, api):
        """PRD §3.4: "A reading strictly above the unit's `warn_threshold_c` but at or
        below its `fail_threshold_c` moves an `OPERATIONAL` unit to `WARNING`."

        Design: Difficulty/boundary_precision_check/temperature_warning_boundary_exact
        """
        unit, _ = create_unit_with_slot(unit_code="FRZ-BND-B", warn_threshold_c=-70.0,
                                        fail_threshold_c=-60.0)
        ingest_reading(unit["id"], "2026-05-01T00:00:00Z", -70.0)
        ingest_reading(unit["id"], "2026-05-01T01:00:00Z", -69.9)
        unit = get_unit(unit["id"])
        assert unit["posture"] == "WARNING"
        assert unit["peak_excursion_c"] == pytest.approx(0.1, abs=0.001)


def test_temperature_reading_out_of_range_rejected(api):
    """PRD §3.4: "The plausible range for `temp_c` is from -100.0 to +25.0 inclusive —
    anything outside is rejected with `ERR_INVALID_TEMPERATURE_READING` (HTTP 400)."

    Design: Corner/validations/temperature_reading_out_of_range_rejected
    """
    unit, _ = create_unit_with_slot(unit_code="FRZ-VAL")
    resp = api.create_temperature_reading(
        unit["id"], {"recorded_at": "2026-05-01T00:00:00Z", "temp_c": 50.0}, LAB_HEADERS)
    validate_error(resp, ApiErrorId.ERR_INVALID_TEMPERATURE_READING)
    assert get_unit(unit["id"])["posture"] == "OPERATIONAL", (
        "a rejected reading must not alter posture")
