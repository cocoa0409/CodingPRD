"""The two settlement-split variants and the purchase-award cascade."""

from test_helpers import (
    FINANCE_A,
    JURY_CHAIR_B_USER_ID,
    api_client,
    fixtures,
    validate_paginated,
)

TWO_SALEABLE_WORKS = [
    {
        "title": "Ridge Line", "medium_category": "PAINTING",
        "width_cm": 90.0, "height_cm": 60.0, "depth_cm": 4.0, "weight_kg": 6.0,
        "declared_value_cents": 400000, "for_sale": True,
        "list_price_cents": 250000,
    },
    {
        "title": "Salt Flat", "medium_category": "PHOTOGRAPHY",
        "width_cm": 100.0, "height_cm": 70.0, "depth_cm": 4.0, "weight_kg": 5.0,
        "declared_value_cents": 300000, "for_sale": True,
        "list_price_cents": 180000,
    },
]

HEADLINE_PRICE_CENTS = 250000

# Tax-inclusive gallery sale of 250,000 at 0.0875 tax and 0.35 commission.
GALLERY_BASE = 229885
GALLERY_TAX = 20115
GALLERY_COMMISSION = 80460
GALLERY_PAYABLE = 149425
GALLERY_BUYER_TOTAL = 250000

# The same 250,000 as a tax-additional purchase award at a flat 0.10 commission.
AWARD_BASE = 250000
AWARD_TAX = 21875
AWARD_COMMISSION = 25000
AWARD_PAYABLE = 225000
AWARD_BUYER_TOTAL = 271875


def _on_view_show_with_sponsor():
    ctx = fixtures.setup_on_view_show(
        works=TWO_SALEABLE_WORKS,
        artist_overrides={"member_status": "MEMBER"},
    )
    ctx["sponsor"] = fixtures.register_sponsor(
        ctx["exhibition"]["id"], name="Harbor Trust",
        contribution_cents=1000000, purchase_award_budget_cents=400000,
    )
    ctx["gallery_work_id"] = ctx["accepted_artwork_ids"][0]
    ctx["award_work_id"] = ctx["accepted_artwork_ids"][1]
    return ctx


def _confirmed_purchase_award(ctx):
    award = fixtures.propose_award(
        ctx["exhibition"]["id"], ctx["award_work_id"],
        category="PURCHASE_AWARD", prize_cents=HEADLINE_PRICE_CENTS,
        sponsor_id=ctx["sponsor"]["id"],
    )
    confirmed = fixtures.confirm_award(award["id"], ctx["exhibition"]["id"])
    sales, meta = validate_paginated(
        api_client.list_sales(
            FINANCE_A, params={"source_award_id": award["id"]}
        )
    )
    return confirmed, sales, meta


# ─── The tax-inclusive gallery variant ────────────────

def test_gallery_sale_price_is_understood_to_include_tax(api):
    """PRD §3.9: "When the sale is a `GALLERY_SALE` that is not tax-exempt, the
    posted price is understood to **include** tax: `taxable_base_cents` is
    `sale_price_cents` divided by one plus the exhibition's `sales_tax_pct`,
    rounded half up to whole cents, and `sales_tax_cents` is the residual,
    `sale_price_cents` minus `taxable_base_cents`, so no cent is created or lost
    in the split."

    Design: Difficulty/dual_variant_calc/sale_split_tax_inclusive_versus_purchase_award_tax_additional
    """
    ctx = _on_view_show_with_sponsor()

    sale = fixtures.record_sale(
        ctx["gallery_work_id"], sale_price_cents=HEADLINE_PRICE_CENTS,
        tax_exempt=False,
    )

    assert sale["sale_type"] == "GALLERY_SALE"
    assert sale["taxable_base_cents"] == GALLERY_BASE
    assert sale["sales_tax_cents"] == GALLERY_TAX
    assert sale["commission_cents"] == GALLERY_COMMISSION
    assert sale["artist_payable_cents"] == GALLERY_PAYABLE
    assert sale["buyer_total_cents"] == GALLERY_BUYER_TOTAL
    assert sale["taxable_base_cents"] + sale["sales_tax_cents"] == HEADLINE_PRICE_CENTS


def test_purchase_award_price_is_tax_additional_at_a_flat_commission(api):
    """PRD §3.9: "When the sale is a `PURCHASE_AWARD` that is not tax-exempt, the
    price is **tax-additional**: `taxable_base_cents` is the whole
    `sale_price_cents`, and `sales_tax_cents` is `sale_price_cents` multiplied by
    the exhibition's `sales_tax_pct`, rounded half up to whole cents."

    Design: Difficulty/dual_variant_calc/sale_split_tax_inclusive_versus_purchase_award_tax_additional
    """
    ctx = _on_view_show_with_sponsor()
    _, sales, meta = _confirmed_purchase_award(ctx)

    assert meta["total_count"] == 1
    sale = sales[0]
    assert sale["sale_type"] == "PURCHASE_AWARD"
    assert sale["sale_price_cents"] == HEADLINE_PRICE_CENTS
    assert sale["taxable_base_cents"] == AWARD_BASE
    assert sale["sales_tax_cents"] == AWARD_TAX
    assert sale["commission_cents"] == AWARD_COMMISSION
    assert sale["artist_payable_cents"] == AWARD_PAYABLE
    assert sale["buyer_total_cents"] == AWARD_BUYER_TOTAL


