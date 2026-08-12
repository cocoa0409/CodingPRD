"""Draft board rerank ordering, manual reorder, OCC (PRD §3.5, §2.6)."""
import pytest

from test_helpers import (
    ApiErrorId,
    add_board_entry,
    api_client,
    create_director,
    create_draft_board,
    create_prospect,
    create_report,
    create_roster_need,
    create_scout,
    director_headers,
    get_board,
    get_success_data,
    list_board_entries,
    lock_report,
    make_board_ready_prospect,
    submit_report,
    validate_error,
    validate_success,
)


class TestBoardReorderReverseConservesRankMass:
    """Difficulty: compensating_invariant/board_reorder_reverse_conserves_rank_mass.

    Scout s (mean 6.00 sd 1.50). p1 raw 9.00 -> normalized 8.00 -> composite 8.00.
    p2 raw 8.00 -> 7.00. p3 raw 7.00 -> 6.00. All BOARD_READY on board b1; ranks
    after reranks: p1=1, p2=2, p3=3; board version 4.
    """

    def _setup(self):
        s1 = create_scout(level="AREA", full_name="S", weight=1.0,
                          season_grade_mean=6.00, season_grade_stdev=1.50)
        d1 = create_director(full_name="Dir One")
        p1 = make_board_ready_prospect(s1, d1, raw_grade=9.00, full_name="P1", position="QB", college="State U")
        p2 = make_board_ready_prospect(s1, d1, raw_grade=8.00, full_name="P2", position="WR", college="Tech")
        p3 = make_board_ready_prospect(s1, d1, raw_grade=7.00, full_name="P3", position="CB", college="College")
        b1 = create_draft_board(d1, season_year=2026)
        e1 = add_board_entry(b1["id"], p1["id"], d1)
        e2 = add_board_entry(b1["id"], p2["id"], d1)
        e3 = add_board_entry(b1["id"], p3["id"], d1)
        board = get_board(b1["id"], d1)
        assert board["version"] == 4
        return s1, d1, p1, p2, p3, b1, e1, e2, e3, board

    def test_forward_reorder_insert_semantics(self, api):
        """PRD §3.5: "The reorder uses insert semantics: the named entry is
        removed from its current position, the remaining entries shift to
        close the gap, and the named entry is inserted at `new_rank`." Moving
        e3 to rank 1 makes the order e3, e1, e2; ranks are reassigned
        contiguously from 1, so sum(rank) == 1+2+3 == 6.

        Design: Difficulty/compensating_invariant/board_reorder_reverse_conserves_rank_mass
        """
        _, d1, _, _, _, b1, e1, e2, e3, board = self._setup()
        bv1 = board["version"]
        validate_success(api_client.reorder_board_entries(
            b1["id"],
            {"entry_id": e3["id"], "new_rank": 1, "expected_board_version": bv1},
            director_headers(d1),
        ))
        entries = list_board_entries(b1["id"], d1)
        order = [e["id"] for e in entries]
        assert order == [e3["id"], e1["id"], e2["id"]], (
            f"insert semantics: expected [e3, e1, e2], got {order}"
        )
        ranks = sorted(e["rank"] for e in entries)
        assert ranks == [1, 2, 3]
        assert sum(ranks) == 6  # N*(N+1)/2 for N=3

    def test_reverse_reorder_restores_permutation_and_increments_version(self, api):
        """PRD §3.5: "A successful reorder reassigns ranks contiguously from 1
        and increments the board's `version` by 1." Applying the reverse move
        restores the original permutation; each reorder bumps version by 1
        (4 -> 5 -> 6).

        Design: Difficulty/compensating_invariant/board_reorder_reverse_conserves_rank_mass
        """
        _, d1, _, _, _, b1, e1, e2, e3, board = self._setup()
        bv1 = board["version"]
        validate_success(api_client.reorder_board_entries(
            b1["id"],
            {"entry_id": e3["id"], "new_rank": 1, "expected_board_version": bv1},
            director_headers(d1),
        ))
        bv2 = get_board(b1["id"], d1)["version"]
        assert bv2 == bv1 + 1
        validate_success(api_client.reorder_board_entries(
            b1["id"],
            {"entry_id": e3["id"], "new_rank": 3, "expected_board_version": bv2},
            director_headers(d1),
        ))
        entries = list_board_entries(b1["id"], d1)
        order = [e["id"] for e in entries]
        assert order == [e1["id"], e2["id"], e3["id"]], (
            f"reverse move restores original permutation; got {order}"
        )
        assert sorted(e["rank"] for e in entries) == [1, 2, 3]
        bv3 = get_board(b1["id"], d1)["version"]
        assert bv3 == bv2 + 1


