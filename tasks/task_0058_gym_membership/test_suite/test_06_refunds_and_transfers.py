"""Card refunds and transfers, including the dual-variant refund preview.

PRD §3.6.
"""
from __future__ import annotations
import pytest
from datetime import timedelta

from test_helpers import (
    ApiErrorId,
    PA, SO,
    advance_clock,
    create_funded_member,
    find_wallet_txn,
    freeze_card,
    get_card,
    get_member,
    iso_z, parse_iso,
    list_wallet_transactions,
    make_member_headers,
    round_half_up,
    setup_annual_card_at_remaining_days,
    setup_member_with_active_card,
    setup_monthly_card_for_refund_eligibility,
    validate_error,
    validate_success,
)


# ===========================================================================
# Refund eligibility days (PRD §3.6) — boundary check
# ===========================================================================
class TestRefundEligibilityBoundary:

    def test_exactly_at_threshold_accepted(self, api):
        """PRD §3.6: 'The card's remaining validity in days —
        effective_expiry_date minus the current instant — must be at
        least CardType.refund_eligibility_days; otherwise the response
        is ERR_REFUND_NOT_ELIGIBLE.'

        Remaining == eligibility → accepted (inclusive >=).
        """
        _, _, card = setup_monthly_card_for_refund_eligibility(
            remaining_days=30,
            refund_eligibility_days=30,
            validity_days=90,
            price_cents=90_000,
        )
        res = api.refund_card(card["id"], SO)
        validate_success(res, expected_status=200)
        after = get_card(card["id"])
        assert after["status"] == "REFUNDED"

    def test_one_below_threshold_rejected(self, api):
        """PRD §3.6: 'must be at least
        CardType.refund_eligibility_days; otherwise the response is
        ERR_REFUND_NOT_ELIGIBLE.'

        Remaining 29 < 30 → rejected.
        """
        _, _, card = setup_monthly_card_for_refund_eligibility(
            remaining_days=29,
            refund_eligibility_days=30,
            validity_days=90,
            price_cents=90_000,
        )
        res = api.refund_card(card["id"], SO)
        validate_error(res, ApiErrorId.ERR_REFUND_NOT_ELIGIBLE.value)


# ===========================================================================
# Refund forward_looking formula (PRD §3.6)
# ===========================================================================
class TestRefundForwardLookingValue:

    def test_remaining_value_round_half_up_at_final_step(self, api):
        """PRD §3.6: 'For a MONTHLY or ANNUAL card the remaining days
        are the maximum of zero and effective_expiry_date minus the
        current instant in days; the remaining value is
        Card.issuance_price_cents multiplied by remaining days divided
        by CardType.validity_days, rounded half-up at the final step.'

        Annual card price 120_000, validity 365, remaining 100 →
        120_000 * 100 / 365 = 32876.71… → round_half_up = 32877.
        """
        _, member, card = setup_annual_card_at_remaining_days(
            remaining_days=100,
            validity_days=365,
            price_cents=120_000,
            refund_eligibility_days=0,
            max_freeze_days=0,         # no ever-frozen, no freeze block
        )
        principal_before = get_member(member["id"])["wallet_balance_cents"]
        validate_success(api.refund_card(card["id"], SO), expected_status=200)
        rows = list_wallet_transactions(
            member["id"], headers=make_member_headers(member["id"]),
        )
        refund_rows = find_wallet_txn(
            rows, kind="REFUND", bucket="PRINCIPAL",
            ref_startswith=f"Card:{card['id']}",
        )
        assert len(refund_rows) == 1, (
            f"PRD §3.6 expects one REFUND row pointing at the refunded "
            f"card; got {refund_rows!r}"
        )
        assert refund_rows[0]["amount_cents"] == 32_877, (
            "PRD §3.6: forward_looking sum-then-round → "
            "round_half_up(120000 * 100 / 365) == 32877."
        )


# ===========================================================================
# Refund preview dual variant (PRD §3.6)
# ===========================================================================
class TestRefundPreviewDualVariant:

    def test_chronological_diverges_from_forward_looking(self, api):
        """PRD §3.6: 'The refund-preview capability surfaces both the
        forward-looking remaining value (which the actual refund will
        use) and a parallel chronological variant. The chronological
        variant ... walks day-by-day from the current instant to
        effective_expiry_date, accumulating Card.issuance_price_cents
        divided by CardType.validity_days per day, rounding each
        per-day amount half-up to the nearest cent before summing.'

        For 120_000 / 365 = 328.767…, round_half_up per day = 329.
        100 days * 329 = 32900 cents (chronological).
        Forward_looking = round_half_up(120_000 * 100 / 365) = 32877.
        Divergence of 23 cents.
        """
        _, _, card = setup_annual_card_at_remaining_days(
            remaining_days=100,
            validity_days=365,
            price_cents=120_000,
            refund_eligibility_days=0,
            max_freeze_days=0,
        )
        res = api.get_refund_preview(card["id"], SO)
        data = validate_success(res, expected_status=200)
        assert data.get("forward_looking_remaining_value_cents") == 32_877, (
            f"PRD §3.6 forward_looking; got "
            f"{data.get('forward_looking_remaining_value_cents')!r}"
        )
        assert data.get("chronological_remaining_value_cents") == 32_900, (
            f"PRD §3.6 chronological round-per-day then sum; got "
            f"{data.get('chronological_remaining_value_cents')!r}"
        )


