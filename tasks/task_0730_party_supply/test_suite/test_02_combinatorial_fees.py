"""Difficulty rule 2 — combinatorial formulas across different modes.

Instance A: mode (b) round-then-sum — helium fill fee per-line rounding.
Instance B: mode (a) ≥3 inputs, non-linear tiered rate + conditional
            revision surcharge — custom print fee.
"""
from test_helpers import (
    validate_success, api_client, make_store_clerk_headers,
    make_customer_headers,
)
from test_helpers.fixtures import (
    set_clock, create_customer, create_sku_with_stock, create_helium_tank,
    setup_draft_order, attach_helium, reserve_order,
    attach_custom_print, pay_order,
)


# =====================================================================
# Instance A — helium_fill_fee_per_line_rounding_order_pinned
# =====================================================================

def test_helium_fill_fee_latex_bulk_and_foil_base_rounded_per_line():
    """PRD §3.4: "The latex line is computed as latex_count multiplied by
    175 cents per balloon, then multiplied by 0.85 if latex_count is at
    least 25 and 1.0 otherwise, and rounded half-up to whole cents."
    PRD §3.4: "The foil line is computed as foil_count multiplied by 425
    cents per balloon, then multiplied by 0.90 if foil_count is at least
    10 and 1.0 otherwise, and rounded half-up to whole cents."
    PRD §3.4: "The fill_fee_cents of the helium order is the sum of the
    two rounded line values — round each line first, then add."

    Design: Difficulty/combinatorial_formula/helium_fill_fee_per_line_rounding_order_pinned
    """
    set_clock("2026-06-15T10:00:00Z")
    cust = create_customer()
    sku = create_sku_with_stock(unit_price_cents=100, on_hand=100,
                                category="BALLOON_LATEX")
    tank = create_helium_tank(capacity=100)
    order = setup_draft_order(cust["id"], sku["id"], qty=1)
    attach_helium(order["id"], latex_count=30, foil_count=7)
    resp = api_client.reserve_order(
        order["id"], order["version"], make_store_clerk_headers()
    )
    reserved = validate_success(resp)
    # latex: 30 * 175 * 0.85 = 4462.5 → round_half_up → 4463
    # foil : 7 * 425 = 2975 (no bulk, foil<10)  → 2975
    # sum  : 4463 + 2975 = 7438
    assert reserved["helium_fee_cents"] == 7438, (
        f"helium_fee_cents = round(30*175*0.85)+round(7*425)"
        f" = 4463 + 2975 = 7438; got {reserved['helium_fee_cents']}"
    )


def test_helium_fill_fee_both_lines_bulk_tier_active():
    """PRD §3.4: "The latex line is computed as latex_count multiplied by
    175 cents per balloon, then multiplied by 0.85 if latex_count is at
    least 25 and 1.0 otherwise, and rounded half-up to whole cents."
    PRD §3.4: "The foil line is computed as foil_count multiplied by 425
    cents per balloon, then multiplied by 0.90 if foil_count is at least
    10 and 1.0 otherwise, and rounded half-up to whole cents."
    PRD §3.4: "The fill_fee_cents of the helium order is the sum of the
    two rounded line values — round each line first, then add."

    Design: Difficulty/combinatorial_formula/helium_fill_fee_per_line_rounding_order_pinned
    """
    set_clock("2026-06-15T10:00:00Z")
    cust = create_customer()
    sku = create_sku_with_stock(unit_price_cents=100, on_hand=100,
                                category="BALLOON_LATEX")
    create_helium_tank(capacity=200)
    order = setup_draft_order(cust["id"], sku["id"], qty=1)
    attach_helium(order["id"], latex_count=40, foil_count=12)
    resp = api_client.reserve_order(
        order["id"], order["version"], make_store_clerk_headers()
    )
    reserved = validate_success(resp)
    # latex: 40 * 175 * 0.85 = 5950 (integer) → 5950
    # foil : 12 * 425 * 0.90 = 4590            → 4590
    # sum  : 10540
    assert reserved["helium_fee_cents"] == 10540, (
        f"helium_fee_cents = round(40*175*0.85) + round(12*425*0.90) "
        f"= 5950 + 4590 = 10540; got {reserved['helium_fee_cents']}"
    )


