"""Settlement creation, posting, and REVERSAL ledger.

Covers PRD §3.9 (waterfall split, POSTING vs REVERSAL variants, money
conservation invariant) and the cross-entity gate from PRD §3.9 that
requires Showtime.lifecycle_status == COMPLETED to POST.
"""
from __future__ import annotations

import pytest

from test_helpers import (
    ApiErrorId,
    PLATFORM_COMMISSION_BPS,
    PROMO_DISTRIBUTOR_BPS_OVERRIDE,
    TAX_BPS,
    api_client,
    assert_settlement,
    assert_settlement_invariant,
    create_settlement,
    create_settlement_payload,
    list_audit_logs_for,
    list_settlements_for,
    post_settlement,
    purchase_ticket,
    refund_ticket,
    setup_completed_showtime,
    setup_posted_settlement,
    setup_showtime_on_sale,
    validate_error,
    validate_success,
)


def _round_half_up(value: float) -> int:
    """Round half-up to nearest integer cent. PRD §2.7: 'Every rounding
    step in the settlement waterfall uses round-half-up to the nearest
    integer cent.'"""
    from decimal import Decimal, ROUND_HALF_UP
    return int(
        Decimal(value).quantize(Decimal("1"), rounding=ROUND_HALF_UP),
    )


# =========================================================================
# Settlement cross-entity gate (PRD §3.9)
# =========================================================================
class TestSettlementPostRequiresCompleted:

    def test_post_when_showtime_not_completed(self, api, finance_headers):
        """PRD §3.9: 'the post is admitted only when the parent
        showtime's lifecycle_status is COMPLETED -- otherwise the
        response is ERR_SHOWTIME_NOT_COMPLETED.'

        Claim: POST /settlements/{id}/post against a draft whose
        underlying showtime is still SCHEDULED -> ERR_SHOWTIME_NOT_COMPLETED.
        """
        base = setup_showtime_on_sale(seat_capacity=10)
        # Sell one ticket so there is gross.
        purchase_ticket(
            base["showtime"], buyer_external_id="b1", paid_amount_cents=1500,
        )
        # Create a DRAFT settlement (showtime still SCHEDULED).
        draft = create_settlement(base["showtime"])
        # Attempt to POST it.
        res = api.post_settlement(
            draft["id"], {}, finance_headers,
        )
        validate_error(res, ApiErrorId.ERR_SHOWTIME_NOT_COMPLETED.value)


# =========================================================================
# Settlement waterfall correctness (PRD §3.9)
# =========================================================================
class TestSettlementWaterfall:

    def test_split_three_tickets_no_promo_distributor_60_percent(self, api):
        """PRD §3.9 step 1: 'compute that ticket's contribution to the
        platform commission as the ticket's paid_amount_cents multiplied
        by PLATFORM_COMMISSION_BPS (800 basis points, or 8 percent)
        divided by 10000, rounded half-up to the nearest integer cent.'
        PRD §3.9 step 3: 'sum the per-ticket commissions ... this is
        round-then-sum, not sum-then-round'.

        Claim: 3 tickets at paid=1500, distributor split 6000bps:
          per-ticket commission = round_half_up(1500*800/10000)=120
          platform = 3*120 = 360
          gross = 4500
          net_after_platform = 4140
          tax = round_half_up(4140*600/10000)=248
          net_after_tax = 3892
          distributor = round_half_up(3892*6000/10000)=2335
          cinema = 3892-2335 = 1557
        """
        base = setup_posted_settlement(
            tickets=3, paid_amount_cents=1500,
            distributor_split_bps=6000, format="2D",
            supported_formats=["2D"],
        )
        settlement = base["settlement"]
        assert_settlement(settlement)
        assert settlement["gross_cents"] == 4500
        assert settlement["platform_commission_cents"] == 360
        assert settlement["tax_cents"] == 248
        assert settlement["distributor_amount_cents"] == 2335
        assert settlement["cinema_amount_cents"] == 1557
        # Invariant -- PRD §3.9 'distributor + cinema + tax + platform == gross'.
        assert (
            settlement["distributor_amount_cents"]
            + settlement["cinema_amount_cents"]
            + settlement["tax_cents"]
            + settlement["platform_commission_cents"]
        ) == settlement["gross_cents"]

    def test_per_line_round_then_sum_diverges_from_sum_then_round(
        self, api,
    ):
        """PRD §3.9: 'sum the per-ticket commissions from step one to
        produce platform_commission_cents -- this is round-then-sum, not
        sum-then-round'.

        Claim: 3 tickets at paid=156:
          per-line: round_half_up(156*800/10000)=round_half_up(12.48)=12
          platform = 3*12 = 36     (PINNED — this is the expected value)
          sum-then-round = round_half_up(468*800/10000)=round_half_up(37.44)=37
          → an implementation using sum-then-round would emit 37 and fail.
        gross = 468; net_after_platform=432; tax=round_half_up(25.92)=26
        net_after_tax=406; distributor 6000bps → round_half_up(243.6)=244
        cinema = 406-244 = 162. invariant: 36+26+244+162 = 468.
        """
        base = setup_posted_settlement(
            tickets=3, paid_amount_cents=156,
            distributor_split_bps=6000, format="2D",
            supported_formats=["2D"],
        )
        s = base["settlement"]
        assert s["gross_cents"] == 468
        assert s["platform_commission_cents"] == 36, (
            "PRD §3.9: per-line round-then-sum pins the platform commission "
            "to 36 (sum-then-round would give 37)"
        )
        assert s["tax_cents"] == 26
        assert s["distributor_amount_cents"] == 244
        assert s["cinema_amount_cents"] == 162
        assert (
            s["distributor_amount_cents"] + s["cinema_amount_cents"]
            + s["tax_cents"] + s["platform_commission_cents"]
        ) == s["gross_cents"]

    def test_promo_code_flips_effective_split_to_50_50(self, api):
        """PRD §3.9: 'if any ticket in the evaluation set carries a
        non-empty promo_code, the effective share is
        PROMO_DISTRIBUTOR_BPS_OVERRIDE (5000 basis points, or 50/50),
        otherwise it is the distributor's default_split_ratio_bps'.

        Claim: when any ticket has promo_code set, the distributor share
        uses 5000bps regardless of distributor.default_split_ratio_bps.

        Three tickets at 1500 with promo on one:
          platform = 360; gross = 4500; net_after_platform = 4140
          tax = 248; net_after_tax = 3892
          distributor = round_half_up(3892*5000/10000) = 1946
          cinema = 3892 - 1946 = 1946
        """
        # Distributor default would say 9000bps; promo flips it to 5000.
        base = setup_posted_settlement(
            tickets=3, paid_amount_cents=1500,
            distributor_split_bps=9000, format="2D",
            supported_formats=["2D"],
            promo_code="SUMMER20",
        )
        s = base["settlement"]
        assert s["gross_cents"] == 4500
        assert s["platform_commission_cents"] == 360
        assert s["tax_cents"] == 248
        assert s["distributor_amount_cents"] == 1946
        assert s["cinema_amount_cents"] == 1946


