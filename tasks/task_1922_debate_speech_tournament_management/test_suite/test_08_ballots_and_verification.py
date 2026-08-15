"""Ballot lifecycle: content validity, submit gating, recall cycle, verification."""
from test_helpers import (
    AFTER_BALLOT_WINDOW,
    TEST_USERS,
    create_debate_ballot,
    create_speech_ballot,
    get_ballot,
    get_pairing,
    get_round,
    make_judge_headers,
    open_round,
    pairing_members,
    recall_ballot,
    setup_ballot_round,
    setup_bye_ballot_round,
    setup_four_school_ballot_round,
    set_clock,
    submit_ballot,
    validate_error,
    validate_paginated,
    verify_ballot,
)

TAB = TEST_USERS["tabstaff_headers"]


class TestBallotRecallCycle:
    def test_submit_recall_submit_cycle(self, api):
        """PRD §3.5: "A judge may recall a submitted ballot — `SUBMITTED` →
        `DRAFT`, otherwise `ERR_BALLOT_INVALID_STATE` — which reverts the pairing
        to `BALLOT_RELEASED`."
        PRD §3.5: "A successful submission moves the pairing `BALLOT_RELEASED` →
        `BALLOT_SUBMITTED` and stamps `submitted_at`".

        Design: Difficulty/non_linear_state_machine/ballot_draft_submit_recall_cycle
        """
        ws = setup_four_school_ballot_round(stage="open", name="Districts BC")
        judge_id = ws["staff_judges"][0]["id"]
        members = pairing_members(ws["p1"]["id"])
        winner, loser = members[0]["entry_id"], members[1]["entry_id"]

        ballot = create_debate_ballot(ws["p1"]["id"], judge_id, winner,
                                      {winner: 30, loser: 26})
        assert ballot["status"] == "DRAFT"

        ballot = submit_ballot(ballot["id"], judge_id)
        assert ballot["status"] == "SUBMITTED"
        assert get_pairing(ws["p1"]["id"])["status"] == "BALLOT_SUBMITTED"

        ballot = recall_ballot(ballot["id"], judge_id)
        assert ballot["status"] == "DRAFT", "recall cycles the ballot back"
        assert get_pairing(ws["p1"]["id"])["status"] == "BALLOT_RELEASED", (
            "the pairing mirrors the cycle")

        ballot = submit_ballot(ballot["id"], judge_id)
        assert ballot["status"] == "SUBMITTED", "a second submit succeeds"

    def test_verify_sets_pairing_winner(self, api):
        """PRD §3.5: "`TabStaff` verifies a `SUBMITTED` ballot — otherwise
        `ERR_BALLOT_INVALID_STATE` — moving it to `VERIFIED`; the pairing moves
        `BALLOT_SUBMITTED` → `VERIFIED`, the round's `pairings_verified_count`
        increments, and for debate the pairing's `winner_entry_id` is set from the
        ballot."

        Design: Difficulty/non_linear_state_machine/ballot_draft_submit_recall_cycle
        """
        ws = setup_four_school_ballot_round(stage="open", name="Districts BC")
        judge_id = ws["staff_judges"][0]["id"]
        members = pairing_members(ws["p1"]["id"])
        winner, loser = members[0]["entry_id"], members[1]["entry_id"]

        ballot = create_debate_ballot(ws["p1"]["id"], judge_id, winner,
                                      {winner: 30, loser: 26})
        submit_ballot(ballot["id"], judge_id)
        verified = verify_ballot(ballot["id"])
        assert verified["status"] == "VERIFIED"

        pairing = get_pairing(ws["p1"]["id"])
        assert pairing["status"] == "VERIFIED"
        assert pairing["winner_entry_id"] == winner


