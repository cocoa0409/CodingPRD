"""Settlement batches: commission, channel fee, tax withholding, net payout.

PRD references:
  - §3.10 Commission, Channel Fees, Refund Reversals, and Per-Order Pinning
  - §3.11 Settlement Batches: Periodic Payouts to the Initiator
  - §3.12 Tax Withholding
  - §3.9 Progress Updates and the Silence Window
"""
from __future__ import annotations

import pytest

from test_helpers import (
    DEFAULT_NOW_ISO,
    add_hours,
    advance_clock,
    approve_refund,
    create_draft_settlement_batch,
    create_refund_request,
    current_clock_iso,
    finalize_settlement_batch,
    publish_progress_update,
    setup_charged_order,
    setup_succeeded_with_pending_refund_and_draft_batch,
    setup_three_charged_orders_for_commission,
    validate_error,
    validate_success,
)


def _wide_period() -> tuple[str, str]:
    """A period broad enough to cover any charge timestamp produced by
    fixtures that also advance the clock past a deadline."""
    return (
        add_hours(DEFAULT_NOW_ISO, -1),
        add_hours(current_clock_iso(), 24),
    )


class TestCommissionPerOrder:
    def test_tech_commission_per_order_round_half_up(self, api):
        """PRD §3.10: 'TECH charges 500 basis points (5.00%) ... The
        per-order commission is computed as the order's order_total_cents
        multiplied by the category rate divided by 10,000, rounded
        half-up to the nearest cent.'

        Claim: 333-cent TECH order → 17 cents commission (333*500/10000 =
        16.65 → round_half_up → 17).
        """
        ctx = setup_three_charged_orders_for_commission(
            totals_cents=[333, 333, 334], category="TECH",
        )
        # Update last_update_published_at so finalize is not blocked by the
        # silence-window rule.
        publish_progress_update(
            project=ctx["project"], initiator=ctx["initiator"],
        )
        period_start, period_end = _wide_period()
        batch = create_draft_settlement_batch(
            project=ctx["project"], period_start=period_start,
            period_end=period_end,
        )
        finalized = finalize_settlement_batch(
            project=ctx["project"], batch=batch,
        )
        # Per-order: round_half_up(333*500/10000)=17,
        #            round_half_up(333*500/10000)=17,
        #            round_half_up(334*500/10000)=17 (334*500/10000 = 16.7).
        # Sum: 17+17+17 = 51.
        assert finalized["commission_cents"] == 51, (
            "PRD §3.10: per-order rounding then sum yields 51 cents on "
            "(333, 333, 334) TECH orders."
        )

    def test_art_commission_700_bps(self, api):
        """PRD §3.10: 'ART charges 700 basis points (7.00%)'.

        Claim: ART 10000-cent order → 700-cent commission.
        """
        # Setup a single-order ART batch and verify commission_cents == 700.
        ctx = setup_three_charged_orders_for_commission(
            totals_cents=[10_000], category="ART",
        )
        publish_progress_update(
            project=ctx["project"], initiator=ctx["initiator"],
        )
        period_start, period_end = _wide_period()
        batch = create_draft_settlement_batch(
            project=ctx["project"], period_start=period_start,
            period_end=period_end,
        )
        finalized = finalize_settlement_batch(
            project=ctx["project"], batch=batch,
        )
        assert finalized["commission_cents"] == 700

    def test_community_commission_300_bps(self, api):
        """PRD §3.10: 'COMMUNITY charges 300 basis points (3.00%)'.

        Claim: COMMUNITY 10000-cent order → 300-cent commission.
        """
        ctx = setup_three_charged_orders_for_commission(
            totals_cents=[10_000], category="COMMUNITY",
        )
        publish_progress_update(
            project=ctx["project"], initiator=ctx["initiator"],
        )
        period_start, period_end = _wide_period()
        batch = create_draft_settlement_batch(
            project=ctx["project"], period_start=period_start,
            period_end=period_end,
        )
        finalized = finalize_settlement_batch(
            project=ctx["project"], batch=batch,
        )
        assert finalized["commission_cents"] == 300


