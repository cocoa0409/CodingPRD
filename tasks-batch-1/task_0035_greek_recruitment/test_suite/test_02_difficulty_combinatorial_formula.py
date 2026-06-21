"""Difficulty Rule 2 — combinatorial_formula.

Two distinct combinatorial axes:
  (A) Mutual-selection nested rank tie-break: chapter_rank, pnm_rank, created_at.
  (B) Dues ledger MODE A (per-row running balance) vs MODE B (chapter aggregate),
      pinned chronological order with mid-cycle REFUND.
"""
import pytest

from test_helpers import (
    api_client,
    validate_success,
    get_success_data,
    set_clock,
    create_chapter,
    create_round,
    register_and_activate_pnm,
    advance_round,
    file_pnm_preference,
    file_chapter_preference,
    create_and_open_party,
    create_invitation,
    accept_invitation,
    complete_party,
    list_pnm_bid_matches,
    list_dues_ledger,
    setup_round_with_accepted_bid,
    rescind_bid_match_payload,
    make_chapter_officer_headers,
    make_pnm_headers,
    TEST_USERS,
)


class TestMutualSelectionNestedRankTieBreak:
    """Chapter C with quota=1. PA has chapter-rank=1 (PNM-rank=2); PB has
    chapter-rank=2 (PNM-rank=1). Per the sort key (chapter_rank, pnm_rank,
    created_at), PA wins despite a lower PNM-side rank."""

    @staticmethod
    def _setup():
        set_clock("2026-09-01T00:00:00Z")
        ch_c = create_chapter(
            name="Gamma",
            greek_type="SORORITY",
            quota_total=1,
            dues_per_member_cents=40000,
            legacy_priority_slots=0,
        )
        # Second chapter created to mirror the design's setup (does not
        # participate in the matching scenario directly).
        create_chapter(
            name="Delta",
            greek_type="SORORITY",
            quota_total=1,
            dues_per_member_cents=40000,
            legacy_priority_slots=0,
        )
        rnd = create_round(cycle_label="Fall 2026 comb1")
        pa = register_and_activate_pnm(full_name="PA", gpa=3.50)
        pb = register_and_activate_pnm(full_name="PB", gpa=3.50)
        party = create_and_open_party(
            rnd["id"], ch_c["id"], scheduled_start_utc="2026-09-05T18:00:00Z"
        )
        inv_a = create_invitation(party["id"], pa["id"], ch_c["id"])
        inv_b = create_invitation(party["id"], pb["id"], ch_c["id"])
        accept_invitation(inv_a["id"], pa["id"])
        accept_invitation(inv_b["id"], pb["id"])
        complete_party(party["id"], ch_c["id"])
        advance_round(rnd["id"])  # PARTY -> MUTUAL_SELECTION
        # PNM-side preferences: PA ranks C at 2, PB ranks C at 1
        file_pnm_preference(rnd["id"], pa["id"], ch_c["id"], rank=2)
        file_pnm_preference(rnd["id"], pb["id"], ch_c["id"], rank=1)
        # Chapter-side preferences: C ranks PA at 1, PB at 2
        file_chapter_preference(rnd["id"], ch_c["id"], pa["id"], rank=1)
        file_chapter_preference(rnd["id"], ch_c["id"], pb["id"], rank=2)
        return ch_c, rnd, pa, pb

    def test_chapter_rank_dominates_pnm_rank_in_tie_break(self, api):
        """PRD §3.5: "The candidate list is sorted primarily by the chapter's `CHAPTER_TO_PNM` rank for the PNM (lower `rank` is better; a missing chapter rank places the candidate at the back); secondarily by the PNM's `PNM_TO_CHAPTER` rank for the chapter (again, lower is better, with missing ranks at the back); and finally by the PNM's `created_at` ascending."

        Design: Difficulty/combinatorial_formula/comb_mutual_select_nested_ranks_chapter_then_pnm_then_created_at
        """
        ch_c, rnd, pa, pb = self._setup()
        advance_round(rnd["id"])  # MUTUAL_SELECTION -> BID_DAY
        bids_a = list_pnm_bid_matches(pa["id"])
        bids_b = list_pnm_bid_matches(pb["id"])
        # PA wins the single quota slot because chapter ranks PA at 1.
        assert len(bids_a) == 1
        assert bids_a[0]["chapter_id"] == ch_c["id"]
        assert bids_a[0]["status"] == "PROPOSED"
        assert bids_a[0]["priority_kind"] == "STANDARD"
        # PB does not get a bid.
        assert len(bids_b) == 0

    def test_unmatched_pnm_remains_active(self, api):
        """PRD §3.5: "When the precondition holds, the round's `phase` advances to `BID_DAY`, `RecruitmentRound.version` advances, and the mutual-selection allocator runs — producing zero or more `BidMatch` rows, each initially in `status` `PROPOSED`, and, for each match produced, transitioning the targeted PNM from `ACTIVE` to `MATCHED` and setting `PNM.matched_chapter_id` to the chapter on the bid."

        Design: Difficulty/combinatorial_formula/comb_mutual_select_nested_ranks_chapter_then_pnm_then_created_at
        """
        ch_c, rnd, pa, pb = self._setup()
        advance_round(rnd["id"])
        pa_after = validate_success(
            api.get_pnm(pa["id"], TEST_USERS["panhellenic_admin_headers"]), 200
        )
        pb_after = validate_success(
            api.get_pnm(pb["id"], TEST_USERS["panhellenic_admin_headers"]), 200
        )
        assert pa_after["status"] == "MATCHED"
        assert pa_after["matched_chapter_id"] == ch_c["id"]
        # PB was unmatched: must remain ACTIVE (no matched_chapter_id set).
        assert pb_after["status"] == "ACTIVE"
        assert pb_after.get("matched_chapter_id") is None


