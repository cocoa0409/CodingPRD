"""Game events: scheduling guards (kit enum, spacing, alternate-kit rotation),
the checklist gate, and the laundry turnaround pipeline with its reorder
cascade."""
from test_helpers import (
    EM,
    LV,
    ApiErrorId,
    assert_game_event,
    committed_units_for,
    create_active_contract,
    create_event,
    create_pool,
    get_contract,
    get_event,
    get_pool,
    setup_completed_event_with_load,
    setup_locked_event,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestEventCreation:
    def test_event_create_invalid_kit_enum_returns_400(self, api):
        """PRD §3.6: "Scheduling a game event takes a `season_label`, an
        `opponent_name`, a `kickoff_at` timestamp, a `designated_kit` of
        `HOME`, `AWAY`, or `ALTERNATE`, and an optional seeded `checklist`"
        PRD §2.9: "all other schema failures answer `ERR_INVALID_REQUEST`."

        Design: Corner/entities/event_create_invalid_kit_enum_returns_400
        """
        resp = api.create_game_event(
            {
                "season_label": "2026-FALL",
                "opponent_name": "X",
                "kickoff_at": "2026-09-05T15:00:00Z",
                "designated_kit": "THIRD",
            },
            EM,
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)
        assert resp.status_code == 400

    def test_alternate_kit_third_allowed_fourth_rejected(self, api):
        """PRD §3.6: "And a season supports at most three alternate-kit games:
        an `ALTERNATE` designation is accepted only while fewer than three
        non-cancelled same-season events carry it — the third succeeds when
        two exist, the attempt with three already present fails with
        `ERR_ALTERNATE_KIT_LIMIT_REACHED` — and cancelling an event frees its
        slot."

        Design: Difficulty/boundary_precision_check/alternate_kit_third_allowed_fourth_rejected
        """
        first = validate_success(api.create_game_event(
            {"season_label": "2026-FALL", "opponent_name": "A",
             "kickoff_at": "2026-09-05T15:00:00Z", "designated_kit": "ALTERNATE"},
            EM,
        ), 201)
        second = validate_success(api.create_game_event(
            {"season_label": "2026-FALL", "opponent_name": "B",
             "kickoff_at": "2026-09-12T15:00:00Z", "designated_kit": "ALTERNATE"},
            EM,
        ), 201)
        third = validate_success(api.create_game_event(
            {"season_label": "2026-FALL", "opponent_name": "C",
             "kickoff_at": "2026-09-19T15:00:00Z", "designated_kit": "ALTERNATE"},
            EM,
        ), 201)
        for event in (first, second, third):
            assert event["status"] == "SCHEDULED"
        assert third["designated_kit"] == "ALTERNATE", (
            "The third ALTERNATE designation succeeds while two exist")

        resp = api.create_game_event(
            {"season_label": "2026-FALL", "opponent_name": "D",
             "kickoff_at": "2026-09-26T15:00:00Z", "designated_kit": "ALTERNATE"},
            EM,
        )
        validate_error(resp, ApiErrorId.ERR_ALTERNATE_KIT_LIMIT_REACHED)

        home = validate_success(api.create_game_event(
            {"season_label": "2026-FALL", "opponent_name": "E",
             "kickoff_at": "2026-10-03T15:00:00Z", "designated_kit": "HOME"},
            EM,
        ), 201)
        assert home["status"] == "SCHEDULED", (
            "The rotation cap applies only to ALTERNATE designations")
        assert get_event(first["id"])["status"] == "SCHEDULED"

    def test_game_event_48h_spacing_boundary(self, api):
        """PRD §3.6: "Within a season, the new kickoff must sit at least 48
        hours away from the kickoff of every other non-cancelled event in that
        season; exactly 48 hours apart is allowed, while one second less is
        rejected with `ERR_EVENT_SPACING_VIOLATION`."

        Design: Difficulty/resource_temporal_overlap/game_event_48h_spacing_boundary
        """
        e1 = create_event(opponent_name="A", kickoff_at="2026-09-05T15:00:00Z",
                          designated_kit="HOME")
        e2 = validate_success(api.create_game_event(
            {"season_label": "2026-FALL", "opponent_name": "B",
             "kickoff_at": "2026-09-07T15:00:00Z", "designated_kit": "AWAY"},
            EM,
        ), 201)
        assert e2["status"] == "SCHEDULED", (
            "Exactly 48 hours after the first kickoff: boundary inclusive")

        resp = api.create_game_event(
            {"season_label": "2026-FALL", "opponent_name": "C",
             "kickoff_at": "2026-09-06T15:00:00Z", "designated_kit": "HOME"},
            EM,
        )
        validate_error(resp, ApiErrorId.ERR_EVENT_SPACING_VIOLATION)
        assert resp.status_code == 409, "A 24-hour gap violates the 48-hour buffer"

        assert get_event(e1["id"])["status"] == "SCHEDULED"
        assert get_event(e2["id"])["status"] == "SCHEDULED", (
            "The two legitimate events are untouched by the rejection")

    def test_alternate_kit_count_excludes_cancelled(self, api):
        """PRD §3.6: "an `ALTERNATE` designation is accepted only while fewer
        than three non-cancelled same-season events carry it — the third
        succeeds when two exist, the attempt with three already present fails
        with `ERR_ALTERNATE_KIT_LIMIT_REACHED` — and cancelling an event frees
        its slot."
        PRD §3.6: "Cancelling an event is permitted from `SCHEDULED` or
        `KIT_LOCKED` (`ERR_EVENT_NOT_SCHEDULED` otherwise); it moves the event
        to `CANCELLED`, converts every still-`PENDING` checklist item to `NA`,
        and releases the alternate-kit slot if one was held."

        Design: Corner/calculations/alternate_kit_count_excludes_cancelled
        """
        create_event(opponent_name="A", kickoff_at="2026-09-05T15:00:00Z",
                     designated_kit="ALTERNATE")
        create_event(opponent_name="B", kickoff_at="2026-09-12T15:00:00Z",
                     designated_kit="ALTERNATE")
        e3 = create_event(opponent_name="C", kickoff_at="2026-09-19T15:00:00Z",
                          designated_kit="ALTERNATE")

        cancelled = validate_success(api.cancel_game_event(e3["id"], EM))
        assert cancelled["status"] == "CANCELLED"

        e4 = validate_success(api.create_game_event(
            {"season_label": "2026-FALL", "opponent_name": "D",
             "kickoff_at": "2026-09-26T15:00:00Z", "designated_kit": "ALTERNATE"},
            EM,
        ), 201)
        assert e4["status"] == "SCHEDULED", (
            "The cancellation dropped the rotation count back to two")
        assert get_event(e3["id"])["status"] == "CANCELLED"


class TestEventStateMachine:
    def test_event_lock_kit_twice_rejected(self, api):
        """PRD §3.6: "Before kickoff the kit must be locked, moving the event
        `SCHEDULED → KIT_LOCKED` (`ERR_EVENT_NOT_SCHEDULED` from any other
        state)."

        Design: Corner/state_machines/event_lock_kit_twice_rejected
        """
        event = create_event(opponent_name="A",
                             kickoff_at="2026-09-05T15:00:00Z")
        locked = validate_success(api.lock_game_event_kit(event["id"], EM))
        assert locked["status"] == "KIT_LOCKED"

        resp = api.lock_game_event_kit(event["id"], EM)
        validate_error(resp, ApiErrorId.ERR_EVENT_NOT_SCHEDULED)
        assert get_event(event["id"])["status"] == "KIT_LOCKED"

    def test_event_complete_from_scheduled_rejected(self, api):
        """PRD §3.6: "Completing an event — valid only from `KIT_LOCKED`
        (`ERR_EVENT_NOT_LOCKED`) — first requires that every checklist item
        flagged `required` has left `PENDING` behind
        (`ERR_CHECKLIST_INCOMPLETE`)."

        Design: Corner/state_machines/event_complete_from_scheduled_rejected
        """
        event = create_event(opponent_name="A",
                             kickoff_at="2026-09-05T15:00:00Z")
        assert event["status"] == "SCHEDULED"

        resp = api.complete_game_event(event["id"], {"laundry_load": []}, EM)
        validate_error(resp, ApiErrorId.ERR_EVENT_NOT_LOCKED)
        assert get_event(event["id"])["status"] == "SCHEDULED", (
            "The rejected completion leaves the event SCHEDULED")

    def test_checklist_incomplete_blocks_event_complete(self, api):
        """PRD §3.6: "Completing an event — valid only from `KIT_LOCKED`
        (`ERR_EVENT_NOT_LOCKED`) — first requires that every checklist item
        flagged `required` has left `PENDING` behind
        (`ERR_CHECKLIST_INCOMPLETE`)."
        PRD §3.6: "sets `laundry_status` to `COLLECTING` when the load is
        non-empty (an empty load leaves it `NOT_STARTED`), and — with a
        non-empty load — fixes `laundry_due_at` at exactly 48 hours after
        `kickoff_at`."

        Design: Corner/validations/checklist_incomplete_blocks_event_complete
        """
        event = create_event(
            opponent_name="A", kickoff_at="2026-09-05T15:00:00Z",
            checklist=[{"item_ref": "BENCH", "label": "Bench set up",
                        "required": True}])
        validate_success(api.lock_game_event_kit(event["id"], EM))

        resp = api.complete_game_event(event["id"], {"laundry_load": []}, EM)
        validate_error(resp, ApiErrorId.ERR_CHECKLIST_INCOMPLETE)

        validate_success(api.complete_checklist_item(
            event["id"], "BENCH", {"outcome": "DONE"}, EM))
        completed = validate_success(api.complete_game_event(
            event["id"], {"laundry_load": []}, EM))
        assert completed["status"] == "COMPLETED"
        assert completed["laundry_status"] == "NOT_STARTED", (
            "An empty load never enters the laundry pipeline")
        assert completed["laundry_due_at"] is None, (
            "The due timestamp is fixed only for a non-empty load")


class TestLaundryTurnaround:
    def test_laundry_advance_from_not_started_rejected(self, api):
        """PRD §3.6: "The laundry cycle is a parallel state dimension advanced
        one step per call — `COLLECTING → IN_WASH → READY → CLOSED` — by
        either the `LaundryVendor` or the `EquipmentManager`. A step attempted
        from `NOT_STARTED` or `CLOSED` is rejected with
        `ERR_LAUNDRY_INVALID_TRANSITION`."

        Design: Corner/state_machines/laundry_advance_from_not_started_rejected
        """
        event = create_event(opponent_name="A",
                             kickoff_at="2026-09-05T15:00:00Z")
        assert event["laundry_status"] == "NOT_STARTED"

        resp = api.advance_laundry(event["id"], LV)
        validate_error(resp, ApiErrorId.ERR_LAUNDRY_INVALID_TRANSITION)
        assert get_event(event["id"])["laundry_status"] == "NOT_STARTED"

    def test_lock_kit_blocked_until_prior_laundry_ready(self, api):
        """PRD §3.6: "Locking enforces the laundry turnaround gate: if any
        other same-season event is already `COMPLETED` with its laundry still
        `COLLECTING` or `IN_WASH`, the lock is refused with
        `ERR_LAUNDRY_NOT_READY` — the sideline cannot commit to a kit while
        the previous game's uniforms are still in the wash pipeline."
        PRD §3.6: "The step into `READY` is the restock: each load line's
        quantity moves back from `in_laundry_quantity` into `stock_on_hand` on
        its pool, followed by reconciliation and the threshold check in the
        increase direction, which may clear a pool's `reorder_blocked`."

        Design: Corner/validations/lock_kit_blocked_until_prior_laundry_ready
        """
        pool = create_pool(season_label="2026-FALL", garment_type="GAME_JERSEY",
                           size_code="M", stock_on_hand=3)
        ev1 = setup_completed_event_with_load(
            pool["id"], quantity=1, kickoff_at="2026-09-05T15:00:00Z")
        assert ev1["laundry_status"] == "COLLECTING"
        ev2 = create_event(opponent_name="B", kickoff_at="2026-09-12T15:00:00Z",
                           designated_kit="AWAY")

        resp = api.lock_game_event_kit(ev2["id"], EM)
        validate_error(resp, ApiErrorId.ERR_LAUNDRY_NOT_READY)
        assert get_event(ev2["id"])["status"] == "SCHEDULED"

        in_wash = validate_success(api.advance_laundry(ev1["id"], LV))
        assert in_wash["laundry_status"] == "IN_WASH"
        ready = validate_success(api.advance_laundry(ev1["id"], LV))
        assert ready["laundry_status"] == "READY"

        locked = validate_success(api.lock_game_event_kit(ev2["id"], EM))
        assert locked["status"] == "KIT_LOCKED", (
            "Once the prior laundry reaches READY the turnaround gate opens")

        pool_after = get_pool(pool["id"])
        assert pool_after["stock_on_hand"] == 3
        assert pool_after["in_laundry_quantity"] == 0, (
            "The READY step restocked the load into the pool")

    def test_event_complete_laundry_reorder_contract_chain(self, api):
        """PRD §3.6: "Completion then moves each line's quantity out of
        `stock_on_hand` and into `in_laundry_quantity` on its pool, records
        the load on the event, sets `laundry_status` to `COLLECTING` when the
        load is non-empty (an empty load leaves it `NOT_STARTED`), and — with
        a non-empty load — fixes `laundry_due_at` at exactly 48 hours after
        `kickoff_at`."
        PRD §3.6: "Each touched pool's reconciliation and threshold check runs
        in the decrease direction, so an event completion can itself mint an
        `AUTO_REORDER` order and commit contract allocation (§3.2, §3.3)."
        PRD §3.2: "The authoritative reorder quantity is the forward-looking
        variant: take the shortfall — the reorder point minus the new
        available quantity minus the inbound open units — and add the pool's
        `reorder_batch_size`."

        Design: Difficulty/transitive_cascade/event_complete_laundry_reorder_contract_chain
        """
        pool = create_pool(season_label="2026-FALL", garment_type="GAME_JERSEY",
                           size_code="M", stock_on_hand=10, reorder_point=9,
                           reorder_batch_size=4)
        contract = create_active_contract(
            vendor_name="ACME", season_label="2026-FALL",
            allocation_caps=[{"garment_type": "GAME_JERSEY", "max_units": 12}],
            default_lead_time_days=30)
        event = setup_locked_event(
            kickoff_at="2026-09-05T15:00:00Z", designated_kit="HOME",
            checklist=[{"item_ref": "SIDELINE_TENT",
                        "label": "Sideline tent erected", "required": True}])

        completed = validate_success(api.complete_game_event(
            event["id"],
            {"laundry_load": [{"pool_id": pool["id"], "quantity": 2}]},
            EM,
        ))
        assert_game_event(completed)
        assert completed["status"] == "COMPLETED"
        assert completed["laundry_status"] == "COLLECTING"
        assert completed["laundry_due_at"] == "2026-09-07T15:00:00Z", (
            "Kickoff 2026-09-05T15:00:00Z plus exactly 48 hours")

        pool_after = get_pool(pool["id"])
        assert pool_after["stock_on_hand"] == 8, (
            "Link 1: the load moved 2 units out of stock")
        assert pool_after["in_laundry_quantity"] == 2
        assert pool_after["available_quantity"] == 6, (
            "PRD §2.6: available = stock_on_hand - reserved - in_laundry "
            "= 8 - 0 - 2 = 6")
        assert pool_after["reorder_blocked"] is False

        data, meta = validate_paginated(api.list_kit_orders(
            EM, params={"supplier_contract_id": contract["id"],
                        "source": "AUTO_REORDER"}))
        assert meta["total_count"] == 1 and len(data) == 1, (
            "Link 2: crossing the reorder point minted exactly one order")
        auto_order = data[0]
        assert auto_order["status"] == "SUBMITTED"
        assert auto_order["lines"][0]["quantity"] == 7, (
            "Forward-looking quantity: (9 - 6 - 0 inbound) + 4 batch = 7")
        assert auto_order["lines"][0]["garment_type"] == "GAME_JERSEY"
        assert auto_order["lines"][0]["size_code"] == "M"

        contract_after = get_contract(contract["id"])
        assert committed_units_for(contract_after, "GAME_JERSEY") == 7, (
            "Link 3: the auto order committed 7 units of contract allocation")
