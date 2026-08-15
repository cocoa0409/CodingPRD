"""Pairing generation order, infeasibility, and room/judge assignment rules."""
from test_helpers import (
    TEST_USERS,
    begin_prelims,
    get_judge,
    get_pairing,
    get_round,
    pairing_members,
    schedule_rounds,
    setup_ballot_round,
    setup_conflict_priority_scenario,
    setup_judge_turnover_scenario,
    setup_registration_scenario,
    setup_room_adjacency_scenario,
    validate_error,
    validate_paginated,
    validate_success,
)

TAB = TEST_USERS["tabstaff_headers"]


class TestRoundOneOrdering:
    def test_round_one_pairing_follows_created_at_order(self, api):
        """PRD §3.4: "For a first-round preliminary debate, eligible entries are
        ordered by `created_at` ascending and paired adjacently — first with
        second, third with fourth, and so on."
        PRD §3.4: "within a debate pairing the first-ordered entry is `AFF` and
        the second is `NEG`".
        PRD §3.4: "Membership listings are sorted by `draw_position` ascending
        within a pairing".

        Design: Corner/calculations/round_one_pairing_created_at_order
        """
        ws = setup_ballot_round(stage="paired", name="R1")
        a1 = ws["entries"]["a"][0]
        b1 = ws["entries"]["b"][0]

        members = pairing_members(ws["p1"]["id"])
        assert len(members) == 2
        assert members[0]["entry_id"] == a1["id"], (
            "A1 was created before B1, so A1 leads the pairing")
        assert members[0]["side"] == "AFF"
        assert members[0]["draw_position"] == 1
        assert members[1]["entry_id"] == b1["id"]
        assert members[1]["side"] == "NEG"
        assert members[1]["draw_position"] == 2

        round_ = get_round(ws["round"]["id"])
        assert round_["status"] == "PAIRED"
        assert round_["pairings_total"] == 1


class TestPairingInfeasibility:
    def test_all_same_school_field_is_infeasible(self, api):
        """PRD §3.4: "Two hard constraints govern every preliminary debate
        arrangement: no pairing may match two entries of the same school, and no
        pairing may repeat a matchup that already occurred in an earlier `PRELIM`
        round of the division."
        PRD §3.4: "If no complete valid arrangement exists, the generate fails
        with `ERR_PAIRING_INFEASIBLE` and persists nothing."

        Design: Corner/validations/pairing_infeasible_all_same_school_rejected
        """
        ws = setup_registration_scenario(
            name="PI", prelim_round_count=4,
            schools=(
                {"key": "a", "name": "Alpha", "entries": {"d": 4},
                 "judges": [4, 4]},
                {"key": "b", "name": "Beta", "entries": {}, "judges": []},
            ))
        schedule_rounds(ws, {"d": [(1, "PRELIM", "2026-08-12T14:00:00Z",
                                    "2026-08-12T15:30:00Z")]})
        begin_prelims(ws)
        round_id = ws["rounds"]["d"][0]["id"]
        version = get_round(round_id)["version"]

        resp = api.generate_pairings(round_id, version, TAB)
        validate_error(resp, "ERR_PAIRING_INFEASIBLE")

        assert get_round(round_id)["status"] == "SCHEDULED", "no partial write"
        _data, meta = validate_paginated(
            api.list_pairings(TAB, params={"round_id": round_id}))
        assert meta["total_count"] == 0


