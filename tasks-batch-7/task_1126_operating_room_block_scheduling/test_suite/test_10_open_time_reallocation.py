"""Open-time slots and the reallocation waterfall: claims, fragments, tie-breaks."""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    assert_open_time_slot,
    assert_reallocation_request,
    assert_room_minute_ledger,
    make_block,
    make_case,
    make_coverage,
    make_line,
    make_reallocation_request,
    make_room,
    make_surgeon,
    make_surgeon_headers,
    schedule_case_in_block,
    setup_open_slot,
    validate_error,
    validate_paginated,
    validate_success,
)

ADMIN = TEST_USERS["admin_headers"]


class TestReallocationRequestLifecycle:
    def test_withdraw_twice_rejected(self, api):
        """PRD §3.5: "Requests are born `PENDING`, and the owning surgeon may
        withdraw one while it is still `PENDING` — otherwise
        `ERR_REQUEST_NOT_PENDING`, or `ERR_NOT_RESOURCE_OWNER` for a non-owner —
        moving it to `WITHDRAWN`."

        Design: Corner/state_machines/withdraw_reallocation_request_twice_rejected
        """
        env = setup_open_slot(block_start=420, block_end=720)  # empty block: 300-min slot
        slot = env["slots"][0]
        case = make_case(env["surgeon"]["id"], procedure_class="MINOR", priority="ADD_ON")
        request = make_reallocation_request(slot["id"], case["id"], env["surgeon"]["id"])
        assert request["status"] == "PENDING"

        withdrawn = validate_success(
            api.withdraw_reallocation_request(
                request["id"], make_surgeon_headers(env["surgeon"]["id"])
            ),
            200,
        )
        assert withdrawn["status"] == "WITHDRAWN"

        res = api.withdraw_reallocation_request(
            request["id"], make_surgeon_headers(env["surgeon"]["id"])
        )
        validate_error(res, ApiErrorId.ERR_REQUEST_NOT_PENDING)
        assert res.status_code == 409


class TestSelectorPolicy:
    def test_created_at_tiebreak_and_empty_pool_fallback(self, api, admin_headers):
        """PRD §3.5: "The winner is the pool request whose line has the lowest
        `prime_time_utilization_pct` — lineless requests first — with ties broken by
        the request's `created_at` ascending."
        PRD §3.5: "Losing requests are never auto-rejected at this point — they stay
        `PENDING` for future slots." and "when the pool is empty the slot simply
        stays `OPEN`".

        Design: Corner/cross_cutting_complexity_layers/selector_tiebreak_created_at_and_empty_pool_fallback
        """
        line = make_line()
        donor = make_surgeon(line["id"], full_name="Dr. S")
        requester = make_surgeon(line["id"], full_name="Dr. Q")
        room1 = make_room("OR1")
        room2 = make_room("OR2")
        make_coverage(room1["id"], "2026-05-04", 420, 1200)
        make_coverage(room2["id"], "2026-05-04", 420, 1200)
        block1 = make_block(line["id"], room1["id"], date="2026-05-04",
                            start_minute=420, end_minute=600, activate=True)
        block2 = make_block(line["id"], room2["id"], date="2026-05-04",
                            start_minute=600, end_minute=780, activate=True)
        schedule_case_in_block(make_case(donor["id"])["id"], block1["id"], donor["id"])
        schedule_case_in_block(make_case(donor["id"])["id"], block2["id"], donor["id"])
        validate_success(api.release_block(block1["id"], admin_headers), 200)
        validate_success(api.release_block(block2["id"], admin_headers), 200)
        slot1 = validate_paginated(
            api.list_open_time_slots(admin_headers, params={"block_id": block1["id"]})
        )[0][0]
        slot2 = validate_paginated(
            api.list_open_time_slots(admin_headers, params={"block_id": block2["id"]})
        )[0][0]
        assert slot1["original_minutes"] == 90   # tail [510,600)
        assert slot2["original_minutes"] == 90   # tail [690,780)

        # Two requests against slot1 from the same line: tied on every ranking key.
        x1 = make_case(requester["id"], procedure_class="MINOR", priority="ADD_ON")
        x2 = make_case(requester["id"], procedure_class="MINOR", priority="ADD_ON")
        r1 = make_reallocation_request(slot1["id"], x1["id"], requester["id"])
        r2 = make_reallocation_request(slot1["id"], x2["id"], requester["id"])

        result = validate_success(api.release_sweep(admin_headers), 200)
        assert result["requests_approved"] == 1

        r1_after = validate_success(api.get_reallocation_request(r1["id"], admin_headers), 200)
        assert_reallocation_request(r1_after)
        assert r1_after["status"] == "APPROVED"  # created_at ASC tie-break
        r2_after = validate_success(api.get_reallocation_request(r2["id"], admin_headers), 200)
        assert r2_after["status"] == "PENDING"   # loser is never auto-rejected

        slot1_after = validate_success(api.get_open_time_slot(slot1["id"], admin_headers), 200)
        assert slot1_after["remaining_minutes"] == 30  # 90 - 60
        assert slot1_after["status"] == "OPEN"
        slot2_after = validate_success(api.get_open_time_slot(slot2["id"], admin_headers), 200)
        assert slot2_after["status"] == "OPEN"
        assert slot2_after["remaining_minutes"] == 90  # empty pool: untouched

        x1_after = validate_success(api.get_case(x1["id"], admin_headers), 200)
        assert x1_after["status"] == "SCHEDULED"
        assert x1_after["scheduled_start_minute"] == 510
        x2_after = validate_success(api.get_case(x2["id"], admin_headers), 200)
        assert x2_after["status"] == "POSTED"