class TestSubmitGatedByPairingRelease:
    def test_submit_rejected_until_pairing_released(self, api):
        """PRD §3.5: "The ballot must be `DRAFT` (otherwise
        `ERR_BALLOT_INVALID_STATE`), and the pairing must be `BALLOT_RELEASED` — a
        cross-entity gate whose failure surfaces as `ERR_PAIRING_INVALID_STATE`".

        Design: Difficulty/cross_entity_state_dependency/ballot_submit_gated_by_pairing_release
        """
        ws = setup_ballot_round(stage="staffed", name="Districts BG")
        judge_id = ws["staff_judge"]["id"]
        members = pairing_members(ws["p1"]["id"])
        winner, loser = members[0]["entry_id"], members[1]["entry_id"]
        ballot = create_debate_ballot(ws["p1"]["id"], judge_id, winner,
                                      {winner: 27, loser: 25})
        assert get_pairing(ws["p1"]["id"])["status"] == "STAFFED"

        resp = api.submit_ballot(ballot["id"], make_judge_headers(judge_id))
        validate_error(resp, "ERR_PAIRING_INVALID_STATE")
        assert get_ballot(ballot["id"])["status"] == "DRAFT"

    def test_submit_succeeds_after_open_ballots_cascade(self, api):
        """PRD §3.4: "Opening cascades every non-bye pairing `STAFFED` →
        `BALLOT_RELEASED` and increments the round's `version`."
        PRD §3.5: "A successful submission moves the pairing `BALLOT_RELEASED` →
        `BALLOT_SUBMITTED`".

        Design: Difficulty/cross_entity_state_dependency/ballot_submit_gated_by_pairing_release
        """
        ws = setup_ballot_round(stage="staffed", name="Districts BG")
        judge_id = ws["staff_judge"]["id"]
        members = pairing_members(ws["p1"]["id"])
        winner, loser = members[0]["entry_id"], members[1]["entry_id"]
        ballot = create_debate_ballot(ws["p1"]["id"], judge_id, winner,
                                      {winner: 27, loser: 25})

        open_round(ws["round"]["id"])
        assert get_pairing(ws["p1"]["id"])["status"] == "BALLOT_RELEASED"

        submitted = submit_ballot(ballot["id"], judge_id)
        assert submitted["status"] == "SUBMITTED"
        assert get_pairing(ws["p1"]["id"])["status"] == "BALLOT_SUBMITTED"


class TestSpeakerPointRange:
    def test_thirty_points_accepted_at_upper_boundary(self, api):
        """PRD §3.5: "a `speaker_points` map from each pairing member's entry id
        to an integer score between 20 and 30 inclusive; every pairing member must
        be present in the map, and a missing or out-of-range score yields
        `ERR_SPEAKER_POINTS_OUT_OF_RANGE` (HTTP 422)".

        Design: Difficulty/boundary_precision_check/speaker_point_range_boundary
        """
        ws = setup_four_school_ballot_round(stage="open", name="Districts SR")
        judge_id = ws["staff_judges"][0]["id"]
        members = pairing_members(ws["p1"]["id"])
        winner, loser = members[0]["entry_id"], members[1]["entry_id"]

        ballot = create_debate_ballot(ws["p1"]["id"], judge_id, winner,
                                      {winner: 30, loser: 26})
        assert ballot["status"] == "DRAFT", "30 is inside the inclusive range"
        submitted = submit_ballot(ballot["id"], judge_id)
        assert submitted["status"] == "SUBMITTED"

    def test_thirty_one_and_nineteen_rejected(self, api):
        """PRD §3.5: "a `speaker_points` map from each pairing member's entry id
        to an integer score between 20 and 30 inclusive; every pairing member must
        be present in the map, and a missing or out-of-range score yields
        `ERR_SPEAKER_POINTS_OUT_OF_RANGE` (HTTP 422)".
        PRD §3.5: "Field validity runs at creation and again at submission."

        Design: Difficulty/boundary_precision_check/speaker_point_range_boundary
        """
        ws = setup_four_school_ballot_round(stage="open", name="Districts SR")
        judge_id = ws["staff_judges"][1]["id"]
        members = pairing_members(ws["p2"]["id"])
        winner, loser = members[0]["entry_id"], members[1]["entry_id"]
        judge = make_judge_headers(judge_id)

        resp_high = api.create_ballot(
            {"pairing_id": ws["p2"]["id"], "winner_entry_id": winner,
             "speaker_points": {winner: 31, loser: 25}}, judge)
        validate_error(resp_high, "ERR_SPEAKER_POINTS_OUT_OF_RANGE")

        # 19 is below the range; the out-of-range score sits on the loser so
        # the low-point-win check (which outranks field validity per §2.7) is
        # not triggered and the range rule surfaces.
        resp_low = api.create_ballot(
            {"pairing_id": ws["p2"]["id"], "winner_entry_id": winner,
             "speaker_points": {winner: 25, loser: 19}}, judge)
        validate_error(resp_low, "ERR_SPEAKER_POINTS_OUT_OF_RANGE")

        _data, meta = validate_paginated(
            api.list_ballots(TAB, params={"pairing_id": ws["p2"]["id"]}))
        assert meta["total_count"] == 0, "rejected ballots persisted nothing"


