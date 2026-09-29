"""Two transitions a block cannot make on its own state alone: signing depends on
the property's standing, opening depends on a sub-block's approval."""

from test_helpers import (
    CONTROLLER,
    COORDINATOR,
    TEST_DEFAULTS,
    approve_sub_block,
    assemble_block,
    contract_block,
    contract_block_payload,
    make_hotel_manager_headers,
    open_block,
    read_block,
    register_event,
    register_hotel,
    set_hotel_standing,
    setup_housing_program,
    submit_terms,
    validate_error,
    validate_success,
)

VIP_CARVE = [{"segment": "VIP", "allotted_rooms": 4, "eligibility_code": "VIP-GOLD"}]


def _block_awaiting_signature(hotel_overrides=None):
    """Event, hotel and a block sitting in TERMS_SUBMITTED."""
    event = register_event()
    hotel = register_hotel(**(hotel_overrides or {}))
    block = submit_terms(assemble_block(event["id"], hotel["id"]))
    return event, hotel, block


class TestContractGatedOnHotelStanding:
    """The signature reads the hotel's standing, not the block's status."""

    def test_suspended_property_cannot_sign_and_the_block_does_not_move(self, api):
        """PRD §3.2: "The transition `TERMS_SUBMITTED → CONTRACTED` succeeds only
        when the property's `standing` is `ACTIVE` — otherwise
        `ERR_HOTEL_SUSPENDED`"
        PRD §3.1: "Only an `ACTIVE` property may sign a block contract, which is
        why suspension is the bureau's lever of last resort mid-negotiation."

        Design: Difficulty/cross_entity_state_dependency/block_contract_blocked_by_suspended_hotel_standing
        """
        event, hotel, block = _block_awaiting_signature()
        suspended = set_hotel_standing(hotel["id"], "SUSPENDED")
        assert suspended["standing"] == "SUSPENDED"
        assert suspended["version"] > hotel["version"]

        response = api.contract_hotel_block(
            block["id"],
            contract_block_payload(confirmation_number="CN-SUM26-005"),
            make_hotel_manager_headers(hotel["id"]),
        )
        validate_error(response, "ERR_HOTEL_SUSPENDED", 409)

        after = read_block(block["id"])
        assert after["status"] == "TERMS_SUBMITTED"
        assert after["version"] == block["version"]
        assert after["confirmation_number"] is None
        assert after["unassigned_rooms_per_night"] == 0

    def test_reinstating_the_property_lets_the_same_block_sign(self, api):
        """PRD §3.1: "A `BureauCoordinator` may later suspend or reinstate a
        property by submitting a new `standing`, which bumps the hotel's
        `version`; the property list can be filtered by `standing`."
        PRD §3.2: "On success the server snapshots
        `original_contracted_rooms_per_night` from the current
        `contracted_rooms_per_night`, initialises `unassigned_rooms_per_night` to
        that same figure so the whole block is available to carve, recomputes the
        event's `total_contracted_room_nights` and `housing_posture`, and bumps
        the block's `version`."

        Design: Difficulty/cross_entity_state_dependency/block_contract_blocked_by_suspended_hotel_standing
        """
        event, hotel, block = _block_awaiting_signature()
        set_hotel_standing(hotel["id"], "SUSPENDED")
        validate_error(
            api.contract_hotel_block(
                block["id"],
                contract_block_payload(confirmation_number="CN-SUM26-005"),
                make_hotel_manager_headers(hotel["id"]),
            ),
            "ERR_HOTEL_SUSPENDED",
            409,
        )

        reinstated = set_hotel_standing(hotel["id"], "ACTIVE")
        assert reinstated["standing"] == "ACTIVE"

        signed = contract_block(
            block["id"], hotel["id"], confirmation_number="CN-SUM26-005"
        )
        assert signed["status"] == "CONTRACTED"
        assert signed["confirmation_number"] == "CN-SUM26-005"
        assert signed["original_contracted_rooms_per_night"] == 10
        assert signed["unassigned_rooms_per_night"] == 10

        event_after = validate_success(api.get_event(event["id"], COORDINATOR))
        assert event_after["total_contracted_room_nights"] == 40
        assert event_after["housing_posture"] == "PLANNING"


class TestOpenGatedOnSubBlockApproval:
    """A block with only a pending carve has nothing bookable, so it cannot open."""

    def test_open_is_refused_while_the_only_carve_awaits_the_controller(self, api):
        """PRD §3.4: "At least one sub-block of the block must already be in
        `APPROVED`, since an open block with nothing bookable is a support ticket
        waiting to happen; otherwise the request is rejected with
        `ERR_NO_APPROVED_SUB_BLOCK`."
        PRD §3.3: "Every other segment is created with `approval_status`
        `PENDING_APPROVAL` and waits for a `BureauController`."

        Design: Difficulty/cross_entity_state_dependency/block_open_gated_on_sub_block_approval_state
        """
        ctx = setup_housing_program(
            carves=VIP_CARVE, confirmation_number="CN-SUM26-006"
        )
        sub_block = ctx["sub_blocks"][0]
        assert sub_block["approval_status"] == "PENDING_APPROVAL"
        assert sub_block["allotted_rooms"] == 4

        response = api.open_hotel_block(ctx["block"]["id"], COORDINATOR)
        validate_error(response, "ERR_NO_APPROVED_SUB_BLOCK", 409)

        after = read_block(ctx["block"]["id"])
        assert after["status"] == "CONTRACTED"
        assert after["unassigned_rooms_per_night"] == 6

        event = validate_success(api.get_event(ctx["event"]["id"], COORDINATOR))
        assert event["housing_posture"] == "PLANNING"

    def test_controller_approval_unblocks_the_open_and_flips_the_posture(self, api):
        """PRD §3.3: "Controller approval moves the sub-block `PENDING_APPROVAL →
        APPROVED`, records the acting `X-User-ID` as `approved_by_user_id`,
        recomputes the event's `housing_posture`, and bumps the sub-block's
        `version`"
        PRD §2.11: "Otherwise, if the open group is non-empty and the available
        room count is greater than zero, the posture is `OPEN`."

        Design: Difficulty/cross_entity_state_dependency/block_open_gated_on_sub_block_approval_state
        """
        ctx = setup_housing_program(
            carves=VIP_CARVE, confirmation_number="CN-SUM26-006"
        )
        approved = approve_sub_block(ctx["sub_blocks"][0]["id"], CONTROLLER)

        assert approved["approval_status"] == "APPROVED"
        assert approved["approved_by_user_id"] == TEST_DEFAULTS["CONTROLLER_ID"]
        assert approved["requested_by_user_id"] == TEST_DEFAULTS["COORDINATOR_ID"]
        assert approved["version"] > ctx["sub_blocks"][0]["version"]

        opened = open_block(ctx["block"]["id"])
        assert opened["status"] == "OPEN"

        event = validate_success(api.get_event(ctx["event"]["id"], COORDINATOR))
        assert event["housing_posture"] == "OPEN"
