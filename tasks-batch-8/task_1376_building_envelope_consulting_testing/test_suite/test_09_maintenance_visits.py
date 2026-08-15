"""Maintenance visits: closed-window completion boundaries."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    api_client,
    create_active_engagement,
    create_maintenance_visit,
    set_clock,
    validate_error,
    validate_success,
)

P = TEST_USERS["principal_headers"]
C = TEST_USERS["consultant_headers"]
FT = TEST_USERS["field_technician_headers"]


class TestMaintenanceVisitWindow:

    def test_maintenance_visit_complete_inside_closed_window_end_inclusive(self):
        """PRD §3.9: "A `FieldTechnician` completes a visit, moving it from
        `SCHEDULED` to `COMPLETED`, only when the logical clock's current date
        falls inside the closed window inclusive of both endpoints; outside the
        window the completion is rejected with `ERR_OUTSIDE_VISIT_WINDOW`
        (HTTP 409)..."
        PRD §3.9: "The visit window is closed and inclusive: it spans from
        `window_start_date` through `window_end_date` including both
        endpoints..."

        Design: Corner/state_machines/maintenance_visit_complete_inside_closed_window_end_inclusive
        """
        eng = create_active_engagement(name="EV")
        v1 = create_maintenance_visit(eng["id"], visit_label="V1",
                                      window_start_date="2026-10-01",
                                      window_end_date="2026-10-05",
                                      buffer_days=0)
        v2 = create_maintenance_visit(eng["id"], visit_label="V2",
                                      window_start_date="2026-10-10",
                                      window_end_date="2026-10-12",
                                      buffer_days=0)
        # Completion on window_end_date itself succeeds (inclusive end).
        set_clock("2026-10-05T12:00:00Z")
        resp = api_client.complete_maintenance_visit(eng["id"], v1["id"], FT)
        data = validate_success(resp, 200)
        assert data["visit_status"] == "COMPLETED"

        # One day after the window the completion is rejected.
        set_clock("2026-10-13T12:00:00Z")
        resp = api_client.complete_maintenance_visit(eng["id"], v2["id"], FT)
        validate_error(resp, ApiErrorId.ERR_OUTSIDE_VISIT_WINDOW)
        after = validate_success(
            api_client.get_maintenance_visit(eng["id"], v2["id"], C), 200)
        assert after["visit_status"] == "SCHEDULED"
