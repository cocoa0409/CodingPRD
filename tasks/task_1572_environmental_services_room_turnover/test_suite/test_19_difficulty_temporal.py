"""Difficulty queue A — resource_temporal_overlap instances (staff buffer;
maintenance aggregate cap)."""
from test_helpers import (
    assert_instant_equal,
    ApiErrorId,
    CLOCK_T0800,
    api_client,
    create_maintenance_window_payload,
    get_success_data,
    set_clock,
    validate_error,
    validate_success,
    TEST_USERS,
)
from test_helpers.fixtures import (
    assign_request,
    create_bed,
    create_request,
    create_standard,
    create_technician,
    create_unit,
    seed_supplies,
)

ADMIN = TEST_USERS["admin_headers"]
DISPATCHER = TEST_USERS["dispatcher_headers"]
ANY = TEST_USERS["any_headers"]


class TestStaffWindowBufferOverlap:
    def test_five_minute_gap_rejected_as_double_booked(self, api):
        """PRD §3.4: "Two planned windows on the same staff member conflict
        unless at least ten full minutes separate them in one direction or the
        other: the new window must start no earlier than ten minutes after the
        existing window ends, or the existing window must start no earlier than
        ten minutes after the new window ends."
        PRD §3.4: "the planned window must satisfy the buffer rule below
        against every other `ASSIGNED` or `IN_PROGRESS` window already on that
        staff member (`ERR_STAFF_DOUBLE_BOOKED`)."

        Design: Difficulty/resource_temporal_overlap/staff_window_buffer_overlap
        """
        set_clock(CLOCK_T0800)
        unit = create_unit()
        create_standard("ROUTINE")
        tech = create_technician("T1")
        b1 = create_bed(unit["id"], "B1", "STANDARD")
        b2 = create_bed(unit["id"], "B2", "STANDARD")

        r1 = create_request(b1["id"], "ROUTINE")
        assign_request(r1["id"], tech["id"], planned_start_at="2026-08-01T09:00:00Z")
        r2 = create_request(b2["id"], "ROUTINE")

        # 09:50 is 5 minutes after the 09:45 end: inside the buffer.
        r = api.assign_clean_request(
            r2["id"],
            {"staff_id": tech["id"], "planned_start_at": "2026-08-01T09:50:00Z"},
            DISPATCHER,
        )
        validate_error(r, ApiErrorId.ERR_STAFF_DOUBLE_BOOKED)

        after = get_success_data(api.get_clean_request(r2["id"], ANY))
        assert after["status"] == "QUEUED"
        assert after["assigned_staff_id"] is None

    def test_exactly_ten_minute_gap_accepted(self, api):
        """PRD §3.4: "Exactly ten minutes of gap is permitted and does not
        conflict. The check is symmetric and considers every other `ASSIGNED`
        or `IN_PROGRESS` window on the staff member."

        Design: Difficulty/resource_temporal_overlap/staff_window_buffer_overlap
        """
        set_clock(CLOCK_T0800)
        unit = create_unit()
        create_standard("ROUTINE")
        tech = create_technician("T1")
        b1 = create_bed(unit["id"], "B1", "STANDARD")
        b2 = create_bed(unit["id"], "B2", "STANDARD")

        r1 = create_request(b1["id"], "ROUTINE")
        assign_request(r1["id"], tech["id"], planned_start_at="2026-08-01T09:00:00Z")
        r2 = create_request(b2["id"], "ROUTINE")

        ok = validate_success(
            api.assign_clean_request(
                r2["id"],
                {"staff_id": tech["id"], "planned_start_at": "2026-08-01T09:55:00Z"},
                DISPATCHER,
            )
        )
        assert ok["status"] == "ASSIGNED"
        assert_instant_equal(ok["planned_start_at"], "2026-08-01T09:55:00Z")

        staff = get_success_data(api.get_staff(tech["id"], ANY))
        assert staff["active_clean_count"] == 2


class TestMaintenanceAggregateCapacityCap:
    def test_third_overlapping_window_rejected_over_cap(self, api):
        """PRD §3.9: "The cap for a unit is one fifth of its bed count rounded
        down, but never less than one. Both at creation and again at
        activation, the system checks the new window against that cap by
        sampling a specific set of instants: the new window's own `start_at`,
        plus the `start_at` of every existing `SCHEDULED` or `ACTIVE` window
        that overlaps it. If at any sampled instant the number of overlapping
        existing windows plus the new window would exceed the cap, the
        operation is rejected with `ERR_CAPACITY_EXCEEDED`."

        Design: Difficulty/resource_temporal_overlap/maintenance_aggregate_capacity_cap
        """
        set_clock(CLOCK_T0800)
        unit = create_unit()
        beds = [
            create_bed(unit["id"], f"B{i:02d}", "STANDARD") for i in range(1, 11)
        ]
        # cap = max(1, floor(0.20 * 10)) = 2; two overlapping windows are at cap.
        w1 = get_success_data(
            api.create_maintenance_window(
                create_maintenance_window_payload(bed_id=beds[0]["id"]), ADMIN
            )
        )
        w2 = get_success_data(
            api.create_maintenance_window(
                create_maintenance_window_payload(bed_id=beds[1]["id"]), ADMIN
            )
        )

        # Third window overlapping the same instant exceeds cap 2.
        r = api.create_maintenance_window(
            create_maintenance_window_payload(
                bed_id=beds[2]["id"],
                start_at="2026-08-01T10:30:00Z",
                end_at="2026-08-01T11:30:00Z",
                reason="plumbing",
            ),
            ADMIN,
        )
        validate_error(r, ApiErrorId.ERR_CAPACITY_EXCEEDED)

    def test_touching_windows_do_not_overlap(self, api):
        """PRD §3.9: "Windows interpret their interval as half-open — the bed
        is out from `start_at` up to but not including `end_at`, so two windows
        that merely touch at a boundary instant do not overlap."

        Design: Difficulty/resource_temporal_overlap/maintenance_aggregate_capacity_cap
        """
        set_clock(CLOCK_T0800)
        unit = create_unit()
        beds = [
            create_bed(unit["id"], f"B{i:02d}", "STANDARD") for i in range(1, 11)
        ]
        w1 = get_success_data(
            api.create_maintenance_window(
                create_maintenance_window_payload(bed_id=beds[0]["id"]), ADMIN
            )
        )
        w2 = get_success_data(
            api.create_maintenance_window(
                create_maintenance_window_payload(bed_id=beds[1]["id"]), ADMIN
            )
        )

        # [11:00, 12:00) touches [10:00, 11:00) at the endpoint: not overlap.
        w3 = validate_success(
            api.create_maintenance_window(
                create_maintenance_window_payload(
                    bed_id=beds[2]["id"],
                    start_at="2026-08-01T11:00:00Z",
                    end_at="2026-08-01T12:00:00Z",
                    reason="plumbing",
                ),
                ADMIN,
            ),
            201,
        )
        assert w3["status"] == "SCHEDULED"
        for w in (w1, w2):
            refreshed = get_success_data(api.get_maintenance_window(w["id"], ANY))
            assert refreshed["status"] == "SCHEDULED"
