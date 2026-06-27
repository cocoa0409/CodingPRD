"""Pricing engine: line totals, loyalty discount tiers, provisional vs final
totals, co-op rebate, special-order surcharge, service fees, rental day billing,
and loyalty accrual.

Covers Difficulty queue rules dual_variant_calc and combinatorial_formula, plus
the Corner queue calculations section.
"""
import pytest
from test_helpers import (
    validate_success, get_success_data,
    create_vendor, create_product, create_account,
    create_order_with_line, place_order, setup_placed_order,
    setup_quoted_special_order, setup_checked_out_rental, create_station,
    book_ticket, setup_submitted_po, set_clock,
    api_client, SALES, INVENTORY, ACCOUNTS, RENTAL,
    make_contractor_headers,
)


# ─── Difficulty: dual_variant_calc ──────────────────────────────────────────

def test_committed_exposure_diverges_from_settled_balance(api):
    """PRD 2.9: "The `committed_cents` is the account's **provisional**
    exposure: it equals `balance_cents` plus the sum of `total_cents` over every
    `SalesOrder` on the account whose `fulfillment_status` is `PLACED` and whose
    `payment_status` is `UNBILLED`."
    PRD 2.9: "The `balance_cents` is the account's **settled** outstanding
    balance: the sum of `amount_cents` over every `Invoice` on the account whose
    `status` is `ISSUED`."

    Design: Difficulty/dual_variant_calc/credit_available_committed_vs_settled_diverge
    """
    vendor = create_vendor()
    product = create_product(vendor_id=vendor["id"], sell_mode="EACH",
                             list_price_cents=5000, on_hand=1000)
    account = create_account(credit_limit_cents=100000, net_terms_days=30)

    order, _ = create_order_with_line(product["id"], qty=12,
                                      contractor_account_id=account["id"])
    placed = place_order(order["id"], order["version"])
    assert placed["total_cents"] == 58800, "subtotal 60000 - tier1 2% (1200)"

    acct = validate_success(
        api.get_contractor_account(account["id"], ACCOUNTS), 200)
    assert acct["balance_cents"] == 0, "no invoice issued yet -> settled balance 0"
    assert acct["committed_cents"] == 58800, "placed-unbilled order counts in committed"


def test_committed_exposure_equals_placed_order_total(api):
    """PRD 2.9: "Because committed exposure also counts the totals of
    placed-but-unbilled orders, the committed available credit can be strictly
    smaller than the settled available credit for the very same account data."

    Design: Difficulty/dual_variant_calc/credit_available_committed_vs_settled_diverge
    """
    vendor = create_vendor()
    product = create_product(vendor_id=vendor["id"], sell_mode="EACH",
                             list_price_cents=5000, on_hand=1000)
    account = create_account(credit_limit_cents=100000, net_terms_days=30)

    placed = setup_placed_order(product["id"], qty=12,
                                contractor_account_id=account["id"])

    acct = validate_success(
        api.get_contractor_account(account["id"], ACCOUNTS), 200)
    # committed (58800) strictly smaller available than settled (0) exposure.
    assert acct["committed_cents"] == placed["total_cents"] == 58800
    assert acct["committed_cents"] > acct["balance_cents"]


def test_provisional_vs_final_total_pricing_mode_flip(api):
    """PRD 3.4: "When fulfillment proceeds, the order's `pricing_mode` flips to
    `FINAL` and its total is recomputed from the final variant."
    PRD 3.4: "The final `subtotal_cents` sums `line_total_cents` over the
    order's lines whose `status` is `FULFILLED` (rather than `PENDING`)."

    Design: Difficulty/dual_variant_calc/order_total_provisional_vs_final_inclusion_set
    """
    vendor = create_vendor()
    product = create_product(vendor_id=vendor["id"], sell_mode="EACH",
                             list_price_cents=1000, on_hand=100)
    placed = setup_placed_order(product["id"], qty=10)
    assert placed["pricing_mode"] == "PROVISIONAL"

    fulfilled = validate_success(api.fulfill_order(
        placed["id"], {"expected_sales_order_version": placed["version"]}, SALES), 200)
    assert fulfilled["pricing_mode"] == "FINAL"
    assert fulfilled["total_cents"] == 10000


