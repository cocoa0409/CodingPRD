"""Difficulty Rule 9 — compensating_invariant.

Forward + compensating actions round-trip a conserved quantity to zero net:
  (A) Chapter dues balance: CHARGE +x then REFUND -x sum to zero.
  (B) Chapter pledged_count (and legacy_pledged_count if LEGACY): accept then
      rescind round-trip to the pre-accept value.
"""
import pytest

from test_helpers import (
    api_client,
    validate_success,
    get_success_data,
    setup_round_with_accepted_bid,
    rescind_bid_match_payload,
    list_bid_match_dues_ledger,
    list_dues_ledger,
    make_chapter_officer_headers,
    TEST_USERS,
)


class TestDuesBalanceConservedAcceptThenRescind:
    """Accept posts +dues; rescind posts -dues; the bid's ledger sums to 0."""

    @staticmethod
    def _setup_accept_and_rescind():
        ctx = setup_round_with_accepted_bid(
            chapter_name="Phi",
            greek_type="FRATERNITY",
            quota_total=3,
            dues_per_member_cents=40000,
            legacy_priority_slots=0,
            pnm_full_name="T1",
            cycle_label="Fall 2026 ci1",
        )
        v_after_accept = ctx["chapter_version_after_accept"]
        rescind_res = api_client.rescind_bid_match(
            ctx["bid_match"]["id"],
            rescind_bid_match_payload(expected_chapter_version=v_after_accept),
            make_chapter_officer_headers(ctx["chapter"]["id"]),
        )
        get_success_data(rescind_res)
        return ctx

    def test_bid_ledger_has_charge_plus_refund_summing_to_zero(self, api):
        """PRD §3.6: "On a successful rescind, the bid's `status` transitions to `DECLINED` (the rescission is modeled as a `DECLINED` bid distinguished from a PNM decline by the trailing refund entry on its `bid_match_id`); a compensating `DuesLedgerEntry` is appended with `entry_kind` `REFUND` and `amount_cents` equal to the *negation* of the bid's `dues_charged_cents`, so the chapter's CHARGE plus REFUND on that bid sums to exactly zero."

        Design: Difficulty/compensating_invariant/ci_dues_balance_conserved_accept_then_rescind
        """
        ctx = self._setup_accept_and_rescind()
        entries = list_bid_match_dues_ledger(ctx["bid_match"]["id"])
        assert len(entries) == 2, f"Expected 2 ledger entries on bid; got {entries}"
        kinds = sorted(e["entry_kind"] for e in entries)
        assert kinds == ["CHARGE", "REFUND"]
        amounts = {e["entry_kind"]: e["amount_cents"] for e in entries}
        assert amounts["CHARGE"] == 40000
        assert amounts["REFUND"] == -40000
        # Conservation invariant:
        assert sum(e["amount_cents"] for e in entries) == 0

    def test_final_running_balance_equals_zero_on_chapter_ledger(self, api):
        """PRD §3.6: "the final entry's running total is the ledger's final balance."
        PRD §3.6: "The chapter-aggregate balance — equivalently, `dues_balance_cents` as reported on the chapter resource — is computed as the plain sum of `amount_cents` across all of that chapter's entries; by construction it equals the final per-entry running total."

        Design: Difficulty/compensating_invariant/ci_dues_balance_conserved_accept_then_rescind
        """
        ctx = self._setup_accept_and_rescind()
        ledger = list_dues_ledger(ctx["chapter"]["id"])
        assert len(ledger) >= 2
        # Final running balance is 0
        assert ledger[-1]["running_balance_cents"] == 0
        # Aggregate also 0
        assert sum(e["amount_cents"] for e in ledger) == 0


class TestChapterQuotaCountConservedAcceptThenRescind:
    """Same conservation, different quantity: a LEGACY accept then rescind
    round-trips Chapter.pledged_count AND Chapter.legacy_pledged_count to 0."""

    @staticmethod
    def _setup_legacy_accept_rescind():
        ctx = setup_round_with_accepted_bid(
            chapter_name="Chi",
            greek_type="FRATERNITY",
            quota_total=2,
            dues_per_member_cents=40000,
            legacy_priority_slots=1,
            pnm_full_name="U1 Legacy",
            pnm_is_legacy=True,
            cycle_label="Fall 2026 ci2",
        )
        v_after_accept = ctx["chapter_version_after_accept"]
        rescind_res = api_client.rescind_bid_match(
            ctx["bid_match"]["id"],
            rescind_bid_match_payload(expected_chapter_version=v_after_accept),
            make_chapter_officer_headers(ctx["chapter"]["id"]),
        )
        get_success_data(rescind_res)
        return ctx

    def test_chapter_pledged_count_round_trips_to_zero_after_legacy_accept_rescind(
        self, api
    ):
        """PRD §3.6: "The chapter's `pledged_count` is decremented (and `legacy_pledged_count` is decremented as well if `priority_kind` is `LEGACY`), freeing the slot."

        Design: Difficulty/compensating_invariant/ci_chapter_quota_count_conserved_accept_then_rescind
        """
        ctx = self._setup_legacy_accept_rescind()
        ch_after = validate_success(
            api.get_chapter(
                ctx["chapter"]["id"], TEST_USERS["panhellenic_admin_headers"]
            ),
            200,
        )
        assert ch_after["pledged_count"] == 0
        assert ch_after["legacy_pledged_count"] == 0

    def test_bid_priority_kind_was_legacy_so_legacy_counter_was_touched(self, api):
        """PRD §3.5: "`priority_kind` is `LEGACY` if and only if the PNM's `legacy_chapter_id` equals the bidding `chapter_id` *and* the chapter's `legacy_pledged_count` is strictly less than its `legacy_priority_slots`, and `STANDARD` otherwise."

        Design: Difficulty/compensating_invariant/ci_chapter_quota_count_conserved_accept_then_rescind
        """
        ctx = self._setup_legacy_accept_rescind()
        bid_after = validate_success(
            api.get_bid_match(
                ctx["bid_match"]["id"], TEST_USERS["panhellenic_admin_headers"]
            ),
            200,
        )
        assert bid_after["priority_kind"] == "LEGACY"
        assert bid_after["status"] == "DECLINED"
