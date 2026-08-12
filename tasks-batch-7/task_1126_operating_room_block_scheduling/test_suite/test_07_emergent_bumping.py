"""Emergent scheduling: single-bump resolution, atomic rejection, reschedule cycle."""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    assert_case_posting,
    make_block,
    make_case,
    make_coverage,
    make_line,
    make_room,
    make_surgeon,
    make_surgeon_headers,
    schedule_case_in_block,
    schedule_emergent_payload,
    validate_error,
    validate_success,
)

ADMIN = TEST_USERS["admin_headers"]


def _setup_emergent_pair(em_class="MINOR", em_start=430):
    """Two-scheduled-case block B1 [420,720), adjacent block B2 [720,1020),
    and a posted EMERGENT case by a second surgeon."""
    line = make_line(name="GS")
    surgeon_e = make_surgeon(line["id"], full_name="Dr. E")
    surgeon_x = make_surgeon(line["id"], full_name="Dr. X")
    room = make_room()
    make_coverage(room["id"], "2026-05-04", 420, 1200)
    block1 = make_block(line["id"], room["id"], date="2026-05-04",
                        start_minute=420, end_minute=720, activate=True)
    block2 = make_block(line["id"], room["id"], date="2026-05-04",
                        start_minute=720, end_minute=1020, activate=True)
    e1 = schedule_case_in_block(
        make_case(surgeon_e["id"], procedure_class="STANDARD")["id"],
        block1["id"], surgeon_e["id"],
    )
    e2 = schedule_case_in_block(
        make_case(surgeon_e["id"], procedure_class="STANDARD")["id"],
        block1["id"], surgeon_e["id"],
    )
    em = make_case(surgeon_x["id"], procedure_class=em_class, priority="EMERGENT")
    return line, surgeon_e, surgeon_x, room, block1, block2, e1, e2, em


class TestEmergentBumpCycle:
    def test_emergent_bump_then_reschedule_cycle(self, api):
        """PRD §3.4: "When the needed window intersects existing `SCHEDULED` cases
        in that room-day, the system frees the window by bumping exactly one victim:
        the intersecting `SCHEDULED` `ELECTIVE` case when there is exactly one,
        otherwise the earliest intersecting `SCHEDULED` `ADD_ON` case."
        PRD §3.4: "A bumped case re-enters through rescheduling: the owning surgeon
        places it into an `ACTIVE` block by supplying `block_id`."

        Design: Difficulty/non_linear_state_machine/case_bumped_then_rescheduled_cycle
        """
        (_, surgeon_e, surgeon_x, room, block1, block2,
         e1, e2, em) = _setup_emergent_pair(em_class="MINOR", em_start=430)

        placed = validate_success(
            api.schedule_case(
                em["id"], schedule_emergent_payload(room["id"], "2026-05-04", 430),
                make_surgeon_headers(surgeon_x["id"]),
            ),
            200,
        )
        assert placed["status"] == "SCHEDULED"
        assert placed["scheduled_start_minute"] == 430
        assert placed["scheduled_end_minute"] == 475
        assert placed["block_id"] is None

        victim = validate_success(api.get_case(e1["id"], ADMIN), 200)
        assert victim["status"] == "BUMPED"
        assert victim["scheduled_start_minute"] is None

        # The victim's successor is NOT repacked on a bump.
        successor = validate_success(api.get_case(e2["id"], ADMIN), 200)
        assert successor["status"] == "SCHEDULED"
        assert successor["scheduled_start_minute"] == 535

        # BUMPED -> SCHEDULED via reschedule into the second block.
        rescheduled = validate_success(
            api.reschedule_case(
                e1["id"], {"block_id": block2["id"]},
                make_surgeon_headers(surgeon_e["id"]),
            ),
            200,
        )
        assert_case_posting(rescheduled)
        assert rescheduled["status"] == "SCHEDULED"
        assert rescheduled["scheduled_start_minute"] == 720
        assert rescheduled["block_id"] == block2["id"]

    def test_bump_clears_window_but_retains_block_provenance(self, api):
        """PRD §3.4: "The victim moves to `BUMPED`, its scheduled start and end
        cleared, its `block_id` retained for audit — and, unlike a cancellation, the
        victim's former block successors are not repacked, because repacking could
        collide with the emergent placement".
        PRD §3.4: "The case lands at `desired_start_minute` in the given room and
        date with `block_id` null".

        Design: Difficulty/non_linear_state_machine/case_bumped_then_rescheduled_cycle
        """
        (_, _, surgeon_x, room, block1, _,
         e1, e2, em) = _setup_emergent_pair(em_class="MINOR", em_start=430)

        placed = validate_success(
            api.schedule_case(
                em["id"], schedule_emergent_payload(room["id"], "2026-05-04", 430),
                make_surgeon_headers(surgeon_x["id"]),
            ),
            200,
        )
        assert placed["block_id"] is None
        assert placed["or_id"] == room["id"]
        assert placed["date"] == "2026-05-04"

        victim = validate_success(api.get_case(e1["id"], ADMIN), 200)
        assert victim["status"] == "BUMPED"
        assert victim["scheduled_start_minute"] is None
        assert victim["scheduled_end_minute"] is None
        assert victim["block_id"] == block1["id"]  # retained for audit

        # First-case flag rederived for the room-day: the emergent case at 430 is
        # now earliest among non-CANCELLED, non-BUMPED cases.
        assert placed["is_first_case_of_day"] is True
        successor = validate_success(api.get_case(e2["id"], ADMIN), 200)
        assert successor["is_first_case_of_day"] is False
        assert successor["scheduled_start_minute"] == 535


class TestEmergentWindowBlocked:
    def test_unresolvable_window_rejected_atomically(self, api):
        """PRD §3.4: "If no single bump can free the window — because multiple cases
        intersect it, or an intersecting case is already `IN_PROGRESS` or itself
        `EMERGENT` — the request is rejected atomically with
        `ERR_EMERGENT_WINDOW_BLOCKED` and no bump, no placement, and no partial side
        effect is applied."

        Design: Corner/errors/emergent_window_blocked_is_atomic_no_partial_bump
        """
        (_, _, surgeon_x, room, block1, _,
         e1, e2, em) = _setup_emergent_pair(em_class="STANDARD", em_start=500)

        # Needed window [500,615) intersects both e1 (padded [420,535)) and
        # e2 (padded [535,660)): one bump cannot free it.
        res = api.schedule_case(
            em["id"], schedule_emergent_payload(room["id"], "2026-05-04", 500),
            make_surgeon_headers(surgeon_x["id"]),
        )
        validate_error(res, ApiErrorId.ERR_EMERGENT_WINDOW_BLOCKED)
        assert res.status_code == 409

        e1_after = validate_success(api.get_case(e1["id"], ADMIN), 200)
        assert e1_after["status"] == "SCHEDULED"
        assert e1_after["scheduled_start_minute"] == 420
        e2_after = validate_success(api.get_case(e2["id"], ADMIN), 200)
        assert e2_after["status"] == "SCHEDULED"
        assert e2_after["scheduled_start_minute"] == 535
        em_after = validate_success(api.get_case(em["id"], ADMIN), 200)
        assert em_after["status"] == "POSTED"

        block_after = validate_success(api.get_block(block1["id"], ADMIN), 200)
        assert block_after["occupied_minutes"] == 205  # 90 + 25 + 90