# ===========================================================================
# Frozen-card refund block (PRD §3.6)
# ===========================================================================
class TestRefundFrozenCardBlocked:

    def test_card_with_settled_freeze_history_rejected(self, api):
        """PRD §3.6: 'The card must additionally have no FreezeEpisode
        in SETTLED status: any card that was ever frozen and settled
        is non-refundable, with rejection code
        ERR_REFUND_FROZEN_CARD_BLOCKED.'"""
        # Annual card, freeze 3 days, advance past ends_at to SETTLED.
        ct, member, card = setup_annual_card_at_remaining_days(
            remaining_days=300,
            refund_eligibility_days=10,
        )
        ep = freeze_card(card["id"], requested_days=3)
        advance_clock(iso_z(parse_iso(ep["ends_at"]) + timedelta(minutes=1)))
        # Card returns to ACTIVE per PRD §3.5.
        assert get_card(card["id"])["status"] == "ACTIVE"

        res = api.refund_card(card["id"], SO)
        validate_error(res, ApiErrorId.ERR_REFUND_FROZEN_CARD_BLOCKED.value)


# ===========================================================================
# Transfer eligibility and recipient checks (PRD §3.6)
# ===========================================================================
class TestTransferEligibility:

    def test_transfer_to_same_family_member_succeeds(self, api):
        """PRD §3.6: 'either the destination member shares the source
        holder's family_group_id, or the card type's family_shareable
        is true, or the card was issued within the last 7 days.'

        Same family_group_id path.
        """
        ct, holder, card = setup_annual_card_at_remaining_days(
            remaining_days=200,
            refund_eligibility_days=0,
            transfer_fee_pct_bp=1_000,
            max_freeze_days=0,
            family_group_id="FAM_SHARE_TEST",
        )
        dest = create_funded_member(
            wallet_balance_cents=10_000,
            family_group_id="FAM_SHARE_TEST",
        )
        res = api.transfer_card(
            card["id"], {"to_member_id": dest["id"]}, SO,
        )
        validate_success(res, expected_status=200)

    def test_transfer_to_unrelated_member_rejected(self, api):
        """PRD §3.6: 'Failing the relationship rule returns
        ERR_TRANSFER_INELIGIBLE_RECIPIENT.'"""
        ct, holder, card = setup_annual_card_at_remaining_days(
            remaining_days=200,    # fresh-issuance grace would also fail
            refund_eligibility_days=0,
            transfer_fee_pct_bp=1_000,
            max_freeze_days=0,
            family_group_id="FAM_ALPHA",
        )
        # Different family_group, card type non-shareable, > 7 days old.
        dest = create_funded_member(
            wallet_balance_cents=10_000,
            family_group_id="FAM_BETA",
        )
        res = api.transfer_card(
            card["id"], {"to_member_id": dest["id"]}, SO,
        )
        validate_error(res, ApiErrorId.ERR_TRANSFER_INELIGIBLE_RECIPIENT.value)


# ===========================================================================
# Transfer fee floor (PRD §3.6)
# ===========================================================================
class TestTransferFeeFloor:

    def test_min_transfer_fee_2000_cents(self, api):
        """PRD §3.6: 'finally taking the maximum of that result and
        2,000 cents — that floor is the minimum transfer fee.'

        Setup: a tiny remaining value such that (remaining_value *
        bp / 10000) < 2000. Annual card priced 10_000, transfer_fee_bp=
        1_000, 30 days remaining of 365: remaining_value = 822 cents.
        Computed fee = 82 cents → floored to 2_000.
        """
        ct, holder, card = setup_annual_card_at_remaining_days(
            remaining_days=30,
            refund_eligibility_days=0,
            transfer_fee_pct_bp=1_000,
            max_freeze_days=0,
            price_cents=10_000,
            family_group_id="FAM_FLOOR",
            extra_funds_cents=100_000,
        )
        dest = create_funded_member(
            wallet_balance_cents=10_000,
            family_group_id="FAM_FLOOR",
        )
        # Capture holder's principal before to validate the debit.
        rows_before = list_wallet_transactions(
            holder["id"], headers=make_member_headers(holder["id"]),
        )
        res = api.transfer_card(
            card["id"], {"to_member_id": dest["id"]}, SO,
        )
        record = validate_success(res, expected_status=200)
        assert record["transfer_fee_cents"] == 2_000, (
            "PRD §3.6: the minimum transfer fee is 2,000 cents."
        )
