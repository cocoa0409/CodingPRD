"""Line-item pricing, the MIN_BILLABLE_SQFT floor, and pinned per-line quote discounting."""
import pytest
from test_helpers import (
    validate_success, validate_error, ApiErrorId,
    TEST_USERS, create_line_item_payload,
)
from test_helpers import fixtures as fx


# ==========================================================================
# combinatorial_formula / line_item_pricing_nonlinear_rate_thickness_edge_area
# ==========================================================================
def test_line_item_pricing_tempered_polished_shower(api):
    """PRD §3.2: "Second, a per-square-foot rate term is assembled: a base rate by
    glass type — 800 cents for `ANNEALED`, 1400 for `TEMPERED`, 2000 for `LAMINATED`,
    and 2600 for `INSULATED` — is multiplied by a thickness multiplier of 1.0 for 6 mm,
    1.25 for 10 mm, or 1.5 for 12 mm, and then an edge rate is added: 0 cents for `NONE`,
    150 for `POLISHED`, or 300 for `BEVELED`."
    PRD §3.2: "The `unit_price_cents` is the `billable_sqft` multiplied by that assembled
    rate term, rounded half up to a whole cent, plus a flat product fee added *after* that
    rounding: 5000 cents for `SHOWER_ENCLOSURE`, 8000 for `STOREFRONT`, 2000 for
    `CUSTOM_MIRROR`, and 1500 for `TABLETOP`."

    Design: Difficulty/combinatorial_formula/line_item_pricing_nonlinear_rate_thickness_edge_area
    """
    account = fx.create_account(api, tier="SILVER")
    quote = fx.create_draft_quote(api, account["id"])
    resp = api.add_line_item(
        quote["id"],
        create_line_item_payload(product_type="SHOWER_ENCLOSURE", glass_type="TEMPERED",
                                 thickness_mm=10, width_in=30, height_in=72, quantity=1,
                                 edge_work="POLISHED"),
        TEST_USERS["estimator_headers"])
    data = validate_success(resp, 201)
    # billable 15.0; rate = 1400*1.25 + 150 = 1900; unit = round(15*1900)+5000 = 33500
    assert data["billable_sqft"] == pytest.approx(15.0), data["billable_sqft"]
    assert data["unit_price_cents"] == 33500, data["unit_price_cents"]
    assert data["line_total_cents"] == 33500, data["line_total_cents"]


def test_line_item_pricing_laminated_10mm_polished(api):
    """PRD §3.2: "The `unit_price_cents` is the `billable_sqft` multiplied by that assembled
    rate term, rounded half up to a whole cent, plus a flat product fee added *after* that
    rounding: 5000 cents for `SHOWER_ENCLOSURE`, 8000 for `STOREFRONT`, 2000 for
    `CUSTOM_MIRROR`, and 1500 for `TABLETOP`."
    PRD §3.2: "Finally, the `line_total_cents` is the `unit_price_cents` multiplied by the
    `quantity`."

    Design: Difficulty/combinatorial_formula/line_item_pricing_nonlinear_rate_thickness_edge_area
    """
    account = fx.create_account(api, tier="SILVER")
    quote = fx.create_draft_quote(api, account["id"])
    resp = api.add_line_item(
        quote["id"],
        create_line_item_payload(product_type="SHOWER_ENCLOSURE", glass_type="LAMINATED",
                                 thickness_mm=10, width_in=40, height_in=36, quantity=1,
                                 edge_work="POLISHED"),
        TEST_USERS["estimator_headers"])
    data = validate_success(resp, 201)
    # billable 10.0; rate = 2000*1.25 + 150 = 2650; unit = round(10*2650)+5000 = 31500
    assert data["billable_sqft"] == pytest.approx(10.0), data["billable_sqft"]
    assert data["unit_price_cents"] == 31500, data["unit_price_cents"]
    assert data["line_total_cents"] == 31500, data["line_total_cents"]


