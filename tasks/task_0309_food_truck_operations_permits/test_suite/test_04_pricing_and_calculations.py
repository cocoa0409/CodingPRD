"""Settlement pricing (live vs settled, rounding, BULK10 per-line) and read aggregations.

Queue A: dual_variant_calc, combinatorial_formula instances.
Queue B: calculations-section corner instances.
"""
import pytest
from test_helpers import (
    validate_success, validate_error,
    setup_captured_order, settle, set_clock,
    create_commissary, create_truck, add_generator,
    make_operable_truck, add_menu_item, add_prep_batch,
    open_order, add_line, authorize, capture,
    api_client, TEST_USERS,
)

DISPATCHER = TEST_USERS["dispatcher_headers"]


# ─── dual_variant_calc ──────────────────────────────────────────────────────

def test_live_total_ignores_discount_estimate(api):
    """PRD §3.6: "the live total does not apply any discount — discount_code is ignored
    at this stage."
    PRD §3.7: "the two figures agree exactly when discount_code is NONE and can diverge
    whenever a discount is in force — the live live_total_cents is always the unreduced
    point-of-sale estimate, while settled_total_cents is the reconciled final figure."

    Two lines of a 101-cent item (qty 1 + qty 3) capture to live_total 404; settling with
    HAPPY_HOUR pins settled_total to 344, so the two diverge.

    Design: Difficulty/dual_variant_calc/order_live_vs_settled_diverge_on_happy_hour
    """
    ctx = setup_captured_order(
        "2026-06-01", clock_iso="2026-06-01T18:00:00.000Z",
        line_specs=[1, 3], item_price_cents=101, prepared_units=10)
    assert ctx["order"]["live_total_cents"] == 404, "live estimate is the unreduced subtotal"
    settled = settle(ctx["truck"]["id"], ctx["order"]["id"], discount_code="HAPPY_HOUR")
    assert settled["settled_total_cents"] == 344
    assert settled["live_total_cents"] == 404
    assert settled["settled_total_cents"] != settled["live_total_cents"]


def test_settled_diverges_from_live_under_happy_hour(api):
    """PRD §3.7: "Because the live total ignores discounts and the settled total applies
    them, the two figures agree exactly when discount_code is NONE and can diverge whenever
    a discount is in force."

    Asserts the settled-total domain figure (344) is strictly less than the live estimate (404).

    Design: Difficulty/dual_variant_calc/order_live_vs_settled_diverge_on_happy_hour
    """
    ctx = setup_captured_order(
        "2026-06-21", clock_iso="2026-06-21T18:00:00.000Z",
        line_specs=[1, 3], item_price_cents=101, prepared_units=10)
    settled = settle(ctx["truck"]["id"], ctx["order"]["id"], discount_code="HAPPY_HOUR")
    assert settled["settled_total_cents"] == 344
    assert settled["settled_total_cents"] < settled["live_total_cents"]


def test_reservation_fee_balance_and_gross_sales_are_distinct_domains(api):
    """PRD §2.8: "The balance for a truck is the sum of the snapshotted reservation_fee_cents
    over all of that truck's bookings whose status is RESERVED, ARRIVED, DEPARTED, or NO_SHOW,
    minus the sum of fee_refunded_cents over that truck's CANCELLED bookings."
    PRD §3.7: "the owning truck's gross_sales_cents is increased by the pinned settled_total_cents."

    A truck with one RESERVED-then-ARRIVED 2500-fee booking and one settled 900-cent order
    holds reservation_fee_balance_cents=2500 and gross_sales_cents=900 — neither contaminates
    the other.

    Design: Difficulty/dual_variant_calc/reservation_fee_balance_vs_gross_sales_distinct_domains
    """
    ctx = setup_captured_order(
        "2026-06-02", clock_iso="2026-06-02T18:00:00.000Z",
        line_specs=[2], item_price_cents=450, prepared_units=10,
        reservation_fee_cents=2500)
    settle(ctx["truck"]["id"], ctx["order"]["id"], discount_code="NONE")
    truck = validate_success(api.get_truck(ctx["truck"]["id"], DISPATCHER), 200)
    assert truck["reservation_fee_balance_cents"] == 2500
    assert truck["gross_sales_cents"] == 900


