"""Two interval families with deliberately different end conventions: the
half-open detection window and the closed kit occupancy interval."""

from test_helpers import (
    ApiErrorId,
    add_complaint,
    add_contact,
    add_kit,
    add_lot,
    assert_append_only_common_fields,
    assert_two_decimal_value,
    seed_base_world,
    seed_shipped_kit,
    set_clock,
    shift,
    trend_signal_payload,
    triage,
    validate_error,
    validate_paginated,
    validate_success,
)

# ---------------------------------------------------------------------------
# Detection windows are half-open, so back-to-back windows are legal
# ---------------------------------------------------------------------------
def _seed_two_complaints_three_weeks_apart(api):
    """One complaint in mid July and one in early August, on the same lot."""
    world = seed_base_world(
        api,
        clock="2026-07-15T00:00:00Z",
        actor_keys=("ag1", "ql1"),
        product="mug",
        create_lot=False,
    )
    add_lot(
        api,
        world,
        "lott",
        product_key="mug",
        batch_code="LOT-T",
        code_date="2026-07-01T00:00:00Z",
        units_produced=100000,
    )
    add_contact(
        api,
        world,
        "cta",
        channel="WEB",
        received_at="2026-07-15T00:00:00Z",
        raw_message="Chip in the rim.",
    )
    add_complaint(
        api, world, "cpa", contact_key="cta",
        complaint_type="FOREIGN_MATERIAL", reported_batch_code="LOTT",
    )
    set_clock(api, "2026-08-05T00:00:00Z")
    add_contact(
        api,
        world,
        "ctb",
        channel="WEB",
        received_at="2026-08-05T00:00:00Z",
        raw_message="Chip in the rim.",
    )
    add_complaint(
        api, world, "cpb", contact_key="ctb",
        complaint_type="FOREIGN_MATERIAL", reported_batch_code="LOTT",
    )
    set_clock(api, "2026-08-20T00:00:00Z")
    return world


def _lot_signal_payload(world, window_start, window_end):
    return trend_signal_payload(
        "LOT",
        world["plant"]["id"],
        window_start,
        window_end,
        production_line_id=world["line"]["id"],
        lot_id=world["lots"]["lott"]["id"],
    )


