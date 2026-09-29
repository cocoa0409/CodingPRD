"""Chamber occupation: single occupancy, turnaround buffers and chamber fit.

PRD §3.3 widens every live occupation by the chamber's `turnaround_hours` on both
sides and compares the candidate's own half-open interval against the result.
"""

import pytest

from test_helpers import *  # noqa: F401,F403

LOW_TEMP_STANDARD = {
    "standard_code": "DOE-2027-RSC-LT",
    "effective_date": "2026-01-01T00:00:00Z",
    "max_gwp": 1500,
    "limit_coefficient_a": 0.90,
    "limit_constant_b": 1.50,
    "temperature_class": "LT",
    "system_type_scope": "ANY",
}

LOW_TEMP_MODEL = {
    "model_code": "MDL-LT-8",
    "application": "FROZEN_REACH_IN",
    "temperature_class": "LT",
    "system_type": "REMOTE",
    "nominal_length_ft": 8,
    "tda_sqft": 26.4,
    "charge_grams": 3600,
    "line_set_length_ft": 120,
    "door_type": "OPEN",
    "glass_door_count": 0,
    "curtain_layers": 3,
    "discharge_velocity_mps": 0.60,
    "case_air_temp_c": -23.0,
    "ambient_dew_point_c": 15.5,
    "lighting_w_per_ft": 12.0,
    "fan_w_per_ft": 9.5,
    "defrost_cycles_per_day": 6,
}


class TestChamberTurnaroundBuffer:
    """PRD §3.3 — the buffer is symmetric and half-open at both ends."""

    def test_01_candidate_inside_the_trailing_turnaround_buffer_is_rejected(self, api):
        """Six hours after a run ends is still inside a twelve-hour buffer.

        PRD §3.3: "the blocked interval starts `turnaround_hours` before that
        test's `window_start` and ends, exclusively, `turnaround_hours` after its
        `window_end`."

        Design: Difficulty/resource_temporal_overlap/chamber_symmetric_turnaround_buffer_single_occupancy
        """
        ctx = setup_scheduled_energy_test()
        held = ctx["energy_test"]
        assert held["status"] == "SCHEDULED"
        assert ctx["test_chamber"]["turnaround_hours"] == 12

        conflicting = schedule_energy_test(
            ctx,
            window_start="2026-08-04T14:00:00Z",
            window_end="2026-08-05T14:00:00Z",
        )
        validate_error(conflicting, ApiErrorId.ERR_CHAMBER_WINDOW_CONFLICT.value)

        accepted = validate_success(
            schedule_energy_test(
                ctx,
                window_start="2026-08-04T20:00:00Z",
                window_end="2026-08-05T20:00:00Z",
            ),
            expected_status=201,
        )
        assert accepted["status"] == "SCHEDULED", (
            "a candidate starting exactly where the blocked interval ends is accepted"
        )
        assert accepted["pinned_design_revision"] == 1
        assert accepted["limit_daily_kwh"] == pytest.approx(17.568, abs=0.0001)

        assert refresh_energy_test(ctx)["status"] == "SCHEDULED", (
            "the original reservation is untouched by either attempt"
        )

        _rows, meta = validate_paginated(
            api.list_energy_tests(
                TEST_USERS["test_lab_technician_headers"],
                params={"test_chamber_id": ctx["test_chamber"]["id"]},
            )
        )
        assert meta["total_count"] == 2, "only the touching candidate was persisted"

    def test_02_the_buffer_extends_symmetrically_before_the_reserved_window(self, api):
        """Twelve hours ahead of a run is blocked; the thirteenth hour is free.

        PRD §3.3: "**Chamber occupation** is single-occupancy with a symmetric
        turnaround buffer."

        Design: Difficulty/resource_temporal_overlap/chamber_symmetric_turnaround_buffer_single_occupancy
        """
        ctx = setup_scheduled_energy_test(
            test_overrides={
                "window_start": "2026-08-05T20:00:00Z",
                "window_end": "2026-08-06T20:00:00Z",
            }
        )

        conflicting = schedule_energy_test(
            ctx,
            window_start="2026-08-04T14:00:00Z",
            window_end="2026-08-05T14:00:00Z",
        )
        validate_error(conflicting, ApiErrorId.ERR_CHAMBER_WINDOW_CONFLICT.value)

        accepted = validate_success(
            schedule_energy_test(
                ctx,
                window_start="2026-08-04T08:00:00Z",
                window_end="2026-08-05T08:00:00Z",
            ),
            expected_status=201,
        )
        assert accepted["status"] == "SCHEDULED", (
            "a candidate ending exactly where the blocked interval starts is accepted"
        )
        assert accepted["limit_daily_kwh"] == pytest.approx(17.568, abs=0.0001)

    def test_03_a_running_test_also_holds_the_chamber_with_its_buffer(self, api):
        """Starting the run does not release any part of the blocked interval.

        PRD §3.3: "For every existing test on the same chamber whose status is
        `SCHEDULED` or `RUNNING`, the service builds a blocked interval by
        widening that test's occupation on **both** sides by the chamber's
        `turnaround_hours`"

        Design: Difficulty/resource_temporal_overlap/chamber_symmetric_turnaround_buffer_single_occupancy
        """
        ctx = setup_running_energy_test()
        assert ctx["energy_test"]["status"] == "RUNNING"

        conflicting = schedule_energy_test(
            ctx,
            window_start="2026-08-04T14:00:00Z",
            window_end="2026-08-05T14:00:00Z",
        )
        validate_error(conflicting, ApiErrorId.ERR_CHAMBER_WINDOW_CONFLICT.value)

        _rows, meta = validate_paginated(
            api.list_energy_tests(
                TEST_USERS["test_lab_technician_headers"],
                params={"test_chamber_id": ctx["test_chamber"]["id"]},
            )
        )
        assert meta["total_count"] == 1

    def test_04_completed_tests_release_the_chamber_entirely(self, api):
        """A finished run is excluded from the scan, so its window is reusable.

        PRD §3.3: "Tests whose status is `COMPLETED_PASS`, `COMPLETED_FAIL` or
        `INVALIDATED` release the chamber entirely and are excluded from the
        scan."

        Design: Corner/calculations/chamber_occupation_ignores_completed_tests
        """
        ctx = setup_completed_energy_test()
        assert ctx["energy_test"]["status"] == "COMPLETED_PASS"

        nested = validate_success(
            schedule_energy_test(
                ctx,
                window_start="2026-08-03T12:00:00Z",
                window_end="2026-08-04T04:00:00Z",
            ),
            expected_status=201,
        )
        assert nested["status"] == "SCHEDULED", (
            "a window nested inside a completed run's window is free again"
        )
        assert nested["limit_daily_kwh"] == pytest.approx(17.568, abs=0.0001)

        _rows, meta = validate_paginated(
            api.list_energy_tests(
                TEST_USERS["test_lab_technician_headers"],
                params={"test_chamber_id": ctx["test_chamber"]["id"]},
            )
        )
        assert meta["total_count"] == 2