class TestRerankTieBreak:
    def test_equal_composite_higher_fit_wins(self, api):
        """PRD §3.5: "The board's `active` entries are sorted by the
        prospect's `composite_grade` descending with nulls placed last, then
        by the entry's `fit_score` descending, then by the entry's
        `created_at` ascending as the final tie-break — never by id." Two
        prospects with composite 7.00: the QB (fit 90.00 via P1 need) outranks
        the WR (fit 20.00 via the default base) regardless of insertion order.

        Design: Corner/calculations/rerank_equal_composite_higher_fit_wins
        """
        s1 = create_scout(level="AREA", full_name="S", weight=1.0,
                          season_grade_mean=6.00, season_grade_stdev=1.50)
        d1 = create_director(full_name="D")
        create_roster_need(season_year=2026, position="QB", priority_tier="P1")
        p_lo = make_board_ready_prospect(s1, d1, raw_grade=8.00, full_name="Lo WR", position="WR", college="A")
        p_hi = make_board_ready_prospect(s1, d1, raw_grade=8.00, full_name="Hi QB", position="QB", college="B")
        b1 = create_draft_board(d1, season_year=2026)
        # Insert the low-fit prospect first to prove fit (not insertion order) breaks the tie.
        add_board_entry(b1["id"], p_lo["id"], d1)
        add_board_entry(b1["id"], p_hi["id"], d1)
        entries = list_board_entries(b1["id"], d1)
        assert entries[0]["prospect_id"] == p_hi["id"]
        assert entries[0]["rank"] == 1
        assert entries[0]["fit_score"] == pytest.approx(90.00, abs=0.005)
        assert entries[1]["prospect_id"] == p_lo["id"]
        assert entries[1]["rank"] == 2
        assert entries[1]["fit_score"] == pytest.approx(20.00, abs=0.005)


class TestReorderStaleVersion:
    def test_stale_board_version_rejected(self, api):
        """PRD §2.6: "Manual reorder of a draft board's entries. The request
        must carry `expected_board_version` equal to the board's current
        `version`. Because a report lock, a flag-exclusion cascade, a scout
        weight change, or another writer's reorder each increment the board's
        `version`, a client holding a stale view is prevented from re-imposing
        a ranking computed on data it has not observed." Mismatch is rejected
        `ERR_STALE_VERSION` (HTTP 412).

        Design: Corner/cross_cutting_layers/reorder_stale_version_rejected
        """
        s1 = create_scout(level="AREA", full_name="S", weight=1.0,
                          season_grade_mean=6.00, season_grade_stdev=1.00)
        d1 = create_director(full_name="D")
        p1 = make_board_ready_prospect(s1, d1, raw_grade=7.00, full_name="P", position="QB", college="A")
        b1 = create_draft_board(d1, season_year=2026)
        e1 = add_board_entry(b1["id"], p1["id"], d1)
        bv = get_board(b1["id"], d1)["version"]
        first = validate_success(api_client.reorder_board_entries(
            b1["id"],
            {"entry_id": e1["id"], "new_rank": 1, "expected_board_version": bv},
            director_headers(d1),
        ))
        assert first["version"] == bv + 1
        resp = api_client.reorder_board_entries(
            b1["id"],
            {"entry_id": e1["id"], "new_rank": 1, "expected_board_version": bv},
            director_headers(d1),
        )
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION)
        assert resp.status_code == 412


