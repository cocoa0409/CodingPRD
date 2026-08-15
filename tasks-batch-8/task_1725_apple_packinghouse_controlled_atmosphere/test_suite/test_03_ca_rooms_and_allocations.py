"""CA room lifecycle, bin allocations, releases, the release selector, and the
room schedule OCC guard."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    allocate_bins,
    assert_ca_room,
    assert_same_instant,
    assert_storage_allocation,
    create_allocation_payload,
    create_block,
    create_grower,
    create_grower_with_block,
    create_room,
    get_success_data,
    open_room,
    receive_lot,
    release_allocation,
    schedule_update_payload,
    seal_payload,
    seal_room,
    set_logical_clock,
    setup_sealed_storage,
    setup_stored_lot,
    validate_error,
    validate_paginated,
    validate_success,
)

ADMIN = TEST_USERS["admin_headers"]
CLERK = TEST_USERS["receiving_clerk_headers"]
STORAGE = TEST_USERS["storage_operator_headers"]


class TestRoomStateGates:
    def test_seal_from_available_rejected(self, api):
        """PRD §3.2: "The room must be `FILLING` with at least one allocated bin,
        else `ERR_ROOM_INVALID_STATE`."

        Design: Corner/state_machines/c_seal_from_available_rejected
        """
        room = create_room()
        resp = api.seal_ca_room(room["id"], seal_payload(), STORAGE)
        validate_error(resp, ApiErrorId.ERR_ROOM_INVALID_STATE)

    def test_open_from_filling_rejected(self, api):
        """PRD §3.2: "Opening a room — allowed only from `SEALED`, else
        `ERR_ROOM_INVALID_STATE` — starts the emptying clock"

        Design: Corner/state_machines/c_open_from_filling_rejected
        """
        ctx = setup_stored_lot()
        assert ctx["room"]["status"] == "AVAILABLE"
        # The allocation moved the room to FILLING.
        room = get_success_data(api.get_ca_room(ctx["room"]["id"], ADMIN))
        assert room["status"] == "FILLING"
        resp = api.open_ca_room(room["id"], STORAGE)
        validate_error(resp, ApiErrorId.ERR_ROOM_INVALID_STATE)

    def test_release_from_sealed_room_rejected(self, api):
        """PRD §3.3: "A manual release by a `StorageOperator` requires the
        allocation to be `ACTIVE` (else `ERR_ALLOCATION_INVALID_STATE`) and its
        room to be `OPENED` (else `ERR_ROOM_INVALID_STATE`)."

        Design: Corner/state_machines/c_release_from_sealed_room_rejected
        """
        ctx = setup_sealed_storage()
        resp = api.release_allocation(ctx["allocation"]["id"], STORAGE)
        validate_error(resp, ApiErrorId.ERR_ROOM_INVALID_STATE)
        allocation = get_success_data(api.get_allocation(ctx["allocation"]["id"], ADMIN))
        assert allocation["status"] == "ACTIVE", "failed release has no side effects"

    def test_release_released_allocation_rejected(self, api):
        """PRD §3.3: "A manual release by a `StorageOperator` requires the
        allocation to be `ACTIVE` (else `ERR_ALLOCATION_INVALID_STATE`) and its
        room to be `OPENED` (else `ERR_ROOM_INVALID_STATE`)."

        Design: Corner/state_machines/c_release_released_allocation_rejected
        """
        grower, block = create_grower_with_block()
        lot1 = receive_lot(grower["id"], block["id"], 5, 4000, 80)
        lot2 = receive_lot(grower["id"], block["id"], 4, 3000, 75)
        room = create_room()
        a1 = allocate_bins(room["id"], lot1["id"], 5)
        allocate_bins(room["id"], lot2["id"], 4)
        seal_room(room)
        open_room(room["id"])
        release_allocation(a1["id"])
        # The second lot's 4 bins keep the room OPENED, isolating the
        # allocation-state gate.
        resp = api.release_allocation(a1["id"], STORAGE)
        validate_error(resp, ApiErrorId.ERR_ALLOCATION_INVALID_STATE)


class TestBinCapacity:
    def test_allocation_beyond_bins_free_rejected(self, api):
        """PRD §3.2: "The requested bins may not exceed the room's `bins_free`,
        else `ERR_ROOM_CAPACITY_EXCEEDED`."
        PRD §2.10: "A room's `bins_allocated` is the summed `bins` of its `ACTIVE`
        storage allocations, and its `bins_free` is `bin_capacity` minus
        `bins_allocated`."

        Design: Difficulty/resource_temporal_overlap/room_bin_capacity_aggregate
        """
        grower, block = create_grower_with_block()
        lot1 = receive_lot(grower["id"], block["id"], 20, 19000, 80)
        lot2 = receive_lot(grower["id"], block["id"], 6, 5500, 75)
        room = create_room(bin_capacity=25)
        allocate_bins(room["id"], lot1["id"], 20)
        room = get_success_data(api.get_ca_room(room["id"], ADMIN))
        assert room["bins_free"] == 5

        resp = api.create_allocation(
            room["id"], create_allocation_payload(lot2["id"], 6), STORAGE)
        validate_error(resp, ApiErrorId.ERR_ROOM_CAPACITY_EXCEEDED)

    def test_allocation_exact_fit_boundary_allowed(self, api):
        """PRD §3.2: "The requested bins may not exceed the room's `bins_free`,
        else `ERR_ROOM_CAPACITY_EXCEEDED`."
        PRD §2.10: "A room's `bins_allocated` is the summed `bins` of its `ACTIVE`
        storage allocations, and its `bins_free` is `bin_capacity` minus
        `bins_allocated`."

        Design: Difficulty/resource_temporal_overlap/room_bin_capacity_aggregate
        """
        grower, block = create_grower_with_block()
        lot1 = receive_lot(grower["id"], block["id"], 20, 19000, 80)
        lot2 = receive_lot(grower["id"], block["id"], 6, 5500, 75)
        room = create_room(bin_capacity=25)
        allocate_bins(room["id"], lot1["id"], 20)

        # Exact fit: 5 bins into exactly 5 free slots succeeds.
        a2 = allocate_bins(room["id"], lot2["id"], 5)
        assert_storage_allocation(a2)
        assert a2["status"] == "ACTIVE"
        room = get_success_data(api.get_ca_room(room["id"], ADMIN))
        assert room["bins_allocated"] == 25
        assert room["bins_free"] == 0, "exact-fit boundary allowed"


class TestRoomCycleRestart:
    def test_room_cycle_empties_back_to_available(self, api):
        """PRD §3.3: "if that empties an `OPENED` room to zero the room returns to
        `AVAILABLE`, clearing `atmosphere_alarm` and `priority_release` and wiping
        `actual_opened_at` and `must_empty_by` for the next fill"

        Design: Difficulty/non_linear_state_machine/ca_room_full_cycle_restart
        """
        ctx = setup_sealed_storage(received_bin_count=20, received_weight_lbs=19000)
        assert ctx["room"]["status"] == "SEALED"

        ctx["room"] = open_room(ctx["room"]["id"])
        assert ctx["room"]["status"] == "OPENED"

        release_allocation(ctx["allocation"]["id"])
        room = get_success_data(api.get_ca_room(ctx["room"]["id"], ADMIN))
        assert_ca_room(room)
        assert room["status"] == "AVAILABLE", "emptied OPENED room cycles back"
        assert room["bins_allocated"] == 0
        assert room["bins_free"] == 40
        assert room["atmosphere_alarm"] is False
        assert room["priority_release"] is False

    def test_room_accepts_new_allocation_after_cycle(self, api):
        """PRD §3.2: "the first allocation into an `AVAILABLE` room moves it
        `AVAILABLE → FILLING`, while an `OPENED` room stays `OPENED`."

        Design: Difficulty/non_linear_state_machine/ca_room_full_cycle_restart
        """
        ctx = setup_sealed_storage(received_bin_count=20, received_weight_lbs=19000)
        open_room(ctx["room"]["id"])
        release_allocation(ctx["allocation"]["id"])
        room = get_success_data(api.get_ca_room(ctx["room"]["id"], ADMIN))
        assert room["status"] == "AVAILABLE"

        # Cycle restart: the same room accepts a fresh allocation afterwards.
        lot2 = receive_lot(ctx["grower"]["id"], ctx["block"]["id"], 8, 7000, 75)
        a2 = allocate_bins(room["id"], lot2["id"], 8)
        assert a2["status"] == "ACTIVE"
        room = get_success_data(api.get_ca_room(room["id"], ADMIN))
        assert room["status"] == "FILLING", "AVAILABLE -> FILLING on first allocation"
        assert room["bins_free"] == 32


class TestAllocateReleaseInvariant:
    def test_allocate_then_release_restores_bins_free(self, api):
        """PRD §2.10: "Creating an allocation and later releasing it is likewise a
        compensating pair that leaves `bins_free` exactly unchanged."

        Design: Difficulty/compensating_invariant/allocate_release_bins_free_restored
        """
        ctx = setup_stored_lot(received_bin_count=20, received_weight_lbs=19000)
        room = get_success_data(api.get_ca_room(ctx["room"]["id"], ADMIN))
        assert room["status"] == "FILLING"
        assert room["bins_free"] == 20, "40 capacity minus 20 allocated"

        seal_room(room)
        open_room(room["id"])
        release_allocation(ctx["allocation"]["id"])

        room = get_success_data(api.get_ca_room(room["id"], ADMIN))
        assert room["bins_free"] == 40, "allocate + release conserves bin slots"
        assert room["status"] == "AVAILABLE", "emptied OPENED room cycles"

    def test_release_marks_allocation_and_releases_lot(self, api):
        """PRD §3.3: "The release stamps `released_at` from the clock, records
        `release_reason` `MANUAL`"
        PRD §3.3: "meanwhile, if this is the lot's first release, the lot
        transitions `IN_STORAGE → RELEASED`."

        Design: Difficulty/compensating_invariant/allocate_release_bins_free_restored
        """
        ctx = setup_stored_lot(received_bin_count=20, received_weight_lbs=19000)
        seal_room(ctx["room"])
        open_room(ctx["room"]["id"])
        released = release_allocation(ctx["allocation"]["id"])

        assert_storage_allocation(released)
        assert released["status"] == "RELEASED"
        assert released["release_reason"] == "MANUAL"
        assert released.get("released_at") is not None

        lot = get_success_data(api.get_lot(ctx["lot"]["id"], ADMIN))
        assert lot["status"] == "RELEASED", "first release transitions the lot"

        room = get_success_data(api.get_ca_room(ctx["room"]["id"], ADMIN))
        assert room["actual_opened_at"] is None, "wiped for the next fill"
        assert room["must_empty_by"] is None, "wiped for the next fill"


class TestSelectRelease:
    def test_select_release_empty_after_divert_rejected(self, api):
        """PRD §3.2: "Opening a room that holds zero `ACTIVE` allocations — for
        example after a diversion emptied it while it was `SEALED` — is permitted,
        and the room simply stays `OPENED`"
        PRD §3.3: "If the room holds no `ACTIVE` allocations, the request is
        rejected with `ERR_NO_RELEASABLE_ALLOCATIONS`."

        Design: Corner/errors/c_select_release_empty_after_divert_rejected
        """
        ctx = setup_sealed_storage()
        # Divert the lot while the room is SEALED: the allocation is released by
        # the cascade and the SEALED room keeps its state with zero bins.
        diverted = validate_success(api.divert_lot(ctx["lot"]["id"], STORAGE))
        assert diverted["status"] == "DIVERTED"
        room = get_success_data(api.get_ca_room(ctx["room"]["id"], ADMIN))
        assert room["status"] == "SEALED"
        assert room["bins_allocated"] == 0

        opened = validate_success(api.open_ca_room(room["id"], STORAGE))
        assert opened["status"] == "OPENED", "opening an emptied room is allowed"

        resp = api.select_release(room["id"], STORAGE)
        validate_error(resp, ApiErrorId.ERR_NO_RELEASABLE_ALLOCATIONS)

    def test_selector_highest_urgency_wins(self, api):
        """PRD §3.3: "the selector release on an `OPENED` room (else
        `ERR_ROOM_INVALID_STATE`) ranks the room's `ACTIVE` allocations by
        `release_priority_score` from highest to lowest, breaking ties toward the
        earliest `allocated_at` and then the earliest `created_at`."
        PRD §3.3: "an urgency term of thirty minus the whole days remaining until
        the allocation's own `must_release_by`, where days remaining is computed
        with whole-day floor semantics and never falls below zero, so an
        allocation at or past its deadline contributes the full thirty points
        while one more than thirty days out contributes nothing."

        The short-life block gives its allocation the strictly higher urgency term
        under any plausible must-empty window, so the ranking is determinate.

        Design: Corner/cross_cutting_layers/c_selector_highest_score_wins
        """
        grower = create_grower()
        block_a = create_block(grower["id"], variety="GALA", block_code="BA",
                               storage_life_days=1)
        block_b = create_block(grower["id"], variety="FUJI", block_code="BB",
                               storage_life_days=240)
        lot_a = receive_lot(grower["id"], block_a["id"], 5, 4000, 80)
        lot_b = receive_lot(grower["id"], block_b["id"], 5, 4000, 78)
        room = create_room()
        a1 = allocate_bins(room["id"], lot_a["id"], 5)
        a2 = allocate_bins(room["id"], lot_b["id"], 5)
        seal_room(room)
        open_room(room["id"])

        picked = validate_success(api.select_release(room["id"], STORAGE))
        assert picked["id"] == a1["id"], (
            "the allocation nearer its deadline carries the higher urgency term"
        )
        assert picked["release_reason"] == "SELECTED"
        assert picked["status"] == "RELEASED"

        other = get_success_data(api.get_allocation(a2["id"], ADMIN))
        assert other["status"] == "ACTIVE", "only the top-ranked allocation releases"

        lot_a_after = get_success_data(api.get_lot(lot_a["id"], ADMIN))
        assert lot_a_after["status"] == "RELEASED", "first release frees the lot"

    def test_selector_tiebreak_earliest_allocated_wins(self, api):
        """PRD §3.3: "the selector release on an `OPENED` room (else
        `ERR_ROOM_INVALID_STATE`) ranks the room's `ACTIVE` allocations by
        `release_priority_score` from highest to lowest, breaking ties toward the
        earliest `allocated_at` and then the earliest `created_at`."

        Both lots come from the same block at the same receiving instant, so the
        two allocations carry identical scores; the clock is advanced between the
        two allocations so the tie-break on `allocated_at` is determinate.

        Design: Corner/cross_cutting_layers/c_selector_tiebreak_earliest_created_wins
        """
        grower, block = create_grower_with_block()
        lot1 = receive_lot(grower["id"], block["id"], 5, 4000, 80)
        lot2 = receive_lot(grower["id"], block["id"], 5, 4000, 78)
        room = create_room()
        a1 = allocate_bins(room["id"], lot1["id"], 5)
        set_logical_clock("2026-08-02T00:00:00Z")
        a2 = allocate_bins(room["id"], lot2["id"], 5)
        seal_room(room)
        open_room(room["id"])

        picked = validate_success(api.select_release(room["id"], STORAGE))
        assert picked["id"] == a1["id"], "tie on score breaks to earliest allocated_at"
        assert picked["release_reason"] == "SELECTED"

        other = get_success_data(api.get_allocation(a2["id"], ADMIN))
        assert other["status"] == "ACTIVE"


class TestAllocationsFiltered:
    def test_allocations_filtered_by_room_and_lot(self, api):
        """PRD §2.3: "the allocation list by `room_id`, `lot_id`, and `status`"

        Design: Corner/endpoints/c_allocations_filtered_by_room_and_lot
        """
        grower, block = create_grower_with_block()
        lot1 = receive_lot(grower["id"], block["id"], 5, 4000, 80)
        lot2 = receive_lot(grower["id"], block["id"], 4, 3000, 75)
        room = create_room()
        a1 = allocate_bins(room["id"], lot1["id"], 5)
        a2 = allocate_bins(room["id"], lot2["id"], 4)

        data, meta = validate_paginated(
            api.list_allocations(ADMIN, params={"lot_id": lot2["id"]}))
        assert meta["total_count"] == 1
        assert data[0]["id"] == a2["id"]

        data2, meta2 = validate_paginated(
            api.list_allocations(ADMIN, params={"room_id": room["id"]}))
        assert meta2["total_count"] == 2
        assert {d["id"] for d in data2} == {a1["id"], a2["id"]}


class TestScheduleUpdateOcc:
    def test_version_required_missing_on_schedule_update(self, api):
        """PRD §2.7: "On both endpoints, omitting the version field entirely is
        rejected with `ERR_VERSION_REQUIRED` (HTTP 400)."

        Design: Corner/cross_cutting_layers/c_version_required_missing_on_schedule_update
        """
        room = create_room()
        resp = api.update_ca_room_schedule(
            room["id"],
            schedule_update_payload(planned_open_date="2026-12-01T00:00:00Z"),
            STORAGE)
        validate_error(resp, ApiErrorId.ERR_VERSION_REQUIRED)

    def test_occ_stale_schedule_update_rejected(self, api):
        """PRD §2.7: "Updating a room's sealing schedule (`PUT
        /ca-rooms/{id}/schedule`) requires `expected_ca_room_version`. If the
        room's stored `version` no longer matches the supplied value — because
        another schedule edit committed after the client's read, or because any
        cascade that touches the room (for example an inspection-driven
        `priority_release` update) has advanced it — the update is based on a
        stale view and is rejected with `ERR_STALE_VERSION` (HTTP 412); the client
        must re-read the room before retrying."
        PRD §3.2: "a committed update increments the room's `version` by one."

        Design: Corner/cross_cutting_layers/c_occ_stale_schedule_update_rejected
        """
        room = create_room()
        base_version = room["version"]

        stale = api.update_ca_room_schedule(
            room["id"],
            schedule_update_payload(expected_ca_room_version=base_version - 1,
                                    planned_open_date="2026-12-01T00:00:00Z"),
            STORAGE)
        validate_error(stale, ApiErrorId.ERR_STALE_VERSION)

        updated = validate_success(api.update_ca_room_schedule(
            room["id"],
            schedule_update_payload(expected_ca_room_version=base_version,
                                    planned_open_date="2026-12-01T00:00:00Z"),
            STORAGE))
        assert updated["version"] == base_version + 1, (
            "a committed schedule update increments the room version by one"
        )
        assert_same_instant(updated["planned_open_date"], "2026-12-01T00:00:00Z",
                            "planned_open_date")
