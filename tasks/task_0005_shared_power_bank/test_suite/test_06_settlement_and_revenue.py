"""
Settlement workflow + revenue-share calculation (PRD §3.9 / §2.6).

Covers DRAFT → APPROVED → INVOICED transitions, provisional vs settled
variants, refund_adjustment cascade-when-INVOICED, gross_revenue, and
the per-rental rounding-then-sum order.
"""

from __future__ import annotations

import pytest

from test_helpers import (
    ADMIN_HEADERS,
    advance_clock_to,
    api_client,
    approve_and_invoice,
    assert_money_equal,
    assert_settlement,
    create_settlement_for,
    heartbeat,
    make_partner_headers,
    setup_settlement_universe,
    validate_error,
    validate_success,
)


# ---------------------------------------------------------------------------
# DRAFT → APPROVED → INVOICED workflow (PRD §3.9)
# ---------------------------------------------------------------------------


def test_settlement_created_in_draft(api):
    """PRD §3.9: "The settlement is born with status DRAFT."
    """
    env = setup_settlement_universe(n_users=2, revenue_share_pct=0.5)
    s = create_settlement_for(
        env["partner"]["id"],
        "2026-01-01T00:00:00Z",
        "2026-01-02T00:00:00Z",
    )
    assert_settlement(s)
    assert s["status"] == "DRAFT"


def test_settlement_period_invalid_rejected(api):
    """PRD §2.7 priority 18: "when creating a settlement, period_end is
    strictly after period_start (rejection: ERR_SETTLEMENT_PERIOD_INVALID,
    HTTP 422)."
    """
    env = setup_settlement_universe(n_users=1)
    res = api.create_settlement(
        {
            "location_partner_id": env["partner"]["id"],
            "period_start": "2026-01-02T00:00:00Z",
            "period_end": "2026-01-01T00:00:00Z",
        },
        ADMIN_HEADERS,
    )
    validate_error(res, "ERR_SETTLEMENT_PERIOD_INVALID")


def test_approve_transitions_to_approved(api):
    """PRD §3.9: "The administrator advances the settlement from DRAFT to
    APPROVED with the approve capability."
    """
    env = setup_settlement_universe(n_users=2, revenue_share_pct=0.5)
    s = create_settlement_for(
        env["partner"]["id"],
        "2026-01-01T00:00:00Z",
        "2026-01-02T00:00:00Z",
    )
    res = api.approve_settlement(s["id"], ADMIN_HEADERS)
    approved = validate_success(res, 200)
    assert approved["status"] == "APPROVED"


def test_invoice_issuance_writes_invoice_number(api):
    """PRD §3.9: "On this transition the server generates an invoice_number
    for the settlement."
    """
    env = setup_settlement_universe(n_users=2, revenue_share_pct=0.5)
    s = create_settlement_for(
        env["partner"]["id"],
        "2026-01-01T00:00:00Z",
        "2026-01-02T00:00:00Z",
    )
    invoiced = approve_and_invoice(s["id"])
    assert invoiced["status"] == "INVOICED"
    assert invoiced["invoice_number"] is not None
    assert isinstance(invoiced["invoice_number"], str)


# ---------------------------------------------------------------------------
# Provisional revenue-share calculation (PRD §3.9 / §2.6)
# ---------------------------------------------------------------------------


def test_provisional_partner_amount_per_rental_rounding(api):
    """PRD §3.9: "The provisional partner amount is the sum, over the rentals
    in the universe whose payment_status is BILLED, of each rental's
    charged_amount multiplied by the partner's revenue_share_pct, rounded to
    two decimal places with round-half-up per rental, before the rounded
    values are summed."

    With 3 BILLED rentals at charged_amount=3.00 each and pct=0.335:
    per-rental round = round(3.00*0.335, 2, ROUND_HALF_UP) = 1.01.
    Sum = 1.01 * 3 = 3.03. (Sum-then-round would give 3.02 — forbidden.)
    """
    env = setup_settlement_universe(
        n_users=3, revenue_share_pct=0.335, rental_hours=1.0,
        base_clock="2026-01-01T10:00:00Z"
    )
    s = create_settlement_for(
        env["partner"]["id"],
        "2026-01-01T00:00:00Z",
        "2026-01-02T00:00:00Z",
    )
    assert_money_equal(s["partner_amount"], 3.03)


def test_provisional_gross_revenue_is_billed_sum(api):
    """PRD §3.9: "The gross_revenue on a provisional settlement is the sum of
    charged_amount over the same BILLED subset."
    """
    env = setup_settlement_universe(
        n_users=3, revenue_share_pct=0.335, rental_hours=1.0,
        base_clock="2026-01-01T10:00:00Z"
    )
    s = create_settlement_for(
        env["partner"]["id"],
        "2026-01-01T00:00:00Z",
        "2026-01-02T00:00:00Z",
    )
    assert_money_equal(s["gross_revenue"], 9.00)