def test_final_total_sums_fulfilled_lines(api):
    """PRD 3.4: "The final `subtotal_cents` sums `line_total_cents` over the
    order's lines whose `status` is `FULFILLED` (rather than `PENDING`)."
    PRD 3.4: "Each `PENDING` line moves to `status` `FULFILLED`; that transition
    debits the line's product `on_hand` by the line's `qty`."

    Design: Difficulty/dual_variant_calc/order_total_provisional_vs_final_inclusion_set
    """
    vendor = create_vendor()
    product = create_product(vendor_id=vendor["id"], sell_mode="EACH",
                             list_price_cents=1000, on_hand=100)
    placed = setup_placed_order(product["id"], qty=10)
    fulfilled = validate_success(api.fulfill_order(
        placed["id"], {"expected_sales_order_version": placed["version"]}, SALES), 200)
    assert fulfilled["total_cents"] == 10000

    from test_helpers import validate_paginated
    data, _ = validate_paginated(api.list_order_lines_for_order(placed["id"], SALES))
    assert len(data) == 1
    assert data[0]["status"] == "FULFILLED"


# ─── Difficulty: combinatorial_formula ──────────────────────────────────────

def test_lumber_per_line_rounding_then_sum(api):
    """PRD 2.6: "when an order total is assembled from several lines, each
    line's charge is rounded to the cent **first**, at the line level, and only
    then are the rounded line charges summed into the order subtotal."
    PRD 3.2: "The raw charge is then rounded half-up to a whole number of cents
    to yield `line_total_cents`."

    Design: Difficulty/combinatorial_formula/lumber_line_per_line_rounding_then_sum
    """
    vendor = create_vendor()
    product = create_product(vendor_id=vendor["id"], sell_mode="BY_FOOT",
                             price_per_foot_cents=333, cut_fee_cents=0,
                             on_hand=1000)
    order = get_success_data(api.create_sales_order({}, SALES))
    l1 = validate_success(api.add_order_line(
        order["id"], {"product_id": product["id"], "qty": 7.5}, SALES), 201)
    l2 = validate_success(api.add_order_line(
        order["id"], {"product_id": product["id"], "qty": 7.5}, SALES), 201)
    # 333 * 7.5 = 2497.5 -> round_half_up -> 2498 per line.
    assert l1["line_total_cents"] == 2498
    assert l2["line_total_cents"] == 2498

    placed = place_order(order["id"], order["version"])
    # Per-line then sum: 2498 + 2498 = 4996 (NOT round(2497.5 + 2497.5) = 4995).
    assert placed["subtotal_cents"] == 4996
    assert placed["total_cents"] == 4996


def test_lumber_line_rounds_half_up_at_line_level(api):
    """PRD 3.2: "The raw charge is then rounded half-up to a whole number of
    cents to yield `line_total_cents`. This rounding happens at the line level,
    before the order ever sums its lines."

    Design: Difficulty/combinatorial_formula/lumber_line_per_line_rounding_then_sum
    """
    vendor = create_vendor()
    product = create_product(vendor_id=vendor["id"], sell_mode="BY_FOOT",
                             price_per_foot_cents=333, cut_fee_cents=0,
                             on_hand=1000)
    order = get_success_data(api.create_sales_order({}, SALES))
    line = validate_success(api.add_order_line(
        order["id"], {"product_id": product["id"], "qty": 7.5}, SALES), 201)
    assert line["line_total_cents"] == 2498, "2497.5 rounds half-up to 2498"


