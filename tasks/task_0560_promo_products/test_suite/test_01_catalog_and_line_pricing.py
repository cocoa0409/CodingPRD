"""Catalog seeding and order-line pricing (tiered + multi-color + setup)."""
from test_helpers import (
    validate_success, validate_error, validate_paginated,
    ApiErrorId, TEST_USERS,
    create_supplier_payload, create_line_payload,
    create_price_tier_payload,
    assert_supplier, assert_order_line,
    seed_catalog, setup_draft_line, setup_catalog_customer_order,
)

ADMIN = TEST_USERS["catalog_admin_headers"]


# ---- combinatorial line_subtotal (queue A) -------------------------------

def test_line_selects_highest_qualifying_tier_unit_price(api):
    """PRD 3.2: "First, among the product's price tiers whose `decoration_method`
    matches the line and whose `min_quantity` is less than or equal to the line's
    quantity, the system selects the tier with the largest `min_quantity`; that
    tier's `unit_price_cents` is the decorated first-color unit price."

    Design: Difficulty/combinatorial_formula/line_subtotal_tiered_multicolor
    """
    ctx = setup_draft_line(quantity=200, imprint_color_count=3)
    line = ctx["line"]
    assert line["unit_price_cents"] == 499, (
        f"quantity 200 must select the 144 tier (499), got {line['unit_price_cents']}")


def test_line_subtotal_combines_tier_run_and_setup(api):
    """PRD 3.2: "The one-time setup charge (`line_setup_cents`) is the method's
    first-color setup charge plus the extra-color count multiplied by the
    method's per-additional-color setup charge. The line subtotal is the goods
    amount plus the setup charge."
    PRD 3.2: "For `SCREEN_PRINT`, the first-color setup is 2500 cents, each
    additional color adds 1500 cents of setup, each extra color adds 40 cents per
    unit of run charge, and a line may use at most 6 colors."

    Design: Difficulty/combinatorial_formula/line_subtotal_tiered_multicolor
    """
    ctx = setup_draft_line(quantity=200, imprint_color_count=3)
    line = ctx["line"]
    assert line["line_setup_cents"] == 5500, f"2500 + 2*1500, got {line['line_setup_cents']}"
    assert line["line_subtotal_cents"] == 121300, (
        f"579*200 goods + 5500 setup, got {line['line_subtotal_cents']}")


# ---- corner: computed pricing fields -------------------------------------

def test_line_pricing_fields_computed_on_creation(api):
    """PRD 3.2: "On creation a line enters status `PENDING_ART`, its pricing fields
    are computed immediately, and the parent order's `art_complete` flag is
    recomputed (and thereby becomes false, since the new line has no approved art)."
    PRD 3.2: "For `EMBROIDERY`, the first-color setup is 4000 cents, additional
    colors add no setup and no run charge, and at most 12 colors are allowed."

    Design: Corner/entities/create_line_computes_pricing_fields
    """
    ctx = setup_catalog_customer_order(tiers=[
        ("SCREEN_PRINT", 48, 599), ("SCREEN_PRINT", 144, 499), ("EMBROIDERY", 24, 800),
    ])
    resp = api.create_line(
        ctx["order_id"],
        create_line_payload(ctx["product_id"], decoration_method="EMBROIDERY",
                            quantity=100, imprint_color_count=1),
        ctx["cust_headers"])
    line = validate_success(resp, 201)
    assert_order_line(line)
    assert line["line_setup_cents"] == 4000, f"EMBROIDERY first-color setup, got {line['line_setup_cents']}"
    assert line["status"] == "PENDING_ART"


# ---- corner: type / enum constraint --------------------------------------

def test_price_tier_invalid_decoration_method_rejected(api):
    """PRD 2.9: "A malformed request body — a missing required field, wrong type,
    or an invalid enum value — is rejected with `ERR_VALIDATION` (HTTP 400)."

    Design: Corner/entities/price_tier_invalid_decoration_method_returns_validation
    """
    ctx = seed_catalog(tiers=[])
    resp = api.create_price_tier(
        ctx["product_id"],
        create_price_tier_payload(decoration_method="GOLD_FOIL"),
        ADMIN)
    validate_error(resp, ApiErrorId.ERR_VALIDATION)


# ---- corner: no matching price tier --------------------------------------

def test_line_without_matching_tier_rejected(api):
    """PRD 3.2: "If no tier qualifies, the line is rejected with `ERR_TIER_NOT_FOUND`."

    Design: Corner/validations/no_matching_price_tier_returns_error
    """
    ctx = setup_catalog_customer_order(min_order_qty=1, tiers=[("EMBROIDERY", 24, 800)])
    resp = api.create_line(
        ctx["order_id"],
        create_line_payload(ctx["product_id"], decoration_method="SCREEN_PRINT",
                            quantity=50, imprint_color_count=1),
        ctx["cust_headers"])
    validate_error(resp, ApiErrorId.ERR_TIER_NOT_FOUND)