# ==========================================================================
# boundary_precision_check / min_billable_sqft_floor_on_line_item
# ==========================================================================
def test_min_billable_floor_below_and_above(api):
    """PRD §3.2: "The `billable_sqft` is then the greater of that area and a per-pane floor
    of 4.0 square feet."
    PRD §3.2: "First, the pane's geometric area in square feet is the `width_in` multiplied
    by the `height_in`, divided by 144, rounded half up to two decimal places."

    Design: Difficulty/boundary_precision_check/min_billable_sqft_floor_on_line_item
    """
    account = fx.create_account(api, tier="WALK_IN")
    quote = fx.create_draft_quote(api, account["id"])
    # 20x20 raw area 2.78 -> floored to 4.0
    small = validate_success(api.add_line_item(
        quote["id"],
        create_line_item_payload(product_type="CUSTOM_MIRROR", glass_type="ANNEALED",
                                 thickness_mm=6, width_in=20, height_in=20, quantity=1),
        TEST_USERS["estimator_headers"]), 201)
    assert small["billable_sqft"] == pytest.approx(4.0), small["billable_sqft"]
    assert small["unit_price_cents"] == 5200, small["unit_price_cents"]
    # 30x24 raw area 5.0 -> above the floor
    big = validate_success(api.add_line_item(
        quote["id"],
        create_line_item_payload(product_type="CUSTOM_MIRROR", glass_type="ANNEALED",
                                 thickness_mm=6, width_in=30, height_in=24, quantity=1),
        TEST_USERS["estimator_headers"]), 201)
    assert big["billable_sqft"] == pytest.approx(5.0), big["billable_sqft"]
    assert big["unit_price_cents"] == 6000, big["unit_price_cents"]


def test_min_billable_floor_at_and_just_above_boundary(api):
    """PRD §3.2: "The `billable_sqft` is then the greater of that area and a per-pane floor
    of 4.0 square feet."

    Design: Difficulty/boundary_precision_check/min_billable_sqft_floor_on_line_item
    """
    account = fx.create_account(api, tier="WALK_IN")
    quote = fx.create_draft_quote(api, account["id"])
    # 24x24 raw area exactly 4.0 -> greater(4.0, 4.0) == 4.0
    at = validate_success(api.add_line_item(
        quote["id"],
        create_line_item_payload(product_type="CUSTOM_MIRROR", glass_type="ANNEALED",
                                 thickness_mm=6, width_in=24, height_in=24, quantity=1),
        TEST_USERS["estimator_headers"]), 201)
    assert at["billable_sqft"] == pytest.approx(4.0), at["billable_sqft"]
    assert at["unit_price_cents"] == 5200, at["unit_price_cents"]
    # 27x24 raw area 4.5 -> just above the floor, billed at 4.5
    above = validate_success(api.add_line_item(
        quote["id"],
        create_line_item_payload(product_type="CUSTOM_MIRROR", glass_type="ANNEALED",
                                 thickness_mm=6, width_in=27, height_in=24, quantity=1),
        TEST_USERS["estimator_headers"]), 201)
    assert above["billable_sqft"] == pytest.approx(4.5), above["billable_sqft"]
    assert above["unit_price_cents"] == 5600, above["unit_price_cents"]


# ==========================================================================
# combinatorial_formula / quote_total_perline_discount_rounding_order
# ==========================================================================
def test_quote_total_perline_gold_discount_rounding(api):
    """PRD §3.3: "The `total_cents` is computed by taking each line's `line_total_cents`,
    multiplying it by one minus the tier percentage, rounding that discounted line half up
    to a whole cent, and only then summing across the lines — the discount is applied and
    rounded per line *before* the sum, not after."
    PRD §3.3: "The `subtotal_cents` is the plain sum of every line's `line_total_cents`."
    PRD §3.3: "The `discount_cents` is the `subtotal_cents` minus the `total_cents`."

    Design: Difficulty/combinatorial_formula/quote_total_perline_discount_rounding_order
    """
    account = fx.create_account(api, tier="GOLD")
    quote = fx.create_draft_quote(api, account["id"])
    fx.add_line(api, quote["id"], **fx.LINE_GOLD_ANNEALED)
    fx.add_line(api, quote["id"], **fx.LINE_GOLD_ANNEALED)
    data = validate_success(api.send_quote(quote["id"], TEST_USERS["estimator_headers"]), 200)
    # two 9750 lines; GOLD 0.15: each 9750*0.85=8287.5 -> 8288; total 16576 (sum-then-round = 16575)
    assert data["subtotal_cents"] == 19500, data["subtotal_cents"]
    assert data["total_cents"] == 16576, data["total_cents"]
    assert data["discount_cents"] == 2924, data["discount_cents"]


