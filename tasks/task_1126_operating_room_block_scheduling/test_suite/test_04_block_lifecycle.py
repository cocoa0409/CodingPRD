"""Block lifecycle: draft, activation, release rules, cancellation, room overlap."""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    assert_block_allocation,
    assert_open_time_slot,
    create_block_payload,
    make_block,
    make_line,
    make_room,
    make_surgeon,
    make_surgeon_headers,
    validate_error,
    validate_paginated,
    validate_success,
)

ADMIN = TEST_USERS["admin_headers"]


class TestBlockCreation:
    def test_new_block_starts_in_draft(self, api, admin_headers):
        """PRD §3.2: "New blocks are born in `DRAFT` status."

        Design: Corner/state_machines/new_block_starts_in_draft
        """
        line = make_line()
        room = make_room()
        res = api.create_block(
            create_block_payload(line["id"], room["id"],
                                 date="2026-05-04", start_minute=420, end_minute=720),
            admin_headers,
        )
        block = validate_success(res, 201)
        assert_block_allocation(block)
        assert block["status"] == "DRAFT"

    def test_get_nonexistent_block_not_found(self, api, admin_headers):
        """PRD §2.7: "Each missing resource yields its own 404:
        `ERR_SERVICE_LINE_NOT_FOUND`, `ERR_SURGEON_NOT_FOUND`, `ERR_ROOM_NOT_FOUND`,
        `ERR_BLOCK_NOT_FOUND`, `ERR_CASE_NOT_FOUND`, `ERR_COVERAGE_NOT_FOUND`,
        `ERR_SLOT_NOT_FOUND`, `ERR_REQUEST_NOT_FOUND`, or `ERR_REVIEW_NOT_FOUND`."

        Design: Corner/entities/get_block_with_nonexistent_id_not_found
        """
        res = api.get_block("11111111-2222-3333-4444-555555555555", admin_headers)
        validate_error(res, ApiErrorId.ERR_BLOCK_NOT_FOUND)
        assert res.status_code == 404


class TestActivation:
    def test_activate_already_active_block_rejected(self, api, admin_headers):
        """PRD §3.2: "Activation moves a block from `DRAFT` to `ACTIVE`; attempting
        it on a block in any other status is rejected with `ERR_BLOCK_NOT_DRAFT`."

        Design: Corner/state_machines/activate_already_active_block_rejected
        """
        line = make_line()
        room = make_room()
        block = make_block(line["id"], room["id"], activate=True)
        res = api.activate_block(block["id"], admin_headers)
        validate_error(res, ApiErrorId.ERR_BLOCK_NOT_DRAFT)
        assert res.status_code == 409


class TestRelease:
    def test_release_twice_rejected_and_no_duplicate_slot(self, api, admin_headers):
        """PRD §3.2: "Releasing a block that is not `ACTIVE` is rejected with
        `ERR_BLOCK_NOT_ACTIVE`."

        Design: Corner/state_machines/release_already_released_block_rejected
        """
        line = make_line()
        room = make_room()
        block = make_block(line["id"], room["id"], activate=True)
        validate_success(api.release_block(block["id"], admin_headers), 200)

        res = api.release_block(block["id"], admin_headers)
        validate_error(res, ApiErrorId.ERR_BLOCK_NOT_ACTIVE)
        assert res.status_code == 409

        _, meta = validate_paginated(
            api.list_open_time_slots(admin_headers, params={"block_id": block["id"]})
        )
        assert meta["total_count"] == 1

    def test_release_side_effects_immediately_visible(self, api, admin_headers):
        """PRD §2.9: "Throughout this API, every side effect is applied immediately:
        it is visible in the triggering request's response and in all subsequent
        reads."
        PRD §3.2: "On release, the free tail runs from the end of the last
        `SCHEDULED` case — or from the block's start when none exists — to the
        block's `end_minute`. A tail of at least thirty minutes becomes an `OPEN`
        open-time slot whose `original_minutes` equals the tail length".

        Design: Corner/consistency_model/release_side_effects_immediately_visible
        """
        line = make_line()
        room = make_room()
        block = make_block(line["id"], room["id"], date="2026-05-04",
                           start_minute=420, end_minute=720, activate=True)

        released = validate_success(api.release_block(block["id"], admin_headers), 200)
        assert released["status"] == "RELEASED"
        assert released["reserved_minutes"] == 0

        slots, meta = validate_paginated(
            api.list_open_time_slots(admin_headers, params={"block_id": block["id"]})
        )
        assert meta["total_count"] == 1
        slot = slots[0]
        assert_open_time_slot(slot)
        assert slot["original_minutes"] == 300
        assert slot["remaining_minutes"] == 300
        assert slot["status"] == "OPEN"


