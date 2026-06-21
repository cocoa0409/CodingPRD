"""Commission waterfall, net-to-seller sheet, and conservation invariants."""
from test_helpers import (
    validate_success,
    setup_active_listing_with_open_offer,
    setup_pending_listing,
    setup_active_listing,
    close_listing,
    get_first_ledger,
    current_listing_version,
    api_client,
    make_listing_agent_headers,
    assert_commission_conserved,
)


def test_net_sheet_provisional_basis_is_leading_live_offer(api):
    """PRD §3.9: "Its price basis is the *leading* live offer's `current_price_cents`
    — the highest `current_price_cents` among the listing's live offers, breaking
    ties in favor of the earliest-created offer."
    PRD §3.9: "the total commission is the basis price multiplied by the listing's
    `total_commission_pct`, rounded half up to whole cents, and the net to the seller
    is the basis price minus that total commission minus a seller-concession amount
    that is currently fixed at 0 cents."

    Design: Difficulty/dual_variant_calc/net_to_seller_provisional_vs_final_diverge
    """
    s = setup_active_listing_with_open_offer(
        list_price_cents=50_000_000, initial_price_cents=49_000_000,
        buyer_overrides={"max_budget_cents": 60_000_000})
    la = s["listing_agent"]["id"]

    resp = api.get_net_sheet(s["listing"]["id"], headers=make_listing_agent_headers(la))
    data = validate_success(resp, 200)

    # Basis is the leading live offer current_price_cents (49000000), NOT list price.
    assert data["basis_price_cents"] == 49_000_000, data
    assert data["total_commission_cents"] == 2_940_000, data
    assert data["net_to_seller_cents"] == 46_060_000, data


def test_final_net_basis_is_accepted_effective_price(api):
    """PRD §3.9: "The **final** variant is computed at close and recorded; its price
    basis is the accepted offer's frozen `effective_price_cents`, which can differ
    from any provisional leading-offer basis because counters may have moved the
    number after the net-sheet was last read."
    PRD §3.8: "its `final_sale_price_cents` is set to the accepted offer's
    `effective_price_cents`"

    Design: Difficulty/dual_variant_calc/net_to_seller_provisional_vs_final_diverge
    """
    # Accepted offer at 50000000 (no counters); final basis == effective price.
    s = setup_pending_listing(sale_price_cents=50_000_000)
    la = s["listing_agent"]["id"]
    closed = close_listing(s["listing"]["id"], la)
    assert closed["final_sale_price_cents"] == 50_000_000, closed

    ledger = get_first_ledger(s["listing"]["id"], la)
    # Final basis is the accepted effective price 50000000 -> commission 3000000,
    # diverging from the provisional leading-offer basis of the other instance.
    assert ledger["sale_price_cents"] == 50_000_000, ledger
    assert ledger["total_commission_cents"] == 3_000_000, ledger


def test_commission_split_nested_rounding_order_pinned(api):
    """PRD §2.7: "The co-op (buyer-side) share is then the **already-rounded** total
    commission multiplied by the listing's co-op split, again rounded half up to whole
    cents — the co-op share is rounded off the rounded total, never off the raw product
    of sale price, total rate, and split."
    PRD §3.8: "the `total_commission_cents` is the sale price multiplied by the
    listing's `total_commission_pct`, rounded half up; the `coop_commission_cents` is
    that already-rounded total multiplied by the listing's `coop_split_pct`, rounded
    half up; and the `listing_side_commission_cents` is the total minus the co-op
    share, so it absorbs the rounding penny"

    Design: Difficulty/combinatorial_formula/commission_split_nested_rounding_order_pinned
    """
    s = setup_pending_listing(sale_price_cents=16_666_675)
    la = s["listing_agent"]["id"]
    close_listing(s["listing"]["id"], la)
    ledger = get_first_ledger(s["listing"]["id"], la)

    # round_half_up(16666675*0.06) = 1000000.5 -> 1000001
    assert ledger["total_commission_cents"] == 1_000_001, ledger
    # round_half_up(1000001*0.50) = 500000.5 -> 500001 (off the rounded total)
    assert ledger["coop_commission_cents"] == 500_001, ledger
    # 1000001 - 500001 = 500000 (listing side absorbs the penny)
    assert ledger["listing_side_commission_cents"] == 500_000, ledger