# =====================================================================
# Instance B — custom_print_fee_tiered_with_revision_conditional_branch
# =====================================================================

def test_custom_print_fee_20ft_no_revision_surcharge():
    """PRD §3.7: "Let the number of feet in the first tier be the smaller
    of banner_length_ft and 5; let the number of feet in the second tier
    be the maximum of zero and the smaller of banner_length_ft and 15
    reduced by 5; let the number of feet in the third tier be the maximum
    of zero and banner_length_ft reduced by 15. The unrounded fee is the
    first-tier feet multiplied by 800 plus the second-tier feet multiplied
    by 600 plus the third-tier feet multiplied by 450 — each per-tier
    product is left unrounded."
    PRD §3.7: "To this the server adds a revision surcharge of 500 cents
    multiplied by the maximum of zero and revision_count minus one — the
    first revision is free, and each additional revision costs 500 cents."

    Design: Difficulty/combinatorial_formula/custom_print_fee_tiered_with_revision_conditional_branch
    """
    set_clock("2026-06-15T10:00:00Z")
    cust = create_customer()
    sku = create_sku_with_stock(unit_price_cents=200, on_hand=100,
                                category="DECOR")
    order = setup_draft_order(cust["id"], sku["id"], qty=1)
    cpo = attach_custom_print(order["id"], banner_length_ft=20)
    reserved = reserve_order(order["id"], order["version"])
    pay_order(reserved["id"], "FULL")
    # send-proof then approve
    resp_sp = api_client.send_proof(cpo["id"], make_store_clerk_headers())
    validate_success(resp_sp)
    resp_ap = api_client.approve_proof(
        cpo["id"], make_customer_headers(cust["id"]),
    )
    approved = validate_success(resp_ap)
    # 20-ft: span_1=5, span_2=10, span_3=5
    # 5*800 + 10*600 + 5*450 = 4000 + 6000 + 2250 = 12250 unrounded
    # revision_count=0 → surcharge branch max(0, 0-1)=0 → 12250
    assert approved["print_fee_cents"] == 12250, (
        f"20-ft banner, revision_count=0: 5*800 + 10*600 + 5*450 = 12250; "
        f"got {approved['print_fee_cents']}"
    )


def test_custom_print_fee_first_tier_only_boundary_5ft():
    """PRD §3.7: "Let the first tier end at 5 feet and the second at 15
    feet. The first tier rate is 800 cents per foot, the second is 600
    cents per foot, and the third — for any additional feet beyond 15 —
    is 450 cents per foot."
    PRD §3.7: "Let the number of feet in the first tier be the smaller of
    banner_length_ft and 5; let the number of feet in the second tier be
    the maximum of zero and the smaller of banner_length_ft and 15
    reduced by 5; let the number of feet in the third tier be the maximum
    of zero and banner_length_ft reduced by 15."
    PRD §3.7: "To this the server adds a revision surcharge of 500 cents
    multiplied by the maximum of zero and revision_count minus one — the
    first revision is free, and each additional revision costs 500 cents."

    Design: Difficulty/combinatorial_formula/custom_print_fee_tiered_with_revision_conditional_branch
    """
    set_clock("2026-06-15T10:00:00Z")
    cust = create_customer()
    sku = create_sku_with_stock(unit_price_cents=200, on_hand=100,
                                category="DECOR")
    order = setup_draft_order(cust["id"], sku["id"], qty=1)
    cpo = attach_custom_print(order["id"], banner_length_ft=5)
    reserved = reserve_order(order["id"], order["version"])
    pay_order(reserved["id"], "FULL")
    resp_sp = api_client.send_proof(cpo["id"], make_store_clerk_headers())
    validate_success(resp_sp)
    resp_ap = api_client.approve_proof(
        cpo["id"], make_customer_headers(cust["id"])
    )
    approved = validate_success(resp_ap)
    # 5-ft: span_1=5, span_2=0, span_3=0 -> 5*800=4000; revision_count=0 → no surcharge
    assert approved["print_fee_cents"] == 4000, (
        f"5-ft banner: 5*800 + 0 + 0 = 4000; got {approved['print_fee_cents']}"
    )