def test_artist_nets_more_from_a_purchase_award_at_the_same_price(api):
    """PRD §3.9: "The two variants diverge sharply on identical numbers: a
    `sale_price_cents` of 250,000 at a `sales_tax_pct` of 0.0875
    and a `commission_pct` of 0.35 gives, as a tax-inclusive gallery sale, a base
    of 229,885, tax of 20,115, commission of 80,460, an artist payable of 149,425
    and a buyer total of 250,000; the same 250,000 as a tax-additional purchase
    award gives a base of 250,000, tax of 21,875, commission of 25,000, an artist
    payable of 225,000 and a buyer total of 271,875 — the artist nets 75,575 cents
    more from the same headline price."

    Design: Difficulty/dual_variant_calc/sale_split_tax_inclusive_versus_purchase_award_tax_additional
    """
    ctx = _on_view_show_with_sponsor()

    gallery = fixtures.record_sale(
        ctx["gallery_work_id"], sale_price_cents=HEADLINE_PRICE_CENTS
    )
    _, sales, _ = _confirmed_purchase_award(ctx)
    award_sale = sales[0]

    assert gallery["sale_price_cents"] == award_sale["sale_price_cents"]
    delta = award_sale["artist_payable_cents"] - gallery["artist_payable_cents"]
    assert delta == 75575


# ─── The purchase-award cascade ───────────────────────

def test_confirming_a_purchase_award_creates_a_sale_and_sells_the_work(api):
    """PRD §3.8: "First, a **Sale** is created with `sale_type` `PURCHASE_AWARD`,
    its `source_award_id` pointing at this award, its `sale_price_cents` equal to
    the award's `prize_cents`, its `buyer_name` taken from the sponsor's `name`,
    and `status` `RECORDED`; its settlement split is computed by the same rules as
    any other sale, in the tax-additional variant described in §3.9. Second, the
    created sale drives the honoured work `ON_VIEW → SOLD` with `sold_price_cents`
    set to the award's `prize_cents`."

    Design: Difficulty/transitive_cascade/purchase_award_confirm_cascades_award_sale_artwork_ledger
    """
    ctx = _on_view_show_with_sponsor()
    confirmed, sales, meta = _confirmed_purchase_award(ctx)

    assert confirmed["status"] == "CONFIRMED"
    assert confirmed["confirmed_by_user_id"] == JURY_CHAIR_B_USER_ID

    assert meta["total_count"] == 1
    sale = sales[0]
    assert sale["status"] == "RECORDED"
    assert sale["source_award_id"] == confirmed["id"]
    assert sale["buyer_name"] == "Harbor Trust"
    assert sale["sale_price_cents"] == HEADLINE_PRICE_CENTS

    sold = fixtures.read_artwork(ctx["award_work_id"])
    assert sold["status"] == "SOLD"
    assert sold["sold_price_cents"] == HEADLINE_PRICE_CENTS

    untouched = fixtures.read_artwork(ctx["gallery_work_id"])
    assert untouched["status"] == "ON_VIEW"


def test_purchase_award_commits_the_sponsor_budget_not_the_council_budget(api):
    """PRD §3.8: "Two budget tests then apply, each to its own kind of award: for
    an award with no sponsor, the exhibition's `award_committed_cents` plus this
    award's `prize_cents` must be at most `award_budget_cents`, else
    `ERR_AWARD_BUDGET_EXCEEDED`; and for a `PURCHASE_AWARD`, the sponsor's
    `purchase_award_committed_cents` plus this award's `prize_cents` must be at
    most that sponsor's `purchase_award_budget_cents`, else
    `ERR_SPONSOR_BUDGET_EXCEEDED`."

    Design: Difficulty/transitive_cascade/purchase_award_confirm_cascades_award_sale_artwork_ledger
    """
    ctx = _on_view_show_with_sponsor()
    _confirmed_purchase_award(ctx)

    sponsor = fixtures.read_sponsor(ctx["sponsor"]["id"])
    assert sponsor["purchase_award_committed_cents"] == HEADLINE_PRICE_CENTS
    assert sponsor["recognition_tier"] == "SILVER"

    exhibition = fixtures.read_exhibition(ctx["exhibition"]["id"])
    assert exhibition["award_committed_cents"] == 0, (
        "award_committed_cents is the sum of prize_cents over CONFIRMED awards "
        "with no sponsor"
    )


def test_purchase_award_sale_recomputes_the_exhibition_money_aggregates(api):
    """PRD §3.8: "Third, the work becoming `SOLD` drives a recompute of the
    exhibition's `sales_gross_cents`, `commission_total_cents`,
    `sales_tax_total_cents` and `artist_payable_total_cents`."

    Design: Difficulty/transitive_cascade/purchase_award_confirm_cascades_award_sale_artwork_ledger
    """
    ctx = _on_view_show_with_sponsor()
    _confirmed_purchase_award(ctx)

    exhibition = fixtures.read_exhibition(ctx["exhibition"]["id"])
    assert exhibition["sales_gross_cents"] == HEADLINE_PRICE_CENTS
    assert exhibition["commission_total_cents"] == AWARD_COMMISSION
    assert exhibition["sales_tax_total_cents"] == AWARD_TAX
    assert exhibition["artist_payable_total_cents"] == AWARD_PAYABLE
    assert exhibition["payouts_released_cents"] == 0
