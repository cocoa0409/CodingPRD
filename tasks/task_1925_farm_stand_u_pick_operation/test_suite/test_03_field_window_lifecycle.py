"""Field and window lifecycle: opening rules, manual cancel, rotation cycle."""
from test_helpers import (
    TEST_USERS,
    activate_season,
    create_crop,
    create_field,
    create_sales_day,
    create_season,
    create_window,
    get_field,
    get_session,
    get_window,
    open_field,
    open_sales_day,
    open_window,
    set_clock,
    setup_operating_day,
    setup_paid_session,
    sign_waiver,
    validate_error,
    validate_paginated,
    validate_success,
    weigh_out,
)

MANAGER = TEST_USERS["farm_manager_headers"]
FIELD_STAFF = TEST_USERS["field_staff_headers"]


def _rotation_world():
    """Field A (estimate 20 oz) driven to PICKED_OUT on Monday 2026-08-03, with
    a DORMANT Field B waiting in the same rotation group."""
    world = setup_operating_day(
        date="2026-08-03", clock_at="2026-08-03T09:30:00Z",
        estimated_harvest_oz=20)
    field_b = create_field(world["season_id"], name="South", rotation_order=2,
                           estimated_harvest_oz=500)
    world["field_b_id"] = field_b["id"]
    session = setup_paid_session(world, container_count=4, enter=True)
    world["session_id"] = session["id"]
    line = weigh_out(session["id"], world["crop_id"], 36, 4)  # net 20 oz
    world["line_id"] = line["id"]
    return world


class TestFieldOpenRules:
    def test_field_open_twice_returns_invalid_state(self, api):
        """PRD §3.2: "attempting to open a field already `OPEN`, `PICKED_OUT`,
        or `RETIRED` instead fails with `ERR_INVALID_STATE` (409)."

        Design: Corner/state_machines/field_open_twice_returns_invalid_state
        """
        season = create_season()
        activate_season(season["id"])
        field = create_field(season["id"])
        opened = open_field(field["id"])

        resp = api.open_field(field["id"], MANAGER)
        validate_error(resp, "ERR_INVALID_STATE", 409)

        after = get_field(field["id"])
        assert after["version"] == opened["version"], (
            "The rejected transition mutated nothing")
        assert after["status"] == "OPEN"

    def test_field_open_requires_active_season(self, api):
        """PRD §3.2: "The season of the field must be `ACTIVE`
        (`ERR_SEASON_NOT_ACTIVE`)"

        Design: Corner/state_machines/field_open_requires_active_season
        """
        season = create_season()  # left DRAFT, never activated
        field = create_field(season["id"])
        resp = api.open_field(field["id"], MANAGER)
        validate_error(resp, "ERR_SEASON_NOT_ACTIVE", 409)

    def test_field_open_blocked_while_rotation_resting(self, api):
        """PRD §3.2: "Attempting to open a field that is currently in
        `ROTATION_REST` therefore fails with the temporal `ERR_FIELD_RESTING`
        (422) rather than a state error, because rest is a time-bound condition"
        PRD §3.8: "every `PICKED_OUT` field of the season enters
        `ROTATION_REST` with `rest_until` set to the closing day's `date` plus
        seven days."

        Design: Corner/state_machines/field_open_blocked_while_rotation_resting
        """
        world = _rotation_world()  # field PICKED_OUT on Monday 2026-08-03
        # Drive the close-day sweep to push the field into ROTATION_REST.
        api.close_day(world["day_id"], MANAGER)
        resting = get_field(world["field_id"])
        assert resting["status"] == "ROTATION_REST"

        day2 = create_sales_day(world["season_id"], date="2026-08-05")
        set_clock("2026-08-05T08:00:00Z")
        open_sales_day(day2["id"])  # sweep: 2026-08-05 < rest_until, stays resting

        resp = api.open_field(world["field_id"], MANAGER)
        validate_error(resp, "ERR_FIELD_RESTING", 422)
        assert get_field(world["field_id"])["status"] == "ROTATION_REST"


class TestWindowOpenRules:
    def test_window_open_outside_hours_rejected(self, api):
        """PRD §3.3: "the logical clock reads within the window's hours — on
        the window's `date`, at or after `open_time` and strictly before
        `close_time` (`ERR_OUTSIDE_WINDOW_HOURS`)."

        Design: Corner/state_machines/window_open_outside_hours_rejected
        """
        season = create_season()
        activate_season(season["id"])
        field = create_field(season["id"])
        day = create_sales_day(season["id"], date="2026-08-04")
        set_clock("2026-08-04T08:00:00Z")  # one hour before the window opens
        open_sales_day(day["id"])
        open_field(field["id"])
        window = create_window(field["id"], date="2026-08-04",
                               open_time="09:00", close_time="17:00")

        resp = api.open_window(window["id"], MANAGER)
        validate_error(resp, "ERR_OUTSIDE_WINDOW_HOURS", 422)
        assert get_window(window["id"])["status"] == "SCHEDULED"

    def test_window_open_requires_open_sales_day(self, api):
        """PRD §3.3: "A `FarmManager` opens a `SCHEDULED` window when three
        conditions hold: the window's field is `OPEN` (`ERR_FIELD_NOT_OPEN`),
        the sales day of the window's `date` is `OPEN` (`ERR_DAY_NOT_OPEN`)"

        Design: Corner/state_machines/window_open_requires_open_sales_day
        """
        season = create_season()
        activate_season(season["id"])
        field = create_field(season["id"])
        create_sales_day(season["id"], date="2026-08-04")  # left PLANNED
        set_clock("2026-08-04T09:30:00Z")
        open_field(field["id"])
        window = create_window(field["id"], date="2026-08-04",
                               open_time="09:00", close_time="17:00")

        resp = api.open_window(window["id"], MANAGER)
        validate_error(resp, "ERR_DAY_NOT_OPEN", 409)


