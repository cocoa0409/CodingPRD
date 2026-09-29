"""Two contended calendars with deliberately opposite geometry: a vehicle's inspection
window (closed, two-hour buffer) and a driver's coaching window (half-open, no buffer).
"""

from typing import Any, Dict

from test_helpers import (
    ApiErrorId,
    BasicCategory,
    CoachingStatus,
    CurriculumCode,
    EmploymentStatus,
    ReportStatus,
    UnitType,
    factories as fac,
    fixtures as fx,
    get_success_data,
    make_carrier_safety_manager_headers,
    validate_error,
    validate_paginated,
    validate_success,
)

SHARED_VIN = "1FUJA6CK21LK00016"


def _one_inspection_from_fourteen_to_fifteen(api) -> Dict[str, Any]:
    """A single RECEIVED report holding the vehicle's calendar from 14:00 to 15:00."""
    fx.set_clock(api)
    carrier = fx.create_carrier(api)
    report = fx.create_report(
        api,
        carrier["id"],
        report_number="OH20260701W0",
        vehicle_vin=SHARED_VIN,
        inspection_start="2026-07-01T14:00:00Z",
        inspection_end="2026-07-01T15:00:00Z",
    )
    return {"carrier": carrier, "report": report}


def _second_inspection(api, carrier_id: str, report_number: str, start: str):
    """Attempt a second inspection of the same vehicle starting at `start`."""
    return api.create_inspection_report(
        fac.create_inspection_report_payload(
            carrier_id,
            report_number=report_number,
            vehicle_vin=SHARED_VIN,
            inspection_start=start,
            inspection_end="2026-07-01T18:00:00Z",
        ),
        fx.OFFICER,
    )


class TestVehicleInspectionWindowBuffer:
    def test_touching_the_widened_window_is_still_a_conflict(self, api):
        """PRD 3.2: "The system takes the new report's closed interval from
        `inspection_start` to `inspection_end`, widens it by two hours at each end, and
        rejects the ingestion with `ERR_DUPLICATE_INSPECTION_WINDOW` if any existing
        report that is not `RESCINDED` and carries the same `vehicle_vin` has a closed
        interval intersecting the widened one."

        Design: Difficulty/resource_temporal_overlap/vehicle_inspection_window_closed_interval_with_120_minute_buffer
        """
        scenario = _one_inspection_from_fourteen_to_fifteen(api)
        carrier_id = scenario["carrier"]["id"]

        inside = _second_inspection(
            api, carrier_id, "OH20260701W1", "2026-07-01T16:59:00Z"
        )
        validate_error(inside, ApiErrorId.DUPLICATE_INSPECTION_WINDOW, 409)

        touching = _second_inspection(
            api, carrier_id, "OH20260701W2", "2026-07-01T17:00:00Z"
        )
        validate_error(touching, ApiErrorId.DUPLICATE_INSPECTION_WINDOW, 409)

    def test_one_minute_past_the_buffer_is_accepted(self, api):
        """PRD 3.2: "Endpoints that merely touch count as an intersection — an existing
        inspection ending at exactly the instant the widened new window begins is a
        conflict."

        Design: Difficulty/resource_temporal_overlap/vehicle_inspection_window_closed_interval_with_120_minute_buffer
        """
        scenario = _one_inspection_from_fourteen_to_fifteen(api)
        carrier_id = scenario["carrier"]["id"]
        _second_inspection(api, carrier_id, "OH20260701W1", "2026-07-01T16:59:00Z")
        _second_inspection(api, carrier_id, "OH20260701W2", "2026-07-01T17:00:00Z")

        accepted = validate_success(
            _second_inspection(
                api, carrier_id, "OH20260701W3", "2026-07-01T17:01:00Z"
            ),
            201,
        )
        assert accepted["status"] == ReportStatus.RECEIVED
        assert accepted["inspection_start"].startswith("2026-07-01T17:01:00")

        rows, meta = validate_paginated(
            api.list_inspection_reports(fx.OFFICER, {"vehicle_vin": SHARED_VIN})
        )
        assert meta["total_count"] == 2
        assert sorted(row["id"] for row in rows) == sorted(
            [scenario["report"]["id"], accepted["id"]]
        )


