"""Difficulty Rule 1 — dual_variant_calc.

Two algorithm variants over the same inputs produce divergent observable
outputs on the same domain entity. Covered instances:
  (A) Mutual-selection legacy_pass vs standard_pass: the legacy pass takes a
      legacy PNM into a reserved seat that standard would otherwise have
      filled with a higher-ranked non-legacy PNM.
  (B) Dues snapshot_at_acceptance vs live_at_read: BidMatch.dues_charged_cents
      is frozen at the accept commit and is NOT mutated by a later chapter
      PUT.
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
    attend_and_complete_party_for_pnm,
    advance_round,
    file_pnm_preference,
    file_chapter_preference,
    list_pnm_bid_matches,
    list_bid_match_dues_ledger,
    setup_round_with_accepted_bid,
    make_chapter_officer_headers,
    make_pnm_headers,
    update_chapter_payload,
    TEST_USERS,
)


# ─── Instance A: legacy_pass vs standard_pass ───────────────────────────────


class TestMutualSelectionLegacyVsStandardPass:
    """One chapter A (quota=2, legacy_priority_slots=1). Two PNMs both rank A
    rank=1: legacy L (chapter ranks rank=2) and standard S (chapter ranks rank=1).
    Legacy pass takes L into the legacy slot before standard pass runs."""

    @staticmethod
    def _setup():
        set_clock("2026-09-01T00:00:00Z")
        ch_a = create_chapter(
            name="Alpha",
            greek_type="SORORITY",
            quota_total=2,
            dues_per_member_cents=50000,
            legacy_priority_slots=1,
        )
        rnd = create_round(cycle_label="Fall 2026 dvc1")
        pnm_l = register_and_activate_pnm(
            full_name="L Legacy", gpa=3.50, legacy_chapter_id=ch_a["id"]
        )
        pnm_s = register_and_activate_pnm(full_name="S Standard", gpa=3.80)
        # Both PNMs attend a party hosted by A.
        from test_helpers import (
            create_and_open_party,
            create_invitation,
            accept_invitation,
            complete_party,
        )

        party = create_and_open_party(
            rnd["id"],
            ch_a["id"],
            scheduled_start_utc="2026-09-05T18:00:00Z",
            duration_minutes=60,
            capacity=20,
        )
        inv_l = create_invitation(party["id"], pnm_l["id"], ch_a["id"])
        inv_s = create_invitation(party["id"], pnm_s["id"], ch_a["id"])
        accept_invitation(inv_l["id"], pnm_l["id"])
        accept_invitation(inv_s["id"], pnm_s["id"])
        complete_party(party["id"], ch_a["id"])
        # Advance PARTY -> MUTUAL_SELECTION
        advance_round(rnd["id"])
        # File preferences
        file_pnm_preference(rnd["id"], pnm_l["id"], ch_a["id"], rank=1)
        file_pnm_preference(rnd["id"], pnm_s["id"], ch_a["id"], rank=1)
        file_chapter_preference(rnd["id"], ch_a["id"], pnm_s["id"], rank=1)
        file_chapter_preference(rnd["id"], ch_a["id"], pnm_l["id"], rank=2)
        return ch_a, rnd, pnm_l, pnm_s

    def test_legacy_pnm_matched_with_priority_kind_legacy(self, api):
        """PRD §3.5: "Every match produced in the legacy pass carries `priority_kind` `LEGACY` and is counted against *both* `Chapter.legacy_priority_slots` and `Chapter.quota_total` — legacy slots sit inside quota, not on top of it."

        Design: Difficulty/dual_variant_calc/dvc_mutual_select_legacy_vs_standard_pass
        """
        ch_a, rnd, pnm_l, pnm_s = self._setup()
        advance_round(rnd["id"])  # MUTUAL_SELECTION -> BID_DAY
        bids_l = list_pnm_bid_matches(pnm_l["id"])
        assert len(bids_l) == 1, f"L should have exactly one BidMatch; got {bids_l}"
        bid_l = bids_l[0]
        assert bid_l["chapter_id"] == ch_a["id"]
        assert bid_l["status"] == "PROPOSED"
        assert bid_l["priority_kind"] == "LEGACY"

    def test_standard_pnm_takes_remaining_slot_with_priority_kind_standard(self, api):
        """PRD §3.5: "Each match produced in this pass carries `priority_kind` `STANDARD` and is counted only against `Chapter.quota_total`."
        PRD §3.5: "A PNM matched in either pass is removed from every chapter's candidate list for the remainder of the run, so no PNM emerges from the allocator with more than one `BidMatch`."

        Design: Difficulty/dual_variant_calc/dvc_mutual_select_legacy_vs_standard_pass
        """
        ch_a, rnd, pnm_l, pnm_s = self._setup()
        advance_round(rnd["id"])  # MUTUAL_SELECTION -> BID_DAY
        bids_s = list_pnm_bid_matches(pnm_s["id"])
        assert len(bids_s) == 1, f"S should have exactly one BidMatch; got {bids_s}"
        bid_s = bids_s[0]
        assert bid_s["chapter_id"] == ch_a["id"]
        assert bid_s["status"] == "PROPOSED"
        assert bid_s["priority_kind"] == "STANDARD"

    def test_both_pnms_transition_to_matched_status(self, api):
        """PRD §3.5: "for each match produced, transitioning the targeted PNM from `ACTIVE` to `MATCHED` and setting `PNM.matched_chapter_id` to the chapter on the bid."

        Design: Difficulty/dual_variant_calc/dvc_mutual_select_legacy_vs_standard_pass
        """
        ch_a, rnd, pnm_l, pnm_s = self._setup()
        advance_round(rnd["id"])
        l_after = validate_success(
            api.get_pnm(pnm_l["id"], TEST_USERS["panhellenic_admin_headers"]), 200
        )
        s_after = validate_success(
            api.get_pnm(pnm_s["id"], TEST_USERS["panhellenic_admin_headers"]), 200
        )
        assert l_after["status"] == "MATCHED"
        assert l_after["matched_chapter_id"] == ch_a["id"]
        assert s_after["status"] == "MATCHED"
        assert s_after["matched_chapter_id"] == ch_a["id"]


# ─── Instance B: dues snapshot_at_acceptance vs live_at_read ────────────────


class TestDuesSnapshotVsLiveAtRead:
    """Chapter B accepts a bid at dues=50000; chapter PUT later changes
    dues to 75000. The accepted BidMatch must retain 50000 (snapshot, not live)."""

    def test_dues_charged_frozen_at_50000_after_chapter_put_to_75000(self, api):
        """PRD §3.6: "The chapter's *current* `dues_per_member_cents` is read at the instant the accept commits and snapshot onto the bid as `BidMatch.dues_charged_cents` — this is the fixed amount that bid will ever be billed for."
        PRD §3.6: "A subsequent `PanhellenicAdmin` revision of `dues_per_member_cents` on the chapter does *not* alter the `dues_charged_cents` of any past `ACCEPTED` bid."

        Design: Difficulty/dual_variant_calc/dvc_dues_snapshot_vs_live_at_read
        """
        ctx = setup_round_with_accepted_bid(
            chapter_name="Beta",
            greek_type="SORORITY",
            quota_total=5,
            dues_per_member_cents=50000,
            legacy_priority_slots=0,
            pnm_full_name="P1",
            cycle_label="Fall 2026 dvc2",
        )
        bid_id = ctx["bid_match"]["id"]
        chapter_id = ctx["chapter"]["id"]
        # Confirm snapshot is 50000 right after accept.
        bid_pre_put = validate_success(
            api.get_bid_match(bid_id, TEST_USERS["panhellenic_admin_headers"]), 200
        )
        assert bid_pre_put["dues_charged_cents"] == 50000

        # Mid-cycle PUT raises chapter dues to 75000.
        res = api.update_chapter(
            chapter_id,
            update_chapter_payload(dues_per_member_cents=75000),
            TEST_USERS["panhellenic_admin_headers"],
        )
        updated_chapter = validate_success(res, 200)
        assert updated_chapter["dues_per_member_cents"] == 75000

        # Re-read the bid: dues_charged_cents must still be 50000.
        bid_post_put = validate_success(
            api.get_bid_match(bid_id, TEST_USERS["panhellenic_admin_headers"]), 200
        )
        assert bid_post_put["dues_charged_cents"] == 50000, (
            "dues_charged_cents must remain the snapshot value (50000), not the "
            f"current chapter dues 75000; got {bid_post_put['dues_charged_cents']}"
        )

    def test_charge_ledger_entry_amount_matches_snapshot(self, api):
        """PRD §3.6: "A `DuesLedgerEntry` is appended with `entry_kind` `CHARGE`, `amount_cents` equal to the positive snapshot value, `chapter_id` set to the bidding chapter, and `bid_match_id` set to the accepting bid."

        Design: Difficulty/dual_variant_calc/dvc_dues_snapshot_vs_live_at_read
        """
        ctx = setup_round_with_accepted_bid(
            chapter_name="BetaLedger",
            greek_type="SORORITY",
            quota_total=5,
            dues_per_member_cents=50000,
            legacy_priority_slots=0,
            pnm_full_name="P1L",
            cycle_label="Fall 2026 dvc2b",
        )
        bid_id = ctx["bid_match"]["id"]
        entries = list_bid_match_dues_ledger(bid_id)
        charge_entries = [e for e in entries if e["entry_kind"] == "CHARGE"]
        assert len(charge_entries) == 1
        assert charge_entries[0]["amount_cents"] == 50000
        assert charge_entries[0]["chapter_id"] == ctx["chapter"]["id"]
        assert charge_entries[0]["bid_match_id"] == bid_id

    def test_put_after_accept_does_not_post_retroactive_ledger_entries(self, api):
        """PRD §3.1: "A subsequent admin update may change `dues_per_member_cents`, `quota_total`, or `legacy_priority_slots`, and bumps `Chapter.version`; crucially, that update has no retroactive effect on dues already snapshot onto past bids — see §3.6."
        PRD §3.6: "A subsequent `PanhellenicAdmin` revision of `dues_per_member_cents` on the chapter does *not* alter the `dues_charged_cents` of any past `ACCEPTED` bid."

        Design: Difficulty/dual_variant_calc/dvc_dues_snapshot_vs_live_at_read
        """
        ctx = setup_round_with_accepted_bid(
            chapter_name="BetaNoRetro",
            greek_type="SORORITY",
            quota_total=5,
            dues_per_member_cents=50000,
            legacy_priority_slots=0,
            pnm_full_name="P1NR",
            cycle_label="Fall 2026 dvc2c",
        )
        bid_id = ctx["bid_match"]["id"]
        ledger_before = list_bid_match_dues_ledger(bid_id)
        # Raise dues mid-cycle.
        api.update_chapter(
            ctx["chapter"]["id"],
            update_chapter_payload(dues_per_member_cents=75000),
            TEST_USERS["panhellenic_admin_headers"],
        )
        ledger_after = list_bid_match_dues_ledger(bid_id)
        assert len(ledger_after) == len(ledger_before), (
            "PUT must not append any new ledger entry; ledger length changed "
            f"from {len(ledger_before)} to {len(ledger_after)}"
        )
        for e in ledger_after:
            if e["entry_kind"] == "CHARGE":
                assert e["amount_cents"] == 50000
