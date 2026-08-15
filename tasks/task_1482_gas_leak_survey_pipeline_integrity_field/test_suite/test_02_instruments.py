"""Instrument lifecycle and calibration discipline (PRD §2.6, §3.2)."""
import pytest

from test_helpers import (
    ApiErrorId,
    assert_instrument,
    assert_timestamp_eq,
    get_success_data,
    make_org,
    make_instrument,
    set_clock,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.factories import create_instrument_payload


class TestInstrumentRegistration:
    def test_instrument_created_in_service_with_null_calibration(self, api):
        """PRD §2.6: "A newly registered instrument starts in `IN_SERVICE` with
        `calibrated_at` and `calibration_due_at` both null until its first
        calibration."

        Design: Corner/entities/instrument_created_in_service_with_null_calibration
        """
        ctx = make_org()
        data = validate_success(api.create_instrument(
            create_instrument_payload(serial_number="I-CGI-D1"), ctx["ct_h"],
        ), expected_status=201)
        assert_instrument(data)
        assert data["status"] == "IN_SERVICE"
        assert data["calibrated_at"] is None
        assert data["calibration_due_at"] is None
        assert data["version"] == 1


class TestCalibrationComputation:
    def test_calibration_drift_and_due_date_computed(self, api):
        """PRD §2.6: "the system computes `drift_pct` as the absolute difference
        between `observed_ppm` and `reference_gas_ppm`, divided by
        `reference_gas_ppm`, multiplied by 100."
        PRD §2.6: "60 days for `CGI`" and "A passing calibration sets the
        instrument's `calibrated_at` to the current logical clock and sets
        `calibration_due_at` to `calibrated_at` plus the interval for the
        instrument's type."

        Design: Corner/calculations/calibration_drift_and_due_date_computed
        """
        ctx = make_org()
        instrument = make_instrument(ctx, serial_number="I-CGI-CL", calibrate=False)
        cal = validate_success(api.calibrate_instrument(
            instrument["id"],
            {"reference_gas_ppm": 100.0, "observed_ppm": 103.0},
            ctx["ct_h"],
        ), expected_status=201)
        assert cal["drift_pct"] == pytest.approx(3.0)
        assert cal["outcome"] == "PASS"

        after = get_success_data(api.get_instrument(instrument["id"], ctx["ct_h"]))
        assert_timestamp_eq(after["calibrated_at"], "2026-08-01T00:00:00Z", "calibrated_at")
        assert_timestamp_eq(after["calibration_due_at"], "2026-09-30T00:00:00Z", "calibration_due_at")

    def test_calibration_drift_exactly_at_max_passes(self, api):
        """PRD §2.6: "If the drift is at most 5.0 percent the calibration outcome
        is `PASS`; strictly above 5.0 percent it is `FAIL`."

        Design: Corner/calculations/calibration_drift_exactly_at_max_passes
        """
        ctx = make_org()
        first = make_instrument(ctx, serial_number="I-CGI-B1", calibrate=False)
        second = make_instrument(ctx, serial_number="I-CGI-B2", calibrate=False)

        at_max = validate_success(api.calibrate_instrument(
            first["id"], {"reference_gas_ppm": 100.0, "observed_ppm": 105.0}, ctx["ct_h"],
        ), expected_status=201)
        assert at_max["drift_pct"] == pytest.approx(5.0)
        assert at_max["outcome"] == "PASS"

        resp = api.calibrate_instrument(
            second["id"], {"reference_gas_ppm": 100.0, "observed_ppm": 105.1}, ctx["ct_h"],
        )
        # Strictly above 5.0 fails: rejected outright with ERR_CALIBRATION_DRIFT_EXCEEDED.
        validate_error(resp, ApiErrorId.ERR_CALIBRATION_DRIFT_EXCEEDED)

    def test_calibration_drift_fail_blocks_reactivation(self, api):
        """PRD §3.2: "A calibration whose drift exceeds the 5.0 percent ceiling is
        rejected with `ERR_CALIBRATION_DRIFT_EXCEEDED` and leaves the instrument's
        status untouched."

        Design: Corner/calculations/calibration_drift_fail_blocks_reactivation
        """
        ctx = make_org()
        instrument = make_instrument(ctx, serial_number="I-CGI-FB")
        set_clock(ctx, "2026-10-01T00:00:00Z")  # past CGI due date 2026-09-30

        resp = api.calibrate_instrument(
            instrument["id"],
            {"reference_gas_ppm": 100.0, "observed_ppm": 106.0},
            ctx["ct_h"],
        )
        validate_error(resp, ApiErrorId.ERR_CALIBRATION_DRIFT_EXCEEDED)
        after = get_success_data(api.get_instrument(instrument["id"], ctx["ct_h"]))
        assert after["status"] == "OUT_OF_CALIBRATION"


class TestInstrumentLifecycleTransitions:
    def test_instrument_retire_while_referenced_by_draft_run(self, api):
        """PRD §3.2: "Retiring an instrument is allowed only when no survey run in
        `DRAFT` or `SUBMITTED` status references it; otherwise the retire is
        refused with `ERR_INSTRUMENT_IN_USE`."

        Design: Corner/state_machines/instrument_retire_while_referenced_by_draft_run
        """
        from test_helpers import setup_dispatched_route, make_run
        ctx = setup_dispatched_route(route_code="R-RU")
        make_run(ctx, ctx["route"]["id"], ctx["instrument"]["id"], submit=False)
        resp = api.retire_instrument(ctx["instrument"]["id"], ctx["ct_h"])
        validate_error(resp, ApiErrorId.ERR_INSTRUMENT_IN_USE)

    def test_instrument_auto_out_of_calibration_past_due(self, api):
        """PRD §2.6: "Whenever the logical clock passes an instrument's
        `calibration_due_at`, the instrument automatically moves from `IN_SERVICE`
        to `OUT_OF_CALIBRATION`."

        Design: Corner/cross_cutting/instrument_auto_out_of_calibration_past_due
        """
        ctx = make_org()
        instrument = make_instrument(ctx, serial_number="I-CGI-AUTO")
        set_clock(ctx, "2026-10-01T00:00:00Z")  # CGI due was 2026-09-30
        after = get_success_data(api.get_instrument(instrument["id"], ctx["ct_h"]))
        assert after["status"] == "OUT_OF_CALIBRATION"

    def test_instrument_calibrations_subresource_lists_records(self, api):
        """PRD §3.2: "each instrument exposes its calibration history."
        PRD §3.2: "each producing a persisted `Calibration` record holding the
        `instrument_id`, the `performed_by_user_id` of the `CalibrationTech`."

        Design: Corner/endpoints/instrument_calibrations_subresource_lists_records
        """
        ctx = make_org()
        instrument = make_instrument(ctx, serial_number="I-CGI-CL2", calibrate=False)
        get_success_data(api.calibrate_instrument(
            instrument["id"], {"reference_gas_ppm": 100.0, "observed_ppm": 103.0}, ctx["ct_h"],
        ))
        get_success_data(api.calibrate_instrument(
            instrument["id"], {"reference_gas_ppm": 100.0, "observed_ppm": 101.0}, ctx["ct_h"],
        ))
        rows, meta = validate_paginated(api.list_calibrations(instrument["id"], ctx["ct_h"]))
        assert meta["total_count"] == 2
        assert all(row["instrument_id"] == instrument["id"] for row in rows)
