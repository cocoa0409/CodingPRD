"""Pricing-engine compliance: tiered buyer's premium, droit de suite resale
royalty (marginal tiers, floor, cap), and seller net payable. Each test pins
a literal expected figure that the PRD's marginal-tier prose uniquely derives.
"""
from test_helpers import get_success_data
from test_helpers.fixtures import (
    setup_statemented_lot, setup_sold_lot, invoice_sold_lot, FINANCE,
)
from test_helpers.factories import STANDARD_TIERS


# ===========================================================================
# Queue A — dual_variant_calc
# ===========================================================================
def test_buyers_premium_and_seller_net_diverge_on_same_hammer(api):
    """PRD §3.6: "These contributions are accumulated as an exact rational
    across all bands the hammer reaches, and only the summed total is rounded
    — once, half up — to give `buyers_premium_cents`."
    PRD §3.6: "The invoice's `total_due_cents` is then the `hammer_price_cents`
    plus the `buyers_premium_cents`."
    PRD §3.8: "the `net_payable_cents` is the `hammer_price_cents` less the
    `seller_commission_cents` less the `resale_royalty_withheld_cents`."

    Same hammer 1,250,000 drives a buyer-side total_due of 1,575,000 on the
    Invoice and a seller-side net_payable of 1,075,000 on the SellerStatement.

    Design: Difficulty/dual_variant_calc/dual_variant_buyers_premium_vs_seller_net_diverge
    """
    scene, statement = setup_statemented_lot(
        hammer_cents=1250000, tiers=STANDARD_TIERS, seller_commission_bps=1000,
        artist_alive=True)
    invoice = scene["invoice"]
    assert invoice["buyers_premium_cents"] == 325000, invoice["buyers_premium_cents"]
    assert invoice["total_due_cents"] == 1575000, invoice["total_due_cents"]
    assert statement["seller_commission_cents"] == 125000, statement["seller_commission_cents"]
    assert statement["net_payable_cents"] == 1075000, statement["net_payable_cents"]
    assert invoice["total_due_cents"] != statement["net_payable_cents"]


def test_royalty_eligible_vs_ineligible_diverge(api):
    """PRD §3.7: "Eligibility has two conditions, both required: the lot's
    `artist_alive` must be true, and the hammer must be at least the royalty
    floor of 1,000.00 (100000 cents). If either condition fails the royalty is
    zero and no `ResaleRoyalty` row is created at all."
    PRD §3.8: "the `resale_royalty_withheld_cents` is read: it is the lot's
    `ResaleRoyalty` `royalty_cents` when a royalty row exists for the lot with
    `bearer` of `SELLER` and a status other than `REVERSED`, and 0 otherwise"
    PRD §3.8: "the `seller_commission_cents` is the lot's `hammer_price_cents`
    multiplied by the governing consignment's `seller_commission_bps`, divided
    by 10000, rounded once half up to integer cents."

    With artist_alive=false no royalty row exists; net = 1,250,000 - 187,500
    (15% commission) - 0 = 1,062,500.

    Design: Difficulty/dual_variant_calc/dual_variant_royalty_eligible_vs_ineligible
    """
    scene, statement = setup_statemented_lot(
        hammer_cents=1250000, tiers=STANDARD_TIERS, seller_commission_bps=1500,
        artist_alive=False)
    royalties = get_success_data(api.list_lot_resale_royalties(scene["lot"]["id"], FINANCE))
    assert royalties == [], f"expected no royalty when artist_alive=false, got {royalties}"
    assert statement["resale_royalty_withheld_cents"] == 0
    assert statement["seller_commission_cents"] == 187500, statement["seller_commission_cents"]
    assert statement["net_payable_cents"] == 1062500, statement["net_payable_cents"]


def test_dual_variant_buyer_charge_is_on_invoice_not_statement(api):
    """PRD §3.6: "The system computes the tiered `buyers_premium_cents` and the
    `total_due_cents`, and sets `amount_paid_cents` to 0."
    PRD §3.8: "the `seller_commission_cents` is the lot's `hammer_price_cents`
    multiplied by the governing consignment's `seller_commission_bps`, divided
    by 10000, rounded once half up to integer cents."

    The buyer charge (premium 325,000) lives on the Invoice while the seller
    charge (commission 125,000) lives on the SellerStatement — two distinct
    figures from the same 1,250,000 hammer on two distinct entities.

    Design: Difficulty/dual_variant_calc/dual_variant_buyers_premium_vs_seller_net_diverge
    """
    scene, statement = setup_statemented_lot(
        hammer_cents=1250000, tiers=STANDARD_TIERS, seller_commission_bps=1000,
        artist_alive=True)
    invoice = scene["invoice"]
    assert "buyers_premium_cents" in invoice and invoice["buyers_premium_cents"] == 325000
    assert "seller_commission_cents" in statement and statement["seller_commission_cents"] == 125000
    assert invoice["hammer_price_cents"] == statement["hammer_price_cents"] == 1250000


