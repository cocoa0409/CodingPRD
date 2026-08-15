"""Order composition and pinned pricing arithmetic (PRD §2.5, §3.3, §3.4)."""
from test_helpers import (
    TEST_USERS,
    canonical_community_scenario,
    confirm_order,
    create_customer,
    create_model,
    create_unit,
    get_success_data,
    is_iso8601_timestamp,
    new_order_scenario,
    validate_success,
)

CONSULTANT = TEST_USERS["consultant_headers"]


def test_order_create_ignores_forged_total(api, consultant_headers):
    """PRD §3.3: "Third, `total_price_cents` is the subtotal minus
    `discount_cents` plus `doc_fee_cents`; it excludes any transport charge."
    PRD §3.3: "The volume tier is selected by the subtotal: a subtotal of at
    least $100,000.00 (10,000,000 cents) earns a 3% tier rate; a subtotal of at
    least $50,000.00 (5,000,000 cents) but under $100,000.00 earns 1.5%;
    anything less earns no discount."

    Design: Corner/entities/sales_order_computed_total_input_ignored
    """
    model = create_model(double_wide=True)
    customer = create_customer()
    unit = create_unit(model["id"])
    payload = {
        "customer_id": customer["id"],
        "home_unit_id": unit["id"],
        "placement_type": "PRIVATE_LAND",
        "financing_type": "CHATTEL",
        "agreed_home_price_cents": 9_200_000,
        "total_price_cents": 1,
    }
    order = validate_success(api.create_sales_order(payload, consultant_headers), expected_status=201)
    assert order["total_price_cents"] == 9_137_000, (
        f"Server-computed total must be 9,137,000 (9,200,000 - 138,000 + 75,000), got {order['total_price_cents']}"
    )
    assert order["discount_cents"] == 138_000
    assert order["doc_fee_cents"] == 75_000


def test_discount_tier_boundary_at_5m(api, consultant_headers):
    """PRD §3.3: "The volume tier is selected by the subtotal: a subtotal of at
    least $100,000.00 (10,000,000 cents) earns a 3% tier rate; a subtotal of at
    least $50,000.00 (5,000,000 cents) but under $100,000.00 earns 1.5%;
    anything less earns no discount."

    Design: Corner/calculations/discount_tier_boundary_at_5m
    """
    scn_a = new_order_scenario(placement_type="PRIVATE_LAND", agreed_home_price_cents=5_000_000)
    scn_b = new_order_scenario(placement_type="PRIVATE_LAND", agreed_home_price_cents=4_999_999)

    order_a = scn_a["order"]
    assert order_a["discount_cents"] == 75_000, "exactly 5,000,000 earns the 1.5% tier (>= boundary)"
    assert order_a["doc_fee_cents"] == 49_250
    assert order_a["total_price_cents"] == 4_974_250

    order_b = scn_b["order"]
    assert order_b["discount_cents"] == 0, "4,999,999 is under the tier and earns no discount"
    assert order_b["doc_fee_cents"] == 50_000
    assert order_b["total_price_cents"] == 5_049_999


def test_doc_fee_floor_applies(api, consultant_headers):
    """PRD §3.3: "`doc_fee_cents` is one percent of the discounted subtotal —
    that is, subtotal minus `discount_cents`, not the final total — rounded
    half-up to whole cents, then clamped to no less than $250.00 (25,000 cents)
    and no more than $750.00 (75,000 cents)."

    Design: Corner/calculations/doc_fee_floor_applies
    """
    scn = new_order_scenario(placement_type="PRIVATE_LAND", agreed_home_price_cents=2_000_000)
    order = scn["order"]
    assert order["doc_fee_cents"] == 25_000, f"1% of 2,000,000 is 20,000, clamped up to the 25,000 floor; got {order['doc_fee_cents']}"
    assert order["total_price_cents"] == 2_025_000


def test_per_line_discount_rounding_sums_lines(api):
    """PRD §3.3: "The `discount_cents` is computed **per line** — each line total
    is multiplied by the tier rate and rounded half-up to whole cents, and those
    per-line amounts are summed. Computing the discount on the whole subtotal in
    one shot is a forbidden variant: it diverges by cents and must not be used."

    Design: Difficulty/combinatorial_formula/per_line_discount_rounding_order
    """
    order = canonical_community_scenario()["order"]
    assert order["options_total_cents"] == 340_099, f"250,100 + 89,999 = 340,099, got {order['options_total_cents']}"
    # Per line: 138,000 + round_half_up(250,100 x 1.5%) + round_half_up(89,999 x 1.5%)
    #         = 138,000 + 3,752 + 1,350 = 143,102 (whole-subtotal rounding would give 143,101).
    assert order["discount_cents"] == 143_102, (
        f"Per-line half-up discount must be 143,102 (not the 143,101 whole-subtotal variant), got {order['discount_cents']}"
    )


