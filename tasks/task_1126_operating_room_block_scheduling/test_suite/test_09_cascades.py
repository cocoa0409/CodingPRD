"""Cascades: block cancellation bumps cases; case cancellation repacks; votes trim blocks."""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    assert_block_allocation,
    assert_committee_review,
    assert_open_time_slot,
    cast_votes_sequential,
    make_block,
    make_case,
    make_coverage,
    make_line,
    make_room,
    make_surgeon,
    make_surgeon_headers,
    schedule_case_in_block,
    setup_active_block_with_case,
    setup_deficient_review,
    validate_error,
    validate_paginated,
    validate_success,
)

ADMIN = TEST_USERS["admin_headers"]
CHAIR = TEST_USERS["chair_headers"]


class TestBlockCancelCascade:
    def test_cancel_active_block_bumps_scheduled_cases(self, api, admin_headers):
        """PRD §3.2: "Cancelling an `ACTIVE` block cascades: every `SCHEDULED` case
        in the block moves to `BUMPED`, its `scheduled_start_minute` and
        `scheduled_end_minute` cleared while its `block_id` is retained for audit."

        Design: Corner/state_machines/block_cancel_cascades_cases_to_bumped
        """
        line = make_line()
        surgeon = make_surgeon(line["id"])
        room = make_room()
        make_coverage(room["id"], "2026-05-04", 420, 1200)
        block = make_block(line["id"], room["id"], date="2026-05-04",
                           start_minute=420, end_minute=720, activate=True)
        c1 = schedule_case_in_block(make_case(surgeon["id"])["id"], block["id"], surgeon["id"])
        c2 = schedule_case_in_block(make_case(surgeon["id"])["id"], block["id"], surgeon["id"])

        cancelled = validate_success(api.cancel_block(block["id"], admin_headers), 200)
        assert cancelled["status"] == "CANCELLED"

        for prior, start in ((c1, 420), (c2, 535)):
            after = validate_success(api.get_case(prior["id"], ADMIN), 200)
            assert after["status"] == "BUMPED"
            assert after["scheduled_start_minute"] is None
            assert after["scheduled_end_minute"] is None
            assert after["block_id"] == block["id"]
            assert prior["scheduled_start_minute"] == start


class TestCaseCancelRepackCascade:
    def _three_case_block(self):
        line = make_line(name="URO")
        surgeon = make_surgeon(line["id"], full_name="Dr. U")
        room = make_room()
        make_coverage(room["id"], "2026-05-04", 420, 1200)
        block = make_block(line["id"], room["id"], date="2026-05-04",
                           start_minute=420, end_minute=720, activate=True)
        c1 = schedule_case_in_block(
            make_case(surgeon["id"], procedure_class="MINOR")["id"], block["id"], surgeon["id"]
        )
        c2 = schedule_case_in_block(
            make_case(surgeon["id"])["id"], block["id"], surgeon["id"]
        )
        c3 = schedule_case_in_block(
            make_case(surgeon["id"])["id"], block["id"], surgeon["id"]
        )
        return line, surgeon, room, block, c1, c2, c3

    def test_cancel_first_case_repacks_successors(self, api):
        """PRD §3.6: "Cancelling a `SCHEDULED` case repairs the block: the remaining
        `SCHEDULED` cases in the same block are repacked — successors have their
        `scheduled_start_minute` recomputed while the relative order of the
        remaining cases is preserved — `occupied_minutes` is recomputed, the block's
        `version` increments by 1, and `is_first_case_of_day` is rederived for the
        room-day."

        Design: Difficulty/transitive_cascade/case_cancel_repack_firstcase_cascade
        """
        _, surgeon, _, block, c1, c2, c3 = self._three_case_block()
        assert c1["scheduled_start_minute"] == 420
        assert c2["scheduled_start_minute"] == 490
        assert c3["scheduled_start_minute"] == 605

        cancelled = validate_success(
            api.cancel_case(c1["id"], make_surgeon_headers(surgeon["id"])), 200
        )
        assert cancelled["status"] == "CANCELLED"

        c2_after = validate_success(api.get_case(c2["id"], ADMIN), 200)
        assert c2_after["scheduled_start_minute"] == 420
        assert c2_after["is_first_case_of_day"] is True
        c3_after = validate_success(api.get_case(c3["id"], ADMIN), 200)
        assert c3_after["scheduled_start_minute"] == 535  # 420 + 90 + 25
        assert c3_after["is_first_case_of_day"] is False

        block_after = validate_success(api.get_block(block["id"], ADMIN), 200)
        assert block_after["occupied_minutes"] == 205  # 90 + 90 + 25

    def test_cancel_middle_case_preserves_order(self, api):
        """PRD §3.6: "the remaining `SCHEDULED` cases in the same block are
        repacked — successors have their `scheduled_start_minute` recomputed while
        the relative order of the remaining cases is preserved".

        Design: Difficulty/transitive_cascade/case_cancel_repack_firstcase_cascade
        """
        _, surgeon, _, block, c1, c2, c3 = self._three_case_block()

        cancelled = validate_success(
            api.cancel_case(c2["id"], make_surgeon_headers(surgeon["id"])), 200
        )
        assert cancelled["status"] == "CANCELLED"

        c1_after = validate_success(api.get_case(c1["id"], ADMIN), 200)
        assert c1_after["scheduled_start_minute"] == 420
        assert c1_after["is_first_case_of_day"] is True
        # c3 slides forward into c2's place: 465 + 25 = 490.
        c3_after = validate_success(api.get_case(c3["id"], ADMIN), 200)
        assert c3_after["scheduled_start_minute"] == 490

        block_after = validate_success(api.get_block(block["id"], ADMIN), 200)
        assert block_after["occupied_minutes"] == 160  # 45 + 90 + 25


