"""Equipment booking windows, breakdown replacement selection, and coverage gates."""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    assert_equipment_assignment,
    book_equipment,
    create_equipment_assignment_payload,
    get_equipment_assignment,
    get_gang,
    get_unit,
    place_gang,
    register_unit,
    register_worker,
    setup_placed_gang,
    setup_dispatched_gang,
    start_shift,
    check_in,
    validate_error,
    validate_success,
    make_foreman_headers,
)

SUPT = TEST_USERS["superintendent_headers"]
CRANE_SPEC = {"full_name": "Crane Op", "registration_number": "R010",
              "classification": "CRANE_OPERATOR", "registered_on": "2010-01-01",
              "base_hourly_rate_cents": 5000}


class TestBufferedWindowRule:

    def _setup_booked_unit(self):
        """Vessel/shift OPEN (08:00-20:00); gangs G1/G2 PLACED; one RTG booked
        08:00-12:00 on G1."""
        ns = setup_placed_gang(
            vessel_overrides={"vessel_name": "MV Buffer", "voyage_number": "O-402"},
            shift_overrides={"start_utc": "2026-08-10T08:00:00Z",
                             "end_utc": "2026-08-10T20:00:00Z"},
            gang_overrides={"gang_type": "CRANE_GANG",
                            "required_classification": "CRANE_OPERATOR",
                            "required_headcount": 1,
                            "required_equipment_type": "RTG",
                            "required_equipment_count": 1})
        g2 = place_gang(ns.shift["id"], gang_type="CRANE_GANG",
                        required_classification="CRANE_OPERATOR",
                        required_headcount=1,
                        required_equipment_type="RTG",
                        required_equipment_count=1)
        unit = register_unit(unit_code="RTG-1", equipment_type="RTG")
        book_equipment(ns.gang["id"], unit["id"],
                       window_start_utc="2026-08-10T08:00:00Z",
                       window_end_utc="2026-08-10T12:00:00Z")
        return ns, g2, unit

    def test_zero_gap_booking_conflicts_under_buffer_rule(self, api, superintendent_headers):
        """PRD §3.4: "That rule imposes a 30-minute buffer around every committed booking: an existing booking of the same unit in `RESERVED` or `ACTIVE` status, with window start s and end e, occupies the buffered span from thirty minutes before s to thirty minutes after e, and a new window conflicts when it begins before e plus thirty minutes and ends after s minus thirty minutes."
        PRD §3.4: "A conflicting booking is rejected with `ERR_EQUIPMENT_WINDOW_CONFLICT` (409)."

        Design: Difficulty/resource_temporal_overlap/equipment_buffered_window_thirty_minute_gap_rule
        """
        ns, g2, unit = self._setup_booked_unit()
        # 0-minute gap: starts at 12:00 exactly when the prior booking ends.
        resp = api.create_equipment_assignment(
            create_equipment_assignment_payload(
                g2["id"], unit["id"],
                window_start_utc="2026-08-10T12:00:00Z",
                window_end_utc="2026-08-10T16:00:00Z"),
            superintendent_headers)
        validate_error(resp, ApiErrorId.ERR_EQUIPMENT_WINDOW_CONFLICT)

    def test_exactly_thirty_minute_gap_is_allowed(self, api, superintendent_headers):
        """PRD §3.4: "Because the comparisons are strict, a gap of exactly thirty minutes between windows is allowed."
        PRD §3.4: "An accepted booking is born `RESERVED`; its unit moves `AVAILABLE` → `ASSIGNED`, or stays `ASSIGNED` when other bookings already hold it"

        Design: Difficulty/resource_temporal_overlap/equipment_buffered_window_thirty_minute_gap_rule
        """
        ns, g2, unit = self._setup_booked_unit()
        # A 0-minute gap conflicts...
        conflict = api.create_equipment_assignment(
            create_equipment_assignment_payload(
                g2["id"], unit["id"],
                window_start_utc="2026-08-10T12:00:00Z",
                window_end_utc="2026-08-10T16:00:00Z"),
            superintendent_headers)
        validate_error(conflict, ApiErrorId.ERR_EQUIPMENT_WINDOW_CONFLICT)

        # ...but exactly 30 minutes of turnaround passes the strict inequality.
        ok = api.create_equipment_assignment(
            create_equipment_assignment_payload(
                g2["id"], unit["id"],
                window_start_utc="2026-08-10T12:30:00Z",
                window_end_utc="2026-08-10T16:00:00Z"),
            superintendent_headers)
        data = validate_success(ok, 201)
        assert_equipment_assignment(data)
        assert data["status"] == "RESERVED"

        assert get_unit(unit["id"])["status"] == "ASSIGNED", (
            "multiple disjoint bookings share one ASSIGNED unit")


