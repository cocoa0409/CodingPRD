"""Terms, academic blocks, and the placement run: status advancement, scoring,
placement order, unplace semantics, and double-finalize rejection."""

from test_helpers import (
    SCHEDULER,
    ApiErrorId,
    advance_term_to_scheduling,
    assert_scheduling_run,
    create_block,
    create_run,
    create_term,
    daily_close,
    finalize_run,
    get_block,
    get_event,
    get_run,
    get_term,
    set_clock,
    setup_placement_contention,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestTermStatusAdvancement:
    def test_term_status_auto_advances_on_daily_close(self, api):
        """PRD §3.3: "The daily-close checkpoint advances a term from `DRAFT` to
        `SCHEDULING` once the clock reaches `priority_open_at`, from `SCHEDULING`
        to `GENERAL` once the clock reaches `general_open_at`, and from any of
        `DRAFT`, `SCHEDULING`, or `GENERAL` to the terminal `CLOSED` once the
        clock passes one full day beyond `term_end_date`."

        Design: Corner/state_machines/term_status_auto_advances_on_daily_close
        """
        term = create_term()
        assert term["status"] == "DRAFT"

        set_clock("2026-08-09T00:00:00Z")
        counters = daily_close()
        assert counters["terms_advanced"] == 0
        assert get_term(term["id"])["status"] == "DRAFT"

        set_clock("2026-08-10T00:00:00Z")
        daily_close()
        assert get_term(term["id"])["status"] == "SCHEDULING"

        set_clock("2026-09-01T00:00:00Z")
        daily_close()
        assert get_term(term["id"])["status"] == "GENERAL"

        set_clock("2026-12-17T00:00:00Z")
        daily_close()
        assert get_term(term["id"])["status"] == "CLOSED"


class TestBlockValidation:
    def test_block_with_start_not_before_end_is_rejected(self, api):
        """PRD §3.3: "The block is rejected with `ERR_BLOCK_WINDOW_OUT_OF_TERM`
        when the start time is not earlier than the end time, when `days_of_week`
        is empty, or when the recurrence would produce no instance inside the
        term's dates."

        Design: Corner/validations/block_window_invalid_returns_422
        """
        term = create_term()
        response = api.create_academic_block(
            {
                "term_id": term["id"],
                "course_code": "BAD-1",
                "instructor_name": "Dr. Bad",
                "enrollment": 10,
                "days_of_week": ["MON"],
                "start_time": "14:00",
                "end_time": "13:00",
            },
            SCHEDULER,
        )
        validate_error(response, ApiErrorId.ERR_BLOCK_WINDOW_OUT_OF_TERM)
        _, meta = validate_paginated(api.list_academic_blocks(SCHEDULER))
        assert meta["total_count"] == 0


class TestPriorityScore:
    def test_priority_score_combines_enrollment_features_and_bonus(self, api):
        """PRD §3.3: "The score awards ten points per enrolled student, adds a
        per-feature weight for each entry in `required_features` — 50 for
        `PIANO`, 40 for `STAGE`, 30 for `LAB_BENCHES`, 25 for `KITCHEN_ACCESS`,
        20 for `VIDEO_CONF`, 15 for `SOUND_SYSTEM`, 10 for `PROJECTOR`, and 5
        for `ADA_LIFT` — and adds a flat 100-point large-class bonus when
        enrollment reaches at least 100."

        Design: Difficulty/combinatorial_formula/priority_score_multiinput_conditional_bonus
        """
        term = create_term()
        b1 = create_block(
            term["id"], course_code="CHEM-401", instructor_name="Dr. A",
            enrollment=180, days_of_week=["MON", "WED", "FRI"],
            start_time="09:00", end_time="09:50", required_features=["STAGE"],
        )
        b2 = create_block(
            term["id"], course_code="ART-110", instructor_name="Dr. B",
            enrollment=95, days_of_week=["TUE", "THU"],
            start_time="11:00", end_time="12:15",
            required_features=["PROJECTOR", "VIDEO_CONF"],
        )
        b3 = create_block(
            term["id"], course_code="MTH-201", instructor_name="Dr. C",
            enrollment=100, days_of_week=["MON"],
            start_time="13:00", end_time="14:15", required_features=[],
        )
        assert b1["priority_score"] == 1940, "180*10 + 40 STAGE + 100 bonus"
        assert b2["priority_score"] == 980, "95*10 + 10 PROJECTOR + 20 VIDEO_CONF"
        assert b3["priority_score"] == 1100, "100*10 + 100 bonus at boundary"

    def test_large_class_bonus_applies_exactly_at_enrollment_100(self, api):
        """PRD §3.3: "adds a flat 100-point large-class bonus when enrollment
        reaches at least 100."

        Design: Difficulty/combinatorial_formula/priority_score_multiinput_conditional_bonus
        """
        term = create_term()
        below = create_block(
            term["id"], course_code="MTH-099", instructor_name="Dr. L",
            enrollment=99, days_of_week=["TUE"],
            start_time="13:00", end_time="14:00", required_features=[],
        )
        at = create_block(
            term["id"], course_code="MTH-100", instructor_name="Dr. M",
            enrollment=100, days_of_week=["WED"],
            start_time="13:00", end_time="14:00", required_features=[],
        )
        assert below["priority_score"] == 990, "99*10 with no bonus"
        assert at["priority_score"] == 1100, "100*10 + 100 bonus (inclusive)"


class TestPlacementOrder:
    def test_higher_scored_block_wins_and_bumps_the_conflicting_event(self, api):
        """PRD §3.3: "Second, the blocks are sorted by descending
        `priority_score`, ties broken by descending `enrollment`, then by
        ascending `created_at`."
        PRD §3.3: "If no free candidate exists, it tries bumpable candidates —
        those with no `PLACED` block overlaps and whose only event conflicts are
        bumpable events — applying the same best-fit rule and bumping every
        conflicting bumpable event with the full cascade of §3.4."

        Design: Difficulty/combinatorial_formula/placement_evaluation_order_score_then_assign_then_bump
        """
        scn = setup_placement_contention()
        run = create_run(scn.term["id"])
        finalized = finalize_run(run["id"])
        assert_scheduling_run(finalized)
        assert finalized["status"] == "FINALIZED"
        assert finalized["placed_count"] == 1
        assert finalized["unplaced_block_ids"] == [scn.by["id"]], (
            "the lower-scored 140-enrollment block loses the only STAGE room"
        )
        assert finalized["bumped_event_ids"] == [scn.event["id"]], (
            "bump is the fallback path for the higher-scored block"
        )

    def test_placement_sets_block_assignment_and_clears_event_room(self, api):
        """PRD §3.3: "Placed blocks move to `PLACED` with `assigned_room_id` and
        `scheduling_run_id` set."
        PRD §3.4: "The bump cascade clears the event's `room_id` to null, voids
        its `PROVISIONAL` invoice in a full waiver when one exists, cancels all
        non-terminal service orders with `fee_waived` set true, and revokes its
        `REQUESTED` access grants."

        Design: Difficulty/combinatorial_formula/placement_evaluation_order_score_then_assign_then_bump
        """
        scn = setup_placement_contention()
        run = create_run(scn.term["id"])
        finalize_run(run["id"])

        bx = get_block(scn.bx["id"])
        assert bx["status"] == "PLACED"
        assert bx["assigned_room_id"] == scn.room["id"]
        assert bx["scheduling_run_id"] == run["id"]

        by = get_block(scn.by["id"])
        assert by["status"] == "UNPLACED"
        assert by["assigned_room_id"] is None

        event = get_event(scn.event["id"])
        assert event["status"] == "BUMPED"
        assert event["room_id"] is None


class TestUnplace:
    def test_unplace_does_not_restore_bumped_events(self, api):
        """PRD §3.3: "a `Scheduler` may unplace a `PLACED` block, clearing
        `assigned_room_id` and `scheduling_run_id` and returning it to
        `UNPLACED`. Events bumped by the original placement are not retroactively
        restored — they remain `BUMPED` and must be rebooked."

        Design: Corner/state_machines/unplace_leaves_bumped_events_bumped
        """
        scn = setup_placement_contention()
        run = create_run(scn.term["id"])
        finalize_run(run["id"])

        response = api.unplace_academic_block(scn.bx["id"], SCHEDULER)
        unplaced = validate_success(response, 200)
        assert unplaced["status"] == "UNPLACED"
        assert unplaced["assigned_room_id"] is None
        assert unplaced["scheduling_run_id"] is None

        event = get_event(scn.event["id"])
        assert event["status"] == "BUMPED", "no retroactive restore"
        assert event["room_id"] is None


class TestDoubleFinalize:
    def test_second_finalize_rejected_term_already_finalized(self, api):
        """PRD §3.3: "Finalizing a run requires the run to be `DRAFT`, the term
        to be in `SCHEDULING` (otherwise `ERR_TERM_PRIORITY_LOCKED`), and no
        other `FINALIZED` run to exist for the term (otherwise
        `ERR_TERM_ALREADY_FINALIZED`)."

        Design: Corner/validations/second_finalize_rejected_term_already_finalized
        """
        term = create_term()
        advance_term_to_scheduling(term["id"])

        run1 = create_run(term["id"])
        finalized = finalize_run(run1["id"])
        assert finalized["status"] == "FINALIZED"
        assert finalized["placed_count"] == 0

        run2 = create_run(term["id"])
        response = api.finalize_scheduling_run(run2["id"], SCHEDULER)
        validate_error(response, ApiErrorId.ERR_TERM_ALREADY_FINALIZED)

        assert get_run(run2["id"])["status"] == "DRAFT"
        assert get_run(run1["id"])["status"] == "FINALIZED"