def test_gross_sales_excludes_reservation_fees(api):
    """PRD §3.7: "the owning truck's `gross_sales_cents` is increased by the pinned
    `settled_total_cents`."

    gross_sales_cents reflects only settled order revenue (900), never the 2500 reservation
    fee that lives on the separate reservation_fee_balance_cents field.

    Design: Difficulty/dual_variant_calc/reservation_fee_balance_vs_gross_sales_distinct_domains
    """
    ctx = setup_captured_order(
        "2026-06-22", clock_iso="2026-06-22T18:00:00.000Z",
        line_specs=[2], item_price_cents=450, prepared_units=10,
        reservation_fee_cents=2500)
    truck_before = validate_success(api.get_truck(ctx["truck"]["id"], DISPATCHER), 200)
    assert truck_before["gross_sales_cents"] == 0, "no settled order yet"
    settle(ctx["truck"]["id"], ctx["order"]["id"], discount_code="NONE")
    truck = validate_success(api.get_truck(ctx["truck"]["id"], DISPATCHER), 200)
    assert truck["gross_sales_cents"] == 900


# ─── combinatorial_formula ──────────────────────────────────────────────────

def test_settled_total_rounds_per_line_then_sums(api):
    """PRD §3.7: "the discounted line amount is the raw amount reduced by 15 percent (that
    is, the raw amount multiplied by 0.85), rounded half-up to a whole cent."
    PRD §2.9: "each discounted line amount is rounded half-up to a whole cent before the
    lines are summed."

    Two 101-cent lines (qty 1 -> round(101*0.85)=86, qty 3 -> round(303*0.85)=258) sum to
    344 under per-line-then-sum; summing raw then discounting once would give 343.

    Design: Difficulty/combinatorial_formula/settled_total_rounding_order_per_line_then_sum
    """
    ctx = setup_captured_order(
        "2026-06-03", clock_iso="2026-06-03T18:00:00.000Z",
        line_specs=[1, 3], item_price_cents=101, prepared_units=10)
    settled = settle(ctx["truck"]["id"], ctx["order"]["id"], discount_code="HAPPY_HOUR")
    assert settled["settled_total_cents"] == 344


def test_settled_total_rounding_not_equal_to_sum_then_round(api):
    """PRD §3.7: "summing the raw lines first and discounting once at the end would, for the
    same inputs, produce a different cent figure, and this benchmark pins the per-line-then-sum
    order."

    The pinned per-line-then-sum result is 344, distinct from the 343 that a sum-then-discount
    implementation would yield.

    Design: Difficulty/combinatorial_formula/settled_total_rounding_order_per_line_then_sum
    """
    ctx = setup_captured_order(
        "2026-06-23", clock_iso="2026-06-23T18:00:00.000Z",
        line_specs=[1, 3], item_price_cents=101, prepared_units=10)
    settled = settle(ctx["truck"]["id"], ctx["order"]["id"], discount_code="HAPPY_HOUR")
    assert settled["settled_total_cents"] == 344
    assert settled["settled_total_cents"] != 343


def test_bulk10_eligibility_is_per_line(api):
    """PRD §3.7: "if `discount_code` is `BULK10` and the line's `quantity` is at least 10, the
    discounted line amount is the raw amount reduced by 10 percent (multiplied by 0.90), rounded
    half-up to a whole cent."
    PRD §3.7: "Note that `BULK10` eligibility is judged per line on that line's own `quantity`,
    not on the order's total quantity."

    Two 199-cent lines (qty 12 eligible -> round(2388*0.9)=2149; qty 5 ineligible -> 995)
    settle to 3144.

    Design: Difficulty/combinatorial_formula/bulk10_per_line_eligibility_conditional_branch
    """
    ctx = setup_captured_order(
        "2026-06-20", clock_iso="2026-06-20T18:00:00.000Z",
        line_specs=[12, 5], item_price_cents=199, prepared_units=30)
    settled = settle(ctx["truck"]["id"], ctx["order"]["id"], discount_code="BULK10")
    assert settled["settled_total_cents"] == 3144