def test_dual_variant_royalty_eligible_accrues_withholding(api):
    """PRD §3.8: "the `resale_royalty_withheld_cents` is read: it is the lot's
    `ResaleRoyalty` `royalty_cents` when a royalty row exists for the lot with
    `bearer` of `SELLER` and a status other than `REVERSED`, and 0 otherwise"

    The eligible counterpart: with artist_alive=true at hammer 1,250,000 the
    royalty (50,000) is withheld on the statement and net = 1,075,000 at 10%
    commission — demonstrably different from the ineligible ledger.

    Design: Difficulty/dual_variant_calc/dual_variant_royalty_eligible_vs_ineligible
    """
    scene, statement = setup_statemented_lot(
        hammer_cents=1250000, tiers=STANDARD_TIERS, seller_commission_bps=1000,
        artist_alive=True)
    assert statement["resale_royalty_withheld_cents"] == 50000, statement["resale_royalty_withheld_cents"]
    assert statement["net_payable_cents"] == 1075000, statement["net_payable_cents"]


# ===========================================================================
# Queue A — combinatorial_formula
# ===========================================================================
def test_royalty_capped_at_high_hammer(api):
    """PRD §3.7: "That raw figure is then capped: the final `royalty_cents` is
    the smaller of the raw royalty and the absolute per-lot cap of 12,500.00
    (1250000 cents)."

    At hammer 200,000,000 the uncapped marginal sum exceeds the cap, so the
    royalty is exactly the cap, 1,250,000.

    Design: Difficulty/combinatorial_formula/combinatorial_royalty_marginal_tiers_with_cap
    """
    scene = setup_sold_lot(
        hammer_cents=200000000, tiers=STANDARD_TIERS, seller_commission_bps=1000,
        artist_alive=True, reserve_cents=100000000,
        low_estimate_cents=150000000, high_estimate_cents=250000000,
        credit_limit_cents=9000000000)
    scene, invoice = invoice_sold_lot(scene)
    royalties = get_success_data(api.list_lot_resale_royalties(scene["lot"]["id"], FINANCE))
    assert len(royalties) == 1, royalties
    assert royalties[0]["royalty_cents"] == 1250000, royalties[0]["royalty_cents"]
    assert royalties[0]["status"] == "ACCRUED"


def test_buyers_premium_rounding_order_pinned(api):
    """PRD §3.6: "These contributions are accumulated as an exact rational
    across all bands the hammer reaches, and only the summed total is rounded
    — once, half up — to give `buyers_premium_cents`. Rounding must not be
    applied tier by tier, because rounding each band and then summing can
    differ from the pinned method by a cent at band boundaries."

    HalfCent schedule (25.50% to 100,050, 10.50% open) at hammer 100,150:
    sum-exact-then-round gives 25,523 (not 25,524 from round-per-tier).

    Design: Difficulty/combinatorial_formula/combinatorial_buyers_premium_rounding_order_pinned
    """
    halfcent_tiers = [
        {"upper_bound_cents": 100050, "rate_bps": 2550},
        {"upper_bound_cents": None, "rate_bps": 1050},
    ]
    scene = setup_sold_lot(
        hammer_cents=100150, tiers=halfcent_tiers, seller_commission_bps=1000,
        artist_alive=False, reserve_cents=90000,
        low_estimate_cents=110000, high_estimate_cents=150000)
    scene, invoice = invoice_sold_lot(scene)
    assert invoice["buyers_premium_cents"] == 25523, invoice["buyers_premium_cents"]
    assert invoice["total_due_cents"] == 125673, invoice["total_due_cents"]