def test_loyalty_discount_keyed_on_pre_discount_subtotal(api):
    """PRD 3.3: "the discount rate is selected from the **pre-discount**
    subtotal, where a subtotal of at least 100000 cents earns a rate of 5
    percent (0.05), a subtotal of at least 50000 but below 100000 cents earns a
    rate of 2 percent (0.02), and any smaller subtotal earns 0."
    PRD 3.3: "The order's `total_cents` is the subtotal minus the loyalty
    discount, floored at 0 so it can never be negative."

    Design: Difficulty/combinatorial_formula/loyalty_discount_keyed_on_pre_discount_subtotal_tier
    """
    vendor = create_vendor()
    product = create_product(vendor_id=vendor["id"], sell_mode="EACH",
                             list_price_cents=5000, on_hand=100)
    account = create_account(credit_limit_cents=1000000, net_terms_days=30)
    placed = setup_placed_order(product["id"], qty=12,
                                contractor_account_id=account["id"])
    assert placed["subtotal_cents"] == 60000
    assert placed["loyalty_discount_cents"] == 1200, "tier1 2% of 60000"
    assert placed["total_cents"] == 58800


def test_loyalty_tier_does_not_retier_on_post_discount_total(api):
    """PRD 3.3: "The tier is fixed from the pre-discount subtotal first; the
    chosen rate is then multiplied by the subtotal and rounded half-up to whole
    cents to give the discount, which is never re-tiered against the
    post-discount figure."

    Design: Difficulty/combinatorial_formula/loyalty_discount_keyed_on_pre_discount_subtotal_tier
    """
    vendor = create_vendor()
    product = create_product(vendor_id=vendor["id"], sell_mode="EACH",
                             list_price_cents=5000, on_hand=100)
    account = create_account(credit_limit_cents=1000000, net_terms_days=30)
    placed = setup_placed_order(product["id"], qty=12,
                                contractor_account_id=account["id"])
    # 60000 -> tier1 (2%) -> 1200 discount; 58800 post-discount is still tier1
    # but the discount is computed from 60000, fixed at 1200 regardless.
    assert placed["loyalty_discount_cents"] == 1200
    assert placed["total_cents"] == placed["subtotal_cents"] - 1200


# ─── Corner: calculations ──────────────────────────────────────────────────

def test_rental_charge_cross_midnight_bills_two_days(api):
    """PRD 3.7: "billed days counts every distinct started UTC calendar day the
    asset was out: a same-day return bills 1 day, crossing one midnight bills 2
    days, and a zero-length window where the return instant equals start_at
    bills a minimum of 1 day."

    Design: Corner/calculations/rental_charge_cross_midnight_bills_two_days
    """
    checked_out, asset = setup_checked_out_rental(
        start_at="2026-05-01T08:00:00Z", due_at="2026-05-03T08:00:00Z",
        checkout_clock="2026-05-01T09:00:00Z", daily_rate_cents=5000)
    set_clock("2026-05-02T10:00:00Z")
    returned = validate_success(api.return_rental(checked_out["id"], RENTAL), 200)
    assert returned["status"] == "RETURNED"
    assert returned["rental_charge_cents"] == 10000, "2 calendar dates * 5000"


def test_service_fee_paint_mix_uses_base_fee_table(api):
    """PRD 3.8: "On a successful start the ticket's fee_cents is set from a
    fixed base-fee table keyed on service_type: a KEY_CUT is 300 cents, a
    PAINT_MIX is 800 cents, and a PROPANE_EXCHANGE is 2499 cents."

    Design: Corner/calculations/service_fee_paint_mix_correct
    """
    station = create_station(buffer_minutes=0)
    ticket = book_ticket(station["id"], "PAINT_MIX",
                         "2026-07-01T09:00:00Z", "2026-07-01T09:30:00Z")
    started = validate_success(api.start_ticket(ticket["id"], SALES), 200)
    assert started["status"] == "IN_PROGRESS"
    assert started["fee_cents"] == 800