class TestTrendWindowsAreHalfOpen:
    def test_upper_bound_of_the_window_is_excluded(self, api):
        """A window ending on the first of August takes only the July complaint.

        PRD: "The detection window is the 30 days ending at the logical clock,
        and it is **half-open** on a complaint's `created_at`: a complaint counts
        when its `created_at` is at or after the window's start and strictly
        before the window's end."

        Design: Difficulty/resource_temporal_overlap/trend_signal_windows_are_half_open_so_adjacency_is_legal
        """
        world = _seed_two_complaints_three_weeks_apart(api)

        signal = validate_success(
            api.create_trend_signal(
                _lot_signal_payload(
                    world, "2026-07-01T00:00:00Z", "2026-08-01T00:00:00Z"
                ),
                world.headers("ql1"),
            ),
            201,
        )

        assert signal["detection_source"] == "MANUAL"
        assert signal["status"] == "DETECTED"
        assert signal["membership_count"] == 1
        assert_two_decimal_value(signal["weighted_complaint_count"], 1.00)

        members, meta = validate_paginated(
            api.list_signal_memberships(signal["id"], world.headers("ql1"))
        )
        assert meta["total_count"] == 1
        assert members[0]["complaint_id"] == world["complaints"]["cpa"]["id"]
        assert_append_only_common_fields(members[0])

    def test_adjacent_window_starting_where_the_first_ended_is_accepted(self, api):
        """Touching bounds share no instant, so the second window is not an overlap.

        PRD: "Two windows overlap when the first starts before the second ends
        and the second starts before the first ends; windows that merely touch at
        a boundary therefore coexist, so a window running from 1 July up to 1
        August and one running from 1 August up to 15 August are both permitted."

        Design: Difficulty/resource_temporal_overlap/trend_signal_windows_are_half_open_so_adjacency_is_legal
        """
        world = _seed_two_complaints_three_weeks_apart(api)
        lead = world.headers("ql1")

        validate_success(
            api.create_trend_signal(
                _lot_signal_payload(
                    world, "2026-07-01T00:00:00Z", "2026-08-01T00:00:00Z"
                ),
                lead,
            ),
            201,
        )
        adjacent = validate_success(
            api.create_trend_signal(
                _lot_signal_payload(
                    world, "2026-08-01T00:00:00Z", "2026-08-15T00:00:00Z"
                ),
                lead,
            ),
            201,
        )

        assert adjacent["membership_count"] == 1
        members, _meta = validate_paginated(
            api.list_signal_memberships(adjacent["id"], lead)
        )
        assert [row["complaint_id"] for row in members] == [
            world["complaints"]["cpb"]["id"]
        ]

    def test_genuinely_overlapping_window_is_refused_for_the_same_scope(self, api):
        """A window straddling both existing windows collides and nothing is written.

        PRD: "The window must not strictly overlap an existing `DETECTED`,
        `INVESTIGATION_OPEN`, or `RECALL_EVALUATION` signal for the same scope
        key, otherwise `ERR_SIGNAL_WINDOW_OVERLAP`; since the windows are
        half-open, two that merely touch at a boundary may coexist."

        Design: Difficulty/resource_temporal_overlap/trend_signal_windows_are_half_open_so_adjacency_is_legal
        """
        world = _seed_two_complaints_three_weeks_apart(api)
        lead = world.headers("ql1")
        for start, end in (
            ("2026-07-01T00:00:00Z", "2026-08-01T00:00:00Z"),
            ("2026-08-01T00:00:00Z", "2026-08-15T00:00:00Z"),
        ):
            validate_success(
                api.create_trend_signal(_lot_signal_payload(world, start, end), lead),
                201,
            )

        refused = api.create_trend_signal(
            _lot_signal_payload(world, "2026-07-10T00:00:00Z", "2026-08-05T00:00:00Z"),
            lead,
        )
        error = validate_error(refused, ApiErrorId.SIGNAL_WINDOW_OVERLAP, 409)
        assert error["error_id"] != ApiErrorId.SIGNAL_EMPTY_MEMBERSHIP

        _rows, meta = validate_paginated(
            api.list_trend_signals(lead, {"lot_id": world["lots"]["lott"]["id"]})
        )
        assert meta["total_count"] == 2


# ---------------------------------------------------------------------------
# Kit occupancy intervals are closed, so the final instant still blocks
# ---------------------------------------------------------------------------
OCCUPANCY_END = "2026-08-17T00:00:00Z"
ONE_MOMENT_LATER = "2026-08-17T00:00:01Z"


def _seed_one_shipped_and_one_requested_kit(api):
    """A dispatched kit holding the interval and a second kit waiting on it."""
    world = seed_base_world(api, actor_keys=("ag1", "sup1"))
    add_contact(api, world, "ct1")
    for key in ("cpa", "cpb"):
        add_complaint(
            api, world, key,
            complaint_type="FOREIGN_MATERIAL", foreign_object_class="SOFT",
        )
        world["complaints"][key] = triage(api, world, world["complaints"][key]["id"])
    seed_shipped_kit(
        api, world, world["complaints"]["cpa"]["id"], "k1",
        kit_code="K-201", seal_id_issued="SEAL-201",
    )
    add_kit(
        api, world, world["complaints"]["cpb"]["id"], "k2",
        kit_code="K-202", seal_id_issued="SEAL-202",
    )
    return world


