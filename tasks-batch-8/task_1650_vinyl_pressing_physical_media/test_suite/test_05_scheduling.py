"""Press scheduling: commit gates, slot interval semantics (half-open with a
family-conditional changeover buffer), maintenance closed intervals, daily
capacity, and the press-start date gate."""
from test_helpers import (
    ApiErrorId,
    create_order,
    create_queued_order,
    create_release,
    get_order,
    press_run,
    schedule_order,
    set_clock,
    setup_world,
    validate_error,
    validate_success,
)
from test_helpers.fixtures import CSR, OPERATOR, PLANNER


class TestScheduleCommitGates:
    def test_schedule_commit_requires_queued_state(self, api):
        """PRD §3.6: "Fourth, the order must actually be `QUEUED` (otherwise
        `ERR_ORDER_INVALID_STATE`)."

        Design: Corner/state_machines/schedule_commit_requires_queued_state
        """
        world = setup_world()
        order = create_order(world["release"]["id"], quantity_ordered=100)
        assert order["production_status"] == "DRAFT"
        resp = api.commit_schedule(
            order["id"],
            {
                "expected_press_order_version": order["version"],
                "slots": [{
                    "press_line_id": world["line"]["id"],
                    "date": "2026-08-10", "start_hour": 0, "end_hour": 2,
                    "planned_units": 100,
                }],
            },
            PLANNER,
        )
        validate_error(resp, ApiErrorId.ERR_ORDER_INVALID_STATE)
        slots = validate_success(
            api.list_order_slots(order["id"], CSR), 200
        )
        assert slots == [], "a rejected commit must create no slots"

    def test_slot_units_mismatch_variants(self, api):
        """PRD §3.6: "First, unit feasibility: each slot's `planned_units` may
        not exceed its length in hours multiplied by the line's hourly rate,
        and the committed slots must plan at least as many units as the order
        still lacks — `quantity_ordered` less any `accepted_units` already
        banked — so a repressed order may legitimately commit a top-up run
        covering only its shortfall; either failure is
        `ERR_SLOT_UNITS_MISMATCH`."

        Design: Corner/validations/slot_units_mismatch_variants
        """
        world = setup_world()
        staged = create_queued_order(world, quantity_ordered=1000)
        order = staged["order"]
        line_id = world["line"]["id"]  # hourly rate ceil(5000/16) = 313

        # Total planned 500 < 1000 remaining.
        r1 = api.commit_schedule(
            order["id"],
            {"expected_press_order_version": order["version"],
             "slots": [{"press_line_id": line_id, "date": "2026-08-10",
                        "start_hour": 0, "end_hour": 8, "planned_units": 500}]},
            PLANNER,
        )
        validate_error(r1, ApiErrorId.ERR_SLOT_UNITS_MISMATCH)

        # A single 1-hour slot at 400 units exceeds 1 x 313 hourly.
        r2 = api.commit_schedule(
            order["id"],
            {"expected_press_order_version": order["version"],
             "slots": [{"press_line_id": line_id, "date": "2026-08-10",
                        "start_hour": 0, "end_hour": 1, "planned_units": 400}]},
            PLANNER,
        )
        validate_error(r2, ApiErrorId.ERR_SLOT_UNITS_MISMATCH)

        # A compliant commit passes.
        committed = schedule_order(order, line_id, planned_units=1000)
        assert committed["production_status"] == "SCHEDULED"