class TestCancellation:
    def test_cancel_released_block_rejected(self, api, admin_headers):
        """PRD §3.2: "Cancellation is available while a block is `DRAFT` or `ACTIVE`;
        attempting it on a block that has already left those states is rejected with
        `ERR_BLOCK_NOT_ACTIVE`."

        Design: Corner/state_machines/cancel_released_block_rejected_terminal_lockdown
        """
        line = make_line()
        room = make_room()
        block = make_block(line["id"], room["id"], activate=True)
        validate_success(api.release_block(block["id"], admin_headers), 200)

        res = api.cancel_block(block["id"], admin_headers)
        validate_error(res, ApiErrorId.ERR_BLOCK_NOT_ACTIVE)
        assert res.status_code == 409

        reread = validate_success(api.get_block(block["id"], admin_headers), 200)
        assert reread["status"] == "RELEASED"


class TestSurgeonReleaseOwnership:
    def test_surgeon_release_ownership_rules(self, api):
        """PRD §3.2: "Three actors can cause it: a `SchedulingAdmin` at any time; the
        owning surgeon, only when the block's `surgeon_id` equals their `X-User-ID`
        (shared blocks are admin-only, and an ownership violation is
        `ERR_NOT_RESOURCE_OWNER`); and the release sweep, once `release_deadline_at`
        is at or before the current clock."

        Design: Corner/rbac/surgeon_release_ownership_rules
        """
        line = make_line()
        surgeon_a = make_surgeon(line["id"], full_name="Dr. A")
        surgeon_b = make_surgeon(line["id"], full_name="Dr. B")
        room = make_room()
        own = make_block(line["id"], room["id"], date="2026-05-04",
                         surgeon_id=surgeon_a["id"], activate=True)
        other = make_block(line["id"], room["id"], date="2026-05-05",
                           surgeon_id=surgeon_b["id"], activate=True)
        shared = make_block(line["id"], room["id"], date="2026-05-06", activate=True)

        released = validate_success(
            api.release_block(own["id"], make_surgeon_headers(surgeon_a["id"])), 200
        )
        assert released["status"] == "RELEASED"

        res_other = api.release_block(other["id"], make_surgeon_headers(surgeon_a["id"]))
        validate_error(res_other, ApiErrorId.ERR_NOT_RESOURCE_OWNER)
        assert res_other.status_code == 403
        assert validate_success(api.get_block(other["id"], ADMIN), 200)["status"] == "ACTIVE"

        res_shared = api.release_block(shared["id"], make_surgeon_headers(surgeon_a["id"]))
        validate_error(res_shared, ApiErrorId.ERR_NOT_RESOURCE_OWNER)
        assert res_shared.status_code == 403
        assert validate_success(api.get_block(shared["id"], ADMIN), 200)["status"] == "ACTIVE"


