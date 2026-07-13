"""Order pricing: the estimate/final two-stage calculation, volume-discount
tiers, fee layering, and the pinned promo-band evaluation order."""
from test_helpers import (
    create_customer, create_order, setup_ready_order,
    file_claim, approve_claim,
)


# ===========================================================================
# dual_variant_calc / order_estimate_vs_final_total_diverge
# ===========================================================================
def test_estimate_frozen_from_declared_counts(api):
    """PRD §3.1: "From these four declared counts the system computes an
    **estimate** and stores it in `estimate_total_cents`."
    PRD §3.1: "Each media type contributes a per-item line rate: 1200 cents per
    tape, 1500 cents per film reel, 50 cents per photo, and 1000 cents per audio
    item."

    Two declared tapes with no discount tier, fee, or promo freeze the estimate
    at 2 * 1200 = 2400.

    Design: Difficulty/dual_variant_calc/order_estimate_vs_final_total_diverge
    """
    cust = create_customer(api, email="dv-est@x.com")
    order = create_order(api, cust["id"], declared={"declared_tape_count": 2})
    assert order["estimate_total_cents"] == 2400, order


def test_final_total_recomputed_from_surviving_items(api):
    """PRD §3.7: "The **final** order total recomputed after a write-off follows
    the same two-stage calculation as the estimate in §3.1, but its four
    media-type counts are drawn from the order's surviving media items rather
    than the declared counts: each count is the number of that order's media
    items of the given media type whose `status` is not `WRITTEN_OFF`."
    PRD §3.7: "Because written-off items drop out of these counts, the final
    total diverges from the estimate whenever the surviving counts differ from
    the originally declared counts."

    Two tapes declared and logged (estimate 2400); one written off via an
    approved claim leaves one surviving tape, so final = 1200 and the two
    persisted totals differ.

    Design: Difficulty/dual_variant_calc/order_estimate_vs_final_total_diverge
    """
    ready = setup_ready_order(api, items=("TAPE", "TAPE"), capture=True,
                              customer_email="dv-final@x.com")
    claim = file_claim(api, ready["order_id"], ready["customer_id"],
                       ready["item_ids"][0], claim_type="LOST")
    approve_claim(api, claim["id"])
    from test_helpers import get_order_admin
    order = get_order_admin(api, ready["order_id"])
    assert order["estimate_total_cents"] == 2400, order
    assert order["final_total_cents"] == 1200, order
    assert order["estimate_total_cents"] != order["final_total_cents"], order


# ===========================================================================
# combinatorial_formula / tiered_volume_discount_mode_a
# ===========================================================================
def test_volume_discount_ten_percent_tier(api):
    """PRD §3.1: "A volume-discount percentage is then selected from the item
    count: when the item count is at least 40 the percentage is twenty percent;
    otherwise when the item count is at least 20 the percentage is ten percent;
    otherwise there is no volume discount."
    PRD §3.1: "The volume discount amount is the raw subtotal multiplied by that
    percentage, rounded half up to whole cents, and the discounted subtotal is
    the raw subtotal minus that discount amount."

    20 tapes (>= 20) select the 10% tier: raw 24000 - 2400 = 21600.

    Design: Difficulty/combinatorial_formula/tiered_volume_discount_mode_a
    """
    cust = create_customer(api, email="cf-a1@x.com")
    order = create_order(api, cust["id"], declared={"declared_tape_count": 20})
    assert order["estimate_total_cents"] == 21600, order


def test_volume_discount_twenty_percent_tier(api):
    """PRD §3.1: "A volume-discount percentage is then selected from the item
    count: when the item count is at least 40 the percentage is twenty percent;
    otherwise when the item count is at least 20 the percentage is ten percent;
    otherwise there is no volume discount."

    40 tapes (>= 40) select the 20% tier: raw 48000 - 9600 = 38400.

    Design: Difficulty/combinatorial_formula/tiered_volume_discount_mode_a
    """
    cust = create_customer(api, email="cf-a2@x.com")
    order = create_order(api, cust["id"], declared={"declared_tape_count": 40})
    assert order["estimate_total_cents"] == 38400, order