# ---- corner: max colors exceeded -----------------------------------------

def test_line_exceeding_method_color_ceiling_rejected(api):
    """PRD 3.2: "A line whose `imprint_color_count` exceeds its method's color
    ceiling is rejected with `ERR_MAX_COLORS_EXCEEDED`."

    Design: Corner/validations/max_colors_exceeded_returns_error
    """
    ctx = setup_catalog_customer_order(tiers=[("SCREEN_PRINT", 48, 599)])
    resp = api.create_line(
        ctx["order_id"],
        create_line_payload(ctx["product_id"], decoration_method="SCREEN_PRINT",
                            quantity=100, imprint_color_count=7),
        ctx["cust_headers"])
    validate_error(resp, ApiErrorId.ERR_MAX_COLORS_EXCEEDED)


# ---- boundary: min order quantity (queue A) ------------------------------

def test_line_below_min_quantity_rejected(api):
    """PRD 3.2: "A line whose quantity is below the product's `min_order_qty` is
    rejected with `ERR_BELOW_MIN_QUANTITY`."

    Design: Difficulty/boundary_precision_check/line_min_quantity_boundary_rejects_below
    """
    ctx = setup_catalog_customer_order(min_order_qty=48, tiers=[("SCREEN_PRINT", 48, 599)])
    resp = api.create_line(
        ctx["order_id"],
        create_line_payload(ctx["product_id"], decoration_method="SCREEN_PRINT",
                            quantity=47, imprint_color_count=1),
        ctx["cust_headers"])
    validate_error(resp, ApiErrorId.ERR_BELOW_MIN_QUANTITY)


def test_line_at_min_quantity_accepted(api):
    """PRD 3.2: "A line whose quantity is below the product's `min_order_qty` is
    rejected with `ERR_BELOW_MIN_QUANTITY`."
    PRD 3.2: "On creation a line enters status `PENDING_ART`, its pricing fields are
    computed immediately, and the parent order's `art_complete` flag is recomputed
    (and thereby becomes false, since the new line has no approved art)."

    Design: Difficulty/boundary_precision_check/line_min_quantity_boundary_rejects_below
    """
    ctx = setup_catalog_customer_order(min_order_qty=48, tiers=[("SCREEN_PRINT", 48, 599)])
    resp = api.create_line(
        ctx["order_id"],
        create_line_payload(ctx["product_id"], decoration_method="SCREEN_PRINT",
                            quantity=48, imprint_color_count=1),
        ctx["cust_headers"])
    line = validate_success(resp, 201)
    assert line["quantity"] == 48
    assert line["status"] == "PENDING_ART"


# ---- corner: supplier creation defaults ----------------------------------

def test_create_supplier_initializes_reserved_qty(api):
    """PRD 3.1: "A freshly created supplier begins with its `reserved_blank_qty` at zero."

    Design: Corner/entities/create_supplier_returns_all_fields
    """
    resp = api.create_supplier(
        create_supplier_payload(blank_unit_cost_cents=150, concurrent_capacity_units=500),
        ADMIN)
    sup = validate_success(resp, 201)
    assert_supplier(sup)
    assert sup["blank_unit_cost_cents"] == 150
    assert sup["concurrent_capacity_units"] == 500
    assert sup["reserved_blank_qty"] == 0


# ---- corner: missing required field --------------------------------------

def test_create_line_missing_quantity_rejected(api):
    """PRD 2.9: "A malformed request body — a missing required field, wrong type,
    or an invalid enum value — is rejected with `ERR_VALIDATION` (HTTP 400)."

    Design: Corner/entities/create_line_missing_quantity_returns_validation
    """
    ctx = setup_catalog_customer_order(min_order_qty=48, tiers=[("SCREEN_PRINT", 48, 599)])
    resp = api.create_line(
        ctx["order_id"],
        {"product_id": ctx["product_id"], "decoration_method": "SCREEN_PRINT"},
        ctx["cust_headers"])
    validate_error(resp, ApiErrorId.ERR_VALIDATION)


# ---- corner: list products filtered by supplier --------------------------

def test_list_products_filtered_by_supplier(api):
    """PRD 2.3: "Every list response includes limit, offset, `total_count`, and
    `has_more` in the meta object of the envelope."
    PRD 3.1: "A product is a catalog blank, created with a `supplier_id` naming the
    vendor that sources it, a sku code, a name such as "12oz Cotton Tote", and a
    `min_order_qty` below which no single line may order it."

    Design: Corner/entities/list_products_by_supplier_fk_filter
    """
    ctx = seed_catalog(tiers=[])
    resp = api.list_products(ADMIN, params={"supplier_id": ctx["supplier_id"]})
    data, meta = validate_paginated(resp)
    match = [p for p in data if p["id"] == ctx["product_id"]]
    assert match, "the supplier's product must appear in the filtered listing"
    assert match[0]["supplier_id"] == ctx["supplier_id"]
