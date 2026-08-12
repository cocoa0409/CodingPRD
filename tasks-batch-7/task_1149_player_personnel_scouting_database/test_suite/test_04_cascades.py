"""Transitive cascades (PRD §3.3 lock cascade, §3.6 exclusion cascade)."""
import pytest

from test_helpers import (
    MED_HEADERS,
    add_board_entry,
    advance_prospect,
    api_client,
    create_and_lock_report,
    create_director,
    create_draft_board,
    create_flag,
    create_prospect,
    create_report,
    create_scout,
    director_headers,
    get_board,
    get_success_data,
    list_board_entries,
    lock_report,
    make_board_ready_prospect,
    submit_report,
    validate_success,
)


class TestReportLockCascadeToBoard:
    """Difficulty: transitive_cascade/report_lock_cascade_to_board.

    Setup yields: p1 composite 6.50 (scout s1 raw 7.00, mean 6.00 sd 1.00);
    p2 composite 6.00 (scout s2 raw 7.00, mean 6.00 sd 1.50). p2 then gets a
    second submitted report from s3 (raw 9.00, sd 1.50 -> normalized 8.00).
    Both prospects BOARD_READY and on the board (version 3). Locking the
    second p2 report lifts p2's composite to (0.5*6.00 -> 3.00) + (0.5*8.00
    -> 4.00) = 7.00 and swaps ranks.
    """

    def _setup(self):
        s1 = create_scout(level="AREA", full_name="S1", weight=1.0,
                          season_grade_mean=6.00, season_grade_stdev=1.00)
        s2 = create_scout(level="AREA", full_name="S2", weight=1.0,
                          season_grade_mean=6.00, season_grade_stdev=1.50)
        s3 = create_scout(level="AREA", full_name="S3", weight=1.0,
                          season_grade_mean=6.00, season_grade_stdev=1.50)
        d1 = create_director(full_name="Dir One")
        p1 = create_prospect(s1, full_name="P One", position="QB", college="State U")
        p2 = create_prospect(s2, full_name="P Two", position="WR", college="Tech")
        create_and_lock_report(p1["id"], s1, d1, raw_grade=7.00, scheme_fit=1.00)
        create_and_lock_report(p2["id"], s2, d1, raw_grade=7.00, scheme_fit=1.00)
        r3 = create_report(p2["id"], s3, raw_grade=9.00, scheme_fit=1.00)
        submit_report(r3["id"], s3)
        advance_prospect(p1["id"], "EVALUATED", d1)
        advance_prospect(p1["id"], "BOARD_READY", d1)
        advance_prospect(p2["id"], "EVALUATED", d1)
        advance_prospect(p2["id"], "BOARD_READY", d1)
        b1 = create_draft_board(d1, season_year=2026)
        add_board_entry(b1["id"], p1["id"], d1)
        add_board_entry(b1["id"], p2["id"], d1)
        board_before = get_board(b1["id"], d1)
        return s1, s2, s3, d1, p1, p2, r3, b1, board_before

    def test_lock_recomputes_composite_and_normalized(self, api):
        """PRD §3.3: "When the director locks a report, four cascades run in
        order: 1. The report's `normalized_grade` is computed... 2. The
        prospect's `composite_grade` and `tier` are recomputed." s3's raw 9.00
        with mean 6.00 sd 1.50 -> normalized 5.0+1.5*2.0 = 8.00. p2's
        composite over two locked reports of equal weight 1.0: 0.5*6.00 ->
        3.00 and 0.5*8.00 -> 4.00, sum 7.00.

        Design: Difficulty/transitive_cascade/report_lock_cascade_to_board
        """
        _, _, _, d1, _, p2, r3, _, _ = self._setup()
        n3 = lock_report(r3["id"], d1)["normalized_grade"]
        assert n3 == pytest.approx(8.00, abs=0.005)
        prospect = get_success_data(api_client.get_prospect(p2["id"], director_headers(d1)))
        assert prospect["composite_grade"] == pytest.approx(7.00, abs=0.005)

    def test_lock_reranks_board_and_bumps_version(self, api):
        """PRD §3.3 steps 3-4: "Every `DraftBoardEntry` for this prospect that
        is still `active` on a board whose `status` is `OPEN` has its
        `fit_score` recomputed per §3.5, and the rerank runs on each affected
        board. Each reranked board's `version` is incremented by 1". Raising
        p2's composite from 6.00 to 7.00 makes p2 outrank p1 (6.50); board
        version goes 3 -> 4.

        Design: Difficulty/transitive_cascade/report_lock_cascade_to_board
        """
        _, _, _, d1, p1, p2, r3, b1, board_before = self._setup()
        bv_pre = board_before["version"]
        assert bv_pre == 3, f"expected board version 3 after two entry adds, got {bv_pre}"
        lock_report(r3["id"], d1)
        entries = list_board_entries(b1["id"], d1)
        assert entries[0]["prospect_id"] == p2["id"] and entries[0]["rank"] == 1
        assert entries[1]["prospect_id"] == p1["id"] and entries[1]["rank"] == 2
        board_after = get_board(b1["id"], d1)
        assert board_after["version"] == bv_pre + 1 == 4