class TestSlotFragmentBoundary:
    def _setup_two_slots(self, api):
        """S1 holds 85 minutes (approve 60 -> remainder 25); S2 holds 90
        (approve 60 -> remainder 30)."""
        line = make_line(name="TX")
        donor = make_surgeon(line["id"], full_name="Dr. S")
        requester = make_surgeon(line["id"], full_name="Dr. Q")
        room1 = make_room("OR1")
        room2 = make_room("OR2")
        make_coverage(room1["id"], "2026-05-04", 420, 1200)
        make_coverage(room2["id"], "2026-05-04", 420, 1200)
        block1 = make_block(line["id"], room1["id"], date="2026-05-04",
                            start_minute=420, end_minute=595, activate=True)
        block2 = make_block(line["id"], room2["id"], date="2026-05-04",
                            start_minute=600, end_minute=780, activate=True)
        schedule_case_in_block(make_case(donor["id"])["id"], block1["id"], donor["id"])
        schedule_case_in_block(make_case(donor["id"])["id"], block2["id"], donor["id"])
        validate_success(api.release_block(block1["id"], ADMIN), 200)
        validate_success(api.release_block(block2["id"], ADMIN), 200)
        slot1 = validate_paginated(
            api.list_open_time_slots(ADMIN, params={"block_id": block1["id"]})
        )[0][0]
        slot2 = validate_paginated(
            api.list_open_time_slots(ADMIN, params={"block_id": block2["id"]})
        )[0][0]
        x1 = make_case(requester["id"], procedure_class="MINOR", priority="ADD_ON")
        x2 = make_case(requester["id"], procedure_class="MINOR", priority="ADD_ON")
        r1 = make_reallocation_request(slot1["id"], x1["id"], requester["id"])
        r2 = make_reallocation_request(slot2["id"], x2["id"], requester["id"])
        return line, donor, requester, slot1, slot2, x1, x2, r1, r2

    def test_fragment_below_thirty_absorbed_at_approval(self, api, admin_headers):
        """PRD §3.5: "When that shrinkage leaves a remainder below thirty minutes,
        the remainder is added to the slot's `forfeited_minutes`, `remaining_minutes`
        is zeroed, and the slot moves to `CLAIMED`."

        Design: Difficulty/boundary_precision_check/slot_fragment_below_30_absorbed_at_approval
        """
        (_, _, _, slot1, slot2, x1, x2, r1, r2) = self._setup_two_slots(api)
        assert slot1["original_minutes"] == 85
        assert slot2["original_minutes"] == 90

        result = validate_success(api.release_sweep(admin_headers), 200)
        assert result["requests_approved"] == 2

        slot1_after = validate_success(api.get_open_time_slot(slot1["id"], admin_headers), 200)
        assert_open_time_slot(slot1_after)
        assert slot1_after["status"] == "CLAIMED"
        assert slot1_after["remaining_minutes"] == 0
        assert slot1_after["forfeited_minutes"] == 25  # 85 - 60 = 25 < 30

        slot2_after = validate_success(api.get_open_time_slot(slot2["id"], admin_headers), 200)
        assert slot2_after["status"] == "OPEN"
        assert slot2_after["remaining_minutes"] == 30  # 90 - 60 = 30, not < 30
        assert slot2_after["forfeited_minutes"] == 0

        for case, expected_start in ((x1, 510), (x2, 690)):
            after = validate_success(api.get_case(case["id"], admin_headers), 200)
            assert after["status"] == "SCHEDULED"
            assert after["scheduled_start_minute"] == expected_start
        for request in (r1, r2):
            after = validate_success(
                api.get_reallocation_request(request["id"], admin_headers), 200
            )
            assert after["status"] == "APPROVED"

    def test_release_tail_floor_thirty_vs_twentynine(self, api, admin_headers):
        """PRD §3.2: "A tail of at least thirty minutes becomes an `OPEN` open-time
        slot whose `original_minutes` equals the tail length, inheriting its
        `block_id` provenance, `or_id`, `date`, and the tail's start as its
        `start_minute`; a shorter tail is written into the block's
        `forfeited_minutes` instead."

        Design: Difficulty/boundary_precision_check/slot_fragment_below_30_absorbed_at_approval
        """
        line = make_line(name="TX")
        surgeon = make_surgeon(line["id"], full_name="Dr. S")
        surgeon2 = make_surgeon(line["id"], full_name="Dr. T")
        room1 = make_room("OR1")
        room2 = make_room("OR2")
        make_coverage(room1["id"], "2026-05-04", 420, 1200)
        make_coverage(room2["id"], "2026-05-04", 420, 1200)
        # MINOR case [420,465): tail [465,495) = 30 -> slot of 30.
        block30 = make_block(line["id"], room1["id"], date="2026-05-04",
                             start_minute=420, end_minute=495, activate=True)
        schedule_case_in_block(
            make_case(surgeon["id"], procedure_class="MINOR")["id"],
            block30["id"], surgeon["id"],
        )
        # MINOR case [420,465): tail [465,494) = 29 -> forfeited.
        # A second surgeon owns the block29 case: placing the same surgeon at an
        # identical window in another room would violate the PRD §3.4 padded
        # double-booking rule, which admits no coincident-start exemption.
        block29 = make_block(line["id"], room2["id"], date="2026-05-04",
                             start_minute=420, end_minute=494, activate=True)
        schedule_case_in_block(
            make_case(surgeon2["id"], procedure_class="MINOR")["id"],
            block29["id"], surgeon2["id"],
        )

        released30 = validate_success(api.release_block(block30["id"], admin_headers), 200)
        assert released30["forfeited_minutes"] == 0
        slots30, meta30 = validate_paginated(
            api.list_open_time_slots(admin_headers, params={"block_id": block30["id"]})
        )
        assert meta30["total_count"] == 1
        assert slots30[0]["original_minutes"] == 30
        assert slots30[0]["status"] == "OPEN"

        released29 = validate_success(api.release_block(block29["id"], admin_headers), 200)
        assert released29["forfeited_minutes"] == 29
        _, meta29 = validate_paginated(
            api.list_open_time_slots(admin_headers, params={"block_id": block29["id"]})
        )
        assert meta29["total_count"] == 0


