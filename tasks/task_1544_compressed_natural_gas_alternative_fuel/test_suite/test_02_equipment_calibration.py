"""Dispenser calibration outcomes, correction factors, posture reconciliation,
and calibration-hold sweeps (PRD §2.5, §2.7, §3.5)."""
import pytest

from test_helpers import (
    ApiErrorId,
    add_compressor,
    add_dispenser,
    calibrate,
    create_active_station,
    create_station,
    set_clock,
    validate_error,
    validate_success,
)


class TestCalibrationToleranceBoundary:
    """Difficulty instance: calibration_tolerance_exact_boundary (two tests)."""

    def test_calibration_exactly_at_tolerance_passes(self, api, station_manager_headers):
        """PRD §3.5: "The record's `result` is computed at creation: PASS when
        the absolute measured error is at most 0.50 percent — exactly 0.50
        passes, while 0.51 fails — and FAIL otherwise. On a PASS the record's
        `applied_correction_factor` is one minus the measured error percentage
        divided by one hundred, carried to four decimal places (an
        over-delivery of 0.40 percent yields 0.9960); on a FAIL it is null."

        Design: Difficulty/boundary_precision_check/calibration_tolerance_exact_boundary
        """
        station = create_station(station_name="Mike", station_code="ST-MIKE")
        add_compressor(station["id"])
        d1 = add_dispenser(station["id"], dispenser_code="DSP-1")
        record = calibrate(d1["id"], 0.50)
        assert record["result"] == "PASS"
        assert record["applied_correction_factor"] == pytest.approx(0.995, abs=1e-9), (
            "factor = 1 - 0.50/100"
        )
        dispenser = validate_success(api.get_dispenser(d1["id"], station_manager_headers), 200)
        assert dispenser["status"] == "IN_SERVICE"

    def test_calibration_above_tolerance_fails_and_knocks_dispenser_out(
        self, api, station_manager_headers
    ):
        """PRD §3.5: "The record's `result` is computed at creation: PASS when
        the absolute measured error is at most 0.50 percent — exactly 0.50
        passes, while 0.51 fails — and FAIL otherwise."
        PRD §3.5: "A FAIL drives an IN_SERVICE or CALIBRATION_HOLD dispenser to
        OUT_OF_SERVICE with its `version` incrementing."

        Design: Difficulty/boundary_precision_check/calibration_tolerance_exact_boundary
        """
        station = create_station(station_name="Mike2", station_code="ST-MIKE2")
        add_compressor(station["id"])
        d2 = add_dispenser(station["id"], dispenser_code="DSP-2")
        record = calibrate(d2["id"], 0.51)
        assert record["result"] == "FAIL"
        assert record["applied_correction_factor"] is None
        dispenser = validate_success(api.get_dispenser(d2["id"], station_manager_headers), 200)
        assert dispenser["status"] == "OUT_OF_SERVICE"


class TestCalibrationRecordImmutability:
    def test_calibration_record_immutable_no_version_field(self, api, station_manager_headers):
        """PRD §2.4: "Two resource types are deliberately thinner: a
        calibration record and a monthly settlement are immutable once created,
        so each carries only `id` and `created_at` — both `updated_at` and
        `version` are absent from them."

        Design: Corner/entities/calibration_record_immutable_no_version_field
        """
        station = create_station(station_name="Imm", station_code="ST-IMM")
        dispenser = add_dispenser(station["id"], dispenser_code="DSP-1")
        record = calibrate(dispenser["id"], 0.10)
        assert record["result"] == "PASS"
        assert record["applied_correction_factor"] == pytest.approx(0.999, abs=1e-9), (
            "factor = 1 - 0.10/100 = 0.9990"
        )
        fetched = validate_success(
            api.get_calibration_record(record["id"], station_manager_headers), 200
        )
        assert fetched["id"] == record["id"]
        assert fetched["dispenser_id"] == dispenser["id"]
        assert "version" not in fetched
        assert "updated_at" not in fetched


class TestPostureReconciliation:
    def test_posture_reconciles_on_calibration_fail_and_pass(self, api, station_manager_headers):
        """PRD §3.5: "Either outcome recomputes the station's uptime posture,
        and a FAIL that removes the last in-service dispenser can tip the
        station into OUTAGE and fire the §2.7 void cascade."
        PRD §3.5: "A passing calibration returns the dispenser to IN_SERVICE
        from whichever of IN_SERVICE, CALIBRATION_HOLD, or OUT_OF_SERVICE it
        occupied — including a recalibration of an already healthy dispenser,
        which is a self-transition that refreshes rather than moves it."

        Design: Corner/cross_cutting_layers/posture_reconciles_on_calibration_fail_and_pass
        """
        env = create_active_station(station_name="Rec", station_code="ST-REC")
        station_id = env["station"]["id"]
        dispenser_id = env["dispensers"][0]["id"]
        assert env["station"]["uptime_posture"] == "OPERATIONAL"

        calibrate(dispenser_id, 0.75)  # FAIL -> OUT_OF_SERVICE
        after_fail = validate_success(api.get_station(station_id, station_manager_headers), 200)
        assert after_fail["uptime_posture"] == "OUTAGE", (
            "zero IN_SERVICE dispensers after the FAIL"
        )

        record2 = calibrate(dispenser_id, 0.20)  # PASS -> back IN_SERVICE
        assert record2["result"] == "PASS"
        after_pass = validate_success(api.get_station(station_id, station_manager_headers), 200)
        assert after_pass["uptime_posture"] == "OPERATIONAL"
        dispenser = validate_success(api.get_dispenser(dispenser_id, station_manager_headers), 200)
        assert dispenser["status"] == "IN_SERVICE"
        assert dispenser["correction_factor"] == pytest.approx(0.998, abs=1e-9)


class TestCalibrationHoldSweep:
    def test_clock_sweep_dispenser_calibration_hold_degrades_posture(
        self, api, station_manager_headers
    ):
        """PRD §2.5: "Any IN_SERVICE dispenser whose `calibration_due_at` has
        passed moves to CALIBRATION_HOLD."
        PRD §2.7: "Otherwise, if any compressor is DEGRADED or any dispenser is
        on CALIBRATION_HOLD, the posture is DEGRADED."

        Design: Corner/state_machines/clock_sweep_dispenser_calibration_hold_degrades_posture
        """
        env = create_active_station(
            station_name="Hold", station_code="ST-HOLD", num_dispensers=2
        )
        station_id = env["station"]["id"]
        d1 = env["dispensers"][0]
        d2 = env["dispensers"][1]
        # Both dispensers created at the default clock 2026-08-01 -> due 2026-10-30.
        # Recalibrate d2 at 2026-10-20 so its due date pushes to 2027-01-18.
        set_clock("2026-10-20T00:00:00Z")
        calibrate(d2["id"], 0.10)
        set_clock("2026-11-01T00:00:00Z")

        d1_after = validate_success(api.get_dispenser(d1["id"], station_manager_headers), 200)
        assert d1_after["status"] == "CALIBRATION_HOLD", (
            "created 2026-08-01, due 2026-10-30, now 2026-11-01"
        )
        d2_after = validate_success(api.get_dispenser(d2["id"], station_manager_headers), 200)
        assert d2_after["status"] == "IN_SERVICE", (
            "recalibrated 2026-10-20, due 2027-01-18"
        )
        station = validate_success(api.get_station(station_id, station_manager_headers), 200)
        assert station["uptime_posture"] == "DEGRADED", (
            "a CALIBRATION_HOLD dispenser exists but one IN_SERVICE remains"
        )
