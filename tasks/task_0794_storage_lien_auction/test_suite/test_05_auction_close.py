"""Closing auctions: the empty-bid branch, sale-charge rounding, close timing."""
from test_helpers import (
    validate_success, validate_error, validate_paginated,
    ApiErrorId, CANONICAL,
    make_platform_admin_headers,
    set_clock, setup_live_auction, setup_sale,
    CLOCK_CLOSE,
)

ADMIN = make_platform_admin_headers()


# ---------------------------------------------------------------------------
# Difficulty: boundary_precision_check / close_with_empty_bid_set
# ---------------------------------------------------------------------------
def test_close_auction_with_no_bids_yields_zero_high_bid(api):
    """PRD §3.4: "The candidates are exactly the bids belonging to the auction whose
    `status` is `ACTIVE`. If there are no such candidates, `high_bid_cents` is zero
    and `high_bid_id` is null."
    PRD §3.5: "A `FacilityOperator` closes a live auction, moving it from `LIVE` to
    `CLOSED`."

    Design: Difficulty/boundary_precision_check/close_with_empty_bid_set
    """
    ctx = setup_live_auction(api)
    set_clock(api, CLOCK_CLOSE)
    auction = validate_success(api.close_auction(ctx["auc"], ctx["fac_hdr"]))
    assert auction["status"] == "CLOSED"
    assert auction["high_bid_cents"] == 0


def test_close_auction_with_no_bids_creates_no_sale_and_reverts_unit(api):
    """PRD §3.5: "In the no-sale branch — taken when there are zero `ACTIVE` bids, or
    the `high_bid_cents` is below the `reserve_cents` — every `ACTIVE` bid transitions
    to `LOST`, no sale is created, and the unit returns from `IN_AUCTION` to
    `LIEN_MATURED`, making it eligible for re-listing."

    Design: Difficulty/boundary_precision_check/close_with_empty_bid_set
    """
    ctx = setup_live_auction(api)
    set_clock(api, CLOCK_CLOSE)
    validate_success(api.close_auction(ctx["auc"], ctx["fac_hdr"]))
    _, meta = validate_paginated(api.list_sales(ADMIN, params={"auction_id": ctx["auc"]}))
    assert meta["total_count"] == 0
    unit = validate_success(api.get_unit(ctx["unit_id"], ADMIN))
    assert unit["status"] == "LIEN_MATURED"


# ---------------------------------------------------------------------------
# Difficulty: combinatorial_formula / sale_charges_rounding_order
# ---------------------------------------------------------------------------
def test_sale_premium_and_tax_use_pinned_rounding_order(api):
    """PRD §3.5: "First, the `buyer_premium_cents` is the `winning_amount_cents`
    multiplied by the buyer-premium rate of 1500 basis points, divided by ten
    thousand and rounded half up."
    PRD §3.5: "Second, the `sales_tax_cents` is computed on the premium-inclusive
    base: take the sum of `winning_amount_cents` and `buyer_premium_cents`, multiply
    by the facility's `sales_tax_rate_bps`, divide by ten thousand, and round half up."

    Design: Difficulty/combinatorial_formula/sale_charges_rounding_order
    """
    ctx = setup_sale(api)  # winning 150000, sales_tax_rate_bps 825
    sale = validate_success(api.get_sale(ctx["sale_id"], ADMIN))
    assert sale["winning_amount_cents"] == CANONICAL["winning_amount_cents"]
    assert sale["buyer_premium_cents"] == CANONICAL["buyer_premium_cents"]   # 22500
    assert sale["sales_tax_cents"] == CANONICAL["sales_tax_cents"]           # 14231


def test_sale_total_due_is_plain_sum_of_components(api):
    """PRD §3.5: "Third, the `total_due_cents` is the plain sum of
    `winning_amount_cents`, `buyer_premium_cents`, and `sales_tax_cents`, with no
    further rounding."

    Design: Difficulty/combinatorial_formula/sale_charges_rounding_order
    """
    ctx = setup_sale(api)
    sale = validate_success(api.get_sale(ctx["sale_id"], ADMIN))
    assert sale["total_due_cents"] == CANONICAL["total_due_cents"]           # 186731
    assert sale["total_due_cents"] == (
        sale["winning_amount_cents"] + sale["buyer_premium_cents"] + sale["sales_tax_cents"]
    )


# ---------------------------------------------------------------------------
# Corner: close timing
# ---------------------------------------------------------------------------
def test_close_before_end_reports_not_ended(api):
    """PRD §3.5: "Closing requires the auction to be `LIVE` and the logical clock now
    to be at or after `end_at`; closing before the window ends is rejected with
    `ERR_AUCTION_NOT_ENDED`."

    Design: Corner/validations/close_before_end_returns_not_ended
    """
    ctx = setup_live_auction(api)  # clock at 2026-03-21T01:00, end_at 2026-03-22
    resp = api.close_auction(ctx["auc"], ctx["fac_hdr"])
    validate_error(resp, ApiErrorId.ERR_AUCTION_NOT_ENDED.value)