class TestLowPointWinFlag:
    def test_low_point_win_requires_flag(self, api):
        """PRD §3.5: "Debate enforces the point-win rule: the winner's total
        speaker points must be at least the loser's total, unless the ballot
        carries `allow_low_point_win` set to true. A ballot awarding the win to
        the lower-speaker-point entry without the flag is rejected with
        `ERR_LOW_POINT_WIN_NOT_FLAGGED` (HTTP 422), and like the field-validity
        rules this check runs both when the ballot is created and again when it is
        submitted".

        Design: Corner/validations/low_point_win_requires_flag
        """
        ws = setup_ballot_round(stage="open", name="LP")
        judge_id = ws["staff_judge"]["id"]
        members = pairing_members(ws["p1"]["id"])
        m1, m2 = members[0]["entry_id"], members[1]["entry_id"]
        judge = make_judge_headers(judge_id)

        # Winner m1 scores 24 < loser m2's 26: the flag is required.
        resp = api.create_ballot(
            {"pairing_id": ws["p1"]["id"], "winner_entry_id": m1,
             "speaker_points": {m1: 24, m2: 26}}, judge)
        validate_error(resp, "ERR_LOW_POINT_WIN_NOT_FLAGGED")

        ballot = create_debate_ballot(ws["p1"]["id"], judge_id, m1,
                                      {m1: 24, m2: 26}, allow_low_point_win=True)
        assert ballot["status"] == "DRAFT"
        submitted = submit_ballot(ballot["id"], judge_id)
        assert submitted["status"] == "SUBMITTED"


class TestSpeechBallotRanks:
    def test_rank_range_and_uniqueness_validated(self, api):
        """PRD §3.5: "A speech ballot carries a `ranks` map from each section
        member's entry id to an integer rank between 1 and the section size
        inclusive; every section member must be present and in range (otherwise
        `ERR_RANK_INVALID`, HTTP 422), and two members sharing a rank in one
        ballot yields `ERR_DUPLICATE_RANK_IN_SECTION` (HTTP 422)."
        PRD §3.4: "Every pairing derives its `format` from its division's
        `event_type`: `HEAD_TO_HEAD` for debate, `SECTION` for speech."

        Design: Corner/validations/speech_ballot_rank_and_duplicate_validation
        """
        ws = setup_ballot_round(stage="open", name="SK", event=("SPEECH", "OO"))
        judge_id = ws["staff_judge"]["id"]
        assert get_pairing(ws["p1"]["id"])["format"] == "SECTION"
        members = pairing_members(ws["p1"]["id"])
        m1, m2 = members[0]["entry_id"], members[1]["entry_id"]
        judge = make_judge_headers(judge_id)

        dup = api.create_ballot({"pairing_id": ws["p1"]["id"],
                                 "ranks": {m1: 1, m2: 1}}, judge)
        validate_error(dup, "ERR_DUPLICATE_RANK_IN_SECTION")

        out_of_range = api.create_ballot({"pairing_id": ws["p1"]["id"],
                                          "ranks": {m1: 1, m2: 3}}, judge)
        validate_error(out_of_range, "ERR_RANK_INVALID")

        ballot = create_speech_ballot(ws["p1"]["id"], judge_id, {m1: 1, m2: 2})
        assert ballot["status"] == "DRAFT"


class TestWinnerMembership:
    def test_winner_not_in_pairing_rejected(self, api):
        """PRD §3.5: "A debate ballot carries a `winner_entry_id`, which must be a
        member of the pairing (otherwise `ERR_WINNER_NOT_IN_PAIRING`, HTTP 422)".

        Design: Corner/validations/winner_not_in_pairing_rejected
        """
        ws = setup_bye_ballot_round(stage="open", name="WN")
        judge_id = ws["staff_judge"]["id"]
        members = pairing_members(ws["p1"]["id"])
        m1, m2 = members[0]["entry_id"], members[1]["entry_id"]
        bye_entry = ws["entries"]["c"][0]  # C1 received the round-1 bye

        resp = api.create_ballot(
            {"pairing_id": ws["p1"]["id"], "winner_entry_id": bye_entry["id"],
             "speaker_points": {m1: 27, m2: 25}},
            make_judge_headers(judge_id))
        validate_error(resp, "ERR_WINNER_NOT_IN_PAIRING")

        _data, meta = validate_paginated(
            api.list_ballots(TAB, params={"pairing_id": ws["p1"]["id"]}))
        assert meta["total_count"] == 0


