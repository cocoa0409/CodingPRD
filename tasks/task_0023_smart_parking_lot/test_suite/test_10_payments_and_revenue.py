"""Payments, refunds, revenue split, and settlement (PRD §3.7)."""
from __future__ import annotations

import pytest

from test_helpers import (
    add_days,
    advance_clock,
    api_client,
    get_card,
    get_revenue,
    get_session,
    refund_payload,
    run_sweep,
    setup_paid_session_for_refund,
    setup_three_paid_sessions_for_revenue_split,
    TEST_USERS,
    unique_external_ref,
    validate_error,
    validate_success,
)


# ===========================================================================
# §3.7 — Per-entry-then-sum invariant
# ===========================================================================
class TestRevenueSplit:
    def test_per_entry_partner_share_rounded_half_up(self, api):
        """PRD §3.7: 'For each new entry, the system first computes the
        partner cut as the entry's gross_amount_cents multiplied by the
        lot's partner_share_bps divided by 10000 and rounded half-up to
        the nearest integer cent.'"""
        scen = setup_three_paid_sessions_for_revenue_split(
            base_iso="2026-03-01T10:00:00.000Z",
            hourly_rate_cents=333,
            daily_cap_cents=10_000,
            partner_share_bps=2500,
        )
        rev = get_revenue(
            scen["lot"]["id"],
            params={
                "from": "2026-03-01",
                "to": "2026-03-02",
                "billing_type": "HOURLY",
            },
        )
        entries = rev if isinstance(rev, list) else rev.get("data", [])
        if isinstance(entries, dict):
            entries = [entries]
        hourly = [
            e for e in entries
            if e.get("billing_type") == "HOURLY"
            and e.get("source_kind") == "SESSION"
        ]
        relevant = [e for e in hourly if e["gross_amount_cents"] == 333]
        assert len(relevant) >= 3, (
            f"Expected at least 3 hourly entries of gross 333, "
            f"got {len(relevant)}"
        )
        # Each entry's partner_share = round(333*2500/10000)=83 (HALF_UP).
        for e in relevant[:3]:
            assert e["partner_share_cents"] == 83, (
                f"Per-entry partner share must be 83, got {e['partner_share_cents']}"
            )

    def test_per_entry_then_sum_authoritative_over_sum_then_round(self, api):
        """PRD §3.7: 'Aggregating partner totals across a settlement period
        sums each entry's already-rounded partner_share_cents; it does not
        multiply the period's gross sum by the basis-point ratio and then
        round once. With mixed-sign entries and more than two rows, those
        two methods can diverge by up to one cent per entry; per-entry-
        then-sum is authoritative.'"""
        scen = setup_three_paid_sessions_for_revenue_split(
            base_iso="2026-03-05T10:00:00.000Z",
            hourly_rate_cents=333,
            daily_cap_cents=10_000,
            partner_share_bps=2500,
        )
        rev = get_revenue(
            scen["lot"]["id"],
            params={
                "from": "2026-03-05",
                "to": "2026-03-06",
                "billing_type": "HOURLY",
            },
        )
        entries = rev if isinstance(rev, list) else rev.get("data", [])
        if isinstance(entries, dict):
            entries = [entries]
        hourly = [
            e for e in entries
            if e.get("billing_type") == "HOURLY"
            and e.get("gross_amount_cents") == 333
        ]
        # 83 + 83 + 83 = 249 (per-entry-then-sum).
        # round(999 * 0.25) = 250 (sum-then-round).
        total_partner = sum(e["partner_share_cents"] for e in hourly[:3])
        assert total_partner == 249, (
            f"Per-entry-then-sum total must be 249, got {total_partner}; "
            f"sum-then-round would give 250."
        )
        assert total_partner != 250

    def test_house_plus_partner_equals_gross_per_entry(self, api):
        """PRD §3.7: 'The house cut is then computed as gross_amount_cents
        minus partner_share_cents.'"""
        scen = setup_three_paid_sessions_for_revenue_split(
            base_iso="2026-03-10T10:00:00.000Z",
            hourly_rate_cents=333,
            partner_share_bps=2500,
        )
        rev = get_revenue(
            scen["lot"]["id"],
            params={"from": "2026-03-10", "to": "2026-03-11"},
        )
        entries = rev if isinstance(rev, list) else rev.get("data", [])
        if isinstance(entries, dict):
            entries = [entries]
        for e in entries:
            assert (
                e["partner_share_cents"] + e["house_share_cents"]
                == e["gross_amount_cents"]
            ), (
                f"house_share + partner_share must equal gross for entry "
                f"{e.get('id')}; got partner={e['partner_share_cents']} "
                f"house={e['house_share_cents']} gross={e['gross_amount_cents']}"
            )


# ===========================================================================
# §3.7 — Partner share non-negative (clamped to zero floor)
# ===========================================================================
class TestPartnerShareClampedToZero:
    def test_partner_share_non_negative_on_hourly_revenue(self, api):
        """PRD §3.7: 'partner_share_cents is always non-negative.' Holds
        on positive-gross entries (the trivial case) but the rule is also
        load-bearing on REFUND/ADJUSTMENT entries with negative gross."""
        scen = setup_three_paid_sessions_for_revenue_split(
            base_iso="2026-03-15T10:00:00.000Z",
            hourly_rate_cents=333,
            partner_share_bps=2500,
        )
        rev = get_revenue(scen["lot"]["id"])
        entries = rev if isinstance(rev, list) else rev.get("data", [])
        if isinstance(entries, dict):
            entries = [entries]
        for e in entries:
            assert e["partner_share_cents"] >= 0, (
                f"partner_share_cents must be >= 0 for entry {e.get('id')}, "
                f"got {e['partner_share_cents']}"
            )


# ===========================================================================
# §3.8 — Settlement run
# ===========================================================================
class TestSettlement:
    def test_settlement_run_returns_invoice_object(self, api, operator_headers):
        """PRD §3.8: 'an Operator posts to the settlement-run endpoint with
        an optional period, and the system emits an immutable invoice
        record carrying invoice_id, the period, and the period's
        gross_total_cents, partner_total_cents, and house_total_cents.'"""
        scen = setup_three_paid_sessions_for_revenue_split(
            base_iso="2026-03-20T10:00:00.000Z",
            hourly_rate_cents=333,
            partner_share_bps=2500,
        )
        res = api.run_settlement(
            scen["lot"]["id"], {"period": "2026-03-20"}, operator_headers
        )
        data = validate_success(res, expected_status=200)
        assert "invoice_id" in data
        assert "period" in data
        assert "gross_total_cents" in data
        assert "partner_total_cents" in data
        assert "house_total_cents" in data
        # Per-entry sum: 333*3=999 gross; partner 83*3=249; house 250*3=750
        assert data["gross_total_cents"] == 999
        assert data["partner_total_cents"] == 249
        assert data["house_total_cents"] == 750
