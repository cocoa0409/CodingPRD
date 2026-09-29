"""Two stale-version guards replayed against their own parents, and the promise
that a writing response already carries every value a later read will show."""
from test_helpers import (
    ApiErrorId,
    api_client,
    assert_daily_calibration,
    assert_excess_emission_event,
    assert_operating_hour,
    assert_permit_limit,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers import fixtures as fx
from test_helpers.factories import (
    bulk_hours_payload,
    cems_hour_payload,
    daily_calibration_payload,
    permit_limit_payload,
    single_hour_payload,
)

CLOCK_APRIL = "2026-04-02T00:00:00Z"
ANCHOR_03 = "2026-04-01T03:00:00Z"


def _system(system_id):
    return validate_success(api_client.get_monitoring_system(system_id, fx.QA))


def _report(report_id):
    return validate_success(api_client.get_quarterly_report(report_id, fx.PREPARER))


class TestStaleMonitoringSystemVersion:
    """A replayed calibration guard value is refused, then honoured."""

    def test_the_second_calibration_needs_the_version_the_first_one_returned(self):
        """Version 1 replayed is 412; version 2 from the response is 201.

        PRD: "Recording a **daily calibration** requires
        `expected_monitoring_system_version` matching the target monitoring system's
        current `version`. A mismatch yields `ERR_STALE_MONITORING_SYSTEM_VERSION`
        (HTTP 412)."

        PRD: "Each requires a non-optional version field in its request body carrying
        the client's last observed `version` of the parent row; if the value does not
        equal the parent's current `version`, the write is rejected and nothing is
        persisted."

        PRD: "Every calibration increments the monitoring system's `version` by at
        least one, and the record reports `monitoring_system_version_after` so the
        operator can immediately chain another guarded write."

        PRD: "`zero_error_pct_of_span` is the absolute difference between
        `zero_measured_value` and `zero_reference_value`, divided by the system's
        `span_value`, multiplied by 100 and rounded half up to two decimal places;
        `span_error_pct_of_span` is the same computation on the upscale pair."

        Design: Corner/complexity_layers/layer_occ_daily_calibration_rejects_a_stale_system_version
        """
        station = fx.setup_facility_and_unit(clock=CLOCK_APRIL)
        system = fx.install_monitoring_system(
            station["unit"]["id"], parameter="SO2", span_value=400.0
        )
        assert system["version"] == 1

        first = validate_success(
            api_client.record_daily_calibration(
                system["id"],
                daily_calibration_payload(
                    system["version"], calibration_utc="2026-04-01T00:00:00Z"
                ),
                fx.QA,
            ),
            201,
        )
        assert_daily_calibration(first)
        assert first["span_error_pct_of_span"] == 2.00, (
            f"8 of 400 span units is 2.00 percent, got {first['span_error_pct_of_span']}"
        )
        assert first["result"] == "PASSED"
        assert first["monitoring_system_version_after"] == 2

        replayed = api_client.record_daily_calibration(
            system["id"],
            daily_calibration_payload(
                system["version"],
                calibration_utc="2026-04-01T12:00:00Z",
                span_measured_value=364.0,
            ),
            fx.QA,
        )
        validate_error(
            replayed, ApiErrorId.ERR_STALE_MONITORING_SYSTEM_VERSION.value
        )

        _, meta = validate_paginated(
            api_client.list_daily_calibrations(
                fx.QA, {"monitoring_system_id": system["id"]}
            )
        )
        assert meta["total_count"] == 1, (
            f"the refused calibration persisted nothing, got {meta['total_count']} rows"
        )
        assert _system(system["id"])["version"] == 2, (
            "a rejected guarded write does not itself bump the parent's version"
        )

        second = validate_success(
            api_client.record_daily_calibration(
                system["id"],
                daily_calibration_payload(
                    first["monitoring_system_version_after"],
                    calibration_utc="2026-04-01T12:00:00Z",
                    span_measured_value=364.0,
                ),
                fx.QA,
            ),
            201,
        )
        assert second["span_error_pct_of_span"] == 1.00
        assert second["result"] == "PASSED"
        assert second["monitoring_system_version_after"] == 3, (
            "exactly one increment per accepted write, got "
            f"{second['monitoring_system_version_after']}"
        )

        final = _system(system["id"])
        assert final["cal_status"] == "CAL_CURRENT"
        assert final["last_calibration_utc"] == "2026-04-01T12:00:00Z"


class TestStaleReportVersionAcrossBothAppendEndpoints:
    """The single append and the bulk append share one report counter."""

    def test_a_spent_report_version_is_refused_on_both_append_endpoints(self):
        """One single append spends version 1; both replays are 412.

        PRD: "Appending a single **operating hour** requires
        `expected_quarterly_report_version` matching the resolved report's current
        `version`. A mismatch yields `ERR_STALE_REPORT_VERSION` (HTTP 412)."

        PRD: "Appending **operating hours in bulk** requires the same
        `expected_quarterly_report_version`, with the same `ERR_STALE_REPORT_VERSION`
        (HTTP 412) on mismatch."

        PRD: "Appending an hour recomputes its owning report's counts and totals,
        reverts that report from `VALIDATED` back to `DRAFT` with its `version`
        incremented, recomputes the unit's `data_availability_pct`, and records
        `quarterly_report_version_after` on the hour so the client can chain the next
        guarded append without re-reading the report."

        Design: Corner/complexity_layers/layer_occ_operating_hour_rejects_a_stale_report_version
        """
        station = fx.setup_certified_so2_station(clock=CLOCK_APRIL)
        unit_id = station["unit"]["id"]
        report = fx.open_quarterly_report(unit_id)
        assert report["version"] == 1

        first = validate_success(
            api_client.append_operating_hour(
                unit_id,
                single_hour_payload(
                    report["version"], cems_hour_payload("2026-04-01T00:00:00Z")
                ),
                fx.PREPARER,
            ),
            201,
        )
        assert_operating_hour(first)
        assert first["quarterly_report_version_after"] == 2

        validate_error(
            api_client.append_operating_hour(
                unit_id,
                single_hour_payload(
                    report["version"], cems_hour_payload("2026-04-01T01:00:00Z")
                ),
                fx.PREPARER,
            ),
            ApiErrorId.ERR_STALE_REPORT_VERSION.value,
        )
        validate_error(
            api_client.append_operating_hours_bulk(
                unit_id,
                bulk_hours_payload(
                    report["version"], [cems_hour_payload("2026-04-01T01:00:00Z")]
                ),
                fx.PREPARER,
            ),
            ApiErrorId.ERR_STALE_REPORT_VERSION.value,
        )

        _, meta = validate_paginated(
            api_client.list_operating_hours(
                fx.PREPARER, {"quarterly_report_id": report["id"]}
            )
        )
        assert meta["total_count"] == 1, (
            f"neither refusal persisted an hour, got {meta['total_count']}"
        )
        assert _report(report["id"])["version"] == 2

        accepted = validate_success(
            api_client.append_operating_hours_bulk(
                unit_id,
                bulk_hours_payload(
                    first["quarterly_report_version_after"],
                    [cems_hour_payload("2026-04-01T01:00:00Z")],
                ),
                fx.PREPARER,
            ),
            201,
        )
        assert len(accepted) == 1
        final = _report(report["id"])
        assert final["version"] == 3, (
            f"the honoured guard value advanced the report to 3, got {final['version']}"
        )
        assert final["operating_hour_count"] == 2


class TestWritingResponseCarriesTheRecomputedHours:
    """The bulk response already holds the derived masses and the new version."""

    def test_the_bulk_response_matches_the_report_and_unit_read_afterwards(self):
        """Three hours priced inside the write; the GET adds nothing new.

        PRD: "`so2_mass_lbs` is the SO2 mass conversion constant 0.000000166 pounds
        per standard cubic foot per ppm, multiplied by `so2_conc_ppm`, by `flow_scfh`,
        by `op_time_fraction`, and finally by the `bias_adjustment_factor` of the
        unit's SO2 monitoring system, rounded half up to one decimal."

        PRD: "`total_so2_tons` is then derived from the **already-rounded**
        `total_so2_lbs`, divided by 2000 pounds per ton and rounded half up to three
        decimals — never from a re-sum of per-hour tons."

        PRD: "This figure is recomputed on every hour append, on every substitution,
        on link two of the out-of-control cascade, and at report validation, and is
        stored both as the unit's `data_availability_pct` and as the report's
        `monitor_data_availability_pct`."

        Design: Corner/consistency_model/consistency_every_derived_value_is_present_in_the_writing_response
        """
        station = fx.setup_certified_so2_station(clock=CLOCK_APRIL)
        unit_id = station["unit"]["id"]
        report = fx.open_quarterly_report(unit_id)

        written = validate_success(
            api_client.append_operating_hours_bulk(
                unit_id, bulk_hours_payload(report["version"], fx.cems_hours(3)), fx.PREPARER
            ),
            201,
        )
        assert len(written) == 3
        for hour in written:
            assert hour["heat_input_mmbtu"] == 555.556
            assert hour["so2_mass_lbs"] == 292.2
            assert hour["nox_mass_lbs"] == 100.0
            assert hour["co2_mass_tons"] == 59.700
            assert hour["data_quality"] == "MEASURED"
            assert hour["quarterly_report_version_after"] == 2, (
                "the write already reports the version it consumed"
            )

        rolled_up = _report(report["id"])
        assert rolled_up["version"] == 2, (
            "the read performs no second write, so the version is unchanged"
        )
        assert rolled_up["operating_hour_count"] == 3
        assert rolled_up["total_heat_input_mmbtu"] == 1666.668
        assert rolled_up["total_so2_lbs"] == 876.6
        assert rolled_up["total_so2_tons"] == 0.438
        assert rolled_up["monitor_data_availability_pct"] == 100.0

        unit = validate_success(api_client.get_unit(unit_id, fx.REVIEWER))
        assert unit["data_availability_pct"] == 100.0, (
            "availability was recomputed inside the same bulk request"
        )


class TestWritingResponseCarriesTheEvaluatedWindow:
    """The evaluate response already holds the window and its consequence."""

    def test_the_evaluate_response_matches_the_limit_read_and_the_event_is_visible(self):
        """EXCEEDED at 292.2 in the POST body, and one event already listed.

        PRD: "`window_sample_count` is the number of hours the window admitted, and
        `window_evaluated_utc` is set to the anchor."

        PRD: "The `evaluation_status` is then `EXCEEDED` when `current_rolling_value`
        is **strictly greater** than `limit_value`, and `IN_COMPLIANCE` otherwise — a
        rolling value exactly equal to the limit is in compliance."

        PRD: "Events are never created by a client request; a limit evaluation is
        their only origin."

        Design: Corner/consistency_model/consistency_every_derived_value_is_present_in_the_writing_response
        """
        station = fx.setup_draft_report_with_cems_hours(hour_count=3, clock=CLOCK_APRIL)
        unit_id = station["unit"]["id"]
        limit = validate_success(
            api_client.create_permit_limit(
                unit_id,
                permit_limit_payload(
                    limit_value=250.0, effective_from_utc="2026-04-01T00:00:00Z"
                ),
                fx.REVIEWER,
            ),
            201,
        )
        assert limit["evaluation_status"] == "NOT_EVALUATED"
        assert limit["current_rolling_value"] is None

        evaluated = validate_success(
            api_client.evaluate_permit_limit(
                limit["id"], {"anchor_utc": ANCHOR_03}, fx.REVIEWER
            )
        )
        assert_permit_limit(evaluated)
        assert evaluated["evaluation_status"] == "EXCEEDED"
        assert evaluated["current_rolling_value"] == 292.2, (
            f"876.6 lb over 3 samples, got {evaluated['current_rolling_value']}"
        )
        assert evaluated["window_sample_count"] == 3
        assert evaluated["window_evaluated_utc"] == ANCHOR_03

        read_back = validate_success(
            api_client.get_permit_limit(limit["id"], fx.REVIEWER)
        )
        assert read_back == evaluated, (
            "the read returns the identical body the write already carried"
        )

        events, meta = validate_paginated(
            api_client.list_excess_emission_events(
                fx.REVIEWER, {"permit_limit_id": limit["id"]}
            )
        )
        assert meta["total_count"] == 1, (
            "the cascade's event is visible immediately, not on a later sweep, got "
            f"{meta['total_count']}"
        )
        assert_excess_emission_event(events[0])
        assert events[0]["status"] == "DETECTED"
        assert events[0]["observed_value"] == 292.2
        assert events[0]["limit_value_snapshot"] == 250.0
