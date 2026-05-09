"""Payouts: assembly, T+N, maturation, release, cancel."""
import pytest
from test_helpers import (
    api_client, validate_success, validate_error, get_success_data,
    setup_picked_up_order,
    advance_clock, run_payouts_sweep, assemble_payout,
    find_commission_entry, list_commission_entries,
    PAYOUT_LAG_BY_TIER,
    ADMIN,
)


class TestPayoutTPlusN:

    def test_payout_target_period_is_paid_period_plus_tier_lag(self, api):
        """PRD §3.9 T+N Payout Schedule: "Each newly created CommissionEntry
        is stamped with a payout_target_period_index equal to the source
        order's paid_period_index plus the payout lag implied by the
        primary leader's tier: 3 periods for tier 1, 5 periods for tier 2,
        and 7 periods for tier 3."

        Claim: for a tier-1 PRIMARY entry, payout_target_period_index ==
        paid_period_index + 3.
        """
        sc = setup_picked_up_order(unit_price_cents=100, quantity=1)
        order = sc["order"]
        entry = find_commission_entry(sc["leader"]["id"], order["id"])
        assert entry is not None
        # tier 1 leader → +3
        assert entry["payout_target_period_index"] == order["paid_period_index"] + PAYOUT_LAG_BY_TIER[1]


class TestPayoutAssemblyAndRelease:

    def test_assemble_payout_starts_scheduled_with_bundled_entries(self, api):
        """PRD §3.9 Payout Assembly, Maturity, and Release: "The new payout
        begins in SCHEDULED with bundled_entry_ids populated, total_amount_cents
        set to the sum of net_rebate_cents over bundled entries".

        Claim: a fresh payout has status=SCHEDULED, bundled_entry_ids
        contains the source entry, and total_amount_cents equals net_rebate_cents.
        """
        sc = setup_picked_up_order(unit_price_cents=100, quantity=1)
        entry = find_commission_entry(sc["leader"]["id"], sc["order"]["id"])
        payout = assemble_payout(sc["leader"]["id"], entry["payout_target_period_index"])
        assert payout["status"] == "SCHEDULED"
        assert entry["id"] in payout["bundled_entry_ids"]
        assert payout["total_amount_cents"] == entry["net_rebate_cents"]

    def test_release_scheduled_payout_rejected(self, api):
        """PRD §3.9 Maturation: "A release request also requires the payout
        to currently be in MATURED; releasing a SCHEDULED payout is
        rejected with ERR_PAYOUT_NOT_MATURED."

        Claim: releasing a SCHEDULED (not yet MATURED) payout is rejected
        with ERR_PAYOUT_NOT_MATURED.
        """
        sc = setup_picked_up_order(unit_price_cents=100, quantity=1)
        entry = find_commission_entry(sc["leader"]["id"], sc["order"]["id"])
        payout = assemble_payout(sc["leader"]["id"], entry["payout_target_period_index"])
        res = api.release_payout(payout["id"], ADMIN)
        validate_error(res, "ERR_PAYOUT_NOT_MATURED")

    def test_full_maturation_and_release_flow(self, api):
        """PRD §3.9 Maturation + Release: "A SCHEDULED payout advances to
        MATURED only when the current system_period_index is at or above
        the payout's target_period_index and none of the bundled entries
        is currently in PENDING_CLAWBACK or CLAWED_BACK."
        PRD §3.9: "On MATURED to RELEASED, every bundled CommissionEntry
        advances from PENDING to SETTLED."

        Claim: SCHEDULED -> MATURED via run-payouts sweep after clock
        advance, then MATURED -> RELEASED via /release; bundled entries
        end at SETTLED.
        """
        sc = setup_picked_up_order(unit_price_cents=100, quantity=1)
        entry = find_commission_entry(sc["leader"]["id"], sc["order"]["id"])
        payout = assemble_payout(sc["leader"]["id"], entry["payout_target_period_index"])
        # Advance clock to or past target_period_index
        target = entry["payout_target_period_index"]
        advance_clock(target + 1)
        run_payouts_sweep()
        payout_matured = validate_success(api.get_payout(payout["id"], ADMIN), 200)
        assert payout_matured["status"] == "MATURED"
        # Now release
        released = validate_success(api.release_payout(payout["id"], ADMIN), 200)
        assert released["status"] == "RELEASED"
        entry_after = find_commission_entry(sc["leader"]["id"], sc["order"]["id"])
        assert entry_after["status"] == "SETTLED"


class TestPayoutCancel:

    def test_cancel_scheduled_payout_returns_entries_to_unbundled(self, api):
        """PRD §3.9 Payout Assembly: "A payout may be cancelled while still
        in SCHEDULED; cancellation moves status to CANCELLED and returns
        its bundled entries to the unbundled pool by setting their
        payout_id back to null so that they become eligible for the next
        assembly."

        Claim: cancelling a SCHEDULED payout sets status=CANCELLED and
        the previously bundled entry's payout_id is null after the cancel.
        """
        sc = setup_picked_up_order(unit_price_cents=100, quantity=1)
        entry = find_commission_entry(sc["leader"]["id"], sc["order"]["id"])
        payout = assemble_payout(sc["leader"]["id"], entry["payout_target_period_index"])
        cancelled = validate_success(api.cancel_payout(payout["id"], ADMIN), 200)
        assert cancelled["status"] == "CANCELLED"
        # Re-find the entry — payout_id should be null
        entry_after = find_commission_entry(sc["leader"]["id"], sc["order"]["id"])
        assert entry_after["payout_id"] is None