class TestChannelFee:
    def test_channel_fee_floor_30_cents_for_small_order(self, api):
        """PRD §3.10: 'take order_total_cents multiplied by 290 divided by
        10,000, drop any fractional cents (floor), and then enforce a
        minimum of 30 cents — the channel fee is the larger of 30 cents
        and the floored result'.

        Claim: 100-cent order → channel fee = 30 (max(30, floor(100*290/10000)=2)).
        """
        ctx = setup_three_charged_orders_for_commission(
            totals_cents=[100], category="TECH",
        )
        publish_progress_update(
            project=ctx["project"], initiator=ctx["initiator"],
        )
        period_start, period_end = _wide_period()
        batch = create_draft_settlement_batch(
            project=ctx["project"], period_start=period_start,
            period_end=period_end,
        )
        finalized = finalize_settlement_batch(
            project=ctx["project"], batch=batch,
        )
        assert finalized["channel_fee_cents"] == 30

    def test_channel_fee_floor_for_large_order(self, api):
        """PRD §3.10: 'take order_total_cents multiplied by 290 divided by
        10,000, drop any fractional cents (floor)'.

        Claim: 100000-cent order → channel fee = floor(100000*290/10000)
        = 2900 cents (>30 floor).
        """
        ctx = setup_three_charged_orders_for_commission(
            totals_cents=[100_000], category="TECH",
        )
        publish_progress_update(
            project=ctx["project"], initiator=ctx["initiator"],
        )
        period_start, period_end = _wide_period()
        batch = create_draft_settlement_batch(
            project=ctx["project"], period_start=period_start,
            period_end=period_end,
        )
        finalized = finalize_settlement_batch(
            project=ctx["project"], batch=batch,
        )
        assert finalized["channel_fee_cents"] == 2_900


class TestSettlementGates:
    def test_finalize_blocked_by_pending_refund(self, api):
        """PRD §3.11: 'no RefundRequest for orders in the batch's period
        may be currently PENDING_REVIEW or APPROVED (otherwise
        ERR_PENDING_REFUNDS_BLOCK_SETTLEMENT)'.

        Claim: PENDING_REVIEW refund in period → finalize returns
        ERR_PENDING_REFUNDS_BLOCK_SETTLEMENT.
        """
        ctx = setup_succeeded_with_pending_refund_and_draft_batch()
        res = api.finalize_settlement_batch(
            ctx["project"]["id"], ctx["batch"]["id"],
            {"X-User-ID": "admin-001", "X-User-Role": "PlatformAdmin"},
        )
        validate_error(res, "ERR_PENDING_REFUNDS_BLOCK_SETTLEMENT")

    def test_finalize_blocked_by_silence_window_breach(self, api):
        """PRD §3.9: 'After the project has transitioned to SUCCEEDED, the
        same threshold becomes a hard gate at settlement finalize: a
        settlement batch may not be finalized while the silence exceeds
        30 days, in which case the request is rejected with
        ERR_UPDATE_FREQUENCY_BREACH.'
        PRD §3.9: 'The 30-day boundary is exclusive of equality — a
        silence of exactly 30 days is compliant; a silence strictly
        greater than 30 days is non-compliant.'

        Claim: SUCCEEDED project whose last_update_published_at is more
        than 30 days behind the clock at finalize → finalize returns
        ERR_UPDATE_FREQUENCY_BREACH.
        """
        # Set a definite last_update_published_at via publish_progress_update,
        # then advance past 30 days. Without an explicit publish, the
        # last_update_published_at is null and PRD does not pin behavior
        # on null.
        initiator, project, _, _, _ = setup_charged_order(
            category="TECH", reward_pledge_cents=10_000,
            funding_target_cents=1, with_tax_id=True,
        )
        publish_progress_update(project=project, initiator=initiator)
        # Advance >30 days past the publish moment.
        new_now = add_hours(current_clock_iso(), 31 * 24)
        advance_clock(new_now)
        period_start = add_hours(DEFAULT_NOW_ISO, -1)
        period_end = add_hours(new_now, 24)
        batch = create_draft_settlement_batch(
            project=project, period_start=period_start, period_end=period_end,
        )
        res = api.finalize_settlement_batch(
            project["id"], batch["id"],
            {"X-User-ID": "admin-001", "X-User-Role": "PlatformAdmin"},
        )
        validate_error(res, "ERR_UPDATE_FREQUENCY_BREACH")


class TestSettlementHappyPath:
    def test_finalize_locks_amounts_in_pinned_order(self, api):
        """PRD §3.11: 'When finalize succeeds, the batch transitions from
        DRAFT to FINALIZED and all five computed amounts are pinned in a
        fixed evaluation order. First, commission_cents ... Second,
        channel_fee_cents ... Third, refund_reversal_cents ... Fourth,
        the taxable base is computed as gross_charged_cents minus
        commission_cents minus channel_fee_cents minus
        refund_reversal_cents. Fifth, tax_withheld_cents is computed by
        the withholding rule from §3.12 against that taxable base.
        Finally, net_payout_cents equals the taxable base minus
        tax_withheld_cents.'

        Claim: TECH order_total=100000 yields commission=5000, channel
        fee=2900, refund_reversal=0, taxable_base=92100 (>60000 →
        tax=10%=9210), net=82890.
        """
        ctx = setup_three_charged_orders_for_commission(
            totals_cents=[100_000], category="TECH",
        )
        publish_progress_update(
            project=ctx["project"], initiator=ctx["initiator"],
        )
        period_start, period_end = _wide_period()
        batch = create_draft_settlement_batch(
            project=ctx["project"], period_start=period_start,
            period_end=period_end,
        )
        finalized = finalize_settlement_batch(
            project=ctx["project"], batch=batch,
        )
        assert finalized["status"] == "FINALIZED"
        assert finalized["gross_charged_cents"] == 100_000
        assert finalized["commission_cents"] == 5_000
        assert finalized["channel_fee_cents"] == 2_900
        assert finalized["refund_reversal_cents"] == 0
        # taxable_base = 100000 - 5000 - 2900 - 0 = 92100. > 60000 →
        # tax = round_half_up(92100*1000/10000) = 9210.
        assert finalized["tax_withheld_cents"] == 9_210
        assert finalized["net_payout_cents"] == 92_100 - 9_210


