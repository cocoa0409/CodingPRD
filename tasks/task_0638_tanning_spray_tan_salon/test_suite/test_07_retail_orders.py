"""Retail order pricing (per-line-then-sum), credit application, and the
refund compensation cascade (inventory + credit + ledger).

Covers queue-B calculation/error corner instances plus the dual_variant_calc,
combinatorial_formula (retail rounding), transitive_cascade (refund), and
compensating_invariant (sale/refund inventory) difficulty instances.
"""
from test_helpers import (
    ApiErrorId,
    validate_success,
    validate_error,
    NON_EXISTENT_UUID,
    TEST_USERS,
    make_member_headers,
    create_retail_order_payload,
    assert_product_stock_invariant,
)
from test_helpers import fixtures as fx

FRONT_DESK = TEST_USERS["front_desk_headers"]


def test_retail_subtotal_per_line_then_sum_is_4945(api):
    """PRD §3.8: "A retail order is priced by discounting and rounding each line
    independently and then summing — the per-line-then-sum order is pinned, and
    sum-then-round is explicitly not used. ... each line's total is the product's
    `unit_price_cents` multiplied by the line's `quantity` multiplied by one minus
    the discount, rounded half up to whole cents. The order's `subtotal_cents` is
    the sum of those already-rounded line totals."

    Design: Difficulty/dual_variant_calc/retail_total_per_line_then_sum_vs_sum_then_round
    """
    plan = fx.create_plan(tier_code="UNLIMITED", monthly_fee_cents=6000,
                          retail_discount_pct=0.10, weekly_uv_session_cap=0)
    prod_a = fx.create_product(sku="A-1299", name="Bronzer", unit_price_cents=1299, initial_stock=10)
    prod_b = fx.create_product(sku="B-0799", name="Mist", unit_price_cents=799, initial_stock=10)
    member = fx.create_active_member(plan["id"], full_name="Buyer One")
    mid = member["id"]
    lines = [{"product_id": prod_a["id"], "quantity": 3}, {"product_id": prod_b["id"], "quantity": 2}]
    resp = api.create_retail_order(
        create_retail_order_payload(member_id=mid, lines=lines), make_member_headers(mid)
    )
    data = validate_success(resp, expected_status=201)
    # line A: round(1299*3*0.9)=round(3507.3)=3507; line B: round(799*2*0.9)=round(1438.2)=1438
    # subtotal = 3507 + 1438 = 4945 (sum-then-round would give 4946).
    assert data["subtotal_cents"] == 4945, f"expected 4945, got {data['subtotal_cents']}"
    assert data["credit_applied_cents"] == 0
    assert data["charged_cents"] == 4945


def test_retail_charged_equals_subtotal_when_no_credit(api):
    """PRD §3.8: "The `credit_applied_cents` is the smaller of the member's
    `account_credit_cents` and the `subtotal_cents`. The `charged_cents` is the
    `subtotal_cents` minus `credit_applied_cents`."

    Design: Difficulty/dual_variant_calc/retail_total_per_line_then_sum_vs_sum_then_round
    """
    plan = fx.create_plan(tier_code="UNLIMITED", monthly_fee_cents=6000,
                          retail_discount_pct=0.10, weekly_uv_session_cap=0)
    prod_a = fx.create_product(sku="A2-1299", name="Bronzer2", unit_price_cents=1299, initial_stock=10)
    prod_b = fx.create_product(sku="B2-0799", name="Mist2", unit_price_cents=799, initial_stock=10)
    member = fx.create_active_member(plan["id"], full_name="Buyer Two")
    mid = member["id"]
    lines = [{"product_id": prod_a["id"], "quantity": 3}, {"product_id": prod_b["id"], "quantity": 2}]
    resp = api.create_retail_order(
        create_retail_order_payload(member_id=mid, lines=lines), make_member_headers(mid)
    )
    data = validate_success(resp, expected_status=201)
    # With no account credit, charged equals the per-line-then-sum subtotal 4945.
    assert data["subtotal_cents"] == 4945
    assert data["charged_cents"] == 4945, f"expected charged 4945, got {data['charged_cents']}"


def test_retail_subtotal_per_line_rounding_premium_plan(api):
    """PRD §3.8: "Because each line is rounded before summing, the result can differ
    by up to a cent from a sum-then-round approach; the per-line order is
    authoritative."

    Design: Difficulty/combinatorial_formula/retail_rounding_order_per_line_then_sum
    """
    plan = fx.create_plan(tier_code="PREMIUM", monthly_fee_cents=8000,
                          retail_discount_pct=0.10, weekly_uv_session_cap=0)
    prod_a = fx.create_product(sku="RA-1299", name="Lotion", unit_price_cents=1299, initial_stock=5)
    prod_b = fx.create_product(sku="RB-0799", name="Spray", unit_price_cents=799, initial_stock=5)
    member = fx.create_active_member(plan["id"], full_name="Round Buyer")
    mid = member["id"]
    lines = [{"product_id": prod_a["id"], "quantity": 3}, {"product_id": prod_b["id"], "quantity": 2}]
    resp = api.create_retail_order(
        create_retail_order_payload(member_id=mid, lines=lines), make_member_headers(mid)
    )
    data = validate_success(resp, expected_status=201)
    assert data["subtotal_cents"] == 4945, f"expected 4945, got {data['subtotal_cents']}"


