"""The out-of-control cascade, and the order in which report validation
reports a collapsed monitor against a collapsed availability figure."""
from test_helpers import (
    ApiErrorId,
    api_client,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers import fixtures as fx


def _hour(hour_id):
    return validate_success(api_client.get_operating_hour(hour_id, fx.PREPARER))


def _report(report_id):
    return validate_success(api_client.get_quarterly_report(report_id, fx.PREPARER))


def _limit(limit_id):
    return validate_success(api_client.get_permit_limit(limit_id, fx.REVIEWER))


def _event(event_id):
    return validate_success(
        api_client.get_excess_emission_event(event_id, fx.REVIEWER)
    )


def _exceeded_station():
    """Three measured hours, a validated report, an EXCEEDED rolling limit and
    the DETECTED event it raised."""
    return fx.setup_exceeded_permit_limit(
        hour_count=3,
        limit_value=250.0,
        anchor_utc="2026-04-01T03:00:00Z",
        validate=True,
    )


def _trip_out_of_control(station):
    """One grossly failed calibration: 25.0 / 400 * 100 is 6.25 percent."""
    return fx.record_daily_calibration(
        station["system"]["id"],
        station["system"]["version"],
        calibration_utc="2026-04-01T01:00:00Z",
        span_reference_value=360.0,
        span_measured_value=385.0,
    )


class TestOutOfControlCascade:
    """One failing check walks monitor, hours, report and permit limit."""

    def test_the_cascade_flips_only_the_hours_at_or_after_the_instant(self):
        """Link 1 and link 2: the 00:00 hour survives, 01:00 and 02:00 do not.

        PRD: "Every operating hour of this system's unit whose `hour_begin_utc`
        is at or after `out_of_control_since_utc` truncated to the hour, and whose
        `data_quality` is `MEASURED`, is set to `data_quality` of `UNAVAILABLE`
        with its `so2_mass_lbs` cleared to null."

        Design: Difficulty/transitive_cascade/cascade_out_of_control_calibration_flips_hours_reverts_report_and_withdraws_event
        """
        station = _exceeded_station()
        first, second, third = station["hours"]

        calibration = _trip_out_of_control(station)
        assert calibration["span_error_pct_of_span"] == 6.25
        assert calibration["result"] == "OUT_OF_CONTROL_TRIGGERED", (
            "6.25 is strictly greater than twice the 2.5 specification, so one "
            "failure suffices"
        )

        system = validate_success(
            api_client.get_monitoring_system(station["system"]["id"], fx.QA)
        )
        assert system["qa_status"] == "OUT_OF_CONTROL"
        assert system["cal_status"] == "CAL_FAILED"
        assert system["out_of_control_since_utc"] == "2026-04-01T01:00:00Z"

        untouched = _hour(first["id"])
        assert untouched["data_quality"] == "MEASURED", (
            "the 00:00 hour is strictly before the instant and is left alone"
        )
        assert untouched["so2_mass_lbs"] == 292.2

        for flipped_id in (second["id"], third["id"]):
            flipped = _hour(flipped_id)
            assert flipped["data_quality"] == "UNAVAILABLE"
            assert flipped["so2_mass_lbs"] is None
            assert flipped["heat_input_mmbtu"] == 555.556, (
                "only the SO2 mass is cleared; the heat input is not voided"
            )

        unit = validate_success(
            api_client.get_unit(station["unit"]["id"], fx.REVIEWER)
        )
        assert unit["data_availability_pct"] == 33.3, (
            f"one measured hour out of three is 33.3, got "
            f"{unit['data_availability_pct']}"
        )

    def test_the_flipped_hours_revert_the_validated_report_to_draft(self):
        """Link 3: the SO2 total collapses while heat input, NOx and CO2 hold.

        PRD: "For each distinct report among the flipped hours,
        `operating_hour_count`, `measured_hour_count`, `substituted_hour_count`,
        `monitor_data_availability_pct` and every total are recomputed; a report
        standing at `VALIDATED` reverts to `DRAFT`, and its `version` increments
        by one."

        Design: Difficulty/transitive_cascade/cascade_out_of_control_calibration_flips_hours_reverts_report_and_withdraws_event
        """
        station = _exceeded_station()
        before = _report(station["report"]["id"])
        assert before["status"] == "VALIDATED"
        assert before["total_so2_lbs"] == 876.6

        _trip_out_of_control(station)

        after = _report(station["report"]["id"])
        assert after["status"] == "DRAFT"
        assert after["version"] > before["version"]
        assert after["total_so2_lbs"] == 292.2, (
            "a null so2_mass_lbs counts as zero, leaving only the surviving hour"
        )
        assert after["total_so2_tons"] == 0.146
        assert after["total_heat_input_mmbtu"] == 1666.668
        assert after["total_nox_lbs"] == 300.0
        assert after["total_co2_tons"] == 179.100
        assert after["operating_hour_count"] == 3
        assert after["measured_hour_count"] == 1
        assert after["substituted_hour_count"] == 0
        assert after["monitor_data_availability_pct"] == 33.3

    def test_the_report_recompute_withdraws_the_already_detected_event(self):
        """Link 4: the limit re-evaluates at its stored anchor and the event closes.

        PRD: "Every permit limit of the same unit whose `evaluation_status` is
        not `NOT_EVALUATED` is re-evaluated at its stored `window_evaluated_utc`.
        A limit that becomes `EXCEEDED` raises a new excess emission event in
        `DETECTED`; a limit that leaves `EXCEEDED` moves each of its events still
        in `DETECTED` to `WITHDRAWN`."

        Design: Difficulty/transitive_cascade/cascade_out_of_control_calibration_flips_hours_reverts_report_and_withdraws_event
        """
        station = _exceeded_station()
        limit_before = _limit(station["permit_limit"]["id"])
        assert limit_before["evaluation_status"] == "EXCEEDED"
        assert limit_before["current_rolling_value"] == 292.2
        assert limit_before["window_sample_count"] == 3

        event_before = _event(station["event"]["id"])
        assert event_before["status"] == "DETECTED"
        assert event_before["observed_value"] == 292.2
        assert event_before["limit_value_snapshot"] == 250.0
        assert event_before["exceedance_magnitude"] == 42.2
        assert event_before["penalty_allowance_debit_tons"] == 17

        _trip_out_of_control(station)

        limit_after = _limit(station["permit_limit"]["id"])
        assert limit_after["evaluation_status"] == "INSUFFICIENT_DATA"
        assert limit_after["window_sample_count"] == 1
        assert limit_after["current_rolling_value"] is None
        assert limit_after["window_evaluated_utc"] == "2026-04-01T03:00:00Z", (
            "the re-evaluation uses the stored anchor, not the logical clock"
        )

        assert _event(station["event"]["id"])["status"] == "WITHDRAWN"

        _, meta = validate_paginated(
            api_client.list_excess_emission_events(fx.REVIEWER, {"status": "DETECTED"})
        )
        assert meta["total_count"] == 0, (
            f"the only detected event was withdrawn, {meta['total_count']} remain"
        )


class TestValidationRefusalOrder:
    """A collapsed monitor is reported ahead of a collapsed availability figure."""

    def _twenty_hour_report_with_declared_outage(self):
        station = fx.setup_draft_report_with_cems_hours(hour_count=20)
        fx.drive_qa_status(
            station["system"]["id"],
            "DECLARE_OUT_OF_CONTROL",
            effective_utc="2026-04-01T15:00:00Z",
            reason="cylinder gas audit exceeded tolerance",
        )
        return station

    def test_validate_reports_the_out_of_control_monitor_not_the_floor(self):
        """The monitor state wins even though availability already sits at 75.0.

        PRD: "The specific out-of-control condition is reported ahead of the
        generic not-certified condition, and both are reported ahead of the
        availability floor even when availability has already collapsed."

        Design: Difficulty/priority_pair_validation_conflict/priority_monitor_out_of_control_beats_data_availability_floor
        """
        station = self._twenty_hour_report_with_declared_outage()

        report = _report(station["report"]["id"])
        assert report["monitor_data_availability_pct"] == 75.0
        assert report["measured_hour_count"] == 15
        assert report["operating_hour_count"] == 20
        assert report["total_so2_lbs"] == 4383.0
        assert report["total_heat_input_mmbtu"] == 11111.120

        system = validate_success(
            api_client.get_monitoring_system(station["system"]["id"], fx.QA)
        )
        assert system["qa_status"] == "OUT_OF_CONTROL"

        response = api_client.validate_quarterly_report(
            station["report"]["id"], {}, fx.PREPARER
        )
        validate_error(response, ApiErrorId.ERR_MONITOR_OUT_OF_CONTROL.value)

        assert _report(station["report"]["id"])["status"] == "DRAFT"

    def test_the_availability_floor_surfaces_only_once_the_monitor_is_restored(self):
        """The same call refuses with the floor error after re-certification.

        PRD: "the recomputed `monitor_data_availability_pct` must be **at or
        above** the data availability floor of 80.0 percent, so exactly 80.0
        passes and 79.9 does not (`ERR_DATA_AVAILABILITY_BELOW_FLOOR`)."

        Design: Difficulty/priority_pair_validation_conflict/priority_monitor_out_of_control_beats_data_availability_floor
        """
        station = self._twenty_hour_report_with_declared_outage()

        restored = fx.drive_qa_status(station["system"]["id"], "CERTIFY")
        assert restored["qa_status"] == "CERTIFIED"
        assert restored["cal_status"] == "CAL_CURRENT"

        response = api_client.validate_quarterly_report(
            station["report"]["id"], {}, fx.PREPARER
        )
        validate_error(response, ApiErrorId.ERR_DATA_AVAILABILITY_BELOW_FLOOR.value)

        report = _report(station["report"]["id"])
        assert report["status"] == "DRAFT"
        assert report["monitor_data_availability_pct"] == 75.0, (
            "restoring the monitor does not reclassify the hours the cascade "
            "already flipped"
        )

        _, meta = validate_paginated(
            api_client.list_report_certifications(station["report"]["id"], fx.PREPARER)
        )
        assert meta["total_count"] == 0, (
            "a refused validation creates no certification"
        )
