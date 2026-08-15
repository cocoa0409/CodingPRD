"""Terminal creation, yard-capacity counters, and derived posture (PRD §2.7, §3.1)."""
import pytest

from test_helpers import (
    NON_EXISTENT_UUID,
    ApiErrorId,
    assert_terminal,
    assert_terminal_capacity_invariant,
    assert_yard_slot,
    create_arrived_train,
    create_slot,
    create_terminal,
    get_container,
    get_slot,
    get_terminal,
    ground_container,
    register_container,
    set_clock,
    setup_full_terminal,
    setup_grounded_container,
    setup_terminal_with_slots,
    TEST_USERS,
    validate_error,
    validate_paginated,
    validate_success,
)

TM = TEST_USERS["terminal_manager_headers"]
YP = TEST_USERS["yard_planner_headers"]


class TestTerminalCreation:
    def test_terminal_creation_applies_computed_defaults(self, api):
        """PRD §3.1: "At creation the terminal's counters are zeroed —
        `yard_slots_in_use` is zero, `yard_slots_free` equals `yard_slot_count`,
        `posture` is `OPEN`, and the `ops_run_index` monotone counter starts at
        zero."

        Design: Corner/entities/terminal_creation_applies_defaults_and_computed_fields
        """
        resp = api.create_terminal(
            {
                "terminal_code": "BNSF-LA",
                "rail_cutoff_minutes_before_departure": 60,
                "gate_free_hours": 48,
                "per_diem_rate_cents": 15000,
                "storage_rate_cents": 8000,
                "flip_fee_cents": 5000,
                "max_stack_height": 3,
                "yard_slot_count": 20,
            },
            TM,
        )
        terminal = validate_success(resp, 201)
        assert_terminal(terminal)
        assert terminal["yard_slots_in_use"] == 0
        assert terminal["yard_slots_free"] == 20
        assert terminal["posture"] == "OPEN"
        assert terminal["ops_run_index"] == 0

    def test_get_terminal_not_found(self, api):
        """PRD §2.6: "The first identifier in the path that does not exist, or
        that exists but is not scoped under its declared parent, produces an
        immediate `ERR_NOT_FOUND` (HTTP 404) without evaluating any deeper
        identifier or any business rule."

        Design: Corner/entities/terminal_get_not_found
        """
        resp = api.get_terminal(NON_EXISTENT_UUID, TM)
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND)


class TestYardSlotListing:
    def test_yard_slot_list_pagination_envelope(self, api):
        """PRD §2.3: "Paginated list responses include four fields in the
        `meta` object of the envelope: `limit`, `offset`, `total_count`, and
        `has_more`."

        Design: Corner/entities/yard_slot_list_pagination
        """
        terminal, slots = setup_terminal_with_slots(yard_slot_count=5, num_slots=3)

        resp = api.list_slots(terminal["id"], YP)
        data, meta = validate_paginated(resp)
        assert len(data) == 3, f"Expected 3 slots, got {len(data)}"
        assert meta["total_count"] == 3
        assert meta["has_more"] is False
        for slot in data:
            assert_yard_slot(slot)


class TestDerivedPosture:
    def test_posture_closed_when_yard_full(self, api):
        """PRD §2.7: "When `yard_slots_free` reaches zero the posture becomes
        `CLOSED`."

        Design: Corner/endpoints/computed_read_terminal_posture
        """
        ctx = setup_full_terminal(yard_slot_count=4)
        terminal = ctx["terminal"]
        assert_terminal(terminal)
        assert terminal["yard_slots_in_use"] == 4
        assert terminal["yard_slots_free"] == 0
        assert terminal["posture"] == "CLOSED"

    def test_posture_congested_at_threshold(self, api):
        """PRD §2.7: "Let the congestion threshold be the greatest whole number
        not exceeding fifteen percent of `yard_slot_count`, computed by integer
        floor. When `yard_slots_free` reaches zero the posture becomes
        `CLOSED`. When `yard_slots_free` is greater than zero but less than or
        equal to the congestion threshold the posture becomes `CONGESTED`."

        yard_slot_count=10 -> threshold floor(1.5)=1; grounding nine containers
        leaves free == 1, which is > 0 and <= 1: CONGESTED.

        Design: Corner/endpoints/computed_read_terminal_posture
        """
        terminal, slots = setup_terminal_with_slots(yard_slot_count=10, num_slots=10)
        tid = terminal["id"]
        train = create_arrived_train(tid)
        set_clock("2026-08-01T00:00:00Z")
        for i in range(9):
            container = register_container(tid, train["id"], f"C{i + 1:010d}")
            ground_container(tid, container["id"])

        terminal = get_terminal(tid)
        assert_terminal(terminal)
        assert terminal["yard_slots_in_use"] == 9
        assert terminal["yard_slots_free"] == 1
        assert terminal["posture"] == "CONGESTED", (
            "free == 1 <= floor(10 * 0.15) == 1 and > 0 must yield CONGESTED")