# =========================================================================
# REVERSAL ledger (PRD §3.9)
# =========================================================================
class TestSettlementReversal:
    """PRD §3.9: 'when a single ticket is refunded or exchanged and the
    parent POSTING is in status POSTED: the evaluation set is exactly
    that one ticket, gross_cents enters the ledger as the negative of
    the refunded ticket's paid_amount_cents, and platform_commission_cents
    is computed on that single ticket'."""

    def test_refund_appends_reversal_row(self, api):
        """Claim: refunding a ticket whose POSTING is POSTED appends a
        REVERSAL settlement with gross_cents = -paid_amount_cents and
        platform_commission_cents = -(per-line rounded share).
        """
        base = setup_posted_settlement(
            tickets=3, paid_amount_cents=1500,
            distributor_split_bps=6000,
            format="2D", supported_formats=["2D"],
        )
        # Refund the first ticket.
        refund_ticket(base["tickets"][0])
        rows = list_settlements_for(base["showtime"]["id"])
        reversals = [r for r in rows if r["kind"] == "REVERSAL"]
        assert len(reversals) >= 1, (
            "PRD §3.9: 'a sibling REVERSAL row is appended that points "
            "back at the original via parent_settlement_id'"
        )
        rev = reversals[0]
        assert rev["gross_cents"] == -1500, (
            "PRD §3.9: 'gross_cents enters the ledger as the negative of "
            "the refunded ticket's paid_amount_cents'"
        )
        # Per-line rounded share of the platform commission is -120.
        assert rev["platform_commission_cents"] == -120
        # parent_settlement_id points at the POSTING.
        assert rev.get("parent_settlement_id") == base["settlement"]["id"]

    def test_money_conservation_across_posting_and_reversals(self, api):
        """PRD §3.9: 'the system actor sets the POSTING's status to
        REVERSED' when reversals offset; meanwhile the ledger preserves
        money: sum(split) over all rows == sum(gross) over all rows.

        Claim: after refund, sum(distributor + cinema + tax + platform)
        across POSTING+REVERSAL rows equals sum(gross_cents).
        """
        base = setup_posted_settlement(
            tickets=3, paid_amount_cents=1500,
            distributor_split_bps=6000,
            format="2D", supported_formats=["2D"],
        )
        refund_ticket(base["tickets"][0])
        rows = list_settlements_for(base["showtime"]["id"])
        # POSTING (gross=4500) + REVERSAL (gross=-1500) → net gross 3000.
        assert_settlement_invariant(rows, expected_net_gross=3000)


# =========================================================================
# Posted settlement emits audit log
# =========================================================================
class TestSettlementAuditTrail:

    def test_post_emits_audit_log(self, api):
        """PRD §3.9: 'An AuditLog row with action SETTLEMENT_POST is
        emitted on a successful post.'

        Claim: a posted settlement has a SETTLEMENT_POST audit row.
        """
        base = setup_posted_settlement(
            tickets=1, paid_amount_cents=1000,
            distributor_split_bps=6000,
            format="2D", supported_formats=["2D"],
        )
        rows = list_audit_logs_for(
            base["settlement"]["id"], action="SETTLEMENT_POST",
        )
        assert len(rows) >= 1
