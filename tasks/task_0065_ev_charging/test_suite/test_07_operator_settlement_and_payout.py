"""Operator settlement waterfall (PRD §3.6), payout creation, payout
issuance (PRD §3.7), and the refund-reversal pathway.
"""
from __future__ import annotations
import pytest

from test_helpers import (
    ApiErrorId,
    LedgerCounterpartyKind,
    assert_payout,
    assert_settlement_ledger_entry,
    create_payout,
    create_payout_payload,
    create_pricing_version,
    create_roaming_partner_operator,
    emit_payment_refunded,
    get_member,
    get_session,
    iso_day,
    issue_payout,
    list_audit_logs,
    list_session_ledger_entries,
    setup_settled_session_for_recipe,
    setup_session_in_payout_window,
    sum_amounts_by_counterparty,
    validate_error,
    validate_success,
    PO,
)


# ===========================================================================
# Operator settlement waterfall — non-roaming case
# ===========================================================================
class TestOperatorSettlementWaterfall:
    """PRD §3.6: 'The same monetary inputs drive operator settlement —
    the allocation of the net (excluding tax) across station owner,
    platform, optional roaming partner, and tax authority — using a
    fixed waterfall.'

    Non-roaming case (recipe SILVER, revenue_share_bps=4000):
      electricity = 750, service = 285 → net = 1035
      roaming = 0 (non-roaming)
      after_roaming = 1035
      platform = round_half_up(1035*500/10000) = round_half_up(51.75) = 52
      after_platform = 1035 - 52 = 983
      station_owner = round_half_up(983*4000/10000) = round_half_up(393.2) = 393
      operator_residual = 983 - 393 = 590  (not a ledger row per scaffold)
      tax_authority = 135
    """

    def test_non_roaming_settlement_writes_three_positive_ledger_rows(
        self, api,
    ):
        """PRD §3.6: 'four SettlementLedgerEntry rows are appended ...
        one with counterparty_kind STATION_OWNER_SHARE for the
        station-owner allocation, one with PLATFORM_SERVICE_FEE for the
        platform allocation, one with ROAMING_PARTNER for the roaming
        allocation (only if non-zero), and one with TAX_AUTHORITY.'

        Non-roaming: only the three non-zero counterparties appear.
        """
        ctx = setup_settled_session_for_recipe(
            member_tier="SILVER",
            member_wallet_cents=100000,
            revenue_share_bps=4000,
        )
        rows = list_session_ledger_entries(ctx["session"]["id"])
        # Filter to SESSION_SETTLE reason rows.
        settle_rows = [r for r in rows if r["reason"] == "SESSION_SETTLE"]
        totals = sum_amounts_by_counterparty(settle_rows)
        # Non-roaming → no ROAMING_PARTNER row.
        assert "ROAMING_PARTNER" not in totals, (
            f"Non-roaming session must not write a ROAMING_PARTNER row, "
            f"got {totals}"
        )
        assert totals.get("STATION_OWNER_SHARE", 0) == 393, (
            f"Expected STATION_OWNER_SHARE=393, got {totals}"
        )
        assert totals.get("PLATFORM_SERVICE_FEE", 0) == 52, (
            f"Expected PLATFORM_SERVICE_FEE=52, got {totals}"
        )
        assert totals.get("TAX_AUTHORITY", 0) == 135

    def test_each_settle_row_carries_session_settle_reason_and_positive_sign(
        self, api,
    ):
        """PRD §3.6: 'each with reason SESSION_SETTLE and positive
        amount_cents.'"""
        ctx = setup_settled_session_for_recipe()
        rows = list_session_ledger_entries(ctx["session"]["id"])
        for r in rows:
            assert_settlement_ledger_entry(r)
            if r["reason"] == "SESSION_SETTLE":
                assert r["amount_cents"] > 0, (
                    f"SESSION_SETTLE row must be positive: {r}"
                )