class TestJudgeAssignmentCapacity:
    def test_assign_judge_increments_booking_and_staffs(self, api):
        """PRD §3.4: "A successful judge assignment increments the judge's
        `assigned_round_count` by one. When both `room_id` and `judge_id` are set,
        the pairing moves `PENDING_STAFFING` → `STAFFED`."

        Design: Difficulty/compensating_invariant/judge_assignment_capacity_conservation
        """
        ws = setup_ballot_round(stage="paired", name="Districts JC")
        judge_id = ws["staff_judge"]["id"]
        assert get_judge(judge_id)["assigned_round_count"] == 0

        validate_success(api.assign_room(ws["p1"]["id"], ws["rooms"][0]["id"], TAB))
        staffed = validate_success(
            api.assign_judge(ws["p1"]["id"], judge_id, TAB))
        assert staffed["status"] == "STAFFED", "room + judge both set"
        assert get_judge(judge_id)["assigned_round_count"] == 1

    def test_unassign_judge_compensates_exactly(self, api):
        """PRD §3.4: "Unassigning a judge — from a `PENDING_STAFFING` or `STAFFED`
        pairing — decrements `assigned_round_count` by one as compensation, and a
        `STAFFED` pairing that loses its staffing reverts to `PENDING_STAFFING`".

        Design: Difficulty/compensating_invariant/judge_assignment_capacity_conservation
        """
        ws = setup_ballot_round(stage="staffed", name="Districts JC")
        judge_id = ws["staff_judge"]["id"]
        assert get_judge(judge_id)["assigned_round_count"] == 1

        reverted = validate_success(api.unassign_judge(ws["p1"]["id"], TAB))
        assert reverted["status"] == "PENDING_STAFFING"
        assert reverted["judge_id"] is None, "the judge is removed from the pairing"

        assert get_judge(judge_id)["assigned_round_count"] == 0, (
            "bookings conserved: +1 then -1 returns to the exact prior value")
        _data, meta = validate_paginated(
            api.list_pairings(TAB, params={"judge_id": judge_id}))
        assert meta["total_count"] == 0


class TestConflictBeatsTurnover:
    def test_conflict_of_interest_reported_over_turnover(self, api):
        """PRD §3.4: "The conflict-of-interest check then comes before both the
        commitment-ceiling and turnover checks per §2.7: assigning a judge to a
        pairing that involves an entry of the judge's own school, or of any school
        recorded in that judge's `JudgeConflict` rows, is rejected with
        `ERR_JUDGE_CONFLICT_OF_INTEREST` (HTTP 409)."
        PRD §2.7: "the conflict-of-interest check (`ERR_JUDGE_CONFLICT_OF_INTEREST`)
        is evaluated before the buffered turnover check
        (`ERR_JUDGE_TURNOVER_CONFLICT`), so a conflicted judge is always reported
        as a conflict rather than a scheduling clash."

        Design: Difficulty/priority_pair_validation_conflict/judge_conflict_beats_turnover_on_assign
        """
        ws = setup_conflict_priority_scenario()
        # J-Alpha staffs the LD pairing (15:45 start, 15 minutes after the CX
        # round ends) and now violates both rules on the CX pairing, which
        # contains Alpha's own entry.
        resp = api.assign_judge(ws["p_cx"]["id"], ws["j_a"]["id"], TAB)
        validate_error(resp, "ERR_JUDGE_CONFLICT_OF_INTEREST")

        pairing = get_pairing(ws["p_cx"]["id"])
        assert pairing["judge_id"] is None, "no assignment persisted"

    def test_rejected_assignment_does_not_touch_booking_count(self, api):
        """PRD §3.4: "A successful judge assignment increments the judge's
        `assigned_round_count` by one."
        PRD §2.7: "the conflict-of-interest check (`ERR_JUDGE_CONFLICT_OF_INTEREST`)
        is evaluated before the buffered turnover check
        (`ERR_JUDGE_TURNOVER_CONFLICT`)".

        Design: Difficulty/priority_pair_validation_conflict/judge_conflict_beats_turnover_on_assign
        """
        ws = setup_conflict_priority_scenario()
        validate_error(api.assign_judge(ws["p_cx"]["id"], ws["j_a"]["id"], TAB),
                       "ERR_JUDGE_CONFLICT_OF_INTEREST")
        judge = get_judge(ws["j_a"]["id"])
        assert judge["assigned_round_count"] == 1, (
            "only the LD pairing holds the judge; the rejected CX assign kept "
            "the count at its prior value")