def test_quote_total_perline_bronze_discount_rounding(api):
    """PRD §3.3: "The `total_cents` is computed by taking each line's `line_total_cents`,
    multiplying it by one minus the tier percentage, rounding that discounted line half up
    to a whole cent, and only then summing across the lines — the discount is applied and
    rounded per line *before* the sum, not after."
    PRD §3.3: "The tier discount percentage is taken from the account's `tier`: `WALK_IN`
    gets 0.0, `BRONZE` 0.05, `SILVER` 0.10, and `GOLD` 0.15."

    Design: Difficulty/combinatorial_formula/quote_total_perline_discount_rounding_order
    """
    account = fx.create_account(api, tier="BRONZE")
    quote = fx.create_draft_quote(api, account["id"])
    fx.add_line(api, quote["id"], **fx.LINE_GOLD_ANNEALED)
    fx.add_line(api, quote["id"], **fx.LINE_GOLD_ANNEALED)
    data = validate_success(api.send_quote(quote["id"], TEST_USERS["estimator_headers"]), 200)
    # BRONZE 0.05: each 9750*0.95=9262.5 -> 9263; total 18526 (sum-then-round = 18525)
    assert data["subtotal_cents"] == 19500, data["subtotal_cents"]
    assert data["total_cents"] == 18526, data["total_cents"]
    assert data["discount_cents"] == 974, data["discount_cents"]


# ==========================================================================
# entities / create_line_item_missing_required_field_returns_400
# ==========================================================================
def test_create_line_item_missing_glass_type_rejected(api):
    """PRD §2.8: "on any creation, required fields are present, enum values are legal,
    `thickness_mm` is one of 6, 10, or 12, `width_in` and `height_in` are greater than 0,
    `quantity` is at least 1, and any window's end is strictly after its start; otherwise
    `ERR_VALIDATION` (400)."

    Design: Corner/entities/create_line_item_missing_required_field_returns_400
    """
    account = fx.create_account(api, tier="SILVER")
    quote = fx.create_draft_quote(api, account["id"])
    resp = api.add_line_item(
        quote["id"],
        {"product_type": "TABLETOP", "thickness_mm": 12, "width_in": 40, "height_in": 20, "quantity": 1},
        TEST_USERS["estimator_headers"])
    validate_error(resp, ApiErrorId.ERR_VALIDATION)


# ==========================================================================
# entities / create_line_item_invalid_thickness_returns_400
# ==========================================================================
def test_create_line_item_invalid_thickness_rejected(api):
    """PRD §2.8: "on any creation, required fields are present, enum values are legal,
    `thickness_mm` is one of 6, 10, or 12, `width_in` and `height_in` are greater than 0,
    `quantity` is at least 1, and any window's end is strictly after its start; otherwise
    `ERR_VALIDATION` (400)."

    Design: Corner/entities/create_line_item_invalid_thickness_returns_400
    """
    account = fx.create_account(api, tier="SILVER")
    quote = fx.create_draft_quote(api, account["id"])
    resp = api.add_line_item(
        quote["id"],
        create_line_item_payload(product_type="TABLETOP", glass_type="ANNEALED",
                                 thickness_mm=8, width_in=40, height_in=20, quantity=1),
        TEST_USERS["estimator_headers"])
    validate_error(resp, ApiErrorId.ERR_VALIDATION)
