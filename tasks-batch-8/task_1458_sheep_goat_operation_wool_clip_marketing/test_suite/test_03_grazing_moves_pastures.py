"""Grazing moves: overlap/capacity/priority, occupancy conservation, filters."""
from test_helpers import (
    ApiErrorId,
    assert_pasture,
    create_flock,
    create_move,
    create_pasture,
    set_clock,
    transition_move,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestPastureOverlapAndCapacity:

    def test_pasture_half_open_interval_allows_adjacency(self, api, range_hand_headers, ranch_manager_headers):
        """PRD §3.2: "the pasture overlap rule rejects the new move with
        `ERR_PASTURE_OVERLAP` (HTTP 409) when another move on the same pasture
        in `PLANNED` or `ACTIVE` status has its `move_start` strictly before
        the new move's `move_end` while the new move's `move_start` is strictly
        before that move's `move_end` — because intervals are half-open,
        back-to-back moves that merely touch at a boundary are allowed".

        Design: Difficulty/resource_temporal_overlap/pasture_half_open_interval_allows_adjacency
        """
        flock = create_flock(flock_name="HalfOpen Ranch", species="SHEEP", baseline_headcount=500)
        pasture = create_pasture(pasture_name="Section 12", acres=640.0, carrying_capacity_head=500)
        create_move(flock["id"], pasture_id=pasture["id"],
                    move_start="2026-09-01T00:00:00Z", move_end="2026-09-15T00:00:00Z",
                    head_count=80)

        # Overlapping [09-10, 09-20) vs existing [09-01, 09-15) -> rejected.
        resp = api.create_grazing_move({
            "flock_id": flock["id"], "pasture_id": pasture["id"],
            "move_start": "2026-09-10T00:00:00Z", "move_end": "2026-09-20T00:00:00Z",
            "head_count": 90,
        }, range_hand_headers)
        validate_error(resp, ApiErrorId.ERR_PASTURE_OVERLAP.value, expected_status=409)

        # Adjacent [09-15, 09-25) touching the other's move_end -> allowed.
        resp = api.create_grazing_move({
            "flock_id": flock["id"], "pasture_id": pasture["id"],
            "move_start": "2026-09-15T00:00:00Z", "move_end": "2026-09-25T00:00:00Z",
            "head_count": 70,
        }, range_hand_headers)
        move3 = validate_success(resp, expected_status=201)
        assert move3["move_status"] == "PLANNED"

        data, meta = validate_paginated(
            api.list_grazing_moves(ranch_manager_headers, params={"pasture_id": pasture["id"]}))
        assert meta["total_count"] == 2, "original + adjacent move only"

    def test_pasture_overlap_rejection_case(self, api, range_hand_headers):
        """PRD §3.2: "the pasture overlap rule rejects the new move with
        `ERR_PASTURE_OVERLAP` (HTTP 409) when another move on the same pasture
        in `PLANNED` or `ACTIVE` status has its `move_start` strictly before
        the new move's `move_end` while the new move's `move_start` is strictly
        before that move's `move_end`".

        Design: Difficulty/resource_temporal_overlap/pasture_half_open_interval_allows_adjacency
        """
        flock = create_flock(flock_name="HalfOpen2 Ranch", species="SHEEP", baseline_headcount=500)
        pasture = create_pasture(pasture_name="Section 13", acres=640.0, carrying_capacity_head=500)
        create_move(flock["id"], pasture_id=pasture["id"],
                    move_start="2026-09-01T00:00:00Z", move_end="2026-09-15T00:00:00Z",
                    head_count=80)
        resp = api.create_grazing_move({
            "flock_id": flock["id"], "pasture_id": pasture["id"],
            "move_start": "2026-09-14T00:00:00Z", "move_end": "2026-09-16T00:00:00Z",
            "head_count": 10,
        }, range_hand_headers)
        validate_error(resp, ApiErrorId.ERR_PASTURE_OVERLAP.value, expected_status=409)

    def test_pasture_overlap_temporal_beats_capacity_constraint(self, api, range_hand_headers, ranch_manager_headers):
        """PRD §2.8: "Every request passes through a fixed validation pipeline,
        and the first check that fails determines the error returned — a
        request that would fail several checks surfaces the earliest one, never
        a later one." Business temporal rules (item 8, pasture overlap) run
        before business constraint rules (item 9, pasture capacity).

        Design: Difficulty/priority_pair_validation_conflict/pasture_overlap_temporal_beats_capacity_constraint
        """
        flock = create_flock(flock_name="Overlap Ranch", species="SHEEP", baseline_headcount=500)
        pasture = create_pasture(pasture_name="Little Pasture", acres=40.0, carrying_capacity_head=100)
        create_move(flock["id"], pasture_id=pasture["id"],
                    move_start="2026-09-01T00:00:00Z", move_end="2026-09-15T00:00:00Z",
                    head_count=80)
        # This move BOTH overlaps the existing PLANNED move AND exceeds capacity (150 > 100).
        resp = api.create_grazing_move({
            "flock_id": flock["id"], "pasture_id": pasture["id"],
            "move_start": "2026-09-10T00:00:00Z", "move_end": "2026-09-20T00:00:00Z",
            "head_count": 150,
        }, range_hand_headers)
        validate_error(resp, ApiErrorId.ERR_PASTURE_OVERLAP.value, expected_status=409)
        data, meta = validate_paginated(
            api.list_grazing_moves(ranch_manager_headers, params={"pasture_id": pasture["id"]}))
        assert meta["total_count"] == 1, "only the original PLANNED move exists"

    def test_pasture_overlap_wins_over_capacity_reverse_dates(self, api, range_hand_headers):
        """PRD §2.8: "a request that would fail several checks surfaces the
        earliest one, never a later one." Overlap (business temporal, item 8)
        precedes capacity (business constraint, item 9).

        Design: Difficulty/priority_pair_validation_conflict/pasture_overlap_temporal_beats_capacity_constraint
        """
        flock = create_flock(flock_name="Overlap2 Ranch", species="SHEEP", baseline_headcount=2000)
        pasture = create_pasture(pasture_name="Tiny Trap", acres=40.0, carrying_capacity_head=100)
        create_move(flock["id"], pasture_id=pasture["id"],
                    move_start="2026-10-01T00:00:00Z", move_end="2026-10-15T00:00:00Z",
                    head_count=80)
        resp = api.create_grazing_move({
            "flock_id": flock["id"], "pasture_id": pasture["id"],
            "move_start": "2026-10-05T00:00:00Z", "move_end": "2026-10-20T00:00:00Z",
            "head_count": 200,
        }, range_hand_headers)
        validate_error(resp, ApiErrorId.ERR_PASTURE_OVERLAP.value, expected_status=409)

    def test_pasture_capacity_exceeded_standalone_rejected(self, api, range_hand_headers, ranch_manager_headers):
        """PRD §3.2: "the capacity rule rejects with `ERR_CAPACITY_EXCEEDED`
        (HTTP 422) when `head_count` exceeds the pasture's
        `carrying_capacity_head`."

        Design: Corner/validations/pasture_capacity_exceeded_standalone_rejected
        """
        flock = create_flock(flock_name="Cap Ranch", species="SHEEP", baseline_headcount=500)
        pasture = create_pasture(pasture_name="Small Trap", acres=30.0, carrying_capacity_head=100)
        resp = api.create_grazing_move({
            "flock_id": flock["id"], "pasture_id": pasture["id"],
            "move_start": "2026-09-01T00:00:00Z", "move_end": "2026-09-10T00:00:00Z",
            "head_count": 101,
        }, range_hand_headers)
        validate_error(resp, ApiErrorId.ERR_CAPACITY_EXCEEDED.value, expected_status=422)
        data, meta = validate_paginated(
            api.list_grazing_moves(ranch_manager_headers, params={"pasture_id": pasture["id"]}))
        assert meta["total_count"] == 0, "no move created on the pasture"


class TestPastureOccupancy:

    def test_pasture_occupancy_start_complete_conservation(self, api, range_hand_headers, ranch_manager_headers):
        """PRD §3.2: "Reading a pasture returns two computed values:
        `occupied_head_count`, the sum of `head_count` over that pasture's
        moves currently in `ACTIVE` status, and `pasture_status`, which reads
        `OCCUPIED` while that count is above zero; otherwise `RESTING` while at
        least one `COMPLETED` move exists and the logical clock has not yet
        reached the most recently completed move's `move_end` plus the
        pasture's `rest_days`".
        PRD §3.2: "Starting a move and later completing it returns
        `occupied_head_count` to exactly its pre-start value — occupancy is a
        compensating invariant, not a running estimate."

        Design: Difficulty/compensating_invariant/pasture_occupancy_start_complete_conservation
        """
        flock = create_flock(flock_name="Occupy Ranch", species="SHEEP", baseline_headcount=400)
        pasture = create_pasture(pasture_name="East Bench", acres=320.0,
                                 carrying_capacity_head=500, rest_days=21)
        before = validate_success(api.get_pasture(pasture["id"], ranch_manager_headers))
        assert before["occupied_head_count"] == 0
        assert before["pasture_status"] == "AVAILABLE"

        move = create_move(flock["id"], pasture_id=pasture["id"],
                           move_start="2026-09-01T00:00:00Z", move_end="2026-09-10T00:00:00Z",
                           head_count=250)
        set_clock("2026-09-03T00:00:00Z")
        transition_move(move["id"], "ACTIVE")
        during = validate_success(api.get_pasture(pasture["id"], ranch_manager_headers))
        assert during["occupied_head_count"] == 250
        assert during["pasture_status"] == "OCCUPIED"

        set_clock("2026-09-10T00:00:00Z")
        transition_move(move["id"], "COMPLETED")
        after = validate_success(api.get_pasture(pasture["id"], ranch_manager_headers))
        assert after["occupied_head_count"] == 0, "occupancy conserved across start+complete"
        # Clock 2026-09-10 < move_end 2026-09-10 + 21 rest days -> RESTING.
        assert after["pasture_status"] == "RESTING"

    def test_pasture_occupancy_available_initially_and_occupied_on_start(self, api, range_hand_headers, ranch_manager_headers):
        """PRD §3.2: "Reading a pasture returns two computed values:
        `occupied_head_count`, the sum of `head_count` over that pasture's
        moves currently in `ACTIVE` status, and `pasture_status`, which reads
        `OCCUPIED` while that count is above zero; otherwise `RESTING` while
        at least one `COMPLETED` move exists and the logical clock has not yet
        reached the most recently completed move's `move_end` plus the
        pasture's `rest_days` (when several moves tie on the latest
        `move_end`, the tie is broken by the latest `updated_at`); and
        `AVAILABLE` in every other case."

        Design: Difficulty/compensating_invariant/pasture_occupancy_start_complete_conservation
        """
        flock = create_flock(flock_name="Occupy2 Ranch", species="SHEEP", baseline_headcount=400)
        pasture = create_pasture(pasture_name="West Bench", acres=320.0,
                                 carrying_capacity_head=500, rest_days=21)
        initial = validate_success(api.get_pasture(pasture["id"], ranch_manager_headers))
        assert initial["pasture_status"] == "AVAILABLE"
        assert initial["occupied_head_count"] == 0

        move = create_move(flock["id"], pasture_id=pasture["id"],
                           move_start="2026-09-01T00:00:00Z", move_end="2026-09-10T00:00:00Z",
                           head_count=120)
        set_clock("2026-09-02T00:00:00Z")
        transition_move(move["id"], "ACTIVE")
        occupied = validate_success(api.get_pasture(pasture["id"], ranch_manager_headers))
        assert occupied["occupied_head_count"] == 120
        assert occupied["pasture_status"] == "OCCUPIED"


class TestMoveStateMachineAndFilters:

    def test_move_complete_from_planned_rejected(self, api, range_hand_headers, ranch_manager_headers):
        """PRD §3.2: "A move can be cancelled only from `PLANNED`, either
        explicitly by the manager or hand, or by the system cascades
        described in §3.7 and §3.8; any other transition attempt is rejected
        with `ERR_MOVE_INVALID_STATE` (HTTP 409)."
        PRD §2.9: "when no such transition exists from the entity's current
        state, the request is rejected with the entity's own invalid-state
        error (HTTP 409)".

        Design: Corner/state_machines/move_complete_from_planned_rejected
        """
        flock = create_flock(flock_name="Move Ranch", species="SHEEP", baseline_headcount=400)
        pasture = create_pasture(pasture_name="North Pivot", acres=200.0, carrying_capacity_head=400)
        move = create_move(flock["id"], pasture_id=pasture["id"],
                           move_start="2026-09-01T00:00:00Z", move_end="2026-09-10T00:00:00Z",
                           head_count=100)
        resp = api.transition_grazing_move(move["id"], {"to": "COMPLETED"}, range_hand_headers)
        validate_error(resp, ApiErrorId.ERR_MOVE_INVALID_STATE.value, expected_status=409)
        move = validate_success(api.get_grazing_move(move["id"], range_hand_headers))
        assert move["move_status"] == "PLANNED"
        pasture = validate_success(api.get_pasture(pasture["id"], ranch_manager_headers))
        assert pasture["occupied_head_count"] == 0

    def test_grazing_moves_filtered_list_reverse_reachability(self, api, ranch_manager_headers):
        """PRD §3.2: "Moves are listed with `limit` and `offset`, filterable by
        `flock_id`, `pasture_id`, `contract_id`, and `move_status`."

        Design: Corner/endpoints/grazing_moves_filtered_list_reverse_reachability
        """
        flock = create_flock(flock_name="Filter Ranch", species="SHEEP", baseline_headcount=500)
        p1 = create_pasture(pasture_name="P1", acres=100.0, carrying_capacity_head=500)
        p2 = create_pasture(pasture_name="P2", acres=100.0, carrying_capacity_head=500)
        create_move(flock["id"], pasture_id=p1["id"],
                    move_start="2026-09-01T00:00:00Z", move_end="2026-09-10T00:00:00Z", head_count=100)
        # Adjacent move on P1 is allowed under the half-open rule (PRD §3.2).
        create_move(flock["id"], pasture_id=p1["id"],
                    move_start="2026-09-10T00:00:00Z", move_end="2026-09-20T00:00:00Z", head_count=80)
        create_move(flock["id"], pasture_id=p2["id"],
                    move_start="2026-09-01T00:00:00Z", move_end="2026-09-10T00:00:00Z", head_count=50)

        _, meta_p1 = validate_paginated(
            api.list_grazing_moves(ranch_manager_headers, params={"pasture_id": p1["id"]}))
        assert meta_p1["total_count"] == 2
        _, meta_fl = validate_paginated(
            api.list_grazing_moves(ranch_manager_headers, params={"flock_id": flock["id"]}))
        assert meta_fl["total_count"] == 3
        _, meta_p2 = validate_paginated(
            api.list_grazing_moves(ranch_manager_headers, params={"pasture_id": p2["id"]}))
        assert meta_p2["total_count"] == 1

    def test_mutation_immediately_visible_in_response(self, api, range_hand_headers, ranch_manager_headers):
        """PRD §2.9: "The response of any mutation reflects the fully applied
        result, including all cascades, at once."
        PRD §1 (Introduction): "Every mutation is immediately visible in the
        response that performs it; there are no deferred or
        eventually-consistent reads anywhere in the system."

        Design: Corner/consistency_model/mutation_immediately_visible_in_response
        """
        flock = create_flock(flock_name="Imm Ranch", species="SHEEP", baseline_headcount=400)
        pasture = create_pasture(pasture_name="Home Field", acres=100.0, carrying_capacity_head=400)
        move = create_move(flock["id"], pasture_id=pasture["id"],
                           move_start="2026-09-01T00:00:00Z", move_end="2026-09-10T00:00:00Z",
                           head_count=100)
        v1 = move["version"]
        set_clock("2026-09-03T00:00:00Z")
        resp = api.transition_grazing_move(move["id"], {"to": "ACTIVE"}, range_hand_headers)
        body = validate_success(resp)
        assert body["move_status"] == "ACTIVE", "transition response carries the new state"
        assert body["version"] == v1 + 1, "transition response carries the incremented version"

        fetched = validate_success(api.get_grazing_move(move["id"], range_hand_headers))
        assert fetched["move_status"] == "ACTIVE"
        pasture = validate_success(api.get_pasture(pasture["id"], ranch_manager_headers))
        assert pasture["occupied_head_count"] == 100
        assert pasture["pasture_status"] == "OCCUPIED"