def test_provisional_refund_adjustment_zero(api):
    """PRD §3.9: "The refund_adjustment on a provisional settlement is 0.00,
    since pending refunds are not yet attributed to this period."
    """
    env = setup_settlement_universe(
        n_users=3, revenue_share_pct=0.335, rental_hours=1.0
    )
    s = create_settlement_for(
        env["partner"]["id"],
        "2026-01-01T00:00:00Z",
        "2026-01-02T00:00:00Z",
    )
    assert_money_equal(s["refund_adjustment"], 0.00)


# ---------------------------------------------------------------------------
# Settled variant after refund (PRD §3.9)
# ---------------------------------------------------------------------------


def test_settled_variant_subtracts_refund_adjustment(api):
    """PRD §3.9: "The settled variant adds refunded rentals into the
    calculation: the refund_adjustment becomes the sum, over the rentals in
    the same universe whose payment_status is REFUNDED, of each rental's
    refund_amount multiplied by the partner's revenue_share_pct, again
    rounded to two decimal places per rental and then summed; the
    partner_amount becomes the provisional-style billed sum (unchanged from
    the provisional formula) minus this refund_adjustment."
    """
    env = setup_settlement_universe(
        n_users=3, revenue_share_pct=0.335, rental_hours=1.0,
        base_clock="2026-01-01T10:00:00Z"
    )
    s = create_settlement_for(
        env["partner"]["id"],
        "2026-01-01T00:00:00Z",
        "2026-01-02T00:00:00Z",
    )
    # Refund the first rental → REFUNDED.
    api.refund_rental(env["rentals"][0]["id"], ADMIN_HEADERS)
    invoiced = approve_and_invoice(s["id"])
    # PRD §3.9: settled-variant partner_amount = (billed-share sum) − refund_adjustment.
    # After refund, BILLED count drops to 2 → billed-share = 2 * round(3.00*0.335,2) = 2.02.
    # refund_adjustment = round(3.00*0.335,2) = 1.01 (one refunded rental).
    # partner_amount = 2.02 - 1.01 = 1.01.
    assert_money_equal(invoiced["refund_adjustment"], 1.01)
    assert_money_equal(invoiced["partner_amount"], 1.01)
    # gross_revenue (settled) = sum(charged for BILLED) − sum(refund for REFUNDED)
    #                        = (2 * 3.00) − (1 * 3.00) = 3.00.
    assert_money_equal(invoiced["gross_revenue"], 3.00)


# ---------------------------------------------------------------------------
# Refund cascade post-INVOICED (PRD §3.9 / §3.7)
# ---------------------------------------------------------------------------


def test_post_invoiced_refund_adjusts_settlement(api):
    """PRD §3.9: "Once a settlement reaches INVOICED, subsequent refunds
    against rentals that fall inside its period continue to flow into its
    refund_adjustment as a cascade leg from the refund operation, increasing
    the running refund_adjustment by the per-rental partner share of each
    new refund."
    """
    env = setup_settlement_universe(
        n_users=3, revenue_share_pct=0.335, rental_hours=1.0,
        base_clock="2026-01-01T10:00:00Z"
    )
    s = create_settlement_for(
        env["partner"]["id"],
        "2026-01-01T00:00:00Z",
        "2026-01-02T00:00:00Z",
    )
    invoiced_pre = approve_and_invoice(s["id"])
    refund_pre = invoiced_pre["refund_adjustment"]
    # Refund a rental inside the period after INVOICED.
    api.refund_rental(env["rentals"][1]["id"], ADMIN_HEADERS)
    fresh = validate_success(
        api.get_settlement(s["id"], ADMIN_HEADERS), 200
    )
    # Per-rental partner share = round(3.00 * 0.335, 2) = 1.01
    assert_money_equal(fresh["refund_adjustment"], refund_pre + 1.01)


# ---------------------------------------------------------------------------
# Partner-scoped read (PRD §2.1 + §3.9)
# ---------------------------------------------------------------------------


def test_partner_can_read_own_settlement(api):
    """PRD §3.9: "A Partner may read settlements scoped to their own partner
    record."
    """
    env = setup_settlement_universe(n_users=2, revenue_share_pct=0.5)
    s = create_settlement_for(
        env["partner"]["id"],
        "2026-01-01T00:00:00Z",
        "2026-01-02T00:00:00Z",
    )
    res = api.get_settlement(
        s["id"], make_partner_headers(env["partner"]["id"])
    )
    fetched = validate_success(res, 200)
    assert fetched["id"] == s["id"]
    assert fetched["location_partner_id"] == env["partner"]["id"]


def test_partner_cannot_read_other_partners_settlement(api):
    """PRD §3.9: "scoped to their own partner record."
    """
    from test_helpers import create_location_partner

    env = setup_settlement_universe(n_users=1, revenue_share_pct=0.5)
    other = create_location_partner()
    s = create_settlement_for(
        env["partner"]["id"],
        "2026-01-01T00:00:00Z",
        "2026-01-02T00:00:00Z",
    )
    res = api.get_settlement(s["id"], make_partner_headers(other["id"]))
    validate_error(res, "ERR_FORBIDDEN")
