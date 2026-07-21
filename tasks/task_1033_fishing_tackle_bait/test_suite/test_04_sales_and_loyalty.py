"""Point-of-sale sales: line totals, tax rounding, completion guards, void,
loyalty-point accrual (provisional vs final), and refund conservation."""
from test_helpers import (
    validate_success, validate_error,
    ApiErrorId,
    TEST_USERS,
    fixtures,
)

MANAGER = TEST_USERS["manager_headers"]
CLERK = TEST_USERS["clerk_headers"]


def test_sale_tax_rounds_half_up_on_line_add(api):
    """PRD 3.6: "tax_cents` is the subtotal multiplied by 800 basis points — that is, divided by 10,000 — and rounded half up, and `total_cents` is the subtotal plus the tax."

    Design: Corner/calculations/calc_sale_tax_rounding_on_line_add
    """
    customer = fixtures.create_customer(name="Tax Cust", email="t@x.com")
    product = fixtures.create_product(sku="TX-1", name="Reel", category="REEL",
                                      unit_price_cents=1299, stock_qty=10)
    sale = fixtures.open_sale(customer["id"])
    data = validate_success(api.add_sale_line(sale["id"],
                                              {"product_id": product["id"], "qty": 1}, CLERK))
    assert data["subtotal_cents"] == 1299
    assert data["tax_cents"] == 104, "round(1299 * 0.08) = 104"
    assert data["total_cents"] == 1403


def test_sale_totals_visible_immediately_on_line_add(api):
    """PRD 3.6: "Adding a line recomputes the sale totals: `subtotal_cents` is the sum of `line_total_cents` over non-refunded lines, `tax_cents` is the subtotal multiplied by 800 basis points — that is, divided by 10,000 — and rounded half up, and `total_cents` is the subtotal plus the tax."

    Design: Corner/consistency_model/consistency_immediate_sale_totals_visible
    """
    customer = fixtures.create_customer(name="Imm Cust", email="im@x.com")
    product = fixtures.create_product(sku="IM-1", name="Bobber", category="TERMINAL_TACKLE",
                                      unit_price_cents=1000, stock_qty=10)
    sale = fixtures.open_sale(customer["id"])
    data = validate_success(api.add_sale_line(sale["id"],
                                              {"product_id": product["id"], "qty": 2}, CLERK))
    assert data["subtotal_cents"] == 2000, "visible immediately in the same response"
    assert data["total_cents"] == 2160, "2000 + round(2000 * 0.08) = 160"


def test_complete_sale_insufficient_stock_rejected(api):
    """PRD 3.6: "Completing a sale (`OPEN → COMPLETED`), performed by a clerk, requires at least one line, else `ERR_EMPTY_SALE` (HTTP 409), and requires that each line's product has `stock_qty` at least the line's `qty`, else `ERR_INSUFFICIENT_STOCK` (HTTP 409)."

    Design: Corner/validations/val_insufficient_stock_on_complete
    """
    customer = fixtures.create_customer(name="Stock Cust", email="st@x.com")
    product = fixtures.create_product(sku="LOW-1", name="Rare Lure", category="TERMINAL_TACKLE",
                                      unit_price_cents=500, stock_qty=1)
    sale = fixtures.open_sale(customer["id"])
    fixtures.add_line(sale["id"], product["id"], qty=5)
    resp = api.transition_sale(sale["id"], {"action": "COMPLETE"}, CLERK)
    validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_STOCK.value)


def test_complete_empty_sale_rejected(api):
    """PRD 3.6: "Completing a sale (`OPEN → COMPLETED`), performed by a clerk, requires at least one line, else `ERR_EMPTY_SALE` (HTTP 409)".

    Design: Corner/validations/val_empty_sale_complete
    """
    customer = fixtures.create_customer(name="Empty Cust", email="e@x.com")
    sale = fixtures.open_sale(customer["id"])
    resp = api.transition_sale(sale["id"], {"action": "COMPLETE"}, CLERK)
    validate_error(resp, ApiErrorId.ERR_EMPTY_SALE.value)


def test_void_completed_sale_rejected(api):
    """PRD 3.6: "Voiding a sale (`OPEN → VOIDED`), also a manager power, discards an open sale and writes no ledger entries because nothing was minted."

    Design: Corner/state_machines/sm_sale_void_from_completed_returns_invalid_state
    """
    fixtures.set_clock("2026-04-01T00:00:00Z")
    customer = fixtures.create_customer(name="Void Cust", email="v@x.com")
    product = fixtures.create_product(sku="VD-1", name="Lure", category="TERMINAL_TACKLE",
                                      unit_price_cents=1000, stock_qty=10)
    sale = fixtures.open_sale_with_lines(customer["id"], product["id"], [1])
    fixtures.complete_sale(sale["id"])
    resp = api.transition_sale(sale["id"], {"action": "VOID"}, MANAGER)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)


# --- Difficulty: dual_variant_calc / loyalty_provisional_vs_final_diverge ---

def _setup_two_line_sale_peak(api):
    """Peak-month clock, BRONZE customer, two 1250 lines. Returns (customer, sale)."""
    fixtures.set_clock("2026-07-15T00:00:00Z")
    customer = fixtures.create_customer(name="Angler B", email="b@x.com")
    product = fixtures.create_product(sku="JIG-1", name="Bass Jig", category="TERMINAL_TACKLE",
                                      unit_price_cents=1250, stock_qty=100)
    sale = fixtures.open_sale_with_lines(customer["id"], product["id"], [1, 1])
    return customer, sale