def test_retail_per_line_rounding_single_line(api):
    """PRD §3.8: "Processing the order's `lines` in the exact order they appear in
    the request array, each line's total is the product's `unit_price_cents`
    multiplied by the line's `quantity` multiplied by one minus the discount,
    rounded half up to whole cents. The order's `subtotal_cents` is the sum of those
    already-rounded line totals."

    Design: Difficulty/combinatorial_formula/retail_rounding_order_per_line_then_sum
    """
    plan = fx.create_plan(tier_code="PREMIUM", monthly_fee_cents=8000,
                          retail_discount_pct=0.10, weekly_uv_session_cap=0)
    # round_half_up(1299 * 3 * 0.9) = round_half_up(3507.3) = 3507.
    prod = fx.create_product(sku="RC-1299", name="Lotion2", unit_price_cents=1299, initial_stock=5)
    member = fx.create_active_member(plan["id"], full_name="Round Buyer 2")
    mid = member["id"]
    resp = api.create_retail_order(
        create_retail_order_payload(member_id=mid, lines=[{"product_id": prod["id"], "quantity": 3}]),
        make_member_headers(mid),
    )
    data = validate_success(resp, expected_status=201)
    assert data["subtotal_cents"] == 3507, f"expected 3507, got {data['subtotal_cents']}"


def test_retail_credit_partial_application(api):
    """PRD §3.8: "The `credit_applied_cents` is the smaller of the member's
    `account_credit_cents` and the `subtotal_cents`. The `charged_cents` is the
    `subtotal_cents` minus `credit_applied_cents`."

    Design: Corner/calculations/retail_credit_application_partial
    """
    # Member with 4000 account credit (frozen at elapsed 10, then unfrozen).
    plan, member, credit = fx.setup_member_with_freeze_credit(
        monthly_fee_cents=6000, anchor="2026-06-01T00:00:00Z", freeze_at="2026-06-11T00:00:00Z",
        retail_discount_pct=0.10, unfreeze_after=True,
    )
    assert credit == 4000
    prod_a = fx.create_product(sku="CA-1299", name="Bronzer", unit_price_cents=1299, initial_stock=10)
    prod_b = fx.create_product(sku="CB-0799", name="Mist", unit_price_cents=799, initial_stock=10)
    mid = member["id"]
    lines = [{"product_id": prod_a["id"], "quantity": 3}, {"product_id": prod_b["id"], "quantity": 2}]
    resp = api.create_retail_order(
        create_retail_order_payload(member_id=mid, lines=lines), make_member_headers(mid)
    )
    data = validate_success(resp, expected_status=201)
    assert data["subtotal_cents"] == 4945
    assert data["credit_applied_cents"] == 4000
    assert data["charged_cents"] == 945


def test_sale_then_refund_conserves_inventory(api):
    """PRD §3.9: "The salon maintains the invariant that `stock_on_hand` plus
    `units_sold` always equals `initial_stock`: every sale decrements
    `stock_on_hand` and increments `units_sold`, and every refund restores them in
    mirror."

    Design: Difficulty/compensating_invariant/sale_then_refund_conserves_inventory
    """
    plan = fx.create_plan(tier_code="UNLIMITED", monthly_fee_cents=6000,
                          retail_discount_pct=0, weekly_uv_session_cap=0)
    product = fx.create_product(sku="INV-1000", name="Serum", unit_price_cents=1000, initial_stock=10)
    member = fx.create_active_member(plan["id"], full_name="Inv Member")
    mid = member["id"]
    order = fx.place_retail_order(mid, [{"product_id": product["id"], "quantity": 3}])
    p_after_sale = validate_success(api.get_product(product["id"], FRONT_DESK))
    assert p_after_sale["stock_on_hand"] == 7
    assert p_after_sale["units_sold"] == 3
    assert_product_stock_invariant(p_after_sale)
    refund_resp = api.refund_retail_order(order["id"], FRONT_DESK)
    refunded = validate_success(refund_resp)
    assert refunded["status"] == "REFUNDED"
    p_after_refund = validate_success(api.get_product(product["id"], FRONT_DESK))
    assert p_after_refund["stock_on_hand"] == 10
    assert p_after_refund["units_sold"] == 0
    assert_product_stock_invariant(p_after_refund)