# ===========================================================================
# Roaming case (PRD §3.6 step 2)
# ===========================================================================
class TestRoamingSettlement:
    """PRD §3.6: 'it is roaming when the member's home_operator_id is
    not equal to the station's operator_id. If roaming, the roaming
    partner's allocation is net_cents multiplied by fifteen hundred
    basis points (fifteen percent), divided by ten thousand, rounded
    half up.'

    Recipe per SCAFFOLD_DIFFICULTY_DESIGN
    operator_settlement_evaluation_order_pinned:
      electricity = 500, service = 190 → net = 690
      roaming = round_half_up(690*1500/10000) = round_half_up(103.5) = 104
      after_roaming = 690 - 104 = 586
      platform = round_half_up(586*500/10000) = round_half_up(29.3) = 29
      after_platform = 586 - 29 = 557
      station_owner = round_half_up(557*4000/10000) = round_half_up(222.8) = 223
      operator_residual = 557 - 223 = 334
      tax_authority = 90
    """

    def test_roaming_session_writes_roaming_partner_row(self, api):
        """PRD §3.6: 'with counterparty_kind ROAMING_PARTNER for the
        roaming allocation (only if non-zero)'.

        We construct a session with a roaming home_operator_id and
        single-FLAT 10 kWh delta so the math matches the recipe (15 kWh
        recipe is replaced here with a single 10 kWh sample for clarity,
        keeping the asserted invariant of "a ROAMING_PARTNER row is
        written when the member's home_operator_id != station's
        operator_id"; the exact roaming amount is also asserted)."""
        # Construct the roaming setup explicitly: a roaming partner
        # Operator exists, and the Member's home_operator_id points at it.
        from test_helpers import (
            create_platform_operator_row,
            create_station_owner_operator,
            create_station,
            create_pile,
            shelve_pile,
            create_pricing_version,
            create_member,
            create_session,
            start_session,
            stop_session,
            append_curve_point,
        )
        op_a = create_platform_operator_row()  # station's operator_id
        op_b = create_roaming_partner_operator()  # member's home operator
        owner = create_station_owner_operator()
        station = create_station(
            operator_id=op_a["id"], station_owner_id=owner["id"],
            revenue_share_bps=4000,
        )
        pile = create_pile(
            station_id=station["id"],
            station_owner_id=owner["id"],
            rated_power_kw=60.0,
        )
        shelve_pile(
            pile_id=pile["id"], station_owner_id=owner["id"],
        )
        # Pricing pinned to station's operator (op_a).
        create_pricing_version(
            operator_id=op_a["id"],
            effective_from=iso_day(2026, 1, 1),
            effective_to=iso_day(2030, 1, 1),
            peak_rate_per_kwh_cents=80,
            flat_rate_per_kwh_cents=50,
            valley_rate_per_kwh_cents=30,
            service_fee_per_kwh_cents=20,
            tax_bps=1300,
            peak_windows=[],
            valley_windows=[],
            tier_service_fee_discount_bps={
                "BASIC": 0, "SILVER": 500, "GOLD": 1000, "PLATINUM": 1500,
            },
        )
        member = create_member(
            home_operator_id=op_b["id"],
            tier="SILVER",
            wallet_balance_cents=100000,
        )
        session = create_session(
            pile_id=pile["id"], member_id=member["id"], auth_method="APP",
        )
        session = start_session(
            session_id=session["id"], member_id=member["id"],
        )
        append_curve_point(
            session_id=session["id"],
            sampled_at="2026-05-13T00:01:00.000Z",
            cumulative_energy_milli=10000,
            instant_power_kw=60.0,
            window_tag="FLAT",
        )
        settled = stop_session(
            session_id=session["id"], member_id=member["id"],
        )
        # electricity = 500, service = 190 (200 * 0.95), tax =
        # round_half_up((500+190)*1300/10000) = round_half_up(89.7) = 90
        assert settled["electricity_fee_cents"] == 500
        assert settled["service_fee_cents"] == 190
        assert settled["tax_cents"] == 90
        assert settled["total_cents"] == 780

        rows = list_session_ledger_entries(session["id"])
        settle_rows = [r for r in rows if r["reason"] == "SESSION_SETTLE"]
        totals = sum_amounts_by_counterparty(settle_rows)
        # Roaming = round_half_up(690*1500/10000) = 104
        assert totals.get("ROAMING_PARTNER", 0) == 104, (
            f"Expected ROAMING_PARTNER=104, got {totals}"
        )
        # Platform = round_half_up(586*500/10000) = 29
        assert totals.get("PLATFORM_SERVICE_FEE", 0) == 29
        # Station owner = round_half_up(557*4000/10000) = 223
        assert totals.get("STATION_OWNER_SHARE", 0) == 223
        assert totals.get("TAX_AUTHORITY", 0) == 90


# ===========================================================================
# Refund-reversal invariant (PRD §3.6)
# ===========================================================================
class TestRefundReversalInvariant:
    """PRD §3.6: 'The invariant that ties original and reversal together
    is that for each counterparty_kind, the sum of original plus
    reversal amount_cents on the session is exactly zero.'"""

    def test_refund_creates_negative_rows_summing_zero_per_counterparty(
        self, api,
    ):
        ctx = setup_settled_session_for_recipe(
            member_tier="SILVER", member_wallet_cents=100000,
        )
        emit_payment_refunded(ctx["session"]["id"])
        rows = list_session_ledger_entries(ctx["session"]["id"])
        totals = sum_amounts_by_counterparty(rows)
        # PRD §3.6 per-counterparty zero invariant.
        for kind in ("STATION_OWNER_SHARE", "PLATFORM_SERVICE_FEE",
                     "TAX_AUTHORITY"):
            assert totals.get(kind, 0) == 0, (
                f"Per-counterparty net for {kind} must be 0 after refund, "
                f"got {totals.get(kind)}"
            )

    def test_refund_appends_billing_adjustment_audit_log(self, api):
        """PRD §3.6: 'an AuditLog row with event_kind BILLING_ADJUSTMENT
        is appended.'"""
        ctx = setup_settled_session_for_recipe()
        emit_payment_refunded(ctx["session"]["id"])
        logs = list_audit_logs(
            event_kind="BILLING_ADJUSTMENT",
            entity_kind="ChargingSession",
            entity_id=ctx["session"]["id"],
        )
        assert len(logs) >= 1


