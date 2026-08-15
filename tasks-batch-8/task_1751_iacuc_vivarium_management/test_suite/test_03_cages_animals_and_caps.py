"""Cage and animal operations: justified-ceiling boundary, protocol-approval
gate on admission, population conservation under transfer, and cage
decommission preconditions (PRD §3.4).
"""
from test_helpers import (
    ADMIN,
    FACILITY,
    STAFF,
    ApiErrorId,
    api_client,
    assert_animal,
    assert_cage,
    create_draft_protocol,
    get_success_data,
    setup_approved_with_cage,
    setup_occupied_cage,
    validate_error,
    validate_success,
)
from test_helpers.factories import create_animal_payload
from test_helpers.fixtures import add_cage, add_mouse, record_dmr_decision, submit_protocol


class TestAnimalCapBoundary:
    def test_animal_at_exact_max_succeeds_then_one_more_rejected(self, api):
        """PRD §3.4: "The ceiling rule counts `animals_used_count`, the number
        of animals on the protocol excluding only those `TRANSFERRED_OUT`, and
        its boundary is inclusive: once the count equals
        `max_animals_justified`, one more animal is refused with
        `ERR_ANIMAL_CAP_EXCEEDED` (HTTP 422)."

        Design: Difficulty/boundary_precision_check/animal_cap_at_exact_max
        """
        scenario = setup_approved_with_cage(max_animals=2, capacity_adults=5)
        cage_id = scenario["cage"]["id"]
        proto_id = scenario["protocol"]["id"]

        first = validate_success(api_client.create_animal(
            create_animal_payload(cage_id, proto_id), STAFF,
        ), expected_status=201)
        assert_animal(first)
        second = validate_success(api_client.create_animal(
            create_animal_payload(cage_id, proto_id), STAFF,
        ), expected_status=201)
        assert second["status"] == "ALIVE", "the second animal (count 1->2) succeeds"

        resp = api_client.create_animal(
            create_animal_payload(cage_id, proto_id), STAFF,
        )
        validate_error(resp, ApiErrorId.ERR_ANIMAL_CAP_EXCEEDED)

        protocol = get_success_data(api_client.get_protocol(proto_id, ADMIN))
        assert protocol["animals_used_count"] == 2, (
            "animals_used_count remains at the cap after the rejection"
        )

    def test_transfer_out_reopens_justified_slot(self, api):
        """PRD §3.4: "Transfer-out moves an animal from `ALIVE` to
        `TRANSFERRED_OUT` and recomputes the protocol's `animals_used_count`
        downward, since transferred-out animals leave the justified-count
        tally." and "The ceiling rule counts `animals_used_count`, the number
        of animals on the protocol excluding only those `TRANSFERRED_OUT`".

        Design: Difficulty/boundary_precision_check/animal_cap_at_exact_max
        """
        scenario = setup_occupied_cage(num_animals=2, max_animals=2,
                                       capacity_adults=5)
        proto_id = scenario["protocol"]["id"]
        cage_id = scenario["cage"]["id"]

        protocol = get_success_data(api_client.get_protocol(proto_id, ADMIN))
        assert protocol["animals_used_count"] == 2

        moved = validate_success(
            api_client.transfer_out_animal(scenario["animals"][0]["id"], STAFF)
        )
        assert moved["status"] == "TRANSFERRED_OUT"

        protocol = get_success_data(api_client.get_protocol(proto_id, ADMIN))
        assert protocol["animals_used_count"] == 1, (
            "transferred-out animals leave the justified-count tally"
        )

        refill = validate_success(api_client.create_animal(
            create_animal_payload(cage_id, proto_id), STAFF,
        ), expected_status=201)
        assert refill["status"] == "ALIVE"
        protocol = get_success_data(api_client.get_protocol(proto_id, ADMIN))
        assert protocol["animals_used_count"] == 2


class TestProtocolApprovalGate:
    def test_animal_add_rejected_in_review_then_succeeds_after_approval(self, api):
        """PRD §3.4: "A protocol that is not `APPROVED` refuses admission with
        `ERR_PROTOCOL_NOT_APPROVED` (HTTP 409)." and "Placing the first animal
        into an `EMPTY` cage flips it to `OCCUPIED` and requires that the
        cage's protocol and species match the animal's".

        Design: Difficulty/cross_entity_state_dependency/animal_add_gated_by_protocol_approved
        """
        scenario = create_draft_protocol(species="MOUSE", max_animals=5)
        proto_id = scenario["protocol"]["id"]
        submit_protocol(proto_id, scenario["investigator"]["id"])
        cage = add_cage(proto_id, species="MOUSE", capacity_adults=5)

        resp = api_client.create_animal(
            create_animal_payload(cage["id"], proto_id, animal_tag="G-1"), STAFF,
        )
        validate_error(resp, ApiErrorId.ERR_PROTOCOL_NOT_APPROVED)

        approved = record_dmr_decision(proto_id, "APPROVE")
        assert approved["status"] == "APPROVED"

        placed = validate_success(api_client.create_animal(
            create_animal_payload(cage["id"], proto_id, animal_tag="G-1"), STAFF,
        ), expected_status=201)
        assert_animal(placed)
        cage_after = get_success_data(api_client.get_cage(cage["id"], FACILITY))
        assert_cage(cage_after)
        assert cage_after["status"] == "OCCUPIED", (
            "placing the first animal flips the EMPTY cage to OCCUPIED"
        )

    def test_animal_add_rejected_while_protocol_in_draft(self, api):
        """PRD §3.4: "A protocol that is not `APPROVED` refuses admission with
        `ERR_PROTOCOL_NOT_APPROVED` (HTTP 409)."

        Design: Difficulty/cross_entity_state_dependency/animal_add_gated_by_protocol_approved
        """
        scenario = create_draft_protocol(species="MOUSE", max_animals=5)
        proto_id = scenario["protocol"]["id"]
        cage = add_cage(proto_id, species="MOUSE", capacity_adults=5)

        resp = api_client.create_animal(
            create_animal_payload(cage["id"], proto_id), STAFF,
        )
        validate_error(resp, ApiErrorId.ERR_PROTOCOL_NOT_APPROVED)

        animals = get_success_data(api_client.list_protocol_animals(proto_id, ADMIN))
        assert animals == []