class TestKitOccupancyIntervalIsClosed:
    def test_the_final_instant_of_the_interval_still_blocks_dispatch(self, api):
        """Shipping exactly on `occupied_until` collides, because the end is included.

        PRD: "Dispatch is refused with `ERR_KIT_INTERVAL_CONFLICT` when any other
        kit belonging to the same consumer, in `REQUESTED`, `SHIPPED`,
        `IN_TRANSIT_INBOUND`, or `RECEIVED`, has an occupancy interval that
        contains the prospective `shipped_at`; because the interval is closed, a
        prospective `shipped_at` exactly equal to another kit's `occupied_until`
        still collides."

        Design: Difficulty/resource_temporal_overlap/sample_kit_occupancy_interval_is_closed_at_both_ends
        """
        world = _seed_one_shipped_and_one_requested_kit(api)
        holder = world["kits"]["k1"]
        assert holder["expected_return_by"] == "2026-08-15T00:00:00.000Z"
        assert holder["occupied_until"] == shift(OCCUPANCY_END)

        set_clock(api, OCCUPANCY_END)
        refused = api.ship_sample_kit(
            world["kits"]["k2"]["id"],
            {"carrier_note": "Kit dispatched."},
            world.headers("ag1"),
        )
        validate_error(refused, ApiErrorId.KIT_INTERVAL_CONFLICT, 409)

        blocked = validate_success(
            api.get_sample_kit(world["kits"]["k2"]["id"], world.headers("ag1"))
        )
        assert blocked["status"] == "REQUESTED"
        assert blocked["shipped_at"] is None

    def test_the_holding_kit_is_untouched_without_an_operations_run(self, api):
        """Passing the return date does not expire a kit on its own.

        PRD: "Alternatively, the periodic quality checkpoint expires a `SHIPPED`
        kit once the logical clock is strictly after its `expected_return_by`:
        the kit becomes `EXPIRED`, its `disposition` is forced to `UNUSABLE` and
        its `chain_integrity_status` forced to `BROKEN`, the complaint again
        moves `AWAITING_SAMPLE → IN_RESOLUTION`, and `open_kit_count` falls by
        one."

        Design: Difficulty/resource_temporal_overlap/sample_kit_occupancy_interval_is_closed_at_both_ends
        """
        world = _seed_one_shipped_and_one_requested_kit(api)
        set_clock(api, OCCUPANCY_END)

        holder = validate_success(
            api.get_sample_kit(world["kits"]["k1"]["id"], world.headers("ag1"))
        )
        assert holder["status"] == "SHIPPED"

        consumer = validate_success(
            api.get_consumer(world["consumer"]["id"], world.headers("sup1"))
        )
        assert consumer["open_kit_count"] == 2

    def test_one_second_past_the_interval_permits_dispatch(self, api):
        """Clearing the closed end by a single second releases the second kit.

        PRD: "Dispatching the kit, optionally with a `carrier_note`, moves it
        `REQUESTED → SHIPPED` and stamps four instants at once." And:
        "`expected_return_by` is 14 days after `shipped_at`."

        Design: Difficulty/resource_temporal_overlap/sample_kit_occupancy_interval_is_closed_at_both_ends
        """
        world = _seed_one_shipped_and_one_requested_kit(api)
        set_clock(api, ONE_MOMENT_LATER)

        shipped = validate_success(
            api.ship_sample_kit(
                world["kits"]["k2"]["id"],
                {"carrier_note": "Kit dispatched."},
                world.headers("ag1"),
            )
        )

        assert shipped["status"] == "SHIPPED"
        assert shipped["shipped_at"] == shift(ONE_MOMENT_LATER)
        assert shipped["expected_return_by"] == shift(ONE_MOMENT_LATER, days=14)
        assert shipped["occupied_from"] == shift(ONE_MOMENT_LATER, hours=-48)
        assert shipped["occupied_until"] == shift(ONE_MOMENT_LATER, days=14, hours=48)

    def test_dispatch_opens_the_custody_chain_with_a_single_issue_event(self, api):
        """One event, of one type, at the first sequence number.

        PRD: "Finally, dispatch automatically appends the chain's first custody
        record, a `KIT_ISSUED` event at `sequence_no` 1."

        Design: Difficulty/resource_temporal_overlap/sample_kit_occupancy_interval_is_closed_at_both_ends
        """
        world = _seed_one_shipped_and_one_requested_kit(api)
        set_clock(api, ONE_MOMENT_LATER)

        shipped = validate_success(
            api.ship_sample_kit(
                world["kits"]["k2"]["id"],
                {"carrier_note": "Kit dispatched."},
                world.headers("ag1"),
            )
        )
        assert shipped["custody_event_count"] == 1

        events, meta = validate_paginated(
            api.list_custody_events(world["kits"]["k2"]["id"], world.headers("ag1"))
        )
        assert meta["total_count"] == 1
        assert events[0]["event_type"] == "KIT_ISSUED"
        assert events[0]["sequence_no"] == 1
