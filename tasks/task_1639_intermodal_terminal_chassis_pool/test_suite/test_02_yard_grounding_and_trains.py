"""Yard-slot selection, container grounding preconditions, and train lifecycle
(PRD §3.2, §3.3)."""
from test_helpers import (
    ApiErrorId,
    assert_container,
    assert_train,
    create_arrived_train,
    create_slot,
    create_terminal,
    create_train,
    get_container,
    get_slot,
    get_terminal,
    get_train,
    ground_container,
    register_container,
    set_clock,
    setup_full_terminal,
    setup_grounded_container,
    setup_terminal_with_slots,
    TEST_USERS,
    validate_error,
    validate_success,
)

TM = TEST_USERS["terminal_manager_headers"]
YP = TEST_USERS["yard_planner_headers"]
RC = TEST_USERS["rail_coordinator_headers"]


class TestYardSlotSelector:
    def test_selector_orders_by_row_then_slot_code(self, api):
        """PRD §3.3: "Otherwise the chosen slot is the first candidate ordered
        by `row` ascending, then `slot_code` ascending, then the slot's
        `created_at` ascending; ties cannot occur because `slot_code` is
        unique per terminal."

        Slots are created out of order (B-01-1, A-02-1, A-01-1); the selector
        must land on A-01-1.

        Design: Corner/calculations/yard_slot_selector_row_then_slot_code_then_created_at
        """
        terminal = create_terminal()
        tid = terminal["id"]
        create_slot(tid, slot_code="B-01-1", row="B")
        create_slot(tid, slot_code="A-02-1", row="A")
        expected = create_slot(tid, slot_code="A-01-1", row="A")
        train = create_arrived_train(tid)
        container = register_container(tid, train["id"])
        set_clock("2026-08-01T00:00:00Z")

        grounded = ground_container(tid, container["id"])
        assert grounded["status"] == "ON_GROUND"
        assert grounded["yard_slot_id"] == expected["id"], (
            f"Selector must pick row A / slot_code A-01-1 over A-02-1 and B-01-1; "
            f"got slot {grounded['yard_slot_id']}, expected {expected['id']}")


class TestYardSlotBlockCycle:
    def test_block_then_unblock_returns_slot_to_empty(self, api):
        """PRD §3.3: "From `EMPTY` a slot may be blocked (to `BLOCKED`) or
        reserved (to `RESERVED`); a `BLOCKED` slot may be unblocked back to
        `EMPTY`, and a `RESERVED` slot may be unreserved back to `EMPTY`."

        Design: Corner/endpoints/yard_slot_block_unblock_cycle
        """
        terminal, slots = setup_terminal_with_slots(yard_slot_count=5, num_slots=1)
        tid, sid = terminal["id"], slots[0]["id"]

        blocked = validate_success(api.block_slot(tid, sid, YP), 200)
        assert blocked["status"] == "BLOCKED"

        unblocked = validate_success(api.unblock_slot(tid, sid, YP), 200)
        assert unblocked["status"] == "EMPTY"
        assert get_slot(tid, sid)["status"] == "EMPTY"

    def test_block_on_blocked_slot_rejected(self, api):
        """PRD §3.3: "Each of these transitions requires the slot to be in
        exactly the named prior state, else `ERR_INVALID_STATE`."

        Design: Corner/endpoints/yard_slot_block_unblock_cycle
        """
        terminal, slots = setup_terminal_with_slots(yard_slot_count=5, num_slots=1)
        tid, sid = terminal["id"], slots[0]["id"]
        validate_success(api.block_slot(tid, sid, YP), 200)

        resp = api.block_slot(tid, sid, YP)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)