def _driver_booked_from_fourteen_to_sixteen(api) -> Dict[str, Any]:
    """A driver with two coachable violations and one ASSIGNED session already holding
    14:00 to 16:00 on 5 August."""
    fx.set_clock(api)
    carrier = fx.create_carrier(api)
    driver = fx.create_driver(
        api,
        carrier["id"],
        cdl_number="OH-D-99001",
        full_name="Dana Reyes",
        employment_status=EmploymentStatus.ACTIVE,
    )
    code = fx.create_violation_code(
        api,
        code="392.2R",
        description="Reckless driving",
        basic_category=BasicCategory.UNSAFE_DRIVING,
        severity_weight=8,
        driver_attributable=True,
    )
    fx.create_threshold(
        api,
        basic_category=BasicCategory.UNSAFE_DRIVING,
        carrier_segment="MEDIUM",
        measure_at_p50=0.5,
        measure_at_p65=1.0,
        measure_at_p80=2.0,
    )
    driver_violation = {
        "violation_code_id": code["id"],
        "unit_type": UnitType.DRIVER,
        "driver_id": driver["id"],
    }
    _, rows = fx.build_scored_report(
        api,
        carrier["id"],
        [dict(driver_violation), dict(driver_violation)],
        report_number="OH2026070117",
        driver_id=driver["id"],
        inspection_start="2026-07-01T14:00:00Z",
        inspection_end="2026-07-01T15:00:00Z",
    )
    first = fx.create_coaching_assignment(
        api,
        carrier["id"],
        driver["id"],
        rows[0]["id"],
        curriculum_code=CurriculumCode.UNSAFE_DRIVING_101,
        session_start="2026-08-05T14:00:00Z",
        session_end="2026-08-05T16:00:00Z",
    )
    return {
        "carrier": carrier,
        "driver": driver,
        "violations": rows,
        "first": first,
        "manager": make_carrier_safety_manager_headers(carrier["id"]),
    }


def _book_session(api, scenario, curriculum_code: str, start: str, end: str):
    """Attempt a second session on the same driver's calendar."""
    return api.create_coaching_assignment(
        fac.create_coaching_assignment_payload(
            scenario["driver"]["id"],
            scenario["violations"][1]["id"],
            curriculum_code=curriculum_code,
            session_start=start,
            session_end=end,
        ),
        scenario["manager"],
    )


class TestDriverCoachingWindowAdjacency:
    def test_a_session_starting_exactly_at_the_previous_end_is_booked(self, api):
        """PRD 3.9: "Adjacency is explicitly permitted — an existing session ending
        exactly when the new one starts, or a new session ending exactly when an existing
        one starts, is fine — and no buffer of any kind is applied."

        Design: Difficulty/resource_temporal_overlap/driver_coaching_window_half_open_adjacency_allowed
        """
        scenario = _driver_booked_from_fourteen_to_sixteen(api)
        adjacent = validate_success(
            _book_session(
                api,
                scenario,
                CurriculumCode.PRETRIP_INSPECTION,
                "2026-08-05T16:00:00Z",
                "2026-08-05T18:00:00Z",
            ),
            201,
        )

        assert adjacent["status"] == CoachingStatus.ASSIGNED
        assert adjacent["session_start"].startswith("2026-08-05T16:00:00")
        assert adjacent["due_at"].startswith("2026-08-19T18:00:00")

    def test_a_session_starting_inside_the_window_is_refused(self, api):
        """PRD 3.9: "The reserved window is half-open, covering `session_start` up to but
        not including `session_end`. A new assignment is rejected with
        `ERR_COACHING_WINDOW_CONFLICT` when another assignment of the same driver whose
        `status` is `ASSIGNED`, `IN_PROGRESS` or `OVERDUE` has a half-open window
        intersecting the new one."

        Design: Difficulty/resource_temporal_overlap/driver_coaching_window_half_open_adjacency_allowed
        """
        scenario = _driver_booked_from_fourteen_to_sixteen(api)
        adjacent = get_success_data(
            _book_session(
                api,
                scenario,
                CurriculumCode.PRETRIP_INSPECTION,
                "2026-08-05T16:00:00Z",
                "2026-08-05T18:00:00Z",
            )
        )

        overlapping = _book_session(
            api,
            scenario,
            CurriculumCode.CDL_COMPLIANCE,
            "2026-08-05T15:00:00Z",
            "2026-08-05T17:00:00Z",
        )
        validate_error(overlapping, ApiErrorId.COACHING_WINDOW_CONFLICT, 409)

        assert fx.read_driver(api, scenario["driver"]["id"])["open_coaching_count"] == 2
        assert fx.read_carrier(api, scenario["carrier"]["id"])["open_coaching_count"] == 2

        rows, meta = validate_paginated(
            api.list_coaching_assignments(
                fx.AUDITOR, {"driver_id": scenario["driver"]["id"]}
            )
        )
        assert meta["total_count"] == 2
        assert sorted(row["id"] for row in rows) == sorted(
            [scenario["first"]["id"], adjacent["id"]]
        )