class TestBreakdownReplacementSelection:

    def _setup_three_units(self):
        """G0 holds RTG-A booked 20:00-22:00; G1 holds RTG-X booked 08:00-12:00;
        RTG-B idle. Shift 08:00-23:00."""
        ns = setup_placed_gang(
            vessel_overrides={"vessel_name": "MV Util", "voyage_number": "C-204"},
            shift_overrides={"start_utc": "2026-08-10T08:00:00Z",
                             "end_utc": "2026-08-10T23:00:00Z"},
            gang_overrides={"gang_type": "CRANE_GANG",
                            "required_classification": "CRANE_OPERATOR",
                            "required_headcount": 1,
                            "required_equipment_type": "RTG",
                            "required_equipment_count": 1})
        g1 = place_gang(ns.shift["id"], gang_type="CRANE_GANG",
                        required_classification="CRANE_OPERATOR",
                        required_headcount=1,
                        required_equipment_type="RTG",
                        required_equipment_count=1)
        foreman = register_worker(**CRANE_SPEC)
        unit_x = register_unit(unit_code="RTG-X", equipment_type="RTG")
        unit_a = register_unit(unit_code="RTG-A", equipment_type="RTG")
        unit_b = register_unit(unit_code="RTG-B", equipment_type="RTG")
        book_equipment(ns.gang["id"], unit_a["id"],
                       window_start_utc="2026-08-10T20:00:00Z",
                       window_end_utc="2026-08-10T22:00:00Z")
        ea_x = book_equipment(g1["id"], unit_x["id"],
                              window_start_utc="2026-08-10T08:00:00Z",
                              window_end_utc="2026-08-10T12:00:00Z")
        return ns, g1, foreman, unit_x, unit_a, unit_b, ea_x

    def test_equipment_replacement_prefers_least_utilized_unit(self, api):
        """PRD §3.4: "The replacement selection then runs over the whole fleet: candidates are units whose `equipment_type` matches the failed unit's, whose status is `AVAILABLE`, and whose existing `RESERVED` or `ACTIVE` bookings leave room for the failed assignment's exact window under the thirty-minute buffer rule. Candidates rank by current utilization — the count of their `RESERVED` and `ACTIVE` assignments ascending, least utilized first — with ties broken by the unit's `created_at` ascending. The top unit, when one exists, receives a replacement assignment in `RESERVED` status carrying the failed assignment's window; the failed assignment's `replaced_by_assignment_id` points to that replacement (and stays null when none is created); and the new unit moves `AVAILABLE` → `ASSIGNED`."
        PRD §3.4: "Reporting a breakdown on a `RESERVED` or `ACTIVE` assignment moves that assignment to `DOWN`; the unit itself moves `ASSIGNED` → `DOWN` and its `total_breakdowns` increments by one."

        Design: Corner/calculations/equipment_replacement_prefers_least_utilized_unit
        """
        ns, g1, foreman, unit_x, _unit_a, unit_b, ea_x = self._setup_three_units()

        resp = api.report_equipment_breakdown(
            ea_x["id"], make_foreman_headers(foreman["id"]))
        failed = validate_success(resp)
        assert failed["status"] == "DOWN"

        unit_x_after = get_unit(unit_x["id"])
        assert unit_x_after["status"] == "DOWN"
        assert unit_x_after["total_breakdowns"] == 1

        replacement_id = failed["replaced_by_assignment_id"]
        assert replacement_id, "a replacement assignment must be created"
        replacement = get_equipment_assignment(replacement_id)
        # RTG-B (zero existing bookings) beats RTG-A (one existing booking).
        assert replacement["equipment_unit_id"] == unit_b["id"]
        assert replacement["status"] == "RESERVED"
        assert replacement["window_start_utc"] == "2026-08-10T08:00:00Z"
        assert replacement["window_end_utc"] == "2026-08-10T12:00:00Z"

        assert get_unit(unit_b["id"])["status"] == "ASSIGNED"
        assert get_gang(g1["id"])["assigned_equipment_ok"] is True

    def test_equipment_breakdown_with_empty_pool_leaves_gang_uncovered(self, api):
        """PRD §3.4: "When no unit qualifies, no replacement is created and the gang remains under-covered: `assigned_equipment_ok` recomputes to false whenever coverage has fallen below `required_equipment_count`."
        PRD §3.4: "The top unit, when one exists, receives a replacement assignment in `RESERVED` status carrying the failed assignment's window; the failed assignment's `replaced_by_assignment_id` points to that replacement (and stays null when none is created); and the new unit moves `AVAILABLE` → `ASSIGNED`."

        Design: Corner/calculations/equipment_breakdown_with_empty_pool_leaves_gang_uncovered
        """
        ns = setup_placed_gang(
            vessel_overrides={"vessel_name": "MV NoSpare", "voyage_number": "C-205"},
            gang_overrides={"gang_type": "CRANE_GANG",
                            "required_classification": "CRANE_OPERATOR",
                            "required_headcount": 1,
                            "required_equipment_type": "RTG",
                            "required_equipment_count": 1})
        foreman = register_worker(**CRANE_SPEC)
        unit_x = register_unit(unit_code="RTG-X", equipment_type="RTG")
        ea_x = book_equipment(ns.gang["id"], unit_x["id"],
                              window_start_utc="2026-08-10T08:00:00Z",
                              window_end_utc="2026-08-10T12:00:00Z")

        resp = api.report_equipment_breakdown(
            ea_x["id"], make_foreman_headers(foreman["id"]))
        failed = validate_success(resp)
        assert failed["status"] == "DOWN"
        assert failed.get("replaced_by_assignment_id") is None, (
            "empty pool creates nothing")

        gang = get_gang(ns.gang["id"])
        assert gang["assigned_equipment_ok"] is False

        unit_after = get_unit(unit_x["id"])
        assert unit_after["status"] == "DOWN"
        assert unit_after["total_breakdowns"] == 1