def test_coop_rebate_applies_when_gross_qualifies(api):
    """PRD 3.10: "the coop_rebate_cents is the gross multiplied by the vendor's
    coop_rebate_pct and rounded half-up to whole cents, but only when
    gross_cents is at least 200000 cents — below that minimum the rebate is 0;
    and net_cost_cents is gross_cents minus coop_rebate_cents."

    Design: Corner/calculations/coop_rebate_qualifying_gross_applies_rebate
    """
    vendor = create_vendor(coop_rebate_pct=0.1)
    product = create_product(vendor_id=vendor["id"], sell_mode="EACH",
                             list_price_cents=3000)
    submitted = setup_submitted_po(vendor, product["id"], qty=100,
                                   unit_cost_cents=2500)
    assert submitted["gross_cents"] == 250000
    assert submitted["coop_rebate_cents"] == 25000, "0.10 * 250000"
    assert submitted["net_cost_cents"] == 225000


def test_coop_rebate_zero_below_threshold(api):
    """PRD 3.10: "only when gross_cents is at least 200000 cents — below that
    minimum the rebate is 0; and net_cost_cents is gross_cents minus
    coop_rebate_cents."

    Design: Corner/calculations/coop_rebate_below_threshold_no_rebate
    """
    vendor = create_vendor(coop_rebate_pct=0.1)
    product = create_product(vendor_id=vendor["id"], sell_mode="EACH",
                             list_price_cents=3000)
    submitted = setup_submitted_po(vendor, product["id"], qty=50,
                                   unit_cost_cents=2000)
    assert submitted["gross_cents"] == 100000
    assert submitted["coop_rebate_cents"] == 0, "100000 < 200000 minimum"
    assert submitted["net_cost_cents"] == 100000


def test_special_order_free_ship_no_surcharge(api):
    """PRD 3.9: "it is the goods value (quoted_unit_cents multiplied by qty)
    plus a drop-ship surcharge, where the surcharge is 0 when the goods value is
    at least 50000 cents (free shipping at or above that threshold) and 1500
    cents otherwise."

    Design: Corner/calculations/special_order_free_ship_no_surcharge
    """
    quoted, vendor, account = setup_quoted_special_order(
        qty=10, quoted_unit_cents=6000)  # goods 60000 >= 50000
    confirmed = validate_success(api.confirm_special_order(
        quoted["id"], make_contractor_headers(account["id"])), 200)
    assert confirmed["confirmed_total_cents"] == 60000, "no surcharge at/above 50000"


def test_loyalty_accrual_floors_points_on_fulfill(api):
    """PRD 3.4: "the system mints a `LoyaltyLedger` entry with `reason`
    `ORDER_ACCRUAL` whose `delta_points` is the order's `total_cents` divided by
    100 and floored to a whole number of points (one point per whole dollar,
    with fractional cents dropped), references the originating order via
    `sales_order_id`, and sets the order's `points_accrued` to that same value;
    the account's `loyalty_points` is recomputed afterward."

    Design: Corner/calculations/loyalty_accrual_floor_on_fulfill
    """
    from test_helpers import validate_paginated
    vendor = create_vendor()
    product = create_product(vendor_id=vendor["id"], sell_mode="EACH",
                             list_price_cents=5000, on_hand=100)
    account = create_account(credit_limit_cents=1000000, net_terms_days=30)
    placed = setup_placed_order(product["id"], qty=12,
                                contractor_account_id=account["id"])
    fulfilled = validate_success(api.fulfill_order(
        placed["id"], {"expected_sales_order_version": placed["version"]}, SALES), 200)
    assert fulfilled["points_accrued"] == 588, "floor(58800 / 100)"

    entries, _ = validate_paginated(
        api.list_account_loyalty_ledger(account["id"], ACCOUNTS))
    assert entries[0]["delta_points"] == 588
    assert entries[0]["reason"] == "ORDER_ACCRUAL"

    acct = validate_success(api.get_contractor_account(account["id"], ACCOUNTS), 200)
    assert acct["loyalty_points"] == 588
