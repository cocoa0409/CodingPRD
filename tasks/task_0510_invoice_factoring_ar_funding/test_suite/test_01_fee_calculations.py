"""Fee calculation depth tests: provisional flat per-diem vs final tiered fee,
the advance split, and the tiered round-per-tier-then-sum order.

Difficulty queue A: dual_variant_calc, combinatorial_formula (fee tier).
"""
import pytest
from test_helpers import (
    api_client, validate_success, validate_paginated, get_success_data,
    setup_funded_invoice, post_collection, advance_clock,
    assert_face_equals_advance_plus_reserve,
    TEST_USERS,
)

FO = TEST_USERS["funding_headers"]
CO = TEST_USERS["collections_headers"]


def test_provisional_fee_at_45_days_is_flat_2250(api):
    """PRD §3.6: "It equals the face amount multiplied by `fee_rate_per_day`
    multiplied by the number of whole days elapsed since funding". §3.7: "This
    per-tier-round-then-sum order is the pinned mode and diverges from the flat
    provisional accrual once the financed span exceeds 30 days."

    Provisional fee on face=100000 at 0.0005/day over 45 days = 2250, flat
    (no tiering), which differs from the FINAL tiered 2625.

    Design: Difficulty/dual_variant_calc/dvc_provisional_vs_final_fee_diverge_at_45_days
    """
    ctx = setup_funded_invoice(face_amount_cents=100000, advance_rate_pct=0.85,
                               fee_rate_per_day=0.0005, tier2_multiplier=1.5,
                               tier3_multiplier=2.0, verification_required=True,
                               invoice_overrides={"invoice_number": "INV-DVC"})
    advance_clock("2026-06-15T00:00:00Z")  # 45 days after funded_at 2026-05-01
    invoice = validate_success(api.get_invoice(ctx["invoice"]["id"], FO), 200)
    assert invoice["accrued_fee_cents"] == 2250, (
        f"PROVISIONAL flat 0.0005*100000*45 = 2250, got {invoice['accrued_fee_cents']}"
    )


def test_final_fee_at_45_days_is_tiered_2625_diverges_from_provisional(api):
    """PRD §3.7: "the first tier is the lesser of the day count and 30 days; the
    second tier is the day count beyond 30, capped at a further 30 days ... the
    second tier's fee is the face amount times `fee_rate_per_day` times
    `tier2_multiplier` times the second tier's days ... Each tier's fee is
    rounded half-up to whole cents independently, and only then are the three
    rounded tier amounts summed to give `final_fee_cents`."

    On settlement at 45 days FINAL = f1(30d)=1500 + f2(15d*1.5)=1125 = 2625,
    diverging from the PROVISIONAL 2250.

    Design: Difficulty/dual_variant_calc/dvc_provisional_vs_final_fee_diverge_at_45_days
    """
    ctx = setup_funded_invoice(face_amount_cents=100000, advance_rate_pct=0.85,
                               fee_rate_per_day=0.0005, tier2_multiplier=1.5,
                               tier3_multiplier=2.0, verification_required=True,
                               invoice_overrides={"invoice_number": "INV-DVC"})
    advance_clock("2026-06-15T00:00:00Z")
    # Full collection received_at 2026-06-15 (45 days) settles the invoice.
    post_collection(ctx["invoice"]["id"], ctx["client"]["id"],
                    100000, "2026-06-15T00:00:00Z")
    invoice = validate_success(api.get_invoice(ctx["invoice"]["id"], FO), 200)
    assert invoice["status"] == "SETTLED"
    assert invoice["final_fee_cents"] == 2625, (
        f"FINAL tiered 1500+1125 = 2625, got {invoice['final_fee_cents']}"
    )
    data, _ = validate_paginated(
        api.list_settlements(FO, params={"invoice_id": ctx["invoice"]["id"]}))
    assert len(data) == 1
    assert data[0]["fee_applied_cents"] == 2625
    assert data[0]["rebate_cents"] == 12375