class TestReleaseSweepCheckpoint:
    def test_release_sweep_respects_release_deadline(self, api, admin_headers):
        """PRD §3.5: "The sweep itself is the `SchedulingAdmin` checkpoint that does
        three things in one pass — it releases every `ACTIVE` block whose
        `release_deadline_at` is at or before the current clock (each behaving
        exactly like a manual release, slot creation included), expires those
        past-date slots and their pending requests, and runs the selector over
        every `OPEN` slot with pending requests."

        Design: Corner/cross_cutting_complexity_layers/release_sweep_respects_release_deadline_checkpoint
        """
        line = make_line(release_deadline_hours=72)
        room = make_room()
        # Deadline: 2026-05-01T08:00:00Z - 72h = 2026-04-28T08:00:00Z (past).
        due = make_block(line["id"], room["id"], date="2026-05-01",
                         start_minute=480, end_minute=1020, activate=True)
        # Deadline: 2026-05-10T08:00:00Z - 72h = 2026-05-07T08:00:00Z (future).
        future = make_block(line["id"], room["id"], date="2026-05-10",
                            start_minute=480, end_minute=1020, activate=True)
        validate_success(api.set_clock("2026-05-01T00:00:00Z", admin_headers), 200)

        result = validate_success(api.release_sweep(admin_headers), 200)
        assert result["released_blocks"] == 1
        assert result["slots_created"] == 1

        due_after = validate_success(api.get_block(due["id"], admin_headers), 200)
        assert due_after["status"] == "RELEASED"
        future_after = validate_success(api.get_block(future["id"], admin_headers), 200)
        assert future_after["status"] == "ACTIVE"

        slots, meta = validate_paginated(
            api.list_open_time_slots(admin_headers, params={"block_id": due["id"]})
        )
        assert meta["total_count"] == 1
        assert slots[0]["original_minutes"] == 540


class TestBlockRoomOverlap:
    def test_adjacency_allowed_overlap_rejected(self, api, admin_headers):
        """PRD §3.2: "Room exclusivity is enforced at creation and protects
        activation integrity as well: creation is rejected with
        `ERR_BLOCK_TIME_OVERLAP` when another block on the same room and date,
        itself in `DRAFT` or `ACTIVE` status, overlaps the new window — overlap
        meaning each window begins before the other ends, with mere touching
        permitted."

        Design: Difficulty/resource_temporal_overlap/block_adjacency_allowed_overlap_rejected
        """
        line = make_line(name="HPB")
        room = make_room()
        first = make_block(line["id"], room["id"], date="2026-05-04",
                           start_minute=480, end_minute=720)
        assert first["status"] == "DRAFT"

        # Touching at 720 == 720 is allowed even against a DRAFT block.
        adjacent = validate_success(
            api.create_block(
                create_block_payload(line["id"], room["id"], date="2026-05-04",
                                     start_minute=720, end_minute=960),
                admin_headers,
            ),
            201,
        )
        assert adjacent["status"] == "DRAFT"

        # One minute of overlap (719 < 720) is rejected.
        overlapping = api.create_block(
            create_block_payload(line["id"], room["id"], date="2026-05-04",
                                 start_minute=719, end_minute=900),
            admin_headers,
        )
        validate_error(overlapping, ApiErrorId.ERR_BLOCK_TIME_OVERLAP)
        assert overlapping.status_code == 409

    def test_released_block_still_occupies_original_window(self, api, admin_headers):
        """PRD §3.2: "Blocks that have been `RELEASED` or `REDUCED` continue to
        occupy their original room window for purposes of this check, so their
        original span still conflicts with a proposed new block."

        Design: Difficulty/resource_temporal_overlap/block_adjacency_allowed_overlap_rejected
        """
        line = make_line(name="HPB")
        room = make_room()
        released = make_block(line["id"], room["id"], date="2026-05-04",
                              start_minute=420, end_minute=720, activate=True)
        validate_success(api.release_block(released["id"], admin_headers), 200)

        conflict = api.create_block(
            create_block_payload(line["id"], room["id"], date="2026-05-04",
                                 start_minute=600, end_minute=800),
            admin_headers,
        )
        validate_error(conflict, ApiErrorId.ERR_BLOCK_TIME_OVERLAP)

        touching = validate_success(
            api.create_block(
                create_block_payload(line["id"], room["id"], date="2026-05-04",
                                     start_minute=720, end_minute=960),
                admin_headers,
            ),
            201,
        )
        assert touching["status"] == "DRAFT"