class TestRoomHalfOpenIntervals:
    def test_touching_slots_share_a_room(self, api):
        """PRD §3.4: "Slots that merely touch — one's end equal to the other's
        start — do not overlap; there is no buffer requirement between room
        bookings."

        Design: Difficulty/resource_temporal_overlap/room_half_open_interval_adjacency
        """
        ws = setup_room_adjacency_scenario()
        # p1 (CX) holds the room 14:00-15:30; p3 (LD) runs 15:30-17:00.
        assigned = validate_success(
            api.assign_room(ws["p3"]["id"], ws["room"]["id"], TAB))
        assert assigned["room_id"] == ws["room"]["id"], (
            "end == start is non-overlapping under half-open [start, end) slots")

    def test_overlapping_slot_rejected(self, api):
        """PRD §3.4: "Assigning a room is rejected with `ERR_ROOM_DOUBLE_BOOKED`
        (HTTP 409) exactly when another pairing in the same tournament already
        holds that room on a slot that overlaps under half-open interval
        semantics: the existing slot's `starts_at` is strictly earlier than the
        new slot's `ends_at` and the new slot's `starts_at` is strictly earlier
        than the existing slot's `ends_at`."

        Design: Difficulty/resource_temporal_overlap/room_half_open_interval_adjacency
        """
        ws = setup_room_adjacency_scenario()
        # p2 (CX) runs 14:00-15:30, strictly overlapping p1's slot in that room.
        resp = api.assign_room(ws["p2"]["id"], ws["room"]["id"], TAB)
        validate_error(resp, "ERR_ROOM_DOUBLE_BOOKED")
        assert get_pairing(ws["p2"]["id"])["room_id"] is None


class TestJudgeTurnoverBuffer:
    def test_fifteen_minute_gap_rejected(self, api):
        """PRD §3.4: "the turnover rule rejects the assignment with
        `ERR_JUDGE_TURNOVER_CONFLICT` (HTTP 409) when any other pairing staffed by
        the same judge has a slot that overlaps the new slot or is separated from
        it by a gap of less than 30 minutes on either side; a gap of exactly 30
        minutes is allowed."

        Design: Difficulty/resource_temporal_overlap/judge_buffered_turnover_gap
        """
        ws = setup_judge_turnover_scenario()
        # J-Delta staffs CX (ends 15:30); LD starts 15:45 — a 15-minute gap.
        resp = api.assign_judge(ws["p_ld"]["id"], ws["j_d"]["id"], TAB)
        validate_error(resp, "ERR_JUDGE_TURNOVER_CONFLICT")
        assert get_judge(ws["j_d"]["id"])["assigned_round_count"] == 1

    def test_exactly_thirty_minute_gap_allowed(self, api):
        """PRD §3.4: "a gap of exactly 30 minutes is allowed."
        PRD §3.4: "A successful judge assignment increments the judge's
        `assigned_round_count` by one."

        Design: Difficulty/resource_temporal_overlap/judge_buffered_turnover_gap
        """
        ws = setup_judge_turnover_scenario()
        # PF starts 16:00 — exactly 30 minutes after the 15:30 CX end.
        assigned = validate_success(
            api.assign_judge(ws["p_pf"]["id"], ws["j_d"]["id"], TAB))
        assert assigned["judge_id"] == ws["j_d"]["id"]
        assert get_judge(ws["j_d"]["id"])["assigned_round_count"] == 2


class TestGeneratePairingsOcc:
    def test_stale_round_version_rejected(self, api):
        """PRD §2.6: "Generating pairings for a round requires
        `expected_round_version` equal to the round's current `version`."
        PRD §2.6: "The concurrency check is evaluated before any entity-state
        precondition on the same request, so a stale view is always reported as
        HTTP 412 rather than being masked by a 409 state error."

        Design: Corner/cross_cutting_layers/occ_generate_pairings_stale_round_rejected
        """
        ws = setup_ballot_round(stage="paired", name="OG")
        round_id = ws["round"]["id"]
        stale_version = ws["round"]["version"]  # captured before generation

        resp = api.generate_pairings(round_id, stale_version, TAB)
        validate_error(resp, "ERR_STALE_VERSION")

        round_ = get_round(round_id)
        assert round_["status"] == "PAIRED"
        assert round_["pairings_total"] == 1, "no duplicate generation"