def test_refund_returns_credit_and_redefers_revenue(api):
    """PRD §3.9: "the member's `account_credit_cents` is increased by the order's
    `credit_applied_cents`, returning the credit that had been drawn; the salon
    ledger's `collected_retail_cents` is decreased by the order's `charged_cents`;
    and the salon ledger's `deferred_revenue_cents` is increased by the order's
    `credit_applied_cents`, re-deferring the returned credit."

    Design: Difficulty/transitive_cascade/refund_returns_credit_then_redefers_revenue
    """
    # Member frozen+unfrozen to mint 4000 credit on UNLIMITED(6000) at elapsed 10.
    plan, member, credit = fx.setup_member_with_freeze_credit(
        monthly_fee_cents=6000, anchor="2026-06-01T00:00:00Z", freeze_at="2026-06-11T00:00:00Z",
        retail_discount_pct=0, unfreeze_after=True,
    )
    assert credit == 4000
    product = fx.create_product(sku="RF-1000", name="Tonic", unit_price_cents=1000, initial_stock=10)
    mid = member["id"]
    # Order draws 1000 of credit (subtotal 1000, credit_applied 1000, charged 0).
    order = fx.place_retail_order(mid, [{"product_id": product["id"], "quantity": 1}])
    assert order["credit_applied_cents"] == 1000
    refund_resp = api.refund_retail_order(order["id"], FRONT_DESK)
    refunded = validate_success(refund_resp)
    assert refunded["status"] == "REFUNDED"
    assert refunded["credit_applied_cents"] == 1000
    member_after = validate_success(api.get_member(mid, FRONT_DESK))
    assert member_after["account_credit_cents"] == 4000, (
        f"credit must return to 4000 after refund, got {member_after['account_credit_cents']}"
    )
    ledger = fx.get_ledger()
    assert ledger["deferred_revenue_cents"] == 4000, (
        f"deferred_revenue_cents must re-defer to 4000, got {ledger['deferred_revenue_cents']}"
    )


def test_sale_then_refund_marks_order_refunded_and_invariant_holds(api):
    """PRD §3.9: "A refund is a full compensating reversal: for each line, the
    product's `stock_on_hand` is increased by the line `quantity` and its
    `units_sold` decreased by the same `quantity`, restoring the stock invariant."

    Design: Difficulty/compensating_invariant/sale_then_refund_conserves_inventory
    """
    plan = fx.create_plan(tier_code="UNLIMITED", monthly_fee_cents=6000,
                          retail_discount_pct=0, weekly_uv_session_cap=0)
    product = fx.create_product(sku="INV2-1000", name="Serum2", unit_price_cents=1000, initial_stock=10)
    member = fx.create_active_member(plan["id"], full_name="Inv Member 2")
    mid = member["id"]
    order = fx.place_retail_order(mid, [{"product_id": product["id"], "quantity": 3}])
    refunded = validate_success(api.refund_retail_order(order["id"], FRONT_DESK))
    assert refunded["status"] == "REFUNDED"
    p = validate_success(api.get_product(product["id"], FRONT_DESK))
    assert p["stock_on_hand"] == 10 and p["units_sold"] == 0
    assert_product_stock_invariant(p)


def test_refund_collected_retail_decreased_back(api):
    """PRD §3.9: "the salon ledger's `collected_retail_cents` is decreased by the
    order's `charged_cents`; and the salon ledger's `deferred_revenue_cents` is
    increased by the order's `credit_applied_cents`, re-deferring the returned
    credit."

    Design: Difficulty/transitive_cascade/refund_returns_credit_then_redefers_revenue
    """
    plan = fx.create_plan(tier_code="UNLIMITED", monthly_fee_cents=6000,
                          retail_discount_pct=0, weekly_uv_session_cap=0)
    product = fx.create_product(sku="RFC-1000", name="Tonic2", unit_price_cents=1000, initial_stock=10)
    member = fx.create_active_member(plan["id"], full_name="Refund Member 2")
    mid = member["id"]
    # No account credit: order charges 3000, collected_retail rises by 3000.
    order = fx.place_retail_order(mid, [{"product_id": product["id"], "quantity": 3}])
    assert order["charged_cents"] == 3000 and order["credit_applied_cents"] == 0
    ledger_before = fx.get_ledger()
    assert ledger_before["collected_retail_cents"] == 3000
    validate_success(api.refund_retail_order(order["id"], FRONT_DESK))
    ledger_after = fx.get_ledger()
    assert ledger_after["collected_retail_cents"] == 0, (
        f"collected_retail must reverse to 0, got {ledger_after['collected_retail_cents']}"
    )


def test_retail_order_product_not_found(api):
    """PRD §2.7: "A product reference inside a retail order line that does not
    resolve likewise yields `ERR_PRODUCT_NOT_FOUND`."

    Design: Corner/errors/product_not_found_on_order_line
    """
    plan = fx.create_plan(tier_code="BASIC", monthly_fee_cents=3000, weekly_uv_session_cap=0)
    member = fx.create_active_member(plan["id"], full_name="Order Member")
    mid = member["id"]
    resp = api.create_retail_order(
        create_retail_order_payload(
            member_id=mid, lines=[{"product_id": NON_EXISTENT_UUID, "quantity": 1}]
        ),
        make_member_headers(mid),
    )
    validate_error(resp, ApiErrorId.ERR_PRODUCT_NOT_FOUND.value, expected_status=404)
