"""Cancellation proration boundary, partial-refund mid-period, and the
charge-amount-mismatch-beats-pcp-required precedence. PRD §3.8, §3.9, §3.14.
"""
import pytest

from test_helpers import (
    api_client, validate_success, validate_error, get_success_data,
    setup_active_member, setup_pending_member_no_pcp,
    make_member_headers, charge_payload, set_clock, ApiErrorId, ADMIN,
)


def test_proration_zero_refund_at_exact_period_end(api):
    """PRD §3.9: "a cancellation made exactly at the period end (elapsed days equal
    to the period length) refunds nothing because the remaining days are zero."

    Design: Difficulty/boundary_precision_check/proration_zero_refund_at_exact_period_end
    """
    # MONTHLY member activated at 2026-06-01; cancel at exactly +30 days.
    ctx = setup_active_member(member_overrides={"plan_type": "MONTHLY"})
    set_clock("2026-07-01T00:00:00Z")  # exactly 30 days elapsed
    member = validate_success(
        api_client.cancel_member(ctx["member"]["id"], make_member_headers(ctx["member"]["id"])), 200)
    assert member["wallet_credit_cents"] == 0
    assert member["membership_status"] == "CANCELLED"


def test_proration_full_refund_same_day_cancel(api):
    """PRD §3.9: "a same-day cancellation (zero days elapsed) refunds the entire
    `member_share_cents` because the remaining days equal the full period length."

    Design: Difficulty/boundary_precision_check/proration_zero_refund_at_exact_period_end
    """
    # MONTHLY member, member_share=15000; cancel same day (0 days elapsed) ->
    # remaining_days == 30 == full period -> refund == 15000.
    ctx = setup_active_member(member_overrides={"plan_type": "MONTHLY"},
                              practice_overrides={"monthly_fee_cents": 15000})
    # No clock advance: cancel on the same instant as activation (2026-06-01).
    member = validate_success(
        api_client.cancel_member(ctx["member"]["id"], make_member_headers(ctx["member"]["id"])), 200)
    assert member["wallet_credit_cents"] == 15000
    assert member["membership_status"] == "CANCELLED"


def test_proration_partial_refund_mid_period(api):
    """PRD §3.9: "the daily share is the `member_share_cents` divided by the period
    length in days, kept as an exact rational value, and the refund is that daily
    share multiplied by the remaining days, rounded half up to whole cents exactly
    once at the end."

    Design: Corner/calculations/proration_partial_refund_mid_period
    """
    # member_share=15000, MONTHLY (30 days), cancel 15 days in:
    # round_half_up(15000/30 * 15) = round_half_up(7500.0) = 7500.
    ctx = setup_active_member(member_overrides={"plan_type": "MONTHLY"},
                              practice_overrides={"monthly_fee_cents": 15000})
    set_clock("2026-06-16T00:00:00Z")  # 15 days elapsed
    member = validate_success(
        api_client.cancel_member(ctx["member"]["id"], make_member_headers(ctx["member"]["id"])), 200)
    assert member["wallet_credit_cents"] == 7500


def test_charge_amount_mismatch_beats_pcp_required(api):
    """PRD §3.14: "charge-amount agreement (`ERR_AMOUNT_MISMATCH`), and
    PCP-before-activation (`ERR_PCP_REQUIRED`) — each evaluated within the workflow
    it guards as described above."
    PRD §3.8: "The submitted `amount_cents` must equal the amount actually owed —
    the membership's `member_share_cents` — or the charge is rejected with
    `ERR_AMOUNT_MISMATCH`."

    Design: Difficulty/priority_pair_validation_conflict/charge_amount_mismatch_beats_pcp_required
    """
    # Member registered (PENDING_PAYMENT), no PCP. member_share=15000.
    # Charge a wrong amount (99): both ERR_AMOUNT_MISMATCH and ERR_PCP_REQUIRED are
    # live, but §3.14 lists amount agreement before PCP-before-activation.
    ctx = setup_pending_member_no_pcp(member_overrides={"plan_type": "MONTHLY"})
    res = api_client.charge_membership(
        ctx["membership"]["id"], charge_payload("MEMBERSHIP_FEE", 99, "SUCCEEDED"),
        make_member_headers(ctx["member"]["id"]))
    validate_error(res, ApiErrorId.ERR_AMOUNT_MISMATCH.value)


def test_pcp_required_blocks_first_activation(api):
    """PRD §3.3: "Attempting the first activating charge while
    `assigned_provider_id` is still null is rejected with `ERR_PCP_REQUIRED`."

    Design: Difficulty/priority_pair_validation_conflict/charge_amount_mismatch_beats_pcp_required
    """
    # No PCP, but submit the CORRECT amount so ERR_AMOUNT_MISMATCH does not apply;
    # only the PCP-required gate is live, isolating the lower-priority face.
    ctx = setup_pending_member_no_pcp(member_overrides={"plan_type": "MONTHLY"})
    share = ctx["membership"]["member_share_cents"]
    res = api_client.charge_membership(
        ctx["membership"]["id"], charge_payload("MEMBERSHIP_FEE", share, "SUCCEEDED"),
        make_member_headers(ctx["member"]["id"]))
    validate_error(res, ApiErrorId.ERR_PCP_REQUIRED.value)