class TestReduceCascade:
    def _setup_reduce_scenario(self):
        """Deficient line with a period block (in-window) plus two future ACTIVE
        blocks dated after the review's period_end."""
        env = setup_deficient_review(line_name="VASC")
        room2 = make_room("OR2")
        block_future_1 = make_block(env["line"]["id"], env["room"]["id"],
                                    date="2026-05-11", start_minute=480,
                                    end_minute=1080, activate=True)  # 600 min
        block_future_2 = make_block(env["line"]["id"], room2["id"],
                                    date="2026-05-11", start_minute=420,
                                    end_minute=720, activate=True)  # 300 min
        return env, block_future_1, block_future_2

    def test_reduce_decision_trims_future_blocks_into_slots(self, api):
        """PRD §3.7: "A `REDUCE` decision is applied the moment it lands. For every
        `ACTIVE` block of the line whose `date` falls strictly after the review's
        `period_end`, the kept window is nine tenths of `original_minutes` rounded
        down to a whole minute, measured from `start_minute` — but a block whose
        last `SCHEDULED` case ends after that trim point is skipped entirely and
        stays `ACTIVE`. For each block actually trimmed, the new `end_minute` is the
        start plus the kept minutes; the trimmed tail from new end to old end
        becomes an `OPEN` slot when it spans at least thirty minutes, and is added
        to the block's `forfeited_minutes` when shorter."

        Design: Difficulty/transitive_cascade/vote_quorum_reduce_cascades_blocks_to_slots
        """
        env, future1, future2 = self._setup_reduce_scenario()
        review = env["review"]

        decided = cast_votes_sequential(
            review["id"],
            [("cm_1", "REDUCE"), ("cm_2", "REDUCE"), ("cm_3", "REDUCE")],
            review["version"],
        )
        assert_committee_review(decided)
        assert decided["status"] == "DECIDED"
        assert decided["decision"] == "REDUCE"

        # 600 -> floor(0.9*600) = 540 kept; end 480+540 = 1020; tail 60 -> slot.
        f1 = validate_success(api.get_block(future1["id"], ADMIN), 200)
        assert f1["status"] == "REDUCED"
        assert f1["end_minute"] == 1020
        slots1, meta1 = validate_paginated(
            api.list_open_time_slots(ADMIN, params={"block_id": future1["id"]})
        )
        assert meta1["total_count"] == 1
        assert slots1[0]["start_minute"] == 1020
        assert slots1[0]["original_minutes"] == 60
        assert slots1[0]["status"] == "OPEN"

        # 300 -> floor(0.9*300) = 270 kept; end 420+270 = 690; tail 30 -> slot.
        f2 = validate_success(api.get_block(future2["id"], ADMIN), 200)
        assert f2["status"] == "REDUCED"
        assert f2["end_minute"] == 690
        slots2, meta2 = validate_paginated(
            api.list_open_time_slots(ADMIN, params={"block_id": future2["id"]})
        )
        assert meta2["total_count"] == 1
        assert slots2[0]["original_minutes"] == 30

        # The period block is dated 2026-05-04, not strictly after period_end
        # 2026-05-08, so it is outside the reduction's scope.
        period_block = validate_success(api.get_block(env["block"]["id"], ADMIN), 200)
        assert period_block["status"] == "ACTIVE"

    def test_reduction_slots_carry_provenance_and_full_remaining(self, api):
        """PRD §3.5: "Every open-time slot is born `OPEN` from a release or a
        reduction, with `remaining_minutes` equal to its `original_minutes`."
        PRD §3.2: "A tail of at least thirty minutes becomes an `OPEN` open-time
        slot whose `original_minutes` equals the tail length, inheriting its
        `block_id` provenance, `or_id`, `date`, and the tail's start as its
        `start_minute`".

        Design: Difficulty/transitive_cascade/vote_quorum_reduce_cascades_blocks_to_slots
        """
        env, future1, future2 = self._setup_reduce_scenario()
        review = env["review"]
        cast_votes_sequential(
            review["id"],
            [("cm_1", "REDUCE"), ("cm_2", "REDUCE"), ("cm_3", "REDUCE")],
            review["version"],
        )

        slots1, _ = validate_paginated(
            api.list_open_time_slots(ADMIN, params={"block_id": future1["id"]})
        )
        slot = slots1[0]
        assert_open_time_slot(slot)
        assert slot["block_id"] == future1["id"]
        assert slot["or_id"] == env["room"]["id"]
        assert slot["date"] == "2026-05-11"
        assert slot["start_minute"] == 1020
        assert slot["original_minutes"] == 60
        assert slot["remaining_minutes"] == 60
        assert slot["forfeited_minutes"] == 0
        assert slot["status"] == "OPEN"

        slots2, _ = validate_paginated(
            api.list_open_time_slots(ADMIN, params={"block_id": future2["id"]})
        )
        assert slots2[0]["remaining_minutes"] == 30
        assert slots2[0]["status"] == "OPEN"