class TestCapacityInvariant:
    def test_ground_then_void_restores_slot_counts(self, api):
        """PRD §2.7: "The terminal is created with a `yard_slot_count` and
        tracks two derived integers: `yard_slots_in_use`, the number of its
        yard slots currently counted as consumed, and `yard_slots_free`, which
        is always exactly `yard_slot_count` minus `yard_slots_in_use`."
        PRD §3.3: "Voiding releases the yard slot through the same cascade as
        a mount: the slot returns to `EMPTY`, its `occupied_container_id`
        clears, its `current_height` resets to zero, the terminal's in-use
        count drops by one, free count rises by one, and posture recomputes."

        Design: Difficulty/compensating_invariant/yard_slot_count_invariant_under_ground_and_void
        """
        ctx = setup_grounded_container(yard_slot_count=5)
        tid = ctx["terminal"]["id"]
        container = ctx["container"]
        slot = ctx["slots"][0]

        after_ground = get_terminal(tid)
        assert_terminal_capacity_invariant(after_ground)
        assert after_ground["yard_slots_in_use"] == 1
        assert after_ground["yard_slots_free"] == 4

        resp = api.void_container(tid, container["id"], TM)
        voided = validate_success(resp, 200)
        assert voided["status"] == "VOIDED"

        after_void = get_terminal(tid)
        assert_terminal_capacity_invariant(after_void)
        assert after_void["yard_slots_in_use"] == 0, (
            "Void must compensate the ground: in-use back to 0")
        assert after_void["yard_slots_free"] == 5
        assert after_void["posture"] == "OPEN"

        slot_after = get_slot(tid, slot["id"])
        assert slot_after["status"] == "EMPTY"
        assert slot_after["occupied_container_id"] is None
        assert slot_after["current_height"] == 0

    def test_block_unblock_reserve_unreserve_preserve_slot_invariant(self, api):
        """PRD §2.7: "Slots in `OCCUPIED`, `BLOCKED`, or `RESERVED` status
        count toward `yard_slots_in_use`; slots in `EMPTY` status do not."

        Design: Difficulty/compensating_invariant/yard_slot_count_invariant_under_ground_and_void
        """
        terminal, slots = setup_terminal_with_slots(yard_slot_count=5, num_slots=2)
        tid = terminal["id"]
        slot_a, slot_b = slots

        baseline = get_terminal(tid)
        assert (baseline["yard_slots_in_use"], baseline["yard_slots_free"]) == (0, 5)

        validate_success(api.block_slot(tid, slot_a["id"], YP), 200)
        blocked = get_terminal(tid)
        assert_terminal_capacity_invariant(blocked)
        assert (blocked["yard_slots_in_use"], blocked["yard_slots_free"]) == (1, 4), (
            "A BLOCKED slot counts toward yard_slots_in_use")

        validate_success(api.unblock_slot(tid, slot_a["id"], YP), 200)
        restored = get_terminal(tid)
        assert (restored["yard_slots_in_use"], restored["yard_slots_free"]) == (0, 5), (
            "Unblock must compensate the block exactly")

        validate_success(api.reserve_slot(tid, slot_b["id"], YP), 200)
        reserved = get_terminal(tid)
        assert_terminal_capacity_invariant(reserved)
        assert (reserved["yard_slots_in_use"], reserved["yard_slots_free"]) == (1, 4), (
            "A RESERVED slot counts toward yard_slots_in_use")

        validate_success(api.unreserve_slot(tid, slot_b["id"], YP), 200)
        final = get_terminal(tid)
        assert (final["yard_slots_in_use"], final["yard_slots_free"]) == (0, 5)


class TestImmediateConsistency:
    def test_ground_is_immediately_visible(self, api):
        """PRD §3.3: "Grounding stamps `in_ground_at` with the current logical
        clock and derives `free_time_expires_at` as `in_ground_at` plus the
        terminal's `gate_free_hours`." and "The terminal's `yard_slots_in_use`
        rises by one, `yard_slots_free` falls by one, and posture is recomputed
        per §2.7."

        Design: Corner/consistency_model/immediate_consistency_on_ground
        """
        terminal, slots = setup_terminal_with_slots(yard_slot_count=20, num_slots=1)
        tid = terminal["id"]
        train = create_arrived_train(tid)
        container = register_container(tid, train["id"], "BMOU1234567")
        set_clock("2026-08-01T00:00:00Z")

        grounded = ground_container(tid, container["id"])
        assert grounded["status"] == "ON_GROUND", (
            "The ground response itself carries the updated container state")

        terminal_after = get_terminal(tid)
        assert terminal_after["yard_slots_in_use"] == 1
        assert terminal_after["yard_slots_free"] == 19

        container_after = get_container(tid, container["id"])
        assert container_after["status"] == "ON_GROUND"
        assert container_after["yard_slot_id"] == slots[0]["id"]
