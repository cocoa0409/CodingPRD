"""What a relative accuracy test audit depends on outside its own row: the
audited unit's dispatch state, the monitor certification it gates, and the
half-open window resource it occupies."""
from test_helpers import (
    ApiErrorId,
    api_client,
    make_facility_operator_headers,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers import fixtures as fx
from test_helpers.factories import (
    cems_hour_payload,
    rata_runs_payload,
    rata_test_payload,
    single_hour_payload,
)


def _read_test(rata_test_id):
    return validate_success(api_client.get_rata_test(rata_test_id, fx.QA))


def _read_system(system_id):
    return validate_success(api_client.get_monitoring_system(system_id, fx.QA))


def _set_dispatch(unit_id, dispatch_state, operator_org="op_alpha"):
    return api_client.set_unit_dispatch(
        unit_id,
        {"dispatch_state": dispatch_state},
        make_facility_operator_headers(operator_org),
    )


class TestRunsRequireADispatchingUnit:
    """The audit reaches across to the Unit before it accepts any measurement."""

    def _offline_station(self):
        return fx.setup_scheduled_rata_test(
            parameter="NOX_RATE", span_value=0.800, online=False
        )

    def test_recording_runs_is_refused_while_the_unit_is_not_dispatching(self):
        """OFFLINE and RESERVE_SHUTDOWN are both refused with the same error.

        PRD: "The system must not be `RETIRED`, and the audited system's unit
        must be dispatching — `dispatch_state` exactly `ONLINE` — else
        `ERR_UNIT_NOT_ONLINE`, since an accuracy audit is only meaningful against
        a generating unit actually producing stack gas."

        Design: Difficulty/cross_entity_state_dependency/cross_entity_rata_runs_require_unit_online
        """
        station = self._offline_station()
        rata_test_id = station["rata_test"]["id"]
        payload = rata_runs_payload(fx.RATA_RUNS_PASSING)

        while_offline = api_client.record_rata_runs(rata_test_id, payload, fx.QA)
        validate_error(while_offline, ApiErrorId.ERR_UNIT_NOT_ONLINE.value)

        untouched = _read_test(rata_test_id)
        assert untouched["status"] == "SCHEDULED"
        assert untouched["run_count"] == 0

        # PRD declares exactly four dispatch moves, so RESERVE_SHUTDOWN is
        # reached from OFFLINE only by way of ONLINE.
        validate_success(_set_dispatch(station["unit"]["id"], "ONLINE"))
        validate_success(_set_dispatch(station["unit"]["id"], "RESERVE_SHUTDOWN"))
        while_reserve = api_client.record_rata_runs(rata_test_id, payload, fx.QA)
        validate_error(while_reserve, ApiErrorId.ERR_UNIT_NOT_ONLINE.value)

        assert _read_test(rata_test_id)["status"] == "SCHEDULED"
        assert _read_test(rata_test_id)["run_count"] == 0

    def test_the_identical_payload_succeeds_once_the_unit_is_online(self):
        """The run data never changes; only the unit's dispatch state does.

        PRD: "Recording the audit's runs advances it from `SCHEDULED` to
        `RUNS_RECORDED`."

        Design: Difficulty/cross_entity_state_dependency/cross_entity_rata_runs_require_unit_online
        """
        station = self._offline_station()
        rata_test_id = station["rata_test"]["id"]
        unit_id = station["unit"]["id"]
        payload = rata_runs_payload(fx.RATA_RUNS_PASSING)

        validate_error(
            api_client.record_rata_runs(rata_test_id, payload, fx.QA),
            ApiErrorId.ERR_UNIT_NOT_ONLINE.value,
        )
        # PRD declares exactly four dispatch moves, so RESERVE_SHUTDOWN is
        # reached from OFFLINE only by way of ONLINE.
        validate_success(_set_dispatch(unit_id, "ONLINE"))
        validate_success(_set_dispatch(unit_id, "RESERVE_SHUTDOWN"))
        validate_error(
            api_client.record_rata_runs(rata_test_id, payload, fx.QA),
            ApiErrorId.ERR_UNIT_NOT_ONLINE.value,
        )
        validate_success(_set_dispatch(unit_id, "ONLINE"))

        recorded = validate_success(
            api_client.record_rata_runs(rata_test_id, payload, fx.QA)
        )
        assert recorded["status"] == "RUNS_RECORDED"
        assert recorded["run_count"] == 9
        assert recorded["relative_accuracy_pct"] is None, (
            "recording runs does not evaluate them"
        )

        unit = validate_success(api_client.get_unit(unit_id, fx.REVIEWER))
        assert unit["dispatch_state"] == "ONLINE"
        assert unit["version"] == 4, (
            f"three dispatch patches each spend one version, got {unit['version']}"
        )


class TestCertificationGatedByOutstandingAudit:
    """A monitor cannot be certified while one of its own audits has failed."""

    def _monitor_with_failed_audit(self):
        station = fx.setup_facility_and_unit(online=True)
        station["system"] = fx.install_monitoring_system(
            station["unit"]["id"],
            parameter="SO2",
            system_type="CEM",
            span_value=400.0,
            calibration_error_spec_pct=2.5,
        )
        fx.record_daily_calibration(
            station["system"]["id"],
            station["system"]["version"],
            calibration_utc="2026-04-01T00:00:00Z",
            span_reference_value=360.0,
            span_measured_value=368.0,
        )
        station["rata_test"] = validate_success(
            api_client.schedule_rata_test(
                station["system"]["id"], rata_test_payload(), fx.QA
            ),
            201,
        )
        fx.record_rata_runs(station["rata_test"]["id"], fx.RATA_RUNS_FAILING)
        station["failed"] = fx.evaluate_rata_test(station["rata_test"]["id"])
        station["report"] = fx.open_quarterly_report(station["unit"]["id"])
        return station

    def test_certification_is_refused_while_an_audit_of_the_monitor_is_failed(self):
        """The calibration is current, so the refusal is the audit condition.

        PRD: "In all three cases, no relative accuracy test audit of this system
        may be sitting in `FAILED`, else `ERR_MONITOR_NOT_CERTIFIED`."

        Design: Difficulty/cross_entity_state_dependency/cross_entity_certify_blocked_by_outstanding_failed_rata_test
        """
        station = self._monitor_with_failed_audit()
        system_id = station["system"]["id"]

        assert station["failed"]["status"] == "FAILED"
        assert _read_system(system_id)["cal_status"] == "CAL_CURRENT"

        blocked = api_client.drive_qa_status(system_id, {"action": "CERTIFY"}, fx.QA)
        validate_error(blocked, ApiErrorId.ERR_MONITOR_NOT_CERTIFIED.value)

        assert _read_system(system_id)["qa_status"] == "RECERTIFICATION_PENDING"

    def test_the_certification_adopts_the_passed_audits_bias_factor(self):
        """1.0883 is copied onto the monitor and raises the next hour's SO2 mass.

        PRD: "It then adopts a bias adjustment: if at least one audit of this
        system has `PASSED`, the `bias_adjustment_factor` of the passed audit with
        the greatest `window_end_utc` — resolving ties by the earlier `created_at`
        — is copied onto the system; if none has passed, the factor stays at 1.0."

        Design: Difficulty/cross_entity_state_dependency/cross_entity_certify_blocked_by_outstanding_failed_rata_test
        """
        station = self._monitor_with_failed_audit()
        system_id = station["system"]["id"]
        rata_test_id = station["rata_test"]["id"]

        validate_error(
            api_client.drive_qa_status(system_id, {"action": "CERTIFY"}, fx.QA),
            ApiErrorId.ERR_MONITOR_NOT_CERTIFIED.value,
        )
        validate_success(
            api_client.reschedule_rata_test(
                rata_test_id,
                {
                    "window_start_utc": "2026-04-05T00:00:00Z",
                    "window_end_utc": "2026-04-06T00:00:00Z",
                },
                fx.QA,
            )
        )
        fx.record_rata_runs(rata_test_id, fx.RATA_RUNS_PASSING)
        passed = fx.evaluate_rata_test(rata_test_id)
        assert passed["status"] == "PASSED"
        assert passed["relative_accuracy_pct"] == 10.0
        assert passed["attempt_number"] == 2
        assert passed["bias_adjustment_factor"] == 1.0883

        certified = fx.drive_qa_status(system_id, "CERTIFY")
        assert certified["qa_status"] == "CERTIFIED"
        assert certified["bias_adjustment_factor"] == 1.0883

        hour = validate_success(
            api_client.append_operating_hour(
                station["unit"]["id"],
                single_hour_payload(
                    station["report"]["version"],
                    cems_hour_payload("2026-04-01T00:00:00Z"),
                ),
                fx.PREPARER,
            ),
            201,
        )
        assert hour["so2_mass_lbs"] == 318.0, (
            "292.2 unadjusted multiplied by 1.0883 rounds to 318.0, got "
            f"{hour['so2_mass_lbs']}"
        )
        assert hour["heat_input_mmbtu"] == 555.556, (
            "the bias factor touches the SO2 mass only"
        )
        assert hour["nox_mass_lbs"] == 100.0
        assert hour["co2_mass_tons"] == 59.700


class TestRataWindowResource:
    """The window is a half-open interval owned by one monitoring system."""

    def _two_systems(self):
        station = fx.setup_facility_and_unit()
        station["system_a"] = fx.install_monitoring_system(
            station["unit"]["id"], parameter="SO2", system_type="CEM", span_value=400.0
        )
        station["system_b"] = fx.install_monitoring_system(
            station["unit"]["id"], parameter="CO2", system_type="CEM", span_value=20.0
        )
        return station

    def _schedule(self, system_id, start, end):
        return api_client.schedule_rata_test(
            system_id,
            rata_test_payload(window_start_utc=start, window_end_utc=end),
            fx.QA,
        )

    def test_abutting_windows_are_legal_and_one_shared_second_is_not(self):
        """[04-04, 04-05) abuts [04-03, 04-04); starting a second earlier collides.

        PRD: "a window overlapping another audit of the same system that is still
        `SCHEDULED` or `RUNS_RECORDED` is `ERR_RATA_WINDOW_OVERLAP`, with
        half-open comparison, so a window starting exactly where an incumbent ends
        is accepted while one second earlier is not, and audits already `PASSED`,
        `FAILED` or `VOIDED` never block"

        Design: Difficulty/resource_temporal_overlap/overlap_rata_windows_are_half_open_per_monitoring_system
        """
        station = self._two_systems()
        system_a = station["system_a"]["id"]

        first = validate_success(
            self._schedule(system_a, "2026-04-03T00:00:00Z", "2026-04-04T00:00:00Z"),
            201,
        )
        assert first["status"] == "SCHEDULED"
        assert first["attempt_number"] == 1
        assert first["retest_of_rata_test_id"] is None

        abutting = validate_success(
            self._schedule(system_a, "2026-04-04T00:00:00Z", "2026-04-05T00:00:00Z"),
            201,
        )
        assert abutting["window_start_utc"] == "2026-04-04T00:00:00Z", (
            "the end bound is exclusive, so the two windows share no instant"
        )

        colliding = self._schedule(
            system_a, "2026-04-04T23:59:59Z", "2026-04-06T00:00:00Z"
        )
        validate_error(colliding, ApiErrorId.ERR_RATA_WINDOW_OVERLAP.value)

        at_the_clock = validate_success(
            self._schedule(system_a, "2026-04-02T00:00:00Z", "2026-04-03T00:00:00Z"),
            201,
        )
        assert at_the_clock["window_start_utc"] == "2026-04-02T00:00:00Z", (
            "a window starting exactly at the logical clock is not in the past"
        )

    def test_the_window_resource_is_scoped_per_monitoring_system(self):
        """The identical interval is free on a sibling system.

        PRD: "a `window_start_utc` strictly before the logical clock is
        `ERR_RATA_WINDOW_IN_PAST`, with equality accepted."

        Design: Difficulty/resource_temporal_overlap/overlap_rata_windows_are_half_open_per_monitoring_system
        """
        station = self._two_systems()
        system_a = station["system_a"]["id"]
        system_b = station["system_b"]["id"]

        validate_success(
            self._schedule(system_a, "2026-04-03T00:00:00Z", "2026-04-04T00:00:00Z"),
            201,
        )
        validate_success(
            self._schedule(system_a, "2026-04-04T00:00:00Z", "2026-04-05T00:00:00Z"),
            201,
        )
        validate_success(
            self._schedule(system_a, "2026-04-02T00:00:00Z", "2026-04-03T00:00:00Z"),
            201,
        )

        in_the_past = self._schedule(
            system_a, "2026-04-01T00:00:00Z", "2026-04-01T12:00:00Z"
        )
        validate_error(in_the_past, ApiErrorId.ERR_RATA_WINDOW_IN_PAST.value)

        zero_length = self._schedule(
            system_a, "2026-04-07T00:00:00Z", "2026-04-07T00:00:00Z"
        )
        validate_error(zero_length, ApiErrorId.ERR_INVALID_INTERVAL.value)

        sibling = validate_success(
            self._schedule(system_b, "2026-04-03T00:00:00Z", "2026-04-04T00:00:00Z"),
            201,
        )
        assert sibling["monitoring_system_id"] == system_b, (
            "the window resource is keyed by monitoring system, so the identical "
            "interval does not collide"
        )

        rows_a, meta_a = validate_paginated(
            api_client.list_rata_tests(fx.QA, {"monitoring_system_id": system_a})
        )
        assert meta_a["total_count"] == 3, (
            f"three windows were accepted on the audited system, listing gave "
            f"{meta_a['total_count']}"
        )
        for row in rows_a:
            assert row["status"] == "SCHEDULED"

        _, meta_b = validate_paginated(
            api_client.list_rata_tests(fx.QA, {"monitoring_system_id": system_b})
        )
        assert meta_b["total_count"] == 1