class TestDownUnitBooking:

    def test_equipment_assignment_on_down_unit_returns_unavailable(self, api, superintendent_headers):
        """PRD §3.4: "A unit whose status is `DOWN` cannot be booked at all — the attempt is rejected with `ERR_EQUIPMENT_UNAVAILABLE` (409) — whereas a unit that is merely `ASSIGNED` accepts further bookings as long as they satisfy the turnaround rule."

        Design: Corner/validations/equipment_assignment_on_down_unit_returns_unavailable
        """
        ns = setup_placed_gang(
            vessel_overrides={"vessel_name": "MV Down", "voyage_number": "V-311"},
            gang_overrides={"gang_type": "CRANE_GANG",
                            "required_classification": "CRANE_OPERATOR",
                            "required_headcount": 1,
                            "required_equipment_type": "RTG",
                            "required_equipment_count": 1})
        g2 = place_gang(ns.shift["id"], gang_type="CRANE_GANG",
                        required_classification="CRANE_OPERATOR",
                        required_headcount=1,
                        required_equipment_type="RTG",
                        required_equipment_count=1)
        foreman = register_worker(**CRANE_SPEC)
        unit_x = register_unit(unit_code="RTG-X", equipment_type="RTG")
        ea_x = book_equipment(ns.gang["id"], unit_x["id"],
                              window_start_utc="2026-08-10T08:00:00Z",
                              window_end_utc="2026-08-10T12:00:00Z")
        api.report_equipment_breakdown(ea_x["id"], make_foreman_headers(foreman["id"]))
        assert get_unit(unit_x["id"])["status"] == "DOWN"

        # 13:00-16:00 respects the 30-minute buffer even against the old window;
        # only the DOWN status can fail this booking.
        resp = api.create_equipment_assignment(
            create_equipment_assignment_payload(
                g2["id"], unit_x["id"],
                window_start_utc="2026-08-10T13:00:00Z",
                window_end_utc="2026-08-10T16:00:00Z"),
            superintendent_headers)
        validate_error(resp, ApiErrorId.ERR_EQUIPMENT_UNAVAILABLE)


class TestStartWorkEquipmentGate:

    def test_start_work_without_equipment_coverage_returns_409(self, api):
        """PRD §3.5: "Three gates guard the start: the shift must be `IN_PROGRESS` (otherwise `ERR_INVALID_STATE`); the vessel's `work_posture` must be `NORMAL` — a `PARTIAL_STOPPAGE` blocks the start just as a full one does, both rejected with `ERR_WORK_STOPPAGE_ACTIVE` (409); and `assigned_equipment_ok` must be true, otherwise `ERR_NO_EQUIPMENT_ASSIGNED` (409)."
        PRD §3.4: "the gang order's `assigned_equipment_ok` recomputes — that flag is true exactly when the count of the order's equipment assignments in `RESERVED` or `ACTIVE` status whose unit's type matches `required_equipment_type` is at least `required_equipment_count`."

        Design: Corner/validations/start_work_without_equipment_coverage_returns_409
        """
        ns = setup_dispatched_gang(
            vessel_overrides={"vessel_name": "MV NoEquip", "voyage_number": "V-305"},
            gang_overrides={"gang_type": "CRANE_GANG",
                            "required_classification": "CRANE_OPERATOR",
                            "required_headcount": 1,
                            "required_equipment_type": "RTG",
                            "required_equipment_count": 1},
            worker_specs=[CRANE_SPEC])
        start_shift(ns.shift["id"])
        check_in(ns.assignments[0]["id"])
        gang = get_gang(ns.gang["id"])
        assert gang["status"] == "MANNED"
        assert gang["assigned_equipment_ok"] is False

        from test_helpers import start_gang_work
        resp = start_gang_work(gang["id"], ns.workers[0]["id"])
        validate_error(resp, ApiErrorId.ERR_NO_EQUIPMENT_ASSIGNED)

        gang_after = get_gang(gang["id"])
        assert gang_after["status"] == "MANNED"
        assert gang_after["assigned_equipment_ok"] is False