class TestReorderRankOutOfBounds:
    def test_new_rank_zero_rejected(self, api):
        """PRD §3.5: "`new_rank` must lie between 1 and the board's
        `active_entry_count` inclusive, and `entry_id` must name an active
        entry of this board; violations are rejected with
        `ERR_RANK_OUT_OF_BOUNDS`."

        Design: Corner/validations/reorder_rank_out_of_bounds_rejected
        """
        s1 = create_scout(level="AREA", full_name="S", weight=1.0,
                          season_grade_mean=6.00, season_grade_stdev=1.00)
        d1 = create_director(full_name="D")
        p1 = make_board_ready_prospect(s1, d1, raw_grade=7.00, full_name="P", position="QB", college="A")
        b1 = create_draft_board(d1, season_year=2026)
        e1 = add_board_entry(b1["id"], p1["id"], d1)
        bv = get_board(b1["id"], d1)["version"]
        resp = api_client.reorder_board_entries(
            b1["id"],
            {"entry_id": e1["id"], "new_rank": 0, "expected_board_version": bv},
            director_headers(d1),
        )
        validate_error(resp, ApiErrorId.ERR_RANK_OUT_OF_BOUNDS)
        assert resp.status_code == 422


class TestBoardEntriesReverseLookup:
    def test_prospect_board_entries_reverse_lookup(self, api):
        """PRD §4 endpoint "List draft board entries referencing this
        prospect" returns exactly the entries for the given prospect;
        `DraftBoardEntry` rows carry `board_id` and `prospect_id` (PRD §3.5:
        "Each `DraftBoardEntry` carries the owning board's `board_id` and the
        ranked prospect's `prospect_id`").

        Design: Corner/entities/prospect_board_entries_reverse_lookup
        """
        s1 = create_scout(level="AREA", full_name="S", weight=1.0,
                          season_grade_mean=6.00, season_grade_stdev=1.00)
        d1 = create_director(full_name="D")
        p1 = make_board_ready_prospect(s1, d1, raw_grade=7.00, full_name="Linked", position="QB", college="A")
        b1 = create_draft_board(d1, season_year=2026)
        e1 = add_board_entry(b1["id"], p1["id"], d1)
        entries = get_success_data(
            api_client.list_prospect_board_entries(p1["id"], director_headers(d1))
        )
        assert len(entries) == 1
        assert entries[0]["id"] == e1["id"]
        assert entries[0]["board_id"] == b1["id"]
        assert entries[0]["prospect_id"] == p1["id"]


class TestWeightChangeRecomputesComposite:
    def test_weight_change_recomputes_composite(self, api):
        """PRD §3.1: "Because the composite is weight-sensitive, changing a
        weight recomputes the `composite_grade` and `tier` of every prospect
        with at least one `LOCKED` report authored by that scout". Scout A's
        weight 1.5 -> 3.0 with scout B at 1.0 changes fractions from
        (0.6, 0.4) to (0.75, 0.25): per-report rounded contributions
        0.75*6.67 -> 5.00 and 0.25*7.36 -> 1.84, sum 6.84.

        Design: Corner/calculations/weight_change_recomputes_composite
        """
        sa = create_scout(level="AREA", full_name="A", weight=1.5,
                          season_grade_mean=6.00, season_grade_stdev=2.00)
        sb = create_scout(level="AREA", full_name="B", weight=1.0,
                          season_grade_mean=6.00, season_grade_stdev=1.00)
        d1 = create_director(full_name="D")
        p1 = create_prospect(sa, full_name="P", position="OT", college="A")
        ra = create_report(p1["id"], sa, raw_grade=8.23, scheme_fit=1.00)
        rb = create_report(p1["id"], sb, raw_grade=7.57, scheme_fit=1.00)
        submit_report(ra["id"], sa)
        submit_report(rb["id"], sb)
        lock_report(ra["id"], d1)
        lock_report(rb["id"], d1)
        before = get_success_data(api_client.get_prospect(p1["id"], director_headers(d1)))
        assert before["composite_grade"] == pytest.approx(6.94, abs=0.005)
        validate_success(api_client.set_scout_weight(
            sa["id"], {"new_weight": 3.0}, director_headers(d1)
        ))
        after = get_success_data(api_client.get_prospect(p1["id"], director_headers(d1)))
        assert after["composite_grade"] == pytest.approx(6.84, abs=0.005), (
            f"weights 0.75/0.25: 0.75*6.67 -> 5.00 and 0.25*7.36 -> 1.84, sum "
            f"6.84; got {after['composite_grade']}"
        )