class TestSlotChangeoverBuffer:
    def test_same_family_adjacency_and_changeover_violation(self, api):
        """PRD §3.6: "`PRODUCTION` slots are half-open intervals — the end hour
        is exclusive — so two such slots conflict exactly when each starts
        strictly before the other ends (`ERR_SLOT_OVERLAP`); back-to-back slots
        are permitted only between slots of the same `color_family`, and slots
        of different families must leave a one-hour changeover gap between the
        earlier slot's end and the later slot's start
        (`ERR_CHANGEOVER_BUFFER_VIOLATION`)"

        Design: Difficulty/resource_temporal_overlap/slot_changeover_conditional_buffer
        """
        world = setup_world()
        line_id = world["line"]["id"]
        cust_id = world["customer"]["id"]
        rel2 = create_release(cust_id, catalog_number="OV1-002", title="TO2",
                              weight_gram=140)
        rel3 = create_release(cust_id, catalog_number="OV1-003", title="TO3",
                              weight_gram=140)

        o1 = create_queued_order(world, quantity_ordered=800)["order"]
        schedule_order(o1, line_id, start_hour=0, end_hour=8, planned_units=800)

        # Same-family (STANDARD) back-to-back [8,9) needs no buffer.
        o3 = create_queued_order(world, release=rel3, quantity_ordered=100)["order"]
        committed3 = schedule_order(o3, line_id, start_hour=8, end_hour=9,
                                    planned_units=100)
        assert committed3["production_status"] == "SCHEDULED", (
            "same color family back-to-back slots must be permitted"
        )

        # SPECIAL_EFFECT [9,12) touches the STANDARD slot ending at 9 without
        # the one-hour changeover gap.
        o2 = create_queued_order(
            world, release=rel2, quantity_ordered=100,
            variants=[{"color_config": "SPLATTER", "quantity": 100}],
        )["order"]
        resp = api.commit_schedule(
            o2["id"],
            {"expected_press_order_version": o2["version"],
             "slots": [{"press_line_id": line_id, "date": "2026-08-10",
                        "start_hour": 9, "end_hour": 12, "planned_units": 100}]},
            PLANNER,
        )
        validate_error(resp, ApiErrorId.ERR_CHANGEOVER_BUFFER_VIOLATION)

    def test_slot_overlap_and_buffered_cross_family_commit(self, api):
        """PRD §3.6: "`PRODUCTION` slots are half-open intervals — the end hour
        is exclusive — so two such slots conflict exactly when each starts
        strictly before the other ends (`ERR_SLOT_OVERLAP`); back-to-back slots
        are permitted only between slots of the same `color_family`, and slots
        of different families must leave a one-hour changeover gap between the
        earlier slot's end and the later slot's start
        (`ERR_CHANGEOVER_BUFFER_VIOLATION`)"

        Design: Difficulty/resource_temporal_overlap/slot_changeover_conditional_buffer
        """
        world = setup_world()
        line_id = world["line"]["id"]
        rel2 = create_release(world["customer"]["id"], catalog_number="OV1-002",
                              title="TO2", weight_gram=140)

        o1 = create_queued_order(world, quantity_ordered=800)["order"]
        schedule_order(o1, line_id, start_hour=0, end_hour=8, planned_units=800)

        o2 = create_queued_order(
            world, release=rel2, quantity_ordered=100,
            variants=[{"color_config": "SPLATTER", "quantity": 100}],
        )["order"]

        # [4,6) intersects [0,8) half-open -> overlap.
        r1 = api.commit_schedule(
            o2["id"],
            {"expected_press_order_version": o2["version"],
             "slots": [{"press_line_id": line_id, "date": "2026-08-10",
                        "start_hour": 4, "end_hour": 6, "planned_units": 100}]},
            PLANNER,
        )
        validate_error(r1, ApiErrorId.ERR_SLOT_OVERLAP)

        # [10,13) leaves the full one-hour changeover after [0,8) -> allowed.
        committed = schedule_order(o2, line_id, start_hour=10, end_hour=13,
                                   planned_units=100)
        assert committed["production_status"] == "SCHEDULED"


