"""Watch group founding, block registration, and block lifecycle rules."""
from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    TEST_USERS,
    add_block,
    assert_block,
    assert_group_invariants,
    assert_watch_group,
    create_block_payload,
    create_member_payload,
    create_watch_group,
    register_block,
    setup_group_with_registered_block,
    get_success_data,
    validate_error,
    validate_paginated,
    validate_success,
)

COORD = TEST_USERS["coordinator_headers"]


class TestWatchGroupCreation:
    def test_watch_group_creation_defaults_applied(self, api):
        """PRD §3.1: "A new group begins with `certification_status` of
        `UNCERTIFIED` and `posture` of `DORMANT`, with `certification_valid_until`
        null — it remains null while the group is `UNCERTIFIED` or `REVOKED` —
        and both inventory ledgers and the `participation_score` at zero. The
        `training_cooldown_until` field is likewise null until a cooldown is armed."

        Design: Corner/entities/watch_group_creation_defaults_applied
        """
        group = validate_success(
            api.create_watch_group({"name": "Default Watch", "precinct_code": "D01"},
                                   COORD),
            201,
        )
        assert_watch_group(group)
        assert_group_invariants(group)
        assert group["certification_status"] == "UNCERTIFIED"
        assert group["posture"] == "DORMANT"
        assert group["certification_valid_until"] is None
        assert group["sign_inventory_count"] == 0
        assert group["materials_inventory_count"] == 0
        assert group["participation_score"] == 0
        assert group["training_cooldown_until"] is None

        fetched = validate_success(api.get_watch_group(group["id"], COORD))
        assert fetched["certification_status"] == "UNCERTIFIED"
        assert fetched["posture"] == "DORMANT"
        assert fetched["sign_inventory_count"] == 0
        assert fetched["materials_inventory_count"] == 0
        assert fetched["participation_score"] == 0

    def test_get_nonexistent_watch_group_returns_not_found(self, api):
        """PRD §2.6: "third, existence of the resources named in the path
        (`ERR_NOT_FOUND`)"

        Design: Corner/entities/entity_get_nonexistent_id_returns_not_found
        """
        resp = api.get_watch_group(NON_EXISTENT_UUID, COORD)
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND)


class TestBlockRegistration:
    def test_register_first_block_bubbles_posture_to_formation(self, api):
        """PRD §3.1: "when a group's first block reaches `REGISTERED` — provided
        the group's certification is `UNCERTIFIED` or `PROVISIONAL` — the group's
        `posture` recomputes from `DORMANT` to `FORMATION`, the participation
        score is recomputed under its census variant, and the group's `version`
        increments."

        Design: Corner/state_machines/block_register_valid_transition_and_posture_bubble_up
        """
        group = create_watch_group("Bubble Watch", "S04")
        block = add_block(group["id"], "4-4 State St", 4)
        assert block["registration_status"] == "PENDING"

        before = validate_success(api.get_watch_group(group["id"], COORD))
        assert before["posture"] == "DORMANT"

        registered = validate_success(api.register_block(block["id"], COORD))
        assert_block(registered)
        assert registered["registration_status"] == "REGISTERED"

        after = validate_success(api.get_watch_group(group["id"], COORD))
        assert after["posture"] == "FORMATION", (
            "First REGISTERED block wakes the group DORMANT -> FORMATION"
        )
        assert after["version"] == before["version"] + 1, (
            "The registration cascade increments the group's version exactly once"
        )

    def test_street_segment_unique_among_live_blocks(self, api):
        """PRD §3.1: "The `street_segment` must be unique within the group among
        blocks that have not been deregistered; a duplicate is rejected with
        `ERR_CONSTRAINT_VIOLATION`."

        Design: Corner/validations/street_segment_uniqueness_among_live_blocks
        """
        group, block = setup_group_with_registered_block(
            "Dup Watch", "V06", "1-1 Dup St", 4,
        )
        # Same segment (same case) while the first block is live: rejected.
        resp = api.create_block(
            group["id"], create_block_payload("1-1 Dup St", 6), COORD,
        )
        validate_error(resp, ApiErrorId.ERR_CONSTRAINT_VIOLATION)

        # Deregistration frees the segment: the same text is accepted again.
        deregistered = validate_success(api.deregister_block(block["id"], COORD))
        assert deregistered["registration_status"] == "DEREGISTERED"
        freed = validate_success(
            api.create_block(
                group["id"], create_block_payload("1-1 DUP ST", 6), COORD,
            ),
            201,
        )
        assert_block(freed)
        assert freed["registration_status"] == "PENDING"

    def test_block_list_pagination_envelope(self, api):
        """PRD §2.3: "Paginated and non-paginated list-based responses include
        the following fields in the `meta` object of the response envelope:
        `limit`, `offset`, `total_count`, and `has_more`."

        Design: Corner/entities/block_list_pagination_envelope
        """
        group = create_watch_group("Page Watch", "D06")
        for segment, households in (
            ("1-1 Page St", 2), ("2-2 Page St", 2), ("3-3 Page St", 2),
        ):
            add_block(group["id"], segment, households)

        resp = api.list_blocks(group["id"], COORD, params={"limit": 2, "offset": 0})
        data, meta = validate_paginated(resp)
        assert len(data) == 2, "limit=2 returns exactly two blocks"
        assert meta["total_count"] == 3, "total_count reports all three blocks"
        assert meta["has_more"] is True, "a third block remains past the page"
        assert meta["limit"] == 2 and meta["offset"] == 0

        data2, meta2 = validate_paginated(
            api.list_blocks(group["id"], COORD, params={"limit": 2, "offset": 2})
        )
        assert len(data2) == 1 and meta2["total_count"] == 3
        assert meta2["has_more"] is False


class TestMemberEnrollmentValidation:
    def test_member_create_missing_full_name_rejected(self, api):
        """PRD §3.2: "Enrollment — open to a `ProgramCoordinator` or a
        `BlockCaptain` — records the member's `full_name`, the `watch_group_id`
        and `block_id` placing them in the program, their primary alert
        `contact_channel` of `SMS`, `EMAIL`, or `PHONE_TREE`"
        PRD §2.6: "then field-level request validity (`ERR_INVALID_REQUEST`)"

        Design: Corner/entities/member_creation_missing_required_field_returns_invalid_request
        """
        group, block = setup_group_with_registered_block(
            "Req Watch", "D02", "1-1 Test Ln", 3,
        )
        payload = create_member_payload(group["id"], block["id"],
                                        contact_channel="SMS")
        del payload["full_name"]
        resp = api.create_member(payload, COORD)
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)

        _, meta = validate_paginated(
            api.list_members(COORD, params={"watch_group_id": group["id"]})
        )
        assert meta["total_count"] == 0, "No member row may persist from the rejected create"
