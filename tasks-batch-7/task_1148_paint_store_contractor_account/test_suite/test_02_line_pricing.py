"""Line pricing and order totals: pinned rounding order, quantity-break
boundary, and tax rounding mode (PRD §3.6, §2.6)."""
from test_helpers import (
    TEST_USERS,
    create_product,
    get_first_order_line,
    place_order,
    setup_account_at_tier,
    setup_account_job_product,
    validate_success,
)

ADMIN = TEST_USERS["admin_headers"]
ASSOCIATE = TEST_USERS["associate_headers"]


def test_unit_price_rounded_before_extension(api):
    """PRD §3.6: "The line's `unit_price_cents` is the snapshotted list price
    reduced by the tier percentage and then by the quantity-break percentage,
    with the result **rounded half up to a whole cent at the per-unit step
    first**; `line_total_cents` is then that rounded unit price multiplied by
    `quantity`. The rounding order is pinned: rounding the per-unit price
    before extending by quantity is the only correct order, and extending the
    list price by quantity before applying discounts and rounding once at the
    line level is a different computation and is rejected."

    GOLD tier (10%) on a 999-cent unit rounds to 899 first; 899 * 7 = 6293,
    whereas the rejected extend-then-round order would give 6294.

    Design: Difficulty/combinatorial_formula/line_pricing_unit_round_first
    """
    account, job, _ = setup_account_at_tier(
        "Round Co", 15_000_000, jurisdiction_code="WA-OPEN", sku_prefix="P-TIER")
    assert account["tier"] == "GOLD", (
        f"setup: volume 15000000 meets the inclusive GOLD threshold, "
        f"got {account['tier']}")
    product = create_product(sku="P-ROUND", name="Quart", list_price_cents=999)
    order = place_order(account["id"], job["id"],
                        [{"product_id": product["id"], "quantity": 7}])
    line = get_first_order_line(order["id"])
    assert line["unit_price_cents"] == 899, (
        f"round_half_up(999 * 0.90) applied per unit first must be 899, "
        f"got {line['unit_price_cents']}")
    assert line["line_total_cents"] == 6293, (
        f"899 * 7 = 6293 (extend-then-round would give 6294), "
        f"got {line['line_total_cents']}")


def test_order_totals_follow_pinned_evaluation_order(api):
    """PRD §3.6: "Order totals derive from the lines in a pinned evaluation
    order — lines, then subtotal, then tax, then total. `subtotal_cents` is
    the sum of `line_total_cents` over all lines. ... `tax_cents` is 8.25
    percent of the discounted `subtotal_cents`, rounded half up, computed
    exactly once at order level and never per line. `total_cents` is
    `subtotal_cents` plus `tax_cents`."

    On the 6293-cent GOLD-tier order: tax round_half_up(6293 * 0.0825) = 519
    and total 6293 + 519 = 6812.

    Design: Difficulty/combinatorial_formula/line_pricing_unit_round_first
    """
    account, job, _ = setup_account_at_tier(
        "Round Co", 15_000_000, jurisdiction_code="WA-OPEN", sku_prefix="P-TIER")
    product = create_product(sku="P-ROUND", name="Quart", list_price_cents=999)
    order = place_order(account["id"], job["id"],
                        [{"product_id": product["id"], "quantity": 7}])
    assert order["subtotal_cents"] == 6293, (
        f"subtotal is the sum of line totals, got {order['subtotal_cents']}")
    assert order["tax_cents"] == 519, (
        f"round_half_up(6293 * 825 / 10000) = 519, got {order['tax_cents']}")
    assert order["total_cents"] == 6812, (
        f"total = subtotal + tax = 6812, got {order['total_cents']}")


def test_quantity_nine_gets_no_break(api):
    """PRD §3.6: "Independently, a quantity break of 3% applies to any line
    whose `quantity` is at least 10 units."

    A 9-unit line at 1000 list on a STANDARD account stays at full price:
    subtotal 9000.

    Design: Corner/calculations/quantity_break_starts_at_ten
    """
    account, _, job, product = setup_account_job_product(
        company_name="Qty Co", credit_limit_cents=1_000_000,
        jurisdiction_code="KS-OPEN", jurisdiction_name="Kansas",
        sku="P-QTY", list_price_cents=1000)
    order9 = place_order(account["id"], job["id"],
                         [{"product_id": product["id"], "quantity": 9}])
    assert order9["subtotal_cents"] == 9000, (
        f"quantity 9 is below the break, so subtotal must be 9000, "
        f"got {order9['subtotal_cents']}")


def test_quantity_ten_triggers_break(api):
    """PRD §3.6: "Independently, a quantity break of 3% applies to any line
    whose `quantity` is at least 10 units."

    A 10-unit line at 1000 list gets the inclusive break: unit
    round_half_up(1000 * 0.97) = 970 and subtotal 9700.

    Design: Corner/calculations/quantity_break_starts_at_ten
    """
    account, _, job, product = setup_account_job_product(
        company_name="Qty Co", credit_limit_cents=1_000_000,
        jurisdiction_code="KS-OPEN", jurisdiction_name="Kansas",
        sku="P-QTY", list_price_cents=1000)
    order10 = place_order(account["id"], job["id"],
                          [{"product_id": product["id"], "quantity": 10}])
    line = get_first_order_line(order10["id"])
    assert line["unit_price_cents"] == 970, (
        f"round_half_up(1000 * 0.97) = 970, got {line['unit_price_cents']}")
    assert order10["subtotal_cents"] == 9700, (
        f"quantity exactly 10 triggers the break: subtotal 9700, "
        f"got {order10['subtotal_cents']}")


def test_tax_rounds_half_up_at_half_cent(api):
    """PRD §2.6: "All monetary amounts are integer cents; no fractional cents
    are stored. Whenever a computation must produce cents from a non-integer
    intermediate, the result is **rounded half up** to the nearest whole cent,
    and each computation pins exactly where that rounding happens (per unit
    price, per return event, per cap, or once at the end) — the pinned
    rounding points appear with the workflows in Section 3. ... Sales tax is
    levied at 8.25 percent (825 basis points) of the discounted merchandise
    subtotal."

    An 825 bp levy on a 200-cent subtotal is exactly 16.5 cents; half-up
    rounding yields 17 (round-half-even would yield 16).

    Design: Corner/calculations/tax_rounds_half_up_at_half_cent
    """
    account, _, job, product = setup_account_job_product(
        company_name="Tax Co", credit_limit_cents=1_000_000,
        jurisdiction_code="MO-OPEN", jurisdiction_name="Missouri",
        sku="P-TAX", product_name="Sample", list_price_cents=200)
    order = place_order(account["id"], job["id"],
                        [{"product_id": product["id"], "quantity": 1}])
    assert order["subtotal_cents"] == 200
    assert order["tax_cents"] == 17, (
        f"round_half_up(200 * 825 / 10000) = round_half_up(16.5) = 17, "
        f"got {order['tax_cents']}")
    assert order["total_cents"] == 217, (
        f"total = 200 + 17 = 217, got {order['total_cents']}")