class TestDuesLedgerModeAVsModeB:
    """Chapter E with three entries in chronological order:
       CHARGE +30000, CHARGE +30000, REFUND -30000.
       MODE A per-row running_balance = [30000, 60000, 30000].
       MODE B aggregate = sum amounts = 30000.
       MODE A's final row == MODE B aggregate."""

    @staticmethod
    def _setup_three_entries():
        set_clock("2026-09-01T00:00:00Z")
        ch_e = create_chapter(
            name="Epsilon",
            greek_type="SORORITY",
            quota_total=3,
            dues_per_member_cents=30000,
            legacy_priority_slots=0,
        )
        rnd = create_round(cycle_label="Fall 2026 comb2")
        q1 = register_and_activate_pnm(full_name="Q1", gpa=3.50)
        q2 = register_and_activate_pnm(full_name="Q2", gpa=3.50)
        party = create_and_open_party(
            rnd["id"], ch_e["id"], scheduled_start_utc="2026-09-05T18:00:00Z"
        )
        inv_q1 = create_invitation(party["id"], q1["id"], ch_e["id"])
        inv_q2 = create_invitation(party["id"], q2["id"], ch_e["id"])
        accept_invitation(inv_q1["id"], q1["id"])
        accept_invitation(inv_q2["id"], q2["id"])
        complete_party(party["id"], ch_e["id"])
        advance_round(rnd["id"])  # PARTY -> MUTUAL_SELECTION
        file_pnm_preference(rnd["id"], q1["id"], ch_e["id"], rank=1)
        file_pnm_preference(rnd["id"], q2["id"], ch_e["id"], rank=1)
        file_chapter_preference(rnd["id"], ch_e["id"], q1["id"], rank=1)
        file_chapter_preference(rnd["id"], ch_e["id"], q2["id"], rank=2)
        advance_round(rnd["id"])  # MUTUAL_SELECTION -> BID_DAY
        bids_q1 = list_pnm_bid_matches(q1["id"])
        bids_q2 = list_pnm_bid_matches(q2["id"])
        bid_q1 = bids_q1[0]
        bid_q2 = bids_q2[0]
        # Accept both bids
        get_success_data(
            api_client.accept_bid_match(bid_q1["id"], make_pnm_headers(q1["id"]))
        )
        get_success_data(
            api_client.accept_bid_match(bid_q2["id"], make_pnm_headers(q2["id"]))
        )
        chapter_after_accepts = get_success_data(
            api_client.get_chapter(
                ch_e["id"], TEST_USERS["panhellenic_admin_headers"]
            )
        )
        # Rescind Q1's bid -> REFUND posts.
        rescind_res = api_client.rescind_bid_match(
            bid_q1["id"],
            rescind_bid_match_payload(
                expected_chapter_version=chapter_after_accepts["version"]
            ),
            make_chapter_officer_headers(ch_e["id"]),
        )
        get_success_data(rescind_res)
        return ch_e, bid_q1, bid_q2

    def test_mode_a_per_row_running_balances_in_chronological_order(self, api):
        """PRD §3.6: "The per-entry running balance, returned by the ledger listing, is computed by walking the chapter's entries in `created_at` ascending order, accumulating the sum of `amount_cents` into a running total, and stamping that running total onto each row's `running_balance_cents`; the final entry's running total is the ledger's final balance."

        Design: Difficulty/combinatorial_formula/comb_dues_ledger_pinned_order_mode_a_vs_mode_b
        """
        ch_e, bid_q1, bid_q2 = self._setup_three_entries()
        ledger = list_dues_ledger(ch_e["id"])
        assert len(ledger) == 3, f"Expected 3 ledger rows; got {len(ledger)}: {ledger}"
        # MODE A: chronological running balance.
        kinds_amounts = [(e["entry_kind"], e["amount_cents"]) for e in ledger]
        assert kinds_amounts == [
            ("CHARGE", 30000),
            ("CHARGE", 30000),
            ("REFUND", -30000),
        ], f"Unexpected ordered entries: {kinds_amounts}"
        running = [e["running_balance_cents"] for e in ledger]
        assert running == [30000, 60000, 30000], (
            f"MODE A running balances mismatch; expected [30000, 60000, 30000], "
            f"got {running}"
        )

    def test_mode_b_aggregate_equals_mode_a_final_row(self, api):
        """PRD §3.6: "The two modes must always agree at the final row: any drift between the last `running_balance_cents` in the listing and the aggregate sum is a bug."

        Design: Difficulty/combinatorial_formula/comb_dues_ledger_pinned_order_mode_a_vs_mode_b
        """
        ch_e, bid_q1, bid_q2 = self._setup_three_entries()
        ledger = list_dues_ledger(ch_e["id"])
        # MODE B: plain sum of amount_cents.
        aggregate = sum(e["amount_cents"] for e in ledger)
        assert aggregate == 30000
        # Final row of MODE A:
        final_running = ledger[-1]["running_balance_cents"]
        assert final_running == aggregate, (
            f"MODE A final row {final_running} must equal MODE B aggregate {aggregate}"
        )