class TestChamberFit:
    """PRD §3.3 — the chamber must support the class and hold the display area."""

    def test_05_energy_test_in_a_chamber_without_class_support_is_rejected(self, api):
        """An LT design cannot be booked into an HT/MT-only chamber.

        PRD §3.3: "Next at rank 22, the model's `temperature_class` must be a
        member of the chamber's `supported_temperature_classes`, else
        `ERR_CHAMBER_CLASS_UNSUPPORTED` (HTTP 422)."

        Design: Corner/validations/energy_test_in_chamber_without_class_support_rejected
        """
        ctx = setup_submitted_case_model(
            chamber_overrides={
                "chamber_code": "CH-2",
                "name": "Energy Lab Chamber 2",
                "supported_temperature_classes": ["HT", "MT"],
            },
            standard_overrides=LOW_TEMP_STANDARD,
            model_overrides=LOW_TEMP_MODEL,
        )

        response = schedule_energy_test(ctx)
        validate_error(response, ApiErrorId.ERR_CHAMBER_CLASS_UNSUPPORTED.value)

        _rows, meta = validate_paginated(
            api.list_energy_tests(TEST_USERS["test_lab_technician_headers"])
        )
        assert meta["total_count"] == 0

    def test_06_energy_test_exceeding_the_chamber_display_area_is_rejected(self, api):
        """A 26.4 sq ft design does not fit a 20.0 sq ft chamber.

        PRD §3.3: "Then at rank 23, the model's `tda_sqft` must be at or below
        the chamber's `max_tda_sqft`, else `ERR_CHAMBER_TDA_EXCEEDED` (HTTP
        422)."

        Design: Corner/validations/energy_test_exceeding_chamber_tda_rejected
        """
        ctx = setup_submitted_case_model(
            chamber_overrides={
                "chamber_code": "CH-3",
                "name": "Energy Lab Chamber 3",
                "max_tda_sqft": 20.0,
            }
        )
        assert ctx["case_model"]["tda_sqft"] == pytest.approx(26.4, abs=0.0001)

        response = schedule_energy_test(ctx)
        validate_error(response, ApiErrorId.ERR_CHAMBER_TDA_EXCEEDED.value)

        _rows, meta = validate_paginated(
            api.list_energy_tests(TEST_USERS["test_lab_technician_headers"])
        )
        assert meta["total_count"] == 0
