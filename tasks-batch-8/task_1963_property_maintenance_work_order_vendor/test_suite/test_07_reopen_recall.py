"""Recall cycle: reopen effects, cyclic re-entry, and the recall window boundary."""
from test_helpers import (
    ApiErrorId,
    complete_as_technician,
    complete_payload,
    dispatch_in_house,
    get_work_order,
    make_resident_headers,
    make_technician_headers,
    set_clock,
    setup_completed_work_order,
    sign_off,
    start_as_technician,
    validate_error,
    validate_success,
)


class TestReopenCycle:
    def test_reopen_resets_signoff_and_increments_recall_count(self, api):
        """PRD §3.5: "Reopening increments `recall_count` by one, resets `resident_signoff` to false — the resident must sign off again on the rework — and clears every assignment field: `assignment_type`, `assigned_technician_id`, `assigned_vendor_id`, the scheduled window, `entry_authorization`, and `notice_posted_at` all return to null."

        Design: Difficulty/non_linear_state_machine/work_order_reopen_cycle
        """
        bundle = setup_completed_work_order(property_name="Cycle Property",
                                            unit_number="105",
                                            description="Recurring leak")
        wo = bundle["work_order"]
        assert wo["status"] == "COMPLETED"
        resp = api.reopen_work_order(
            wo["id"], {}, make_resident_headers(bundle["resident"]["id"])
        )
        data = validate_success(resp, 200)
        assert data["status"] == "REOPENED"
        assert data["recall_count"] == 1
        assert data["resident_signoff"] is False
        assert data["assignment_type"] is None
        assert data["assigned_technician_id"] is None

    def test_second_cycle_requires_fresh_signoff_and_completes(self, api):
        """PRD §3.5: "a `REOPENED` work order dispatches under exactly the same assignment, entry, trade, insurance, and schedule-conflict rules as a `TRIAGED` one."
        PRD §3.5: "Reopening increments `recall_count` by one, resets `resident_signoff` to false — the resident must sign off again on the rework — and clears every assignment field: `assignment_type`, `assigned_technician_id`, `assigned_vendor_id`, the scheduled window, `entry_authorization`, and `notice_posted_at` all return to null."
        PRD §3.4: "`resident_signoff` must be true; otherwise the completion is rejected with `ERR_RESIDENT_SIGNOFF_REQUIRED` (HTTP 409)."

        Design: Difficulty/non_linear_state_machine/work_order_reopen_cycle
        """
        bundle = setup_completed_work_order(property_name="Cycle Property",
                                            unit_number="105",
                                            description="Recurring leak")
        wo_id = bundle["work_order"]["id"]
        res_id = bundle["resident"]["id"]
        tech_id = bundle["technician"]["id"]

        reopened = validate_success(
            api.reopen_work_order(wo_id, {}, make_resident_headers(res_id)), 200
        )
        assert reopened["status"] == "REOPENED"

        # Cyclic re-entry: REOPENED dispatches like TRIAGED.
        redispatched = dispatch_in_house(
            wo_id, tech_id,
            scheduled_start_at="2026-08-01T14:00:00Z",
            scheduled_end_at="2026-08-01T16:00:00Z",
        )
        assert redispatched["status"] == "ASSIGNED"
        start_as_technician(wo_id, tech_id)

        # The reset sign-off gate bites: completing before a fresh sign-off fails.
        premature = api.complete_work_order(
            wo_id,
            complete_payload(photo_urls=["https://x/c2.jpg"], damage_reported=False),
            make_technician_headers(tech_id),
        )
        validate_error(premature, ApiErrorId.ERR_RESIDENT_SIGNOFF_REQUIRED)

        sign_off(wo_id, res_id)
        done = complete_as_technician(
            wo_id, tech_id,
            photo_urls=["https://x/c2.jpg"], damage_reported=False,
        )
        assert done["status"] == "COMPLETED"
        assert done["recall_count"] == 1, "a second completion does not reopen again"


class TestRecallWindowBoundary:
    def test_reopen_exactly_at_window_end_allowed(self, api):
        """PRD §3.5: "The window test compares the current logical clock against `completed_at`: the elapsed time must be at most `recall_window_days`, with exactly-on-the-boundary allowed; a reopen after the window is rejected with `ERR_RECALL_WINDOW_EXPIRED` (HTTP 409)."

        Design: Difficulty/boundary_precision_check/reopen_window_exact_boundary
        """
        bundle = setup_completed_work_order(property_name="Recall Property",
                                            unit_number="112",
                                            description="Boundary job")
        wo = bundle["work_order"]
        # Completed at the boot clock 2026-08-01T00:00:00Z; default window 30 days.
        set_clock("2026-08-31T00:00:00Z")  # exactly completed_at + 30 days
        resp = api.reopen_work_order(
            wo["id"], {}, make_resident_headers(bundle["resident"]["id"])
        )
        data = validate_success(resp, 200)
        assert data["status"] == "REOPENED", "equality at the window boundary is allowed"
        assert data["recall_count"] == 1

    def test_reopen_one_second_past_window_rejected(self, api):
        """PRD §3.5: "The window test compares the current logical clock against `completed_at`: the elapsed time must be at most `recall_window_days`, with exactly-on-the-boundary allowed; a reopen after the window is rejected with `ERR_RECALL_WINDOW_EXPIRED` (HTTP 409)."

        Design: Difficulty/boundary_precision_check/reopen_window_exact_boundary
        """
        bundle = setup_completed_work_order(property_name="Recall Property",
                                            unit_number="112",
                                            description="Boundary job")
        wo = bundle["work_order"]
        # 30 days + 1 second after the completion at 2026-08-01T00:00:00Z.
        set_clock("2026-08-31T00:00:01Z")
        resp = api.reopen_work_order(
            wo["id"], {}, make_resident_headers(bundle["resident"]["id"])
        )
        validate_error(resp, ApiErrorId.ERR_RECALL_WINDOW_EXPIRED)
        assert get_work_order(wo["id"])["status"] == "COMPLETED"