class TestWindowManualCancel:
    def test_window_cancel_with_bookings_returns_invalid_state(self, api):
        """PRD §3.3: "A window may instead be cancelled manually, which
        requires it to still be `SCHEDULED` and to have `booked_slots` of zero
        — either violation is `ERR_INVALID_STATE` (409) — and lands the window
        in `CANCELLED` with `cancel_reason` `MANUAL`."

        Design: Corner/state_machines/window_cancel_with_bookings_returns_invalid_state
        """
        world = setup_operating_day()
        create_sales_day(world["season_id"], date="2026-08-05")
        window2 = create_window(world["field_id"], date="2026-08-05",
                                open_time="09:00", close_time="12:00")
        setup_paid_session(world)  # books 1 slot on the OPEN window

        resp = api.cancel_window(world["window_id"], MANAGER)
        validate_error(resp, "ERR_INVALID_STATE", 409)

        cancelled = validate_success(api.cancel_window(window2["id"], MANAGER))
        assert cancelled["status"] == "CANCELLED"
        assert cancelled["cancel_reason"] == "MANUAL"


class TestFieldRotationCycle:
    def test_field_rotation_picked_out_then_resting(self, api):
        """PRD §3.2: "The moment a weigh-out creation or finalization pushes a
        field's `committed_picked_oz` to equal or exceed its
        `estimated_harvest_oz`, the field transitions from `OPEN` to
        `PICKED_OUT`"
        PRD §3.8: "every `PICKED_OUT` field of the season enters
        `ROTATION_REST` with `rest_until` set to the closing day's `date` plus
        seven days."

        Design: Difficulty/non_linear_state_machine/field_rotation_full_cycle
        """
        world = _rotation_world()
        picked = get_field(world["field_id"])
        assert picked["status"] == "PICKED_OUT", (
            "committed 20 >= estimated 20 flips the field")
        assert picked["committed_picked_oz"] == 20
        assert picked["rotation_successor_field_id"] == world["field_b_id"]

        validate_success(api.close_day(world["day_id"], MANAGER))
        resting = get_field(world["field_id"])
        assert resting["status"] == "ROTATION_REST"
        assert resting["rest_until"] == "2026-08-10", (
            "closing date 2026-08-03 plus seven days")

    def test_field_rotation_rest_lifts_on_inclusive_boundary(self, api):
        """PRD §3.2: "When a later sales day is opened, every field of that
        season in `ROTATION_REST` whose `rest_until` is on or before the opened
        day's `date` — the comparison is inclusive — returns to `DORMANT` and
        its `rest_until` is cleared to null."
        PRD §3.2: "the successor is the field with the lowest `rotation_order`,
        ties broken by earlier `created_at`"

        Design: Difficulty/non_linear_state_machine/field_rotation_full_cycle
        """
        world = _rotation_world()
        validate_success(api.close_day(world["day_id"], MANAGER))

        day2 = create_sales_day(world["season_id"], date="2026-08-10")
        set_clock("2026-08-10T08:00:00Z")
        validate_success(api.open_day(day2["id"], MANAGER))

        field = get_field(world["field_id"])
        assert field["status"] == "DORMANT", (
            "rest_until 2026-08-10 is on the opened date, inclusive")
        assert field["rest_until"] is None
        assert field["rotation_successor_field_id"] == world["field_b_id"]


class TestWindowOverlap:
    def _overlap_base(self, api):
        season = create_season()
        activate_season(season["id"])
        field = create_field(season["id"])
        create_sales_day(season["id"], date="2026-08-04", staff_on_duty=3)
        create_window(field["id"], date="2026-08-04", open_time="09:00",
                      close_time="12:00", picking_capacity_slots=30)
        return season, field

    def test_window_overlapping_interval_rejected(self, api):
        """PRD §3.3: "Two windows on the same field and date may not overlap:
        their half-open intervals, each running from its `open_time` up to but
        not including its `close_time`, must not intersect"
        PRD §3.3: "a violation is `ERR_WINDOW_OVERLAP` (422)."

        Design: Difficulty/resource_temporal_overlap/window_half_open_adjacency_vs_overlap
        """
        _, field = self._overlap_base(api)
        resp = api.create_window(
            {"field_id": field["id"], "date": "2026-08-04",
             "open_time": "11:00", "close_time": "13:00",
             "picking_capacity_slots": 10},
            MANAGER)
        validate_error(resp, "ERR_WINDOW_OVERLAP", 422)

    def test_window_back_to_back_adjacency_allowed(self, api):
        """PRD §3.3: "though back-to-back adjacency where one window's
        `close_time` equals the other's `open_time` is allowed; only
        non-`CANCELLED` windows participate"

        Design: Difficulty/resource_temporal_overlap/window_half_open_adjacency_vs_overlap
        """
        _, field = self._overlap_base(api)
        adjacent = validate_success(api.create_window(
            {"field_id": field["id"], "date": "2026-08-04",
             "open_time": "12:00", "close_time": "15:00",
             "picking_capacity_slots": 30},
            MANAGER), 201)
        assert adjacent["status"] == "SCHEDULED"

        rows, meta = validate_paginated(api.list_windows(
            MANAGER, params={"field_id": field["id"], "date": "2026-08-04"}))
        assert meta["total_count"] == 2