class TestRoomMinuteLedger:
    def _setup_ledger_block(self):
        """Block [420,1020) original 600 with two STANDARD cases [420,510) and
        [535,625); released manually, then one 60-minute reallocation claim."""
        line = make_line(name="TTS")
        owner = make_surgeon(line["id"], full_name="Dr. S")
        requester = make_surgeon(line["id"], full_name="Dr. Q")
        room = make_room()
        make_coverage(room["id"], "2026-05-04", 420, 1200)
        block = make_block(line["id"], room["id"], date="2026-05-04",
                           start_minute=420, end_minute=1020, activate=True)
        schedule_case_in_block(make_case(owner["id"])["id"], block["id"], owner["id"])
        schedule_case_in_block(make_case(owner["id"])["id"], block["id"], owner["id"])
        return line, owner, requester, room, block

    def test_ledger_conserved_through_release_and_claim(self, api, admin_headers):
        """PRD §2.10: "Room-minutes are never created or destroyed, only
        reclassified. Every block freezes its `original_minutes` — end minus start —
        at creation as the ledger anchor, and every open-time slot likewise freezes
        its own `original_minutes` at creation. From then on, each minute of a block
        is always accountable as exactly one of: still block-controlled
        (`reserved_minutes`), committed to scheduled cases (`occupied_minutes`),
        released into a claimable slot (the slot's `original_minutes`, shrinking via
        `remaining_minutes`), or written off (`forfeited_minutes`)."

        Design: Difficulty/compensating_invariant/room_minute_ledger_conserved_through_release_and_claim
        """
        _, _, requester, _, block = self._setup_ledger_block()

        released = validate_success(api.release_block(block["id"], admin_headers), 200)
        assert released["status"] == "RELEASED"
        assert released["reserved_minutes"] == 205  # frozen occupied span 625-420

        slots, meta = validate_paginated(
            api.list_open_time_slots(admin_headers, params={"block_id": block["id"]})
        )
        assert meta["total_count"] == 1
        slot = slots[0]
        assert slot["original_minutes"] == 395  # free tail [625,1020)
        assert_room_minute_ledger(released, slots)  # 600 == 205 + 395 + 0

        x = make_case(requester["id"], procedure_class="MINOR", priority="ADD_ON")
        make_reallocation_request(slot["id"], x["id"], requester["id"])
        validate_success(api.release_sweep(admin_headers), 200)

        slot_after = validate_success(api.get_open_time_slot(slot["id"], admin_headers), 200)
        assert slot_after["remaining_minutes"] == 335  # 395 - 60
        assert slot_after["original_minutes"] == 395   # ledger anchor unchanged
        assert slot_after["status"] == "OPEN"
        block_after = validate_success(api.get_block(block["id"], admin_headers), 200)
        assert_room_minute_ledger(block_after, [slot_after])  # still 600 == 205+395+0

        x_after = validate_success(api.get_case(x["id"], admin_headers), 200)
        assert x_after["status"] == "SCHEDULED"
        assert x_after["scheduled_start_minute"] == 625

    def test_ledger_conserved_with_single_case_and_partial_claim(self, api, admin_headers):
        """PRD §3.2: "The block's `reserved_minutes` freezes to the occupied span
        (zero when no cases remain scheduled), its `version` increments by 1, and
        every newly created slot is immediately evaluated against the pool of
        `PENDING` reallocation requests described in §3.5."
        PRD §3.5: "the winning case is scheduled at the slot's `start_minute` with
        `block_id` null and `or_id` and `date` inherited from the slot; the request
        moves to `APPROVED`; and the slot's `remaining_minutes` shrinks by the
        needed minutes."

        Design: Difficulty/compensating_invariant/room_minute_ledger_conserved_through_release_and_claim
        """
        line = make_line(name="TTS")
        owner = make_surgeon(line["id"], full_name="Dr. S")
        requester = make_surgeon(line["id"], full_name="Dr. Q")
        room = make_room()
        make_coverage(room["id"], "2026-05-04", 420, 1200)
        block = make_block(line["id"], room["id"], date="2026-05-04",
                           start_minute=420, end_minute=720, activate=True)
        schedule_case_in_block(make_case(owner["id"])["id"], block["id"], owner["id"])

        released = validate_success(api.release_block(block["id"], admin_headers), 200)
        assert released["reserved_minutes"] == 90  # 510 - 420
        slots, meta = validate_paginated(
            api.list_open_time_slots(admin_headers, params={"block_id": block["id"]})
        )
        assert meta["total_count"] == 1
        slot = slots[0]
        assert slot["original_minutes"] == 210  # tail [510,720)
        assert_room_minute_ledger(released, slots)  # 300 == 90 + 210 + 0

        x = make_case(requester["id"], procedure_class="MINOR", priority="ADD_ON")
        make_reallocation_request(slot["id"], x["id"], requester["id"])
        validate_success(api.release_sweep(admin_headers), 200)

        slot_after = validate_success(api.get_open_time_slot(slot["id"], admin_headers), 200)
        assert slot_after["remaining_minutes"] == 150  # 210 - 60
        assert slot_after["original_minutes"] == 210
        assert slot_after["status"] == "OPEN"
        block_after = validate_success(api.get_block(block["id"], admin_headers), 200)
        assert_room_minute_ledger(block_after, [slot_after])
        x_after = validate_success(api.get_case(x["id"], admin_headers), 200)
        assert x_after["scheduled_start_minute"] == 510
