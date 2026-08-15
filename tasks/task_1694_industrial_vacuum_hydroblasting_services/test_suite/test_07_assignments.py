"""Assignment temporal constraints: windows, equipment overlap, operator rest,
and certification coverage."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    create_equipment_assignment_payload,
    create_equipment_unit,
    create_job,
    create_operator,
    create_operator_assignment_payload,
    create_site_with_active_schedule,
    get_success_data,
    validate_error,
)

PM = TEST_USERS["project_manager_headers"]


class TestAssignmentWindow:
    def test_window_end_before_start_rejected(self, api):
        """PRD §3.2: "The window must be positive — an end at or before the
        start is rejected with `ERR_INVALID_WINDOW`".

        Design: Corner/validations/assignment_window_end_before_start_rejected
        """
        site, _ = create_site_with_active_schedule()
        unit = create_equipment_unit()
        job = create_job(site["id"], description="bad window")
        resp = api.create_assignment(
            create_equipment_assignment_payload(
                job["id"], unit["id"],
                window_start="2026-08-01T14:00:00Z",
                window_end="2026-08-01T06:00:00Z",
            ),
            PM,
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_WINDOW.value)
        assert resp.status_code == 422


class TestEquipmentOverlap:
    def test_back_to_back_adjacency_allowed(self, api):
        """PRD §3.2: "Intervals are half-open, so one assignment ending exactly
        when another begins is allowed".

        Design: Difficulty/resource_temporal_overlap/equipment_half_open_adjacency_allowed_overlap_rejected
        """
        site, _ = create_site_with_active_schedule()
        unit = create_equipment_unit()
        job = create_job(site["id"], description="Overlap job")
        get_success_data(
            api.create_assignment(
                create_equipment_assignment_payload(
                    job["id"], unit["id"],
                    window_start="2026-08-01T06:00:00Z",
                    window_end="2026-08-01T10:00:00Z",
                ),
                PM,
            )
        )
        adjacent = get_success_data(
            api.create_assignment(
                create_equipment_assignment_payload(
                    job["id"], unit["id"],
                    window_start="2026-08-01T10:00:00Z",
                    window_end="2026-08-01T14:00:00Z",
                ),
                PM,
            )
        )
        assert adjacent["status"] == "SCHEDULED"

    def test_one_minute_overlap_rejected(self, api):
        """PRD §3.2: "a genuine overlap is rejected with
        `ERR_RESOURCE_SCHEDULE_CONFLICT`".

        Design: Difficulty/resource_temporal_overlap/equipment_half_open_adjacency_allowed_overlap_rejected
        """
        site, _ = create_site_with_active_schedule()
        unit = create_equipment_unit()
        job = create_job(site["id"])
        get_success_data(
            api.create_assignment(
                create_equipment_assignment_payload(
                    job["id"], unit["id"],
                    window_start="2026-08-01T06:00:00Z",
                    window_end="2026-08-01T10:00:00Z",
                ),
                PM,
            )
        )
        resp = api.create_assignment(
            create_equipment_assignment_payload(
                job["id"], unit["id"],
                window_start="2026-08-01T09:59:00Z",
                window_end="2026-08-01T11:00:00Z",
            ),
            PM,
        )
        validate_error(resp, ApiErrorId.ERR_RESOURCE_SCHEDULE_CONFLICT.value)
        assert resp.status_code == 409


class TestOperatorRestBuffer:
    def test_exactly_ten_hour_gap_allowed(self, api):
        """PRD §3.2: "Operators are protected by a ten-hour rest buffer: the new
        window must end at least ten hours before, or start at least ten hours
        after, every other `SCHEDULED` or `CONFIRMED` assignment of the same
        operator — a gap of exactly ten hours is allowed".

        Design: Difficulty/resource_temporal_overlap/operator_rest_buffer_blocks_adjacent_shifts
        """
        site, _ = create_site_with_active_schedule()
        op = create_operator()
        job = create_job(site["id"], description="Rest buffer job")
        get_success_data(
            api.create_assignment(
                create_operator_assignment_payload(
                    job["id"], op["id"],
                    window_start="2026-08-01T06:00:00Z",
                    window_end="2026-08-01T16:00:00Z",
                ),
                PM,
            )
        )
        # 16:00 -> next day 02:00 is exactly 10 hours.
        ok = get_success_data(
            api.create_assignment(
                create_operator_assignment_payload(
                    job["id"], op["id"],
                    window_start="2026-08-02T02:00:00Z",
                    window_end="2026-08-02T06:00:00Z",
                ),
                PM,
            )
        )
        assert ok["status"] == "SCHEDULED"

    def test_four_hour_gap_rejected_despite_no_overlap(self, api):
        """PRD §3.2: "otherwise the create fails with
        `ERR_OPERATOR_REST_PERIOD`".

        Design: Difficulty/resource_temporal_overlap/operator_rest_buffer_blocks_adjacent_shifts
        """
        site, _ = create_site_with_active_schedule()
        op = create_operator()
        job = create_job(site["id"])
        get_success_data(
            api.create_assignment(
                create_operator_assignment_payload(
                    job["id"], op["id"],
                    window_start="2026-08-01T06:00:00Z",
                    window_end="2026-08-01T16:00:00Z",
                ),
                PM,
            )
        )
        resp = api.create_assignment(
            create_operator_assignment_payload(
                job["id"], op["id"],
                window_start="2026-08-01T20:00:00Z",
                window_end="2026-08-01T23:00:00Z",
            ),
            PM,
        )
        validate_error(resp, ApiErrorId.ERR_OPERATOR_REST_PERIOD.value)
        assert resp.status_code == 409


class TestOperatorCertification:
    def test_hazwoper_must_cover_full_window(self, api):
        """PRD §3.2: "An operator's `hazwoper_expires_on` must cover the full
        assignment window; a certification expiring mid-window is rejected with
        `ERR_OPERATOR_NOT_CERTIFIED`."

        Design: Corner/validations/operator_certification_must_cover_full_window
        """
        site, _ = create_site_with_active_schedule()
        op = create_operator(
            full_name="Carl C", employee_ref="E-203",
            hazwoper_expires_on="2026-08-01",
        )
        job = create_job(site["id"], description="cert window")
        resp = api.create_assignment(
            create_operator_assignment_payload(
                job["id"], op["id"],
                window_start="2026-08-01T06:00:00Z",
                window_end="2026-08-02T14:00:00Z",
            ),
            PM,
        )
        validate_error(resp, ApiErrorId.ERR_OPERATOR_NOT_CERTIFIED.value)
        assert resp.status_code == 422