# ===========================================================================
# combinatorial_formula / promo_evaluation_order_mode_c
# ===========================================================================
def test_promo_band_selected_from_pre_discount_total_with_protection(api):
    """PRD §3.1: "Third, a pre-discount total is formed as the discounted
    subtotal plus the rush surcharge plus the protection fee — this pre-discount
    total must be computed before any promotional reduction."
    PRD §3.1: "Fourth, the promotional reduction is selected from the
    pre-discount total, not from the subtotal: only the code `SAVE5` is
    recognized, and when it is present the reduction is 1000 cents if the
    pre-discount total is at least 13000 cents, or 500 cents if the pre-discount
    total is at least 10000 cents but below that, or zero otherwise; with no
    recognized code the reduction is zero."

    10 tapes (subtotal 12000) + protection (1500 + 2% of 12000 = 1740) gives a
    pre-discount total of 13740, selecting the 1000-cent band; total 12740.
    Keying the band off the 12000 subtotal would wrongly yield 13240.

    Design: Difficulty/combinatorial_formula/promo_evaluation_order_mode_c
    """
    cust = create_customer(api, email="cf-c1@x.com")
    order = create_order(api, cust["id"], protection=True, promo="SAVE5",
                         declared={"declared_tape_count": 10})
    assert order["estimate_total_cents"] == 12740, order


def test_promo_band_selected_from_pre_discount_total_with_rush(api):
    """PRD §3.1: "Fourth, the promotional reduction is selected from the
    pre-discount total, not from the subtotal: only the code `SAVE5` is
    recognized, and when it is present the reduction is 1000 cents if the
    pre-discount total is at least 13000 cents, or 500 cents if the pre-discount
    total is at least 10000 cents but below that, or zero otherwise; with no
    recognized code the reduction is zero."
    PRD §3.1: "First, a rush surcharge applies only when `turnaround` is `RUSH`:
    it is the discounted subtotal multiplied by thirty percent, rounded half up
    to whole cents; for `STANDARD` turnaround the surcharge is zero."

    10 tapes (subtotal 12000) + RUSH (3600) gives a pre-discount total of 15600,
    selecting the 1000-cent band; total 14600. The 12000 subtotal alone would
    select only the 500-cent band.

    Design: Difficulty/combinatorial_formula/promo_evaluation_order_mode_c
    """
    cust = create_customer(api, email="cf-c2@x.com")
    order = create_order(api, cust["id"], turnaround="RUSH", promo="SAVE5",
                         declared={"declared_tape_count": 10})
    assert order["estimate_total_cents"] == 14600, order


# ===========================================================================
# boundary_precision_check / volume_discount_threshold_at_20_items
# ===========================================================================
def test_volume_discount_boundary_below_and_at_twenty(api):
    """PRD §3.1: "A volume-discount percentage is then selected from the item
    count: when the item count is at least 40 the percentage is twenty percent;
    otherwise when the item count is at least 20 the percentage is ten percent;
    otherwise there is no volume discount."

    19 items miss the tier (no discount -> 22800); 20 items hit it inclusively
    (10% -> 21600).

    Design: Difficulty/boundary_precision_check/volume_discount_threshold_at_20_items
    """
    cust = create_customer(api, email="bp-1@x.com")
    order_19 = create_order(api, cust["id"], declared={"declared_tape_count": 19})
    order_20 = create_order(api, cust["id"], declared={"declared_tape_count": 20})
    assert order_19["estimate_total_cents"] == 22800, order_19
    assert order_20["estimate_total_cents"] == 21600, order_20


def test_volume_discount_boundary_above_twenty_still_discounted(api):
    """PRD §3.1: "A volume-discount percentage is then selected from the item
    count: when the item count is at least 40 the percentage is twenty percent;
    otherwise when the item count is at least 20 the percentage is ten percent;
    otherwise there is no volume discount."

    21 items remain in the 10% tier: raw 25200 - 2520 = 22680, confirming the
    tier applies for counts above the inclusive boundary as well.

    Design: Difficulty/boundary_precision_check/volume_discount_threshold_at_20_items
    """
    cust = create_customer(api, email="bp-2@x.com")
    order_21 = create_order(api, cust["id"], declared={"declared_tape_count": 21})
    assert order_21["estimate_total_cents"] == 22680, order_21


# ===========================================================================
# calculations / rush_fee_thirty_percent_of_subtotal (corner, queue B)
# ===========================================================================
def test_rush_surcharge_thirty_percent(api):
    """PRD §3.1: "First, a rush surcharge applies only when `turnaround` is
    `RUSH`: it is the discounted subtotal multiplied by thirty percent, rounded
    half up to whole cents; for `STANDARD` turnaround the surcharge is zero."

    10 tapes (subtotal 12000) with RUSH add 3600: estimate 15600.

    Design: Corner/calculations/rush_fee_thirty_percent_of_subtotal
    """
    cust = create_customer(api, email="rush@x.com")
    order = create_order(api, cust["id"], turnaround="RUSH",
                         declared={"declared_tape_count": 10})
    assert order["estimate_total_cents"] == 15600, order
