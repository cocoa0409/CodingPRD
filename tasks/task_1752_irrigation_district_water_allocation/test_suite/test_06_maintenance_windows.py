"""Canal reaches and maintenance shutdown windows: pagination, half-open
overlap, activation gating, cascades, and completion restoration."""
from test_helpers import (
    ADMIN,
    ApiErrorId,
    assert_amount,
    assert_canal_reach,
    create_reach,
    create_window,
    get_allocation,
    get_order,
    get_reach,
    get_window,
    get_work_order,
    place_order,
    schedule_order,
    set_clock,
    setup_open_season_with_allocation,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestReachListing:
    def test_canal_reach_list_pagination_defaults(self, api):
        """PRD §2.3: "`limit` defaults to 10 when omitted, accepts a minimum
        of 1 and a maximum of 100; `offset` defaults to 0." and "The `meta`
        object of a list response carries `limit`, `offset`, `total_count`,
        and `has_more` alongside the request identifiers."
        PRD §2.2: "The `response_type` is either "object" for a single
        resource or "array" for a list of resources."

        Design: Corner/entities/canal_reach_list_pagination_defaults
        """
        create_reach(name="Reach P1", max_capacity_cfs=10.0)
        create_reach(name="Reach P2", max_capacity_cfs=20.0)

        resp = api.list_canal_reaches(ADMIN)
        data, meta = validate_paginated(resp)
        assert meta["limit"] == 10, "Default limit is 10"
        assert meta["offset"] == 0, "Default offset is 0"
        assert meta["total_count"] == 2
        assert meta["has_more"] is False
        assert isinstance(meta["api_request_id"], str)
        assert resp.json()["response_type"] == "array"
        for row in data:
            assert_canal_reach(row)


class TestWindowPlanning:
    def _setup_first_window(self):
        reach = create_reach(name="Reach WO", max_capacity_cfs=50.0)
        window = create_window(
            reach["id"],
            start_at="2026-08-10T08:00:00Z", end_at="2026-08-10T14:00:00Z",
            reason="morning crew",
        )
        return reach, window

    def test_adjacent_window_accepted(self, api):
        """PRD §3.5: "Planning rejects any new window that overlaps an
        existing `PLANNED` or `ACTIVE` window on the same reach —
        `ERR_WINDOW_OVERLAP` — under half-open semantics in which a new window
        beginning exactly when an existing one ends is adjacent and allowed;
        windows already `COMPLETED` or `CANCELLED` impose no constraint."
        PRD §2.4: "Two windows whose boundary instants merely touch — one
        ending exactly when the next begins — are adjacent, not overlapping."

        Design: Difficulty/resource_temporal_overlap/maintenance_window_half_open_adjacency
        """
        reach, _window1 = self._setup_first_window()
        resp = api.create_maintenance_window(
            {
                "canal_reach_id": reach["id"],
                "start_at": "2026-08-10T14:00:00Z",
                "end_at": "2026-08-10T18:00:00Z",
                "reason": "afternoon crew",
            },
            ADMIN,
        )
        adjacent = validate_success(resp, expected_status=201)
        assert adjacent["status"] == "PLANNED", (
            "A window starting exactly when the existing one ends is adjacent"
        )

    def test_overlapping_window_rejected(self, api):
        """PRD §3.5: "Planning rejects any new window that overlaps an
        existing `PLANNED` or `ACTIVE` window on the same reach —
        `ERR_WINDOW_OVERLAP` — under half-open semantics in which a new window
        beginning exactly when an existing one ends is adjacent and
        allowed..."
        [13:00, 15:00) overlaps [08:00, 14:00) by one hour and is rejected.

        Design: Difficulty/resource_temporal_overlap/maintenance_window_half_open_adjacency
        """
        reach, window1 = self._setup_first_window()
        resp = api.create_maintenance_window(
            {
                "canal_reach_id": reach["id"],
                "start_at": "2026-08-10T13:00:00Z",
                "end_at": "2026-08-10T15:00:00Z",
                "reason": "overlapping crew",
            },
            ADMIN,
        )
        validate_error(resp, ApiErrorId.ERR_WINDOW_OVERLAP)
        assert get_window(window1["id"])["status"] == "PLANNED", (
            "The rejected plan has no side effects"
        )

    def test_create_window_end_before_start_returns_invalid_request(self, api):
        """PRD §2.7: "2. **Request shape** — required fields present, types
        valid, enum values within their declared sets, numbers positive where
        constrained, and end timestamps strictly after start timestamps, else
        `ERR_INVALID_REQUEST`."

        Design: Corner/validations/create_window_end_before_start_returns_invalid_request
        """
        reach = create_reach(name="Reach SV", max_capacity_cfs=50.0)
        resp = api.create_maintenance_window(
            {
                "canal_reach_id": reach["id"],
                "start_at": "2026-08-10T10:00:00Z",
                "end_at": "2026-08-10T08:00:00Z",
                "reason": "backwards",
            },
            ADMIN,
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)
        _data, meta = validate_paginated(api.list_maintenance_windows(ADMIN))
        assert meta["total_count"] == 0, "No window may be persisted"


class TestWindowActivation:
    def test_activate_window_outside_period_rejected(self, api):
        """PRD §3.5: "Activating a window is permitted only while the logical
        clock sits inside the window's half-open period, else
        `ERR_WINDOW_OUT_OF_PERIOD`."

        Design: Corner/state_machines/activate_window_outside_period_rejected
        """
        reach = create_reach(name="Reach OP", max_capacity_cfs=50.0)
        window = create_window(
            reach["id"],
            start_at="2026-08-10T08:00:00Z", end_at="2026-08-10T10:00:00Z",
            reason="missed crew",
        )
        set_clock("2026-08-10T11:00:00Z")

        resp = api.activate_maintenance_window(window["id"], ADMIN)
        validate_error(resp, ApiErrorId.ERR_WINDOW_OUT_OF_PERIOD)
        assert get_window(window["id"])["status"] == "PLANNED"
        assert get_reach(reach["id"])["status"] == "IN_SERVICE"

    def test_cancel_then_activate_window_rejected(self, api):
        """PRD §3.5: "A planned window is born `PLANNED` and may be cancelled
        while still `PLANNED`, moving it to `CANCELLED`." and "Window
        transitions from wrong from-states, such as activating twice or
        completing a still-`PLANNED` window, are refused with
        `ERR_INVALID_WINDOW_STATE`."

        Design: Corner/state_machines/cancel_then_activate_window_rejected
        """
        reach = create_reach(name="Reach CW", max_capacity_cfs=50.0)
        window = create_window(
            reach["id"],
            start_at="2026-08-10T08:00:00Z", end_at="2026-08-10T10:00:00Z",
            reason="crew A",
        )
        validate_success(api.cancel_maintenance_window(window["id"], ADMIN))
        set_clock("2026-08-10T09:00:00Z")

        resp = api.activate_maintenance_window(window["id"], ADMIN)
        validate_error(resp, ApiErrorId.ERR_INVALID_WINDOW_STATE)
        assert get_reach(reach["id"])["status"] == "IN_SERVICE"


class TestActivationCascade:
    def _setup_cascade(self):
        # 5.0 acres x 2.0 af/acre = 10.00 af; order 5 cfs x 10 h = 4.13 af,
        # SCHEDULED with its ASSIGNED work order before the window exists.
        scenario = setup_open_season_with_allocation(
            holder_name="Cascade C", parcel_number="APN-008",
        )
        order = place_order(
            scenario["account"]["id"], scenario["allocation"]["id"],
            scenario["reach"]["id"],
            requested_cfs=5.0,
            start="2026-07-10T08:00:00Z", end="2026-07-10T18:00:00Z",
        )
        order, work_order = schedule_order(order["id"], "rider-1")
        window = create_window(
            scenario["reach"]["id"],
            start_at="2026-07-10T12:00:00Z", end_at="2026-07-10T20:00:00Z",
            reason="flume repair",
        )
        set_clock("2026-07-10T12:30:00Z")
        scenario.update({"order": order, "work_order": work_order,
                         "window": window})
        return scenario

    def test_activation_shuts_down_reach(self, api):
        """PRD §3.5: "Activation moves the window `PLANNED → ACTIVE` and flips
        the reach to `SHUTDOWN`."

        Design: Difficulty/transitive_cascade/maintenance_window_activation_cascade
        """
        scenario = self._setup_cascade()
        resp = api.activate_maintenance_window(scenario["window"]["id"], ADMIN)
        activated = validate_success(resp, expected_status=200)
        assert activated["status"] == "ACTIVE"
        assert get_reach(scenario["reach"]["id"])["status"] == "SHUTDOWN", (
            "The reach flips to SHUTDOWN in the same act"
        )

    def test_activation_cascade_cancels_order_and_work_order(self, api):
        """PRD §3.5: "The shutdown is not merely a label: every `SCHEDULED`
        turnout order on that reach whose delivery window overlaps the
        activated window is cascade-cancelled, each cancellation releasing its
        `requested_quantity_af` from its allocation's `committed_af` and
        cancelling the order's non-terminal rider work order."

        Design: Difficulty/transitive_cascade/maintenance_window_activation_cascade
        """
        scenario = self._setup_cascade()
        validate_success(
            api.activate_maintenance_window(scenario["window"]["id"], ADMIN)
        )

        assert get_order(scenario["order"]["id"])["status"] == "CANCELLED", (
            "The overlapping SCHEDULED order is cascade-cancelled"
        )
        assert get_work_order(scenario["work_order"]["id"])["status"] == "CANCELLED", (
            "Its ASSIGNED work order is cancelled alongside"
        )
        allocation = get_allocation(scenario["allocation"]["id"])
        assert_amount(allocation["committed_af"], 0.00,
                      "The 4.13 af commitment is released")


class TestWindowCompletion:
    def test_complete_window_with_second_active_window_keeps_shutdown(self, api):
        """PRD §3.5: "Completing an `ACTIVE` window moves it `ACTIVE →
        COMPLETED` and returns the reach to `IN_SERVICE` — but only when no
        other `ACTIVE` window remains on that reach."

        Design: Corner/state_machines/complete_window_with_second_active_window_keeps_shutdown
        """
        reach = create_reach(name="Reach 2W", max_capacity_cfs=50.0)
        window1 = create_window(
            reach["id"],
            start_at="2026-08-10T08:00:00Z", end_at="2026-08-10T12:00:00Z",
            reason="crew A",
        )
        window2 = create_window(
            reach["id"],
            start_at="2026-08-10T12:00:00Z", end_at="2026-08-10T16:00:00Z",
            reason="crew B",
        )
        set_clock("2026-08-10T10:00:00Z")
        validate_success(api.activate_maintenance_window(window1["id"], ADMIN))
        set_clock("2026-08-10T12:30:00Z")
        validate_success(api.activate_maintenance_window(window2["id"], ADMIN))

        validate_success(api.complete_maintenance_window(window1["id"], ADMIN))
        assert get_reach(reach["id"])["status"] == "SHUTDOWN", (
            "Reach stays SHUTDOWN while the second window is ACTIVE"
        )

        validate_success(api.complete_maintenance_window(window2["id"], ADMIN))
        assert get_reach(reach["id"])["status"] == "IN_SERVICE", (
            "Reach returns to service once no ACTIVE window remains"
        )