def test_royalty_cap_row_created_and_accrued(api):
    """PRD §3.7: "When a royalty-eligible lot is invoiced, the house accrues a
    droit de suite resale royalty as a `ResaleRoyalty` tied to the lot through
    its `lot_id`."
    PRD §3.7: "A royalty is created in `ACCRUED` status, and its `royalty_cents`
    is computed as below."

    Even when the marginal sum is driven into the cap, exactly one ACCRUED
    royalty row is created for the eligible lot.

    Design: Difficulty/combinatorial_formula/combinatorial_royalty_marginal_tiers_with_cap
    """
    scene = setup_sold_lot(
        hammer_cents=200000000, tiers=STANDARD_TIERS, seller_commission_bps=1000,
        artist_alive=True, reserve_cents=100000000,
        low_estimate_cents=150000000, high_estimate_cents=250000000,
        credit_limit_cents=9000000000)
    scene, invoice = invoice_sold_lot(scene)
    royalties = get_success_data(api.list_lot_resale_royalties(scene["lot"]["id"], FINANCE))
    assert len(royalties) == 1
    assert royalties[0]["status"] == "ACCRUED"
    assert royalties[0]["bearer"] == "SELLER"
    assert royalties[0]["hammer_price_cents"] == 200000000


def test_buyers_premium_rounding_total_due_matches(api):
    """PRD §3.6: "The invoice's `total_due_cents` is then the
    `hammer_price_cents` plus the `buyers_premium_cents`."

    With the pinned sum-then-round premium of 25,523 on hammer 100,150, the
    total_due is exactly 125,673 (100,150 + 25,523), confirming the rounding
    order propagates into total_due.

    Design: Difficulty/combinatorial_formula/combinatorial_buyers_premium_rounding_order_pinned
    """
    halfcent_tiers = [
        {"upper_bound_cents": 100050, "rate_bps": 2550},
        {"upper_bound_cents": None, "rate_bps": 1050},
    ]
    scene = setup_sold_lot(
        hammer_cents=100150, tiers=halfcent_tiers, seller_commission_bps=1000,
        artist_alive=False, reserve_cents=90000,
        low_estimate_cents=110000, high_estimate_cents=150000)
    scene, invoice = invoice_sold_lot(scene)
    assert invoice["hammer_price_cents"] == 100150
    assert invoice["buyers_premium_cents"] == 25523
    assert invoice["total_due_cents"] == invoice["hammer_price_cents"] + invoice["buyers_premium_cents"]
    assert invoice["total_due_cents"] == 125673


# ===========================================================================
# Queue B — calculations section
# ===========================================================================
def test_buyers_premium_cross_tier_correct(api):
    """PRD §3.6: "Each tier's `rate_bps` applies only to the portion of the
    hammer that falls within that tier's band — the slice between the previous
    tier's upper bound and this tier's upper bound (with the open tier's band
    running up to the full hammer)."

    Hammer 5,000,000 on the Standard schedule: 3,000,000*26% + 2,000,000*20%
    = 1,180,000 premium; total_due 6,180,000.

    Design: Corner/calculations/buyers_premium_cross_tier_correct
    """
    scene = setup_sold_lot(
        hammer_cents=5000000, tiers=STANDARD_TIERS, seller_commission_bps=1000,
        artist_alive=False, reserve_cents=3000000,
        low_estimate_cents=4000000, high_estimate_cents=6000000,
        credit_limit_cents=900000000)
    scene, invoice = invoice_sold_lot(scene)
    assert invoice["buyers_premium_cents"] == 1180000, invoice["buyers_premium_cents"]
    assert invoice["total_due_cents"] == 6180000, invoice["total_due_cents"]


def test_royalty_below_floor_not_accrued(api):
    """PRD §3.7: "Eligibility has two conditions, both required: the lot's
    `artist_alive` must be true, and the hammer must be at least the royalty
    floor of 1,000.00 (100000 cents). If either condition fails the royalty is
    zero and no `ResaleRoyalty` row is created at all."

    Hammer 90,000 (< 100,000 floor) with artist_alive=true -> no royalty row.

    Design: Corner/calculations/royalty_below_floor_not_accrued
    """
    scene = setup_sold_lot(
        hammer_cents=90000, tiers=STANDARD_TIERS, seller_commission_bps=1000,
        artist_alive=True, reserve_cents=50000,
        low_estimate_cents=95000, high_estimate_cents=150000)
    scene, invoice = invoice_sold_lot(scene)
    royalties = get_success_data(api.list_lot_resale_royalties(scene["lot"]["id"], FINANCE))
    assert royalties == [], f"hammer below floor must accrue no royalty, got {royalties}"