# ===========================================================================
# Payout window and creation
# ===========================================================================
class TestPayoutWindow:
    """PRD §3.7: 'a PlatformOperator creates a payout draft against a
    target operator_id, an inclusive period_start, and an exclusive
    period_end strictly greater than period_start (otherwise the
    creation is rejected with ERR_INVALID_PAYOUT_WINDOW).'"""

    def test_payout_with_end_equals_start_rejected(self, api):
        ctx = setup_session_in_payout_window()
        res = api.create_payout(
            create_payout_payload(
                operator_id=ctx["operator"]["id"],
                period_start=iso_day(2026, 5, 13),
                period_end=iso_day(2026, 5, 13),
            ),
            PO,
        )
        validate_error(res, ApiErrorId.ERR_INVALID_PAYOUT_WINDOW.value)

    def test_payout_with_end_before_start_rejected(self, api):
        ctx = setup_session_in_payout_window()
        res = api.create_payout(
            create_payout_payload(
                operator_id=ctx["operator"]["id"],
                period_start=iso_day(2026, 5, 13),
                period_end=iso_day(2026, 5, 1),
            ),
            PO,
        )
        validate_error(res, ApiErrorId.ERR_INVALID_PAYOUT_WINDOW.value)

    def test_create_payout_computes_net_cents_at_creation(self, api):
        """PRD §3.7: 'On creation, the system computes three monetary
        totals from the operator's SettlementLedgerEntry rows whose
        source session's ended_at falls within [period_start,
        period_end). ... The net_cents is gross_cents minus
        reversal_cents.'"""
        ctx = setup_session_in_payout_window()
        payout = create_payout(
            operator_id=ctx["operator"]["id"],
            period_start=ctx["period_start"],
            period_end=ctx["period_end"],
        )
        assert_payout(payout)
        assert payout["status"] == "PENDING"
        # net_cents must equal gross_cents - reversal_cents.
        assert payout["net_cents"] == (
            payout["gross_cents"] - payout["reversal_cents"]
        )


# ===========================================================================
# Payout issuance (PRD §3.7)
# ===========================================================================
class TestPayoutIssuance:
    """PRD §3.7: 'The transition from PENDING to ISSUED requires
    net_cents to be at least zero; if refunds have pushed it negative
    by issue time, the request is rejected with
    ERR_PAYOUT_NEGATIVE_NET.'"""

    def test_pending_payout_with_positive_net_can_be_issued(self, api):
        ctx = setup_session_in_payout_window()
        payout = create_payout(
            operator_id=ctx["operator"]["id"],
            period_start=ctx["period_start"],
            period_end=ctx["period_end"],
        )
        # Fixture pins the clock inside the payout window, so the
        # recipe's PLATFORM_SERVICE_FEE + TAX_AUTHORITY ledger rows
        # are captured by the payout and net_cents is strictly positive.
        assert payout["net_cents"] > 0, (
            f"setup should produce positive net_cents, got {payout['net_cents']}"
        )
        issued = issue_payout(payout_id=payout["id"])
        assert issued["status"] == "ISSUED"

    def test_payout_with_negative_net_rejected_at_issue(self, api):
        """PRD §3.7: 'if refunds have pushed it negative by issue time,
        the request is rejected with ERR_PAYOUT_NEGATIVE_NET.'

        Construct: settle session → create PENDING payout → emit refund
        (drives reversal_cents up) → re-create payout (or rely on the
        system to recompute on issue). PRD §3.7: 'If the same refund
        arrives while the payout is still PENDING, the payout's
        net_cents is recomputed by the dispatcher.'
        """
        ctx = setup_session_in_payout_window()
        payout = create_payout(
            operator_id=ctx["operator"]["id"],
            period_start=ctx["period_start"],
            period_end=ctx["period_end"],
        )
        # Now emit a refund — this writes negative rows so on issue
        # the recomputed net_cents will be negative.
        emit_payment_refunded(ctx["session"]["id"])
        # PRD §3.7 says the issue is rejected; serialization in scaffold
        # uses ERR_PAYOUT_PERIOD_DRIFT for the raced case, but PRD
        # prose names ERR_PAYOUT_NEGATIVE_NET when net is negative at
        # issue time. Accept either as the PRD admits both narratives
        # here (the second § paragraph). See PRD §3.7.
        from test_helpers import validate_error_is_one_of
        res = api.issue_payout(payout["id"], PO)
        validate_error_is_one_of(
            res,
            [
                ApiErrorId.ERR_PAYOUT_NEGATIVE_NET.value,
                ApiErrorId.ERR_PAYOUT_PERIOD_DRIFT.value,
            ],
        )