def test_advance_split_round_half_up_per_invoice(api):
    """PRD §3.5: "The `advance_amount_cents` is the face value multiplied by the
    advance rate, rounded half-up to whole cents, and the `reserve_held_cents`
    is the exact remainder of `face_amount_cents` minus `advance_amount_cents`."

    face=12345 @ 0.85 = 10493.25 -> round_half_up -> 10493; reserve 1852.

    Design: Difficulty/dual_variant_calc/dvc_advance_split_vs_concentration_ratio_diff_domains
    """
    ctx = setup_funded_invoice(face_amount_cents=12345, advance_rate_pct=0.85,
                               concentration_pct=0.50,
                               invoice_overrides={"invoice_number": "INV-SPLIT"})
    invoice = ctx["invoice"]
    assert invoice["advance_amount_cents"] == 10493, (
        f"round_half_up(12345*0.85)=round_half_up(10493.25)=10493, "
        f"got {invoice['advance_amount_cents']}"
    )
    assert invoice["reserve_held_cents"] == 1852, (
        f"12345-10493=1852, got {invoice['reserve_held_cents']}"
    )
    assert_face_equals_advance_plus_reserve(invoice)


def test_advance_split_distinct_domain_from_debtor_face_aggregate(api):
    """PRD §2.8: "On each debtor, `outstanding_face_cents` is the sum of
    `face_amount_cents` across the debtor's invoices in those same three
    statuses."

    The debtor face aggregate (12345) is a different domain from the per-invoice
    advance rounding (10493); after funding the debtor reflects the full face.

    Design: Difficulty/dual_variant_calc/dvc_advance_split_vs_concentration_ratio_diff_domains
    """
    ctx = setup_funded_invoice(face_amount_cents=12345, advance_rate_pct=0.85,
                               concentration_pct=0.50,
                               invoice_overrides={"invoice_number": "INV-SPLIT"})
    debtor = validate_success(api.get_debtor(ctx["debtor"]["id"], FO), 200)
    assert debtor["outstanding_face_cents"] == 12345, (
        f"debtor face aggregate is the full face 12345, "
        f"got {debtor['outstanding_face_cents']}"
    )


def test_final_fee_round_per_tier_then_sum_face_33333(api):
    """PRD §3.7: "Each tier's fee is rounded half-up to whole cents
    independently, and only then are the three rounded tier amounts summed to
    give `final_fee_cents`."

    face=33333 over 45 days: tier1 round_half_up(33333*0.0005*30)=round(499.995)=500;
    tier2 round_half_up(33333*0.0005*1.5*15)=round(374.99625)=375; sum 875.

    Design: Difficulty/combinatorial_formula/cf_final_fee_round_per_tier_then_sum
    """
    ctx = setup_funded_invoice(face_amount_cents=33333, advance_rate_pct=0.80,
                               fee_rate_per_day=0.0005, tier2_multiplier=1.5,
                               tier3_multiplier=2.0,
                               invoice_overrides={"invoice_number": "INV-CF"})
    advance_clock("2026-06-15T00:00:00Z")  # 45 days
    post_collection(ctx["invoice"]["id"], ctx["client"]["id"],
                    33333, "2026-06-15T00:00:00Z")
    invoice = validate_success(api.get_invoice(ctx["invoice"]["id"], FO), 200)
    assert invoice["status"] == "SETTLED"
    assert invoice["final_fee_cents"] == 875, (
        f"tier1 500 + tier2 375 = 875 (round per tier then sum), "
        f"got {invoice['final_fee_cents']}"
    )


def test_final_fee_pinned_on_settlement_face_33333(api):
    """PRD §3.7: "When an invoice terminalizes — on settlement, short-pay,
    buyback, or write-off — its `final_fee_cents` is pinned as a tiered,
    escalating per-diem figure and never recomputed thereafter."

    Full collection drives the face-33333 invoice to SETTLED and pins the FINAL
    tiered fee on the Settlement record (fee_applied 875).

    Design: Difficulty/combinatorial_formula/cf_final_fee_round_per_tier_then_sum
    """
    ctx = setup_funded_invoice(face_amount_cents=33333, advance_rate_pct=0.80,
                               fee_rate_per_day=0.0005, tier2_multiplier=1.5,
                               tier3_multiplier=2.0,
                               invoice_overrides={"invoice_number": "INV-CF"})
    advance_clock("2026-06-15T00:00:00Z")  # 45 days
    post_collection(ctx["invoice"]["id"], ctx["client"]["id"],
                    33333, "2026-06-15T00:00:00Z")
    invoice = validate_success(api.get_invoice(ctx["invoice"]["id"], FO), 200)
    assert invoice["status"] == "SETTLED"
    data, _ = validate_paginated(
        api.list_settlements(FO, params={"invoice_id": ctx["invoice"]["id"]}))
    assert len(data) == 1
    assert data[0]["fee_applied_cents"] == 875, (
        f"FINAL tiered fee 875 pinned on settlement, got {data[0]['fee_applied_cents']}")