class TestGroundingPreconditions:
    def test_ground_rejected_until_train_arrives(self, api):
        """PRD §3.3: "Grounding is legal only when the container is
        `INBOUND_TRAIN`, its planned train is `ARRIVED` (otherwise
        `ERR_TRAIN_NOT_ARRIVED`), the terminal posture is not `CLOSED`
        (otherwise `ERR_TERMINAL_CLOSED`), and the yard-slot selector finds a
        home for the box (otherwise `ERR_NO_YARD_SLOT_AVAILABLE`)."

        Design: Difficulty/cross_entity_state_dependency/container_ground_depends_on_train_arrived
        """
        terminal, slots = setup_terminal_with_slots(yard_slot_count=20, num_slots=1)
        tid = terminal["id"]
        train = create_train(tid)  # stays SCHEDULED
        container = register_container(tid, train["id"])
        set_clock("2026-08-01T00:00:00Z")
        version = get_terminal(tid)["version"]

        resp = api.ground_container(
            tid, container["id"], {"expected_terminal_version": version}, YP)
        validate_error(resp, ApiErrorId.ERR_TRAIN_NOT_ARRIVED)
        assert get_container(tid, container["id"])["status"] == "INBOUND_TRAIN"

    def test_ground_succeeds_once_train_arrived(self, api):
        """PRD §3.3: "Grounding stamps `in_ground_at` with the current logical
        clock and derives `free_time_expires_at` as `in_ground_at` plus the
        terminal's `gate_free_hours`."

        Design: Difficulty/cross_entity_state_dependency/container_ground_depends_on_train_arrived
        """
        ctx = setup_grounded_container(
            gate_free_hours=48, ground_clock="2026-08-01T00:00:00Z")
        container = ctx["container"]
        assert_container(container)
        assert container["status"] == "ON_GROUND"
        assert container["in_ground_at"] == "2026-08-01T00:00:00Z"
        assert container["free_time_expires_at"] == "2026-08-03T00:00:00Z", (
            "free_time_expires_at = in_ground_at + 48 gate_free_hours")
        assert container["stack_height"] == 1

    def test_ground_on_voided_container_rejected(self, api):
        """PRD §3.3: "Grounding is legal only when the container is
        `INBOUND_TRAIN`, its planned train is `ARRIVED` (otherwise
        `ERR_TRAIN_NOT_ARRIVED`), the terminal posture is not `CLOSED`
        (otherwise `ERR_TERMINAL_CLOSED`), and the yard-slot selector finds a
        home for the box (otherwise `ERR_NO_YARD_SLOT_AVAILABLE`)."

        Design: Corner/state_machines/container_terminal_voided_lockdown
        """
        ctx = setup_grounded_container()
        tid = ctx["terminal"]["id"]
        container = ctx["container"]
        validate_success(api.void_container(tid, container["id"], TM), 200)
        assert get_container(tid, container["id"])["status"] == "VOIDED"

        version = get_terminal(tid)["version"]
        resp = api.ground_container(
            tid, container["id"], {"expected_terminal_version": version}, YP)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)


class TestYardCapacityFailures:
    def test_ground_into_full_yard_rejected_terminal_closed(self, api):
        """PRD §2.7: "A `CLOSED` posture blocks two operations outright:
        grounding a container and completing an inbound gate transaction both
        fail with `ERR_TERMINAL_CLOSED` (HTTP 409)."
        PRD §2.11: "11. Terminal capacity — the posture is not `CLOSED` for
        grounding or inbound completion, else `ERR_TERMINAL_CLOSED`." and
        "12. Yard-slot availability — the slot selector finds an eligible slot,
        else `ERR_NO_YARD_SLOT_AVAILABLE`."

        With yard_slot_count=1 and its only slot occupied, the posture is
        CLOSED; the capacity check (earlier in the fixed sequence) masks the
        selector check.

        Design: Difficulty/resource_temporal_overlap/yard_slot_single_occupancy_aggregate_capacity
        """
        ctx = setup_full_terminal(yard_slot_count=1)
        tid = ctx["terminal"]["id"]
        spare = ctx["spare_container"]
        version = get_terminal(tid)["version"]

        resp = api.ground_container(
            tid, spare["id"], {"expected_terminal_version": version}, YP)
        validate_error(resp, ApiErrorId.ERR_TERMINAL_CLOSED)
        assert get_container(tid, spare["id"])["status"] == "INBOUND_TRAIN"

    def test_ground_with_no_eligible_slot_rejected(self, api):
        """PRD §3.3: "Eligible candidates are yard slots belonging to this
        terminal whose status is `EMPTY` or `RESERVED` and whose `tier_max` is
        at least one — the slot must accept at least one container. If no
        candidate exists the grounding fails." and "the yard-slot selector
        finds a home for the box (otherwise `ERR_NO_YARD_SLOT_AVAILABLE`)."

        The only slot is BLOCKED (posture stays OPEN because
        yard_slot_count=5 leaves four units free), so the selector — not the
        posture check — produces the failure.

        Design: Difficulty/resource_temporal_overlap/yard_slot_single_occupancy_aggregate_capacity
        """
        terminal, slots = setup_terminal_with_slots(yard_slot_count=5, num_slots=1)
        tid = terminal["id"]
        validate_success(api.block_slot(tid, slots[0]["id"], YP), 200)
        train = create_arrived_train(tid)
        container = register_container(tid, train["id"])
        set_clock("2026-08-01T00:00:00Z")
        assert get_terminal(tid)["posture"] == "OPEN"
        version = get_terminal(tid)["version"]

        resp = api.ground_container(
            tid, container["id"], {"expected_terminal_version": version}, YP)
        validate_error(resp, ApiErrorId.ERR_NO_YARD_SLOT_AVAILABLE)