def test_bulk10_ineligible_line_keeps_raw_amount(api):
    """PRD §3.7: "otherwise — `NONE`, or `BULK10` on a line whose quantity is below 10 — the
    line keeps its raw amount with no reduction."

    The 5-unit line (below the per-line BULK10 threshold) contributes its full raw 995, so the
    settled total of 3144 reflects a discount applied only to the 12-unit line.

    Design: Difficulty/combinatorial_formula/bulk10_per_line_eligibility_conditional_branch
    """
    ctx = setup_captured_order(
        "2026-06-24", clock_iso="2026-06-24T18:00:00.000Z",
        line_specs=[12, 5], item_price_cents=199, prepared_units=30)
    settled = settle(ctx["truck"]["id"], ctx["order"]["id"], discount_code="BULK10")
    # 2149 (discounted 12-line) + 995 (undiscounted 5-line) = 3144
    assert settled["settled_total_cents"] == 3144


# ─── Corner: calculations section ───────────────────────────────────────────

def test_generator_runtime_accumulates_across_logs(api):
    """PRD §3.8: "A GENERATOR entry must carry generator_delta_hours, the runtime hours this
    log adds, and that value is added to the truck's cumulative generator_runtime_hours ...
    its generator_runtime_hours is the running sum of generator deltas."

    Two GENERATOR logs of 30 and 45 hours leave generator_runtime_hours at 75.

    Design: Corner/calculations/generator_runtime_accumulates_across_logs
    """
    commissary = create_commissary()
    truck = create_truck(commissary["id"])
    add_generator(truck["id"], 30)
    add_generator(truck["id"], 45)
    fresh = validate_success(api.get_truck(truck["id"], DISPATCHER), 200)
    assert fresh["generator_runtime_hours"] == 75


def test_generator_service_threshold_grounds_to_restricted(api):
    """PRD §3.8: "Generator soft gate S3 holds when the truck's generator_runtime_hours is
    strictly below 100 hours (the generator service interval); at 100 hours or more the gate
    fails and the generator is due for service."
    PRD §2.5: "If all hard gates hold but at least one soft gate fails, the truck is RESTRICTED."

    An otherwise-OPERABLE truck pushed to exactly 100 generator hours fails S3 and drops to
    RESTRICTED.

    Design: Corner/calculations/generator_service_threshold_grounds_to_restricted
    """
    ctx = make_operable_truck("2026-07-07", "2026-07-07T18:00:00.000Z")
    truck_id = ctx["truck"]["id"]
    assert ctx["truck"]["operability"] == "OPERABLE"
    add_generator(truck_id, 100)
    fresh = validate_success(api.get_truck(truck_id, DISPATCHER), 200)
    assert fresh["generator_runtime_hours"] == 100
    assert fresh["operability"] == "RESTRICTED"


def test_sales_report_aggregation_after_settle(api):
    """PRD §3.10: "`gross_sales_cents`, the sum of `settled_total_cents` over the event's settled
    orders; `order_count`, the count of those settled orders."

    After one settled order (line 250 x 2 = 500, NONE discount, no tip), the event sales report
    reports gross_sales_cents=500 and order_count=1.

    Design: Corner/calculations/sales_report_aggregation_after_settle
    """
    ctx = setup_captured_order(
        "2026-07-08", clock_iso="2026-07-08T18:00:00.000Z",
        line_specs=[2], item_price_cents=250, prepared_units=5)
    settle(ctx["truck"]["id"], ctx["order"]["id"], discount_code="NONE")
    report = validate_success(api.get_sales_report(ctx["event"]["id"], DISPATCHER), 200)
    assert report["gross_sales_cents"] == 500
    assert report["order_count"] == 1


def test_prepared_units_credit_on_prep_batch(api):
    """PRD §3.5: "For a given item, it equals the sum of units_made over that item's OPEN prep
    batches, minus the sum of quantity over all order lines for that item that belong to
    SETTLED orders."

    Logging a 7-unit prep batch against a fresh item (prepared_units 0) makes prepared_units 7.

    Design: Corner/calculations/prepared_units_credit_on_prep_batch
    """
    commissary = create_commissary()
    truck = create_truck(commissary["id"])
    item = add_menu_item(truck["id"], unit_price_cents=300, par_units=5)
    assert item["prepared_units"] == 0
    add_prep_batch(truck["id"], item["id"], units_made=7)
    fresh = validate_success(api.get_menu_item(item["id"], DISPATCHER), 200)
    assert fresh["prepared_units"] == 7