class TestFlagEscalationExclusionCascade:
    """Difficulty: transitive_cascade/flag_escalation_exclusion_cascade.

    Setup: p1 composite 6.50 (raw 7.00, mean 6.00 sd 1.00); p2 composite 9.00
    (raw 9.00 -> z=3.0 -> 9.50 clamps to 9.00). Both BOARD_READY on an OPEN
    board; after rerank p2 rank 1, p1 rank 2 (board version 3). One OPEN HIGH
    MEDICAL flag on p1; escalating it excludes p1, deactivates p1's entry,
    compacts ranks, and bumps the board version to 4.
    """

    def _setup(self):
        s1 = create_scout(level="AREA", full_name="S1", weight=1.0,
                          season_grade_mean=6.00, season_grade_stdev=1.00)
        d1 = create_director(full_name="Dir One")
        p1 = make_board_ready_prospect(s1, d1, raw_grade=7.00, full_name="Risky", position="QB", college="State U")
        p2 = make_board_ready_prospect(s1, d1, raw_grade=9.00, full_name="Clean", position="WR", college="Tech")
        b1 = create_draft_board(d1, season_year=2026)
        add_board_entry(b1["id"], p1["id"], d1)
        add_board_entry(b1["id"], p2["id"], d1)
        f1 = create_flag(p1["id"], MED_HEADERS,
                         flag_type="MEDICAL", severity="HIGH", detail="degenerative knee")
        return s1, d1, p1, p2, b1, f1

    def test_escalation_excludes_prospect(self, api):
        """PRD §3.6: "the prospect's `flag_status` becomes `EXCLUDED`; every
        `DraftBoardEntry` for this prospect on a board whose `status` is
        `OPEN` or `FROZEN` has its `active` flag set to `false`".

        Design: Difficulty/transitive_cascade/flag_escalation_exclusion_cascade
        """
        _, d1, p1, _, _, f1 = self._setup()
        resp = api_client.escalate_flag(f1["id"], director_headers(d1))
        escalated = validate_success(resp)
        assert escalated["status"] == "ESCALATED"
        prospect = get_success_data(api_client.get_prospect(p1["id"], director_headers(d1)))
        assert prospect["flag_status"] == "EXCLUDED"

    def test_escalation_deactivates_entry_compacts_and_bumps_board_version(self, api):
        """PRD §3.6: "the rerank runs on each affected board, closing the rank
        gaps left by the deactivated entries, with each reranked board's
        `version` incremented by 1". After setup the board is at version 3;
        the cascade bumps it to 4, deactivates p1's entry, and reranks p2's
        surviving entry to rank 1.

        Design: Difficulty/transitive_cascade/flag_escalation_exclusion_cascade
        """
        _, d1, p1, p2, b1, f1 = self._setup()
        api_client.escalate_flag(f1["id"], director_headers(d1))
        board = get_board(b1["id"], d1)
        assert board["version"] == 4
        assert board["active_entry_count"] == 1
        # Active entries listing should show p2 at rank 1
        active_entries = list_board_entries(b1["id"], d1, params={"active": "true"})
        assert len(active_entries) == 1
        assert active_entries[0]["prospect_id"] == p2["id"]
        assert active_entries[0]["rank"] == 1
        # The excluded prospect's entry survives but is inactive
        p1_entries = get_success_data(
            api_client.list_prospect_board_entries(p1["id"], director_headers(d1))
        )
        assert p1_entries[0]["active"] is False