class TestContainerRegistrationValidation:
    def test_container_missing_container_number_rejected(self, api):
        """PRD §3.2: "The same role registers inbound containers against a
        scheduled train with a payload carrying the `container_number` (an ISO
        6346 identifier), the `iso_type` — one of `20FT`, `40FT`, `40HC`, or
        `45FT` — and the `planned_train_id`."
        PRD §2.11: "18. Payload shape — required fields are present, enums are
        valid, datetimes are ISO 8601, and integers are positive where
        required, else `ERR_INVALID_REQUEST`."

        Design: Corner/entities/container_missing_required_field_returns_invalid_request
        """
        terminal = create_terminal()
        tid = terminal["id"]
        train = create_train(tid)

        resp = api.create_container(
            tid, {"iso_type": "40FT", "planned_train_id": train["id"]}, RC)
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)

    def test_container_invalid_iso_type_rejected(self, api):
        """PRD §3.2: "the `iso_type` — one of `20FT`, `40FT`, `40HC`, or
        `45FT`" and PRD §2.11: "18. Payload shape — required fields are
        present, enums are valid, datetimes are ISO 8601, and integers are
        positive where required, else `ERR_INVALID_REQUEST`."

        Design: Corner/entities/container_invalid_enum_returns_invalid_request
        """
        terminal = create_terminal()
        tid = terminal["id"]
        train = create_train(tid)

        resp = api.create_container(
            tid,
            {"container_number": "BMOU1234567", "iso_type": "60FT",
             "planned_train_id": train["id"]},
            RC,
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)


class TestTrainLifecycleAndContainerCascade:
    def test_departure_voids_still_inbound_containers_only(self, api):
        """PRD §3.2: "Departure stamps `actual_departure_utc` with the current
        logical clock and has two cleanup effects: any container still
        `INBOUND_TRAIN` on that train transitions to `VOIDED` with no yard-slot
        side effects (it never touched the ground), and any `OPEN` billing
        ledger entries for per-diem or storage on those departed-train
        containers are `WAIVED` — no charges accrue against a departed train."

        Design: Difficulty/non_linear_state_machine/container_branching_void_vs_depart
        """
        ctx = setup_grounded_container()
        tid = ctx["terminal"]["id"]
        train = ctx["train"]
        grounded_container = ctx["container"]
        still_inbound = register_container(tid, train["id"], "C0000000002")

        validate_success(api.begin_train_loading(tid, train["id"], RC), 200)
        departed = validate_success(api.mark_train_departed(tid, train["id"], RC), 200)
        assert_train(departed)
        assert departed["status"] == "DEPARTED"
        assert departed["actual_departure_utc"] is not None

        assert get_container(tid, grounded_container["id"])["status"] == "ON_GROUND", (
            "A container already grounded before departure is not cascaded to VOIDED")
        assert get_container(tid, still_inbound["id"])["status"] == "VOIDED", (
            "A container still INBOUND_TRAIN at departure must be VOIDED")

    def test_cancel_voids_inbound_containers(self, api):
        """PRD §3.2: "A train in `SCHEDULED` or `ARRIVED` may instead be
        cancelled, becoming `CANCELLED`; cancellation likewise voids every
        container still `INBOUND_TRAIN` on it."

        Design: Difficulty/non_linear_state_machine/container_branching_void_vs_depart
        """
        terminal, slots = setup_terminal_with_slots(yard_slot_count=20, num_slots=1)
        tid = terminal["id"]
        train = create_arrived_train(tid)
        container = register_container(tid, train["id"])

        cancelled = validate_success(api.cancel_train(tid, train["id"], RC), 200)
        assert cancelled["status"] == "CANCELLED"
        assert get_container(tid, container["id"])["status"] == "VOIDED"

    def test_train_departed_rejects_further_transitions(self, api):
        """PRD §3.2: "Trains advance through `SCHEDULED` → `ARRIVED` →
        `LOADING` → `DEPARTED`, each step driven by the `RailCoordinator`:
        marking arrived requires the train be `SCHEDULED`, beginning loading
        requires `ARRIVED`, and marking departed requires `LOADING`."

        Design: Corner/state_machines/train_terminal_lockdown_departed
        """
        terminal = create_terminal()
        tid = terminal["id"]
        train = create_train(tid)
        validate_success(api.mark_train_arrived(tid, train["id"], RC), 200)
        validate_success(api.begin_train_loading(tid, train["id"], RC), 200)
        validate_success(api.mark_train_departed(tid, train["id"], RC), 200)
        assert get_train(tid, train["id"])["status"] == "DEPARTED"

        resp = api.mark_train_arrived(tid, train["id"], RC)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
