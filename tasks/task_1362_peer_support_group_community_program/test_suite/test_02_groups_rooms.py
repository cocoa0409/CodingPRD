"""PeerGroup lifecycle and modality-aware session capacity (PRD §3.1, §3.5)."""
from test_helpers import (
    ADMIN,
    ApiErrorId,
    assert_peer_group,
    make_active_group,
    make_group,
    make_program,
    make_room,
    make_session,
    reset_clock,
    setup_certified_facilitator,
    setup_program_with_active_group,
    validate_error,
    validate_success,
)


class TestRoomValidation:
    def test_room_capacity_zero_rejected(self, api):
        """PRD §3.1: "Each room is created with a `name` unique across the
        whole system and a `physical_capacity` that must be at least 1; a
        capacity below 1 is rejected with `ERR_INVALID_CAPACITY` (HTTP 422)."

        Design: Corner/entities/room_capacity_zero_rejected
        """
        reset_clock()
        resp = api.create_room({"name": "Bad", "physical_capacity": 0}, ADMIN)
        validate_error(resp, ApiErrorId.ERR_INVALID_CAPACITY)


class TestPeerGroupLifecycle:
    def test_retired_group_rejects_further_transitions(self, api):
        """PRD §3.1: "Retirement is terminal: a group in `ACTIVE` or `PAUSED`
        may move to `RETIRED` only when no session under it is `SCHEDULED` or
        `IN_PROGRESS` and no enrollment under it is `RESERVED` or `CONFIRMED`"
        PRD §3.1: "Attempting any of these transitions from a state that does
        not permit it is rejected with `ERR_INVALID_STATE`."

        Design: Corner/state_machines/peer_group_terminal_retired_no_further_transitions
        """
        program = make_program(name="P")
        group = make_active_group(program["id"], modality="VIRTUAL", base_capacity=5)
        retired = validate_success(api.retire_group(program["id"], group["id"], ADMIN))
        assert retired["status"] == "RETIRED"

        resp = api.pause_group(program["id"], group["id"], ADMIN)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
        after = validate_success(api.get_group(program["id"], group["id"], ADMIN))
        assert after["status"] == "RETIRED", "RETIRED is terminal; status must be unchanged"


class TestSessionCapacityFormula:
    def test_hybrid_and_virtual_effective_capacity(self, api):
        """PRD §3.5: "For a `VIRTUAL` group it equals the group's
        `base_capacity`."
        PRD §3.5: "For a `HYBRID` group, the in-person seats are a
        sub-allocation equal to the smaller of the room's `physical_capacity`
        and half of `base_capacity` rounded up to a whole number; the virtual
        seats are whatever remains of `base_capacity` after removing the
        in-person seats; and `effective_capacity` is the sum of the two — which
        equals `base_capacity`, though the in-person sub-allocation binds
        separately at check-in time."

        Design: Difficulty/combinatorial_formula/session_capacity_formula_mode_a_hybrid_split
        """
        reset_clock()
        program = make_program(name="P")
        room = make_room(name="SmallRoom", physical_capacity=2)
        group_h = make_active_group(
            program["id"], name="GH", modality="HYBRID", base_capacity=7)
        group_v = make_active_group(
            program["id"], name="GV", modality="VIRTUAL", base_capacity=7)
        fac = setup_certified_facilitator()

        session_h = make_session(
            program["id"], group_h["id"], fac.facilitator["id"],
            start_at="2026-08-03T10:00:00Z", end_at="2026-08-03T11:00:00Z",
            room_id=room["id"])
        # in_person = min(2, ceil(7 * 0.5)) = min(2, 4) = 2; virtual = 7 - 2 = 5
        assert session_h["effective_capacity"] == 7, (
            f"HYBRID base 7 with room capacity 2 must yield effective_capacity 7 "
            f"(2 in-person + 5 virtual), got {session_h['effective_capacity']}")

        session_v = make_session(
            program["id"], group_v["id"], fac.facilitator["id"],
            start_at="2026-08-04T10:00:00Z", end_at="2026-08-04T11:00:00Z")
        assert session_v["effective_capacity"] == 7, (
            f"VIRTUAL effective_capacity must equal base_capacity 7, got {session_v['effective_capacity']}")

    def test_in_person_capacity_is_min_of_base_and_room(self, api):
        """PRD §3.5: "For an `IN_PERSON` group it is the smaller of
        `base_capacity` and the assigned room's `physical_capacity`."

        Design: Difficulty/combinatorial_formula/session_capacity_formula_mode_a_hybrid_split
        """
        reset_clock()
        program = make_program(name="P")
        room_big = make_room(name="BigRoom", physical_capacity=10)
        room_small = make_room(name="TinyRoom", physical_capacity=3)
        group = make_active_group(
            program["id"], name="GIP", modality="IN_PERSON", base_capacity=8)
        fac = setup_certified_facilitator()

        session_big = make_session(
            program["id"], group["id"], fac.facilitator["id"],
            start_at="2026-08-03T10:00:00Z", end_at="2026-08-03T11:00:00Z",
            room_id=room_big["id"])
        assert session_big["effective_capacity"] == 8, (
            f"min(base 8, room 10) must be 8, got {session_big['effective_capacity']}")

        session_small = make_session(
            program["id"], group["id"], fac.facilitator["id"],
            start_at="2026-08-04T10:00:00Z", end_at="2026-08-04T11:00:00Z",
            room_id=room_small["id"])
        assert session_small["effective_capacity"] == 3, (
            f"min(base 8, room 3) must be 3, got {session_small['effective_capacity']}")