class TestPopulationConservation:
    def test_transfer_conserves_population_across_cages(self, api):
        """PRD §3.4: "A cage-to-cage transfer keeps the animal `ALIVE` and
        reassigns its `cage_id` to the `target_cage_id` in the request" and
        the justified count "excluding only those `TRANSFERRED_OUT`" — a
        transfer between cages changes no tallies.

        Design: Difficulty/compensating_invariant/cage_occupancy_conserved_across_transfer
        """
        scenario = setup_approved_with_cage(max_animals=10, capacity_adults=5)
        proto_id = scenario["protocol"]["id"]
        cage_a = scenario["cage"]
        cage_b = add_cage(proto_id, species="MOUSE", capacity_adults=5,
                          room_code=cage_a["room_code"])
        a1 = add_mouse(cage_a["id"], proto_id)
        a2 = add_mouse(cage_a["id"], proto_id)

        moved = validate_success(api_client.transfer_animal(
            a1["id"], {"target_cage_id": cage_b["id"]}, STAFF,
        ))
        assert moved["status"] == "ALIVE"
        assert moved["cage_id"] == cage_b["id"]

        protocol = get_success_data(api_client.get_protocol(proto_id, ADMIN))
        assert protocol["animals_used_count"] == 2, (
            "transfer conserves the protocol population tally"
        )
        in_a = get_success_data(api_client.list_cage_animals(cage_a["id"], STAFF))
        in_b = get_success_data(api_client.list_cage_animals(cage_b["id"], STAFF))
        alive_a = [x for x in in_a if x["status"] == "ALIVE"]
        alive_b = [x for x in in_b if x["status"] == "ALIVE"]
        assert len(alive_a) == 1 and alive_a[0]["id"] == a2["id"]
        assert len(alive_b) == 1 and alive_b[0]["id"] == a1["id"]
        assert len(alive_a) + len(alive_b) == 2, (
            "total ALIVE count across both cages is invariant under transfer"
        )

    def test_retire_keeps_count_but_transfer_out_decrements(self, api):
        """PRD §3.4: "Retirement and euthanasia recompute the housing cage's
        occupancy but leave `animals_used_count` untouched, because only
        `TRANSFERRED_OUT` animals exit that count."

        Design: Difficulty/compensating_invariant/cage_occupancy_conserved_across_transfer
        """
        scenario = setup_approved_with_cage(max_animals=10, capacity_adults=5)
        proto_id = scenario["protocol"]["id"]
        cage_a = scenario["cage"]
        cage_b = add_cage(proto_id, species="MOUSE", capacity_adults=5,
                          room_code=cage_a["room_code"])
        a1 = add_mouse(cage_a["id"], proto_id)
        a2 = add_mouse(cage_a["id"], proto_id)
        validate_success(api_client.transfer_animal(
            a1["id"], {"target_cage_id": cage_b["id"]}, STAFF,
        ))

        retired = validate_success(api_client.retire_animal(a1["id"], STAFF))
        assert retired["status"] == "RETIRED"
        protocol = get_success_data(api_client.get_protocol(proto_id, ADMIN))
        assert protocol["animals_used_count"] == 2, (
            "RETIRED animals still count toward the justified ceiling"
        )
        in_b = get_success_data(api_client.list_cage_animals(cage_b["id"], STAFF))
        assert [x["id"] for x in in_b if x["status"] == "ALIVE"] == [], (
            "the retired animal no longer reads ALIVE in its cage"
        )

        out = validate_success(api_client.transfer_out_animal(a2["id"], STAFF))
        assert out["status"] == "TRANSFERRED_OUT"
        protocol = get_success_data(api_client.get_protocol(proto_id, ADMIN))
        assert protocol["animals_used_count"] == 1, (
            "only TRANSFERRED_OUT animals exit the count"
        )


class TestCageDecommission:
    def test_decommission_only_from_empty(self, api):
        """PRD §3.4: "A manager may decommission a cage that stands `EMPTY`,
        moving it to `DECOMMISSIONED` — terminal — after which the cage is
        excluded from all future census and billing activity." PRD §2.8:
        "State legality — the target resource is in a state from which the
        requested transition exists (`ERR_INVALID_STATE`, 409)."

        Design: Corner/state_machines/cage_decommission_only_from_empty
        """
        scenario = setup_occupied_cage(num_animals=1)
        occupied = scenario["cage"]
        empty = add_cage(scenario["protocol"]["id"], species="MOUSE",
                         capacity_adults=5, room_code=occupied["room_code"])

        resp = api_client.decommission_cage(occupied["id"], FACILITY)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

        done = validate_success(api_client.decommission_cage(empty["id"], FACILITY))
        assert done["status"] == "DECOMMISSIONED"
