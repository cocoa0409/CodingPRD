"""The two independent status axes of a monitoring system, and the
calibration-error ladder that drives the calibration axis."""
from test_helpers import (
    ApiErrorId,
    api_client,
    assert_daily_calibration,
    assert_monitoring_system,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers import fixtures as fx


def _bare_so2_cem():
    """Facility + unit + a freshly installed, never-certified SO2 CEM."""
    station = fx.setup_facility_and_unit()
    station["system"] = fx.install_monitoring_system(
        station["unit"]["id"],
        parameter="SO2",
        system_type="CEM",
        span_value=400.0,
        calibration_error_spec_pct=2.5,
    )
    return station


def _read_system(system_id):
    return validate_success(api_client.get_monitoring_system(system_id, fx.QA))


class TestParallelStatusAxes:
    """`qa_status` and `cal_status` move independently on one row."""

    def test_calibration_axis_cycles_while_the_qa_axis_stays_certified(self):
        """One failed check moves cal_status only; a pass resets the counter.

        PRD: "A `PASSED` result sets `cal_status` to `CAL_CURRENT` from either
        `CAL_EXPIRED` or `CAL_FAILED`, stamps `last_calibration_utc` from
        `calibration_utc`, and resets `consecutive_failed_calibrations` to 0; the
        QA axis is untouched, so a certified system that failed one check is back
        to `CAL_CURRENT` without any QA action, and an out-of-control system
        remains out of control."

        Design: Difficulty/non_linear_state_machine/non_linear_monitoring_system_qa_and_calibration_dimensions_move_independently
        """
        station = _bare_so2_cem()
        system_id = station["system"]["id"]

        assert station["system"]["qa_status"] == "RECERTIFICATION_PENDING"
        assert station["system"]["cal_status"] == "CAL_EXPIRED"
        assert station["system"]["consecutive_failed_calibrations"] == 0

        first = fx.record_daily_calibration(
            system_id,
            station["system"]["version"],
            calibration_utc="2026-04-01T00:00:00Z",
            span_reference_value=360.0,
            span_measured_value=368.0,
        )
        assert_daily_calibration(first)
        assert first["span_error_pct_of_span"] == 2.00
        assert first["result"] == "PASSED"

        after_pass = _read_system(system_id)
        assert after_pass["cal_status"] == "CAL_CURRENT"
        assert after_pass["qa_status"] == "RECERTIFICATION_PENDING", (
            "a passing calibration must not move the QA axis"
        )

        certified = fx.drive_qa_status(system_id, "CERTIFY")
        assert certified["qa_status"] == "CERTIFIED"
        assert certified["cal_status"] == "CAL_CURRENT"

        failed = fx.record_daily_calibration(
            system_id,
            certified["version"],
            calibration_utc="2026-04-01T01:00:00Z",
            span_reference_value=360.0,
            span_measured_value=374.0,
        )
        assert failed["span_error_pct_of_span"] == 3.50, (
            f"|374 - 360| / 400 * 100 is 3.50, got {failed['span_error_pct_of_span']}"
        )
        assert failed["result"] == "FAILED", (
            "3.50 exceeds the 2.5 specification but not twice it, and it is the "
            "first consecutive failure, so the result stays FAILED"
        )

        after_failure = _read_system(system_id)
        assert after_failure["cal_status"] == "CAL_FAILED"
        assert after_failure["qa_status"] == "CERTIFIED", (
            "the QA axis did not move: CERTIFIED with CAL_FAILED is a legal state"
        )
        assert after_failure["consecutive_failed_calibrations"] == 1

        recovered = fx.record_daily_calibration(
            system_id,
            after_failure["version"],
            calibration_utc="2026-04-01T02:00:00Z",
            span_reference_value=360.0,
            span_measured_value=368.0,
        )
        assert recovered["result"] == "PASSED"

        after_recovery = _read_system(system_id)
        assert after_recovery["cal_status"] == "CAL_CURRENT"
        assert after_recovery["consecutive_failed_calibrations"] == 0, (
            "the counter is reset by a pass, not merely stalled"
        )
        assert after_recovery["qa_status"] == "CERTIFIED"

    def test_the_second_consecutive_failure_couples_the_axes(self):
        """Two failures in a row escalate to OUT_OF_CONTROL_TRIGGERED.

        PRD: "Otherwise, if the worse percentage is **strictly greater than** the
        specification, the check has failed: taking the system's
        `consecutive_failed_calibrations` as it stood before this call and adding
        one, a running count that reaches **two** upgrades the `result` to
        `OUT_OF_CONTROL_TRIGGERED`, and a count of one leaves the `result` at
        `FAILED`."

        Design: Difficulty/non_linear_state_machine/non_linear_monitoring_system_qa_and_calibration_dimensions_move_independently
        """
        station = _bare_so2_cem()
        system_id = station["system"]["id"]

        fx.record_daily_calibration(
            system_id,
            station["system"]["version"],
            calibration_utc="2026-04-01T00:00:00Z",
            span_reference_value=360.0,
            span_measured_value=368.0,
        )
        version = fx.drive_qa_status(system_id, "CERTIFY")["version"]

        for hour, measured in (("01", 374.0), ("02", 368.0), ("03", 374.0)):
            record = fx.record_daily_calibration(
                system_id,
                version,
                calibration_utc=f"2026-04-01T{hour}:00:00Z",
                span_reference_value=360.0,
                span_measured_value=measured,
            )
            version = record["monitoring_system_version_after"]

        assert _read_system(system_id)["qa_status"] == "CERTIFIED"
        assert _read_system(system_id)["consecutive_failed_calibrations"] == 1

        escalating = fx.record_daily_calibration(
            system_id,
            version,
            calibration_utc="2026-04-01T04:00:00Z",
            span_reference_value=360.0,
            span_measured_value=375.0,
        )
        assert escalating["span_error_pct_of_span"] == 3.75
        assert escalating["result"] == "OUT_OF_CONTROL_TRIGGERED", (
            "the running count reaches two, so the result is upgraded"
        )

        system = _read_system(system_id)
        assert_monitoring_system(system)
        assert system["qa_status"] == "OUT_OF_CONTROL", (
            "only the second consecutive failure couples the QA axis to the "
            "calibration axis"
        )
        assert system["cal_status"] == "CAL_FAILED"
        assert system["out_of_control_since_utc"] == "2026-04-01T04:00:00Z"

        blocked = api_client.drive_qa_status(
            system_id, {"action": "CERTIFY"}, fx.QA
        )
        validate_error(blocked, ApiErrorId.ERR_CALIBRATION_NOT_CURRENT.value)

    def test_out_of_control_with_cal_current_is_the_only_restore_point(self):
        """A pass while out of control reaches the combined state that re-certifies.

        PRD: "A system may legitimately sit at `CERTIFIED` with `CAL_FAILED`, or
        at `OUT_OF_CONTROL` with `CAL_CURRENT`. Neither axis constrains the
        other's reachable set — but the classification of an operating hour reads
        *both*."

        Design: Difficulty/non_linear_state_machine/non_linear_monitoring_system_qa_and_calibration_dimensions_move_independently
        """
        station = _bare_so2_cem()
        system_id = station["system"]["id"]

        fx.record_daily_calibration(
            system_id,
            station["system"]["version"],
            calibration_utc="2026-04-01T00:00:00Z",
            span_reference_value=360.0,
            span_measured_value=368.0,
        )
        version = fx.drive_qa_status(system_id, "CERTIFY")["version"]
        for hour, measured in (
            ("01", 374.0),
            ("02", 368.0),
            ("03", 374.0),
            ("04", 375.0),
        ):
            record = fx.record_daily_calibration(
                system_id,
                version,
                calibration_utc=f"2026-04-01T{hour}:00:00Z",
                span_reference_value=360.0,
                span_measured_value=measured,
            )
            version = record["monitoring_system_version_after"]

        assert _read_system(system_id)["qa_status"] == "OUT_OF_CONTROL"

        clearing = fx.record_daily_calibration(
            system_id,
            version,
            calibration_utc="2026-04-01T05:00:00Z",
            span_reference_value=360.0,
            span_measured_value=368.0,
        )
        assert clearing["result"] == "PASSED"

        combined = _read_system(system_id)
        assert combined["qa_status"] == "OUT_OF_CONTROL"
        assert combined["cal_status"] == "CAL_CURRENT", (
            "the combined OUT_OF_CONTROL / CAL_CURRENT state must be reachable"
        )

        restored = fx.drive_qa_status(system_id, "CERTIFY")
        assert restored["qa_status"] == "CERTIFIED"
        assert restored["cal_status"] == "CAL_CURRENT"
        assert restored["out_of_control_since_utc"] is None, (
            "a successful certification clears out_of_control_since_utc"
        )
        assert restored["consecutive_failed_calibrations"] == 0
        assert restored["bias_adjustment_factor"] == 1.0, (
            "no audit of this system has passed, so the factor stays at 1.0"
        )

        rows, meta = validate_paginated(
            api_client.list_system_daily_calibrations(system_id, fx.QA)
        )
        assert meta["total_count"] == 6, (
            f"six calibrations were recorded, listing returned {meta['total_count']}"
        )
        for row in rows:
            assert "version" not in row or row["version"] is None, (
                "a daily calibration is an append-only record and carries no version"
            )


class TestCalibrationErrorLadder:
    """The ladder is evaluated top to bottom and the first match wins."""

    def test_span_error_exactly_at_spec_passes_and_twice_spec_only_fails(self):
        """2.50 passes, 5.00 is FAILED, and the zero pair can govern the verdict.

        PRD: "If the worse percentage is **strictly greater than twice** the
        specification, the `result` is `OUT_OF_CONTROL_TRIGGERED` on this single
        grossly failed check — a percentage exactly equal to twice the
        specification does *not* take this branch."

        Design: Difficulty/boundary_precision_check/boundary_calibration_span_error_exactly_at_spec_passes
        """
        station = _bare_so2_cem()
        system_id = station["system"]["id"]
        version = station["system"]["version"]

        at_spec = fx.record_daily_calibration(
            system_id,
            version,
            calibration_utc="2026-04-01T00:00:00Z",
            span_reference_value=360.0,
            span_measured_value=370.0,
        )
        assert at_spec["span_error_pct_of_span"] == 2.50
        assert at_spec["zero_error_pct_of_span"] == 0.00
        assert at_spec["result"] == "PASSED", (
            "equality with the specification passes; the comparison is strictly "
            "greater-than"
        )
        after = _read_system(system_id)
        assert after["cal_status"] == "CAL_CURRENT"
        assert after["consecutive_failed_calibrations"] == 0

        at_twice_spec = fx.record_daily_calibration(
            system_id,
            at_spec["monitoring_system_version_after"],
            calibration_utc="2026-04-01T01:00:00Z",
            span_reference_value=360.0,
            span_measured_value=380.0,
        )
        assert at_twice_spec["span_error_pct_of_span"] == 5.00
        assert at_twice_spec["result"] == "FAILED", (
            "exactly twice the specification does not take the out-of-control "
            "branch, and this is only the first consecutive failure"
        )
        after = _read_system(system_id)
        assert after["cal_status"] == "CAL_FAILED"
        assert after["consecutive_failed_calibrations"] == 1

        recovered = fx.record_daily_calibration(
            system_id,
            at_twice_spec["monitoring_system_version_after"],
            calibration_utc="2026-04-01T02:00:00Z",
            span_reference_value=360.0,
            span_measured_value=368.0,
        )
        assert recovered["result"] == "PASSED"
        assert _read_system(system_id)["consecutive_failed_calibrations"] == 0

        zero_drift = fx.record_daily_calibration(
            system_id,
            recovered["monitoring_system_version_after"],
            calibration_utc="2026-04-01T03:00:00Z",
            zero_measured_value=12.0,
            span_reference_value=360.0,
            span_measured_value=368.0,
        )
        assert zero_drift["zero_error_pct_of_span"] == 3.00
        assert zero_drift["span_error_pct_of_span"] == 2.00
        assert zero_drift["result"] == "FAILED", (
            "the verdict reads the worse of the two percentages, so the zero "
            "drift governs even though the span pair is inside spec"
        )

    def test_the_first_percentage_past_twice_spec_trips_out_of_control(self):
        """5.03 percent of span is out of control on one single check.

        PRD: "`zero_error_pct_of_span` is the absolute difference between
        `zero_measured_value` and `zero_reference_value`, divided by the system's
        `span_value`, multiplied by 100 and rounded half up to two decimal
        places; `span_error_pct_of_span` is the same computation on the upscale
        pair."

        Design: Difficulty/boundary_precision_check/boundary_calibration_span_error_exactly_at_spec_passes
        """
        station = _bare_so2_cem()
        system_id = station["system"]["id"]

        version = station["system"]["version"]
        for hour, kwargs in (
            ("00", {"span_measured_value": 370.0}),
            ("01", {"span_measured_value": 380.0}),
            ("02", {"span_measured_value": 368.0}),
            ("03", {"span_measured_value": 368.0, "zero_measured_value": 12.0}),
            ("04", {"span_measured_value": 368.0}),
        ):
            record = fx.record_daily_calibration(
                system_id,
                version,
                calibration_utc=f"2026-04-01T{hour}:00:00Z",
                span_reference_value=360.0,
                **kwargs,
            )
            version = record["monitoring_system_version_after"]

        assert _read_system(system_id)["consecutive_failed_calibrations"] == 0

        gross = fx.record_daily_calibration(
            system_id,
            version,
            calibration_utc="2026-04-01T05:00:00Z",
            span_reference_value=360.0,
            span_measured_value=380.1,
        )
        assert gross["span_error_pct_of_span"] == 5.03, (
            "20.1 / 400 * 100 is 5.025, which rounds half up to 5.03, got "
            f"{gross['span_error_pct_of_span']}"
        )
        assert gross["result"] == "OUT_OF_CONTROL_TRIGGERED"

        system = _read_system(system_id)
        assert system["cal_status"] == "CAL_FAILED"
        assert system["qa_status"] == "RECERTIFICATION_PENDING", (
            "the system was never certified, so no out-of-control cascade fires"
        )

        _, meta = validate_paginated(
            api_client.list_daily_calibrations(
                fx.QA, {"monitoring_system_id": system_id, "result": "PASSED"}
            )
        )
        assert meta["total_count"] == 3, (
            f"three of the six calibrations passed, listing gave {meta['total_count']}"
        )