def test_commission_total_rounds_half_up_at_half_cent(api):
    """PRD §2.7: "The total commission is the sale price multiplied by the listing's
    total commission rate, rounded half up to whole cents."
    PRD §3.8: "the `total_commission_cents` is the sale price multiplied by the listing's
    `total_commission_pct`, rounded half up".

    Design: Difficulty/combinatorial_formula/commission_split_nested_rounding_order_pinned
    """
    # 16666675*0.06 = 1000000.5 exactly -> round_half_up -> 1000001 (the .5 boundary
    # that feeds the pinned nested rounding of the co-op share).
    s = setup_pending_listing(sale_price_cents=16_666_675)
    la = s["listing_agent"]["id"]
    close_listing(s["listing"]["id"], la)
    ledger = get_first_ledger(s["listing"]["id"], la)
    assert ledger["total_commission_cents"] == 1_000_001, ledger
    # Co-op rounded off the already-rounded total (1000001*0.5=500000.5 -> 500001),
    # not off the raw product (which would yield 500000).
    assert ledger["coop_commission_cents"] == 500_001, ledger


def test_commission_shares_sum_to_total_invariant(api):
    """PRD §2.7: "The listing-side share is the rounded total minus the rounded co-op
    share, so the listing side absorbs any single-cent rounding remainder and the two
    shares always sum exactly to the total."
    PRD §3.8: "it absorbs the rounding penny and the two shares sum exactly to the total."

    Design: Difficulty/compensating_invariant/commission_shares_sum_to_total_invariant
    """
    s = setup_pending_listing(sale_price_cents=16_666_675)
    la = s["listing_agent"]["id"]
    close_listing(s["listing"]["id"], la)
    ledger = get_first_ledger(s["listing"]["id"], la)

    assert ledger["coop_commission_cents"] == 500_001, ledger
    assert ledger["listing_side_commission_cents"] == 500_000, ledger
    assert ledger["total_commission_cents"] == 1_000_001, ledger
    assert_commission_conserved(ledger)


def test_commission_shares_conserved_round_number_sale(api):
    """PRD §2.7: "The listing-side share is the rounded total minus the rounded co-op
    share, so the listing side absorbs any single-cent rounding remainder and the two
    shares always sum exactly to the total."

    Design: Difficulty/compensating_invariant/commission_shares_sum_to_total_invariant
    """
    s = setup_pending_listing(sale_price_cents=50_000_000)
    la = s["listing_agent"]["id"]
    close_listing(s["listing"]["id"], la)
    ledger = get_first_ledger(s["listing"]["id"], la)

    # 50000000*0.06 = 3000000; coop 0.50 -> 1500000; listing side 1500000.
    assert ledger["total_commission_cents"] == 3_000_000, ledger
    assert ledger["coop_commission_cents"] == 1_500_000, ledger
    assert ledger["listing_side_commission_cents"] == 1_500_000, ledger
    assert_commission_conserved(ledger)


def test_net_sheet_null_when_no_live_offer(api):
    """PRD §3.9: "If the listing has no live offer and no accepted offer, the sheet's
    `net_to_seller_cents` is null."

    Design: Corner/endpoints/net_sheet_null_when_no_live_offer
    """
    s = setup_active_listing(list_price_cents=50_000_000)
    la = s["listing_agent"]["id"]
    resp = api.get_net_sheet(s["listing"]["id"], headers=make_listing_agent_headers(la))
    data = validate_success(resp, 200)
    assert data["net_to_seller_cents"] is None, data