class TestMaintenanceWindows:
    def test_maintenance_closed_interval_touch_conflicts(self, api):
        """PRD §3.6: "`MAINTENANCE` windows are closed intervals, and a
        production slot conflicts with a maintenance window whenever the
        production start falls on or before the maintenance end while the
        maintenance start falls strictly before the production end — merely
        touching a maintenance endpoint already conflicts
        (`ERR_MAINTENANCE_WINDOW_CONFLICT`)"
        PRD §3.6: "Maintenance windows are booked on a line as `MAINTENANCE`
        PressSlots — `press_order_id` left null, `planned_units` zero"

        Design: Corner/calculations/maintenance_closed_interval_touch_conflicts
        """
        world = setup_world()
        line_id = world["line"]["id"]
        mw = validate_success(
            api.create_maintenance_window(
                line_id,
                {"date": "2026-08-10", "start_hour": 8, "end_hour": 10,
                 "reason": "bearing swap"},
                PLANNER,
            ),
            201,
        )
        assert mw["slot_kind"] == "MAINTENANCE"
        assert mw["press_order_id"] is None

        staged = create_queued_order(world, quantity_ordered=500)
        order = staged["order"]

        # [7,9) intersects the closed window [8,10].
        r1 = api.commit_schedule(
            order["id"],
            {"expected_press_order_version": order["version"],
             "slots": [{"press_line_id": line_id, "date": "2026-08-10",
                        "start_hour": 7, "end_hour": 9, "planned_units": 500}]},
            PLANNER,
        )
        validate_error(r1, ApiErrorId.ERR_MAINTENANCE_WINDOW_CONFLICT)

        # [10,12) touches the closed end hour 10 -> still a conflict.
        r2 = api.commit_schedule(
            order["id"],
            {"expected_press_order_version": order["version"],
             "slots": [{"press_line_id": line_id, "date": "2026-08-10",
                        "start_hour": 10, "end_hour": 12, "planned_units": 500}]},
            PLANNER,
        )
        validate_error(r2, ApiErrorId.ERR_MAINTENANCE_WINDOW_CONFLICT)

        # [11,13) is clear of the window.
        committed = schedule_order(order, line_id, start_hour=11, end_hour=13,
                                   planned_units=500)
        assert committed["production_status"] == "SCHEDULED"


class TestLineDailyCapacity:
    def test_line_daily_capacity_inclusive_boundary(self, api):
        """PRD §3.6: "Third, daily capacity: the sum of `planned_units` on a
        line and date may not exceed the line's `daily_unit_capacity`
        (`ERR_LINE_DAILY_CAPACITY_EXCEEDED`)."

        Design: Corner/calculations/line_daily_capacity_inclusive_boundary
        """
        world = setup_world(line_over={"line_code": "L2", "hours_per_day": 16,
                                       "daily_unit_capacity": 3999})
        line_id = world["line"]["id"]  # hourly rate ceil(3999/16) = 250
        rel2 = create_release(world["customer"]["id"], catalog_number="CU7-002",
                              title="T2", weight_gram=140)

        o1 = create_queued_order(world, quantity_ordered=2000)["order"]
        schedule_order(o1, line_id, start_hour=0, end_hour=8, planned_units=2000)

        o2 = create_queued_order(world, release=rel2, quantity_ordered=1999)["order"]

        # 2000 + 2000 = 4000 > 3999 daily capacity -> rejected.
        r1 = api.commit_schedule(
            o2["id"],
            {"expected_press_order_version": o2["version"],
             "slots": [{"press_line_id": line_id, "date": "2026-08-10",
                        "start_hour": 8, "end_hour": 16, "planned_units": 2000}]},
            PLANNER,
        )
        validate_error(r1, ApiErrorId.ERR_LINE_DAILY_CAPACITY_EXCEEDED)

        # 2000 + 1999 = 3999 == capacity -> allowed (inclusive boundary).
        committed = schedule_order(o2, line_id, start_hour=8, end_hour=16,
                                   planned_units=1999)
        assert committed["production_status"] == "SCHEDULED"


class TestPressStartDateGate:
    def test_press_start_before_slot_date_rejected(self, api):
        """PRD §3.7: "`START_PRESSING` moves a `SCHEDULED` order to `PRESSING`,
        but only once the logical clock's date has reached the order's earliest
        slot date; an earlier attempt is rejected with
        `ERR_PRESS_DATE_NOT_REACHED`."

        Design: Corner/validations/press_start_before_slot_date_rejected
        """
        world = setup_world()
        staged = create_queued_order(world, quantity_ordered=1000)
        order = schedule_order(staged["order"], world["line"]["id"],
                               date="2026-08-10", start_hour=0, end_hour=8,
                               planned_units=1000)

        set_clock("2026-08-05T00:00:00Z")
        r1 = api.post_production_event(order["id"], {"event": "START_PRESSING"},
                                       OPERATOR)
        validate_error(r1, ApiErrorId.ERR_PRESS_DATE_NOT_REACHED)

        set_clock("2026-08-10T00:00:00Z")
        r2 = api.post_production_event(order["id"], {"event": "START_PRESSING"},
                                       OPERATOR)
        data = validate_success(r2, 200)
        assert data["production_status"] == "PRESSING"