class TestTaxWithholding:
    def test_backup_withholding_when_no_tax_id(self, api):
        """PRD §3.12: 'When the initiator's tax_id is missing or the empty
        string, the system applies backup withholding at 2,400 basis
        points (24%) of the taxable base regardless of size, rounded
        half-up to the nearest cent.'

        Claim: initiator without tax_id → tax_withheld = 24% of taxable base.
        """
        # 100k TECH order: commission=5000, channel=2900, taxable_base=92100.
        # Backup 24%: round_half_up(92100*2400/10000) = 22104.
        from test_helpers import (
            create_backer, create_draft_project, create_reward,
            place_order, setup_live_project, succeed_project_and_charge_all,
            take_project_live, create_verified_initiator,
        )
        initiator = create_verified_initiator(with_tax_id=False)
        project = create_draft_project(
            initiator=initiator, category="TECH",
            funding_model="ALL_OR_NOTHING",
            funding_target_cents=1,
            deadline_hours_from_now=24.5,
        )
        reward = create_reward(
            project=project, initiator=initiator,
            pledge_amount_cents=100_000, reward_type="DIGITAL",
        )
        project = take_project_live(project=project, initiator=initiator)
        backer = create_backer()
        order = place_order(project=project, reward=reward, backer=backer)
        succeed_project_and_charge_all(project=project, orders=[order])
        publish_progress_update(project=project, initiator=initiator)
        period_start, period_end = _wide_period()
        batch = create_draft_settlement_batch(
            project=project, period_start=period_start, period_end=period_end,
        )
        finalized = finalize_settlement_batch(project=project, batch=batch)
        # taxable_base = 100000-5000-2900-0 = 92100; backup 24%.
        assert finalized["tax_withheld_cents"] == 22_104

    def test_below_threshold_no_tax_when_tax_id_present(self, api):
        """PRD §3.12: 'otherwise, when the taxable base in cents is less
        than or equal to 60,000, tax_withheld_cents is zero.'

        Claim: tax_id present and taxable_base ≤ 60000 → tax = 0.
        """
        # Pick a TECH order_total that yields taxable_base well below 60000.
        # order_total=10000: commission=500, channel=290 (max(30,290))=290,
        # taxable_base=10000-500-290-0=9210.
        ctx = setup_three_charged_orders_for_commission(
            totals_cents=[10_000], category="TECH",
        )
        publish_progress_update(
            project=ctx["project"], initiator=ctx["initiator"],
        )
        period_start, period_end = _wide_period()
        batch = create_draft_settlement_batch(
            project=ctx["project"], period_start=period_start,
            period_end=period_end,
        )
        finalized = finalize_settlement_batch(
            project=ctx["project"], batch=batch,
        )
        assert finalized["tax_withheld_cents"] == 0


class TestSettlementBankingEvent:
    def test_paid_on_banking_success(self, api):
        """PRD §3.11: 'A finalized batch becomes PAID when the simulated
        banking event reports SUCCESS against the batch_id'.

        Claim: banking SUCCESS on FINALIZED batch → status PAID.
        """
        from test_helpers import emit_banking, get_batch
        ctx = setup_three_charged_orders_for_commission(
            totals_cents=[10_000], category="TECH",
        )
        publish_progress_update(
            project=ctx["project"], initiator=ctx["initiator"],
        )
        period_start, period_end = _wide_period()
        batch = create_draft_settlement_batch(
            project=ctx["project"], period_start=period_start,
            period_end=period_end,
        )
        finalized = finalize_settlement_batch(
            project=ctx["project"], batch=batch,
        )
        emit_banking(
            "SETTLEMENT_BATCH", finalized["id"], "SUCCESS",
            external_ref="bank-ref-001",
        )
        b = get_batch(ctx["project"]["id"], finalized["id"])
        assert b["status"] == "PAID"