class TestBallotWindow:
    def test_submit_after_window_closed_rejected(self, api):
        """PRD §2.5: "Submitting a ballot requires the current logical UTC to be
        at or before the round's `ends_at` plus a grace period of 60 minutes,
        otherwise it fails with `ERR_BALLOT_WINDOW_CLOSED` (HTTP 409)."

        Design: Corner/validations/ballot_window_closed_rejected
        """
        ws = setup_ballot_round(stage="open", name="BW")
        judge_id = ws["staff_judge"]["id"]
        members = pairing_members(ws["p1"]["id"])
        winner, loser = members[0]["entry_id"], members[1]["entry_id"]
        ballot = create_debate_ballot(ws["p1"]["id"], judge_id, winner,
                                      {winner: 27, loser: 25})

        # Round ends 15:30; the deadline is 16:30. 16:31 is one minute past.
        set_clock(AFTER_BALLOT_WINDOW)
        resp = api.submit_ballot(ballot["id"], make_judge_headers(judge_id))
        validate_error(resp, "ERR_BALLOT_WINDOW_CLOSED")
        assert get_ballot(ballot["id"])["status"] == "DRAFT"


class TestVerificationGates:
    def test_void_submitted_ballot_rejected(self, api):
        """PRD §3.5: "Voiding is the correction path: `TabStaff` voids a
        `VERIFIED` ballot, moving it to its terminal `VOIDED` state."
        PRD §2.7: "the per-entity state errors `ERR_SCHOOL_INVALID_STATE`,
        `ERR_ENTRY_INVALID_STATE`, `ERR_JUDGE_INVALID_STATE`,
        `ERR_ROUND_INVALID_STATE`, `ERR_PAIRING_INVALID_STATE`,
        `ERR_BALLOT_INVALID_STATE`, `ERR_CONTRACT_INVALID_STATE`, and
        `ERR_ORDER_INVALID_STATE`".

        Design: Corner/state_machines/void_submitted_ballot_rejected
        """
        ws = setup_ballot_round(stage="submitted", name="VS")
        ballot = ws["ballot"]
        resp = api.void_ballot(ballot["id"], TAB)
        validate_error(resp, "ERR_BALLOT_INVALID_STATE")
        assert get_ballot(ballot["id"])["status"] == "SUBMITTED"
        assert get_pairing(ws["p1"]["id"])["status"] == "BALLOT_SUBMITTED"

    def test_judge_cannot_verify_own_ballot(self, api):
        """PRD §2.1: "A `Judge` creates, submits, and recalls ballots only for
        pairings assigned to them; verification of any ballot is performed by
        `TabStaff`, never by the judge who submitted it."
        PRD §2.1: "a request whose role is not in the target endpoint's authorized
        role list is rejected with `ERR_FORBIDDEN` (HTTP 403)."

        Design: Corner/rbac/judge_cannot_verify_ballot_forbidden
        """
        ws = setup_ballot_round(stage="submitted", name="JV")
        ballot = ws["ballot"]
        resp = api.verify_ballot(ballot["id"],
                                 make_judge_headers(ws["staff_judge"]["id"]))
        validate_error(resp, "ERR_FORBIDDEN")
        assert get_ballot(ballot["id"])["status"] == "SUBMITTED"

    def test_tabulate_requires_all_pairings_verified(self, api):
        """PRD §3.5: "Tabulating a round moves it `BALLOTS_OPEN` → `TABULATED` and
        requires every pairing of the round to be `VERIFIED` (otherwise
        `ERR_ROUND_INVALID_STATE`)."

        Design: Corner/state_machines/round_tabulate_requires_all_verified_rejected
        """
        ws = setup_ballot_round(stage="submitted", name="TV")
        resp = api.tabulate_round(ws["round"]["id"], TAB)
        validate_error(resp, "ERR_ROUND_INVALID_STATE")
        assert get_round(ws["round"]["id"])["status"] == "BALLOTS_OPEN", (
            "the submitted-but-unverified pairing blocks tabulation")
