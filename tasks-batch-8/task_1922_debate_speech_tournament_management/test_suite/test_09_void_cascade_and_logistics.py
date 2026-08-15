"""Ballot-void cascade (pairing -> round -> standings) and hosting logistics."""
from test_helpers import (
    LOCK_DAY,
    TEST_USERS,
    add_division,
    add_entry,
    confirm_entry,
    confirm_school,
    create_order,
    create_tournament,
    get_entry,
    get_order,
    get_pairing,
    get_round,
    lock_tournament,
    open_registration,
    set_clock,
    setup_catering_freeze_scenario,
    setup_four_school_ballot_round,
    start_prelims,
    submit_order,
    validate_error,
    void_ballot,
)

DIRECTOR = TEST_USERS["director_headers"]
TAB = TEST_USERS["tabstaff_headers"]


class TestBallotVoidCascade:
    def _tabulated_scenario(self):
        """Round 1 fully verified and tabulated: p1 (A1,B1) A1 wins 28/26;
        p2 (C1,D1) C1 wins 27/25."""
        return setup_four_school_ballot_round(
            stage="tabulated", name="Districts BV",
            plans=(("first", 28, 26), ("first", 27, 25)))

    def test_void_reverts_pairing_and_reopens_round(self, api):
        """PRD §3.5: "A void fires a three-link cascade: the pairing reverts
        `VERIFIED` → `BALLOT_RELEASED` with its winner cleared and
        `pairings_verified_count` decremented; if the pairing's round was already
        `TABULATED`, the round auto-reverts `TABULATED` → `BALLOTS_OPEN`
        (incrementing the round's `version`) so a replacement ballot can be
        entered".

        Design: Difficulty/transitive_cascade/ballot_void_reopens_round_and_recomputes_standings
        """
        ws = self._tabulated_scenario()
        ballot = ws["ballots"][0]
        assert get_round(ws["round"]["id"])["status"] == "TABULATED"

        voided = void_ballot(ballot["id"])
        assert voided["status"] == "VOIDED"

        pairing = get_pairing(ws["p1"]["id"])
        assert pairing["status"] == "BALLOT_RELEASED", "link 1: pairing reverts"
        assert pairing["winner_entry_id"] is None, "winner cleared"

        round_ = get_round(ws["round"]["id"])
        assert round_["status"] == "BALLOTS_OPEN", (
            "link 2: the tabulated round auto-reopens")
        assert round_["pairings_verified_count"] == 1

    def test_void_excludes_ballot_from_entry_stats(self, api):
        """PRD §3.5: "every affected entry's statistics are recomputed excluding
        the `VOIDED` ballot — wins, `speaker_points_raw` and
        `speaker_points_adjusted`, `rank_points_raw` and `rank_points_adjusted`,
        `opponent_strength`, and `prelim_rank` all refreshed."
        PRD §3.5: "The entry's `speaker_points_raw` is the plain sum of all
        contributions."

        Design: Difficulty/transitive_cascade/ballot_void_reopens_round_and_recomputes_standings
        """
        ws = self._tabulated_scenario()
        a1 = ws["entries"]["a"][0]
        before = get_entry(a1["id"])
        assert before["wins"] == 1 and before["speaker_points_raw"] == 28

        void_ballot(ws["ballots"][0]["id"])

        after = get_entry(a1["id"])
        assert after["wins"] == 0, "link 3: the voided win no longer counts"
        assert after["speaker_points_raw"] == 0
        assert after["speaker_points_adjusted"] == 0


class TestCateringFreeze:
    def test_submit_freezes_meal_count(self, api):
        """PRD §3.8: "A catering order's `headcount_demand` is the number of the
        tournament's entries in `COMPETING`, `ADVANCED`, `ELIMINATED`, or
        `FINISHED`, plus the number of its `COMMITTED` judges, plus the
        tournament's `tournament_staff_count`. Its `meal_count` adds a ten percent
        buffer and rounds up to a whole meal."
        PRD §3.8: "Submitting an order moves it `DRAFT` → `SUBMITTED` (from any
        other state, `ERR_ORDER_INVALID_STATE`) and freezes the demand:
        `frozen_meal_count` snapshots the live `meal_count` and
        `frozen_awards_count` snapshots the live `awards_count`. After submission
        the live fields keep recomputing as the graph mutates, but the frozen
        fields never change."

        Design: Corner/state_machines/catering_order_submit_freezes_counts
        """
        ws = setup_catering_freeze_scenario()
        order = get_order(ws["order"]["id"])
        # 0 competing entries + 2 COMMITTED judges + 10 staff = 12; ceil(13.2) = 14.
        assert order["headcount_demand"] == 12
        assert order["meal_count"] == 14

        submitted = submit_order(order["id"])
        assert submitted["status"] == "SUBMITTED"
        assert submitted["frozen_meal_count"] == 14, "demand frozen at submit"

        # Drive one entry into COMPETING: live demand moves, frozen does not.
        school_id = ws["schools"]["a"]["id"]
        entry = add_entry(school_id, ws["divisions"]["d"]["id"], "A-One")
        confirm_entry(entry["id"], school_id)
        confirm_school(school_id)
        set_clock(LOCK_DAY)
        lock_tournament(ws["t"]["id"])
        start_prelims(ws["t"]["id"])

        after = get_order(order["id"])
        # ceil((1 + 2 + 10) * 1.10) = ceil(14.3) = 15 live; frozen stays 14.
        assert after["meal_count"] == 15
        assert after["frozen_meal_count"] == 14


class TestOrderStateAndUniqueness:
    def test_awards_submit_requires_breaks(self, api):
        """PRD §3.8: "Submitting an awards order additionally requires the
        tournament to be `ELIMS_ACTIVE` or `COMPLETED` and every division with a
        `competing_entry_count` of at least 2 to have its `bracket_size` set
        (otherwise `ERR_BREAKS_NOT_DETERMINED`)."

        Design: Corner/state_machines/awards_order_submit_requires_breaks
        """
        tournament = create_tournament(name="AW")
        add_division(tournament["id"])
        open_registration(tournament["id"])
        order = create_order(tournament["id"], "AWARDS")

        resp = api.submit_order(order["id"], DIRECTOR)
        validate_error(resp, "ERR_BREAKS_NOT_DETERMINED")
        fetched = get_order(order["id"])
        assert fetched["status"] == "DRAFT"
        assert fetched["frozen_awards_count"] is None

    def test_second_catering_order_rejected(self, api):
        """PRD §3.8: "At most one non-`FULFILLED` order of each kind may exist per
        tournament; a conflicting create is rejected with `ERR_ORDER_KIND_EXISTS`
        (HTTP 409)."

        Design: Corner/state_machines/second_catering_order_rejected
        """
        tournament = create_tournament(name="OC")
        create_order(tournament["id"], "CATERING")
        resp = api.create_order(
            {"tournament_id": tournament["id"], "kind": "CATERING"}, DIRECTOR)
        validate_error(resp, "ERR_ORDER_KIND_EXISTS")

    def test_fulfill_draft_order_rejected(self, api):
        """PRD §3.8: "Fulfilling moves a `SUBMITTED` order to `FULFILLED`
        (otherwise `ERR_ORDER_INVALID_STATE`)."

        Design: Corner/state_machines/fulfill_draft_order_rejected
        """
        tournament = create_tournament(name="FD")
        order = create_order(tournament["id"], "CATERING")
        resp = api.fulfill_order(order["id"], DIRECTOR)
        validate_error(resp, "ERR_ORDER_INVALID_STATE")
        assert get_order(order["id"])["status"] == "DRAFT"