def test_per_line_discount_feeds_fee_and_total(api):
    """PRD §3.3: "`doc_fee_cents` is one percent of the discounted subtotal — that
    is, subtotal minus `discount_cents`, not the final total — rounded half-up to
    whole cents, then clamped to no less than $250.00 (25,000 cents) and no more
    than $750.00 (75,000 cents)."
    PRD §3.3: "Third, `total_price_cents` is the subtotal minus `discount_cents`
    plus `doc_fee_cents`; it excludes any transport charge."

    Design: Difficulty/combinatorial_formula/per_line_discount_rounding_order
    """
    order = canonical_community_scenario()["order"]
    # 1% of (9,540,099 - 143,102) = 93,970 -> clamped to the 75,000 cap.
    assert order["doc_fee_cents"] == 75_000, f"doc fee must clamp to the 75,000 cap, got {order['doc_fee_cents']}"
    assert order["total_price_cents"] == 9_471_997, (
        f"total = 9,540,099 - 143,102 + 75,000 = 9,471,997, got {order['total_price_cents']}"
    )


def test_doc_fee_base_is_discounted_subtotal_not_total(api, consultant_headers):
    """PRD §3.3: "`doc_fee_cents` is one percent of the discounted subtotal —
    that is, subtotal minus `discount_cents`, not the final total — rounded
    half-up to whole cents, then clamped to no less than $250.00 (25,000 cents)
    and no more than $750.00 (75,000 cents). This base is pinned deliberately:
    the fee is conventionally described as \"one percent of the amount financed,\"
    which would be circular, since the financed amount depends on the total and
    the total includes the fee."

    Design: Difficulty/combinatorial_formula/doc_fee_circular_pin
    """
    scn = new_order_scenario(placement_type="PRIVATE_LAND", agreed_home_price_cents=6_000_000)
    order = scn["order"]
    # Pinned: 1% of (6,000,000 - 90,000) = 59,100. The circular variant (1% of a
    # fee-inclusive base) would produce 59,691.
    assert order["doc_fee_cents"] == 59_100, (
        f"doc fee must be 1% of the discounted subtotal = 59,100 (not the circular 59,691), got {order['doc_fee_cents']}"
    )


def test_doc_fee_pin_flows_to_total_and_amount_financed(api, consultant_headers):
    """PRD §3.3: "Third, `total_price_cents` is the subtotal minus
    `discount_cents` plus `doc_fee_cents`; it excludes any transport charge.
    Finally, `amount_financed_cents` is the total minus `deposit_cents` minus
    `trade_in_credit_cents`, floored at zero, and is recomputed on every pricing
    or trade-in mutation."

    Design: Difficulty/combinatorial_formula/doc_fee_circular_pin
    """
    scn = new_order_scenario(placement_type="PRIVATE_LAND", agreed_home_price_cents=6_000_000)
    order = scn["order"]
    assert order["total_price_cents"] == 5_969_100, f"6,000,000 - 90,000 + 59,100 = 5,969,100, got {order['total_price_cents']}"
    assert order["amount_financed_cents"] == 5_969_100, "no deposit or trade credit yet"


def test_version_increments_on_every_mutation(api, consultant_headers):
    """PRD §2.5: "The `version` starts at 1 on creation and increments by exactly
    1 on every mutation of that resource; any mutation also refreshes
    `updated_at`."
    PRD §3.3: "Every option add and every void recomputes the order's pricing
    fields and increments the order's `version`."

    Design: Corner/cross_cutting_layers/version_increments_on_every_mutation
    """
    scn = new_order_scenario(placement_type="PRIVATE_LAND")
    order = scn["order"]
    assert order["version"] == 1, f"version starts at 1, got {order['version']}"

    api_resp = api.add_order_option(order["id"], {"option_code": "OPT-APP", "description": "Appliance package", "unit_price_cents": 125_050, "quantity": 2}, consultant_headers)
    validate_success(api_resp, expected_status=201)
    v1 = get_success_data(api.get_sales_order(order["id"], consultant_headers))
    assert v1["version"] == 2, f"first option add bumps version to 2, got {v1['version']}"

    validate_success(api.add_order_option(order["id"], {"option_code": "OPT-EXT", "description": "Exterior package", "unit_price_cents": 89_999, "quantity": 1}, consultant_headers), expected_status=201)
    confirmed = confirm_order(scn)
    assert confirmed["version"] == 4, f"second option -> 3, confirm -> 4; got {confirmed['version']}"
    assert is_iso8601_timestamp(confirmed["updated_at"]), "updated_at must remain a valid timestamp"


def test_confirm_response_immediately_consistent(api, consultant_headers):
    """PRD §3.4: "Confirmation records the deposit, moves `deal_status` from
    `DRAFT` to `PENDING_SITE_EVAL`, moves `payment_status` from `UNPAID` to
    `DEPOSIT_PAID`, and increments the order's `version`."
    PRD §2.2: "Unless otherwise noted, operations that create or modify a
    resource will return the created or updated resource object in the data
    field."

    Design: Corner/consistency_model/confirm_response_immediately_consistent
    """
    scn = new_order_scenario(placement_type="PRIVATE_LAND", agreed_home_price_cents=4_200_000)
    resp = api.confirm_sales_order(scn["order"]["id"], {"deposit_cents": 212_100}, consultant_headers)
    order = validate_success(resp)
    assert order["deal_status"] == "PENDING_SITE_EVAL"
    assert order["payment_status"] == "DEPOSIT_PAID"
    assert order["deposit_cents"] == 212_100
    assert order["amount_financed_cents"] == 4_029_900, f"4,242,000 - 212,100 = 4,029,900, got {order['amount_financed_cents']}"