def test_sale_provisional_points_exclude_seasonal_bonus(api):
    """PRD 3.6: "Provisional points are computed by rounding each non-refunded line's `line_total_cents` divided by 100 to whole points, summing those per-line points into a base, then multiplying the base by the holder's tier multiplier and rounding half up."

    Design: Difficulty/dual_variant_calc/loyalty_provisional_vs_final_diverge
    """
    _customer, sale = _setup_two_line_sale_peak(api)
    completed = fixtures.complete_sale(sale["id"])
    assert completed["points_provisional"] == 26, "round(12.5)+round(12.5) = 13+13, BRONZE x1.0"


def test_sale_final_points_add_peak_seasonal_bonus(api):
    """PRD 3.6: "When the logical-clock month at settle is a peak month (May, June, July, or August), a seasonal bonus is added: that settled base multiplied by the tier multiplier multiplied by one tenth, rounded half up; otherwise the bonus is zero. The `points_final` is the tier-adjusted settled base plus the seasonal bonus."

    Design: Difficulty/dual_variant_calc/loyalty_provisional_vs_final_diverge
    """
    _customer, sale = _setup_two_line_sale_peak(api)
    completed = fixtures.complete_sale(sale["id"])
    settled = validate_success(api.transition_sale(sale["id"], {"action": "SETTLE"}, CLERK))
    assert settled["points_final"] == 29, "26 + round(26 * 1.0 * 0.10) = 26 + 3"
    assert settled["points_final"] != completed["points_provisional"], (
        "seasonal bonus makes final diverge from provisional"
    )


# --- Difficulty: combinatorial_formula / loyalty_rounding_order_pinned_mode_b ---

def _setup_two_line_sale_off(api):
    fixtures.set_clock("2026-04-01T00:00:00Z")
    customer = fixtures.create_customer(name="Angler D", email="d@x.com")
    product = fixtures.create_product(sku="JIG-2", name="Crappie Jig", category="TERMINAL_TACKLE",
                                      unit_price_cents=1250, stock_qty=100)
    sale = fixtures.open_sale_with_lines(customer["id"], product["id"], [1, 1])
    return customer, sale


def test_two_line_sale_totals(api):
    """PRD 3.6: "subtotal_cents` is the sum of `line_total_cents` over non-refunded lines, `tax_cents` is the subtotal multiplied by 800 basis points — that is, divided by 10,000 — and rounded half up, and `total_cents` is the subtotal plus the tax."

    Design: Difficulty/combinatorial_formula/loyalty_rounding_order_pinned_mode_b
    """
    _customer, sale = _setup_two_line_sale_off(api)
    completed = fixtures.complete_sale(sale["id"])
    assert completed["subtotal_cents"] == 2500
    assert completed["total_cents"] == 2700, "2500 + round(2500 * 0.08) = 200"


def test_loyalty_points_round_per_line_then_sum(api):
    """PRD 2.6: "Where a points calculation sums per-line contributions, each line's contribution is rounded to whole points before the contributions are summed, and any tier multiplier is applied to the summed base and rounded once more; per-line rounding always precedes summation."

    Design: Difficulty/combinatorial_formula/loyalty_rounding_order_pinned_mode_b
    """
    _customer, sale = _setup_two_line_sale_off(api)
    completed = fixtures.complete_sale(sale["id"])
    assert completed["points_provisional"] == 26, (
        "per-line 13 + 13 = 26, NOT sum-then-round(2500/100) = 25"
    )


# --- Difficulty: compensating_invariant / loyalty_points_conserved_on_sale_refund ---

def _setup_completed_sale_off(api):
    fixtures.set_clock("2026-04-01T00:00:00Z")
    customer = fixtures.create_customer(name="Angler M", email="m@x.com")
    product = fixtures.create_product(sku="ROD-1", name="Spin Rod", category="ROD",
                                      unit_price_cents=5000, stock_qty=10)
    sale = fixtures.open_sale_with_lines(customer["id"], product["id"], [1])
    completed = fixtures.complete_sale(sale["id"])
    return customer, sale, completed


def test_sale_complete_mints_provisional_points(api):
    """PRD 3.6: "A ledger entry with `delta_points` equal to `points_provisional`, a `reason` of `SALE_COMPLETE`, and a reference to the sale is appended, the holder's balance and tier are recomputed, and `total_cents` is added to the holder's `lifetime_spend_cents`."

    Design: Difficulty/compensating_invariant/loyalty_points_conserved_on_sale_refund
    """
    customer, _sale, completed = _setup_completed_sale_off(api)
    assert completed["points_provisional"] == 50, "round(5000/100) = 50, BRONZE x1.0"
    holder = fixtures.get_customer(customer["id"])
    assert holder["loyalty_points_balance"] == 50


def test_sale_refund_reverses_points_to_zero(api):
    """PRD 3.6: "appends a compensating ledger entry with `delta_points` equal to the negative of `points_provisional` and a `reason` of `SALE_REFUND` so the sale's net point contribution returns to zero, recomputes the balance and tier, and subtracts `total_cents` from the holder's `lifetime_spend_cents`."

    Design: Difficulty/compensating_invariant/loyalty_points_conserved_on_sale_refund
    """
    customer, sale, _completed = _setup_completed_sale_off(api)
    refunded = validate_success(api.transition_sale(sale["id"], {"action": "REFUND"}, MANAGER))
    assert refunded["status"] == "REFUNDED"
    holder = fixtures.get_customer(customer["id"])
    assert holder["loyalty_points_balance"] == 0, "net of +50 and -50 ledger deltas"
