"""Order pricing: rounding order, trade-in cap, delivery fee, amendment OCC (PRD §2.7, §3.4, §3.5, §3.6)."""
import pytest
from test_helpers import (
    validate_success, validate_error,
    create_customer, create_instrument, create_available_instrument,
    create_accepted_appraisal, create_order, order_line, create_order_payload,
    post_payment, get_order,
    assert_sales_order,
    TEST_USERS,
)

ASSOCIATE = TEST_USERS["sales_associate_headers"]


def _round_family_setup(api):
    """Customer with ACCEPTED 630000 appraisal + two AVAILABLE 333333 instruments."""
    customer = create_customer(full_name="Rita Round", email="rita@x.com")
    appraisal = create_accepted_appraisal(
        customer["id"], 0, 0.0, category="UPRIGHT", manufacturer="Kawai",
        model="K300", year_built=2016, condition_grade="EXCELLENT")
    i1 = create_available_instrument(
        serial_number="SN-R-1", category="GRAND", manufacturer="Steinway", model="M",
        year_built=2023, condition_grade="EXCELLENT", acquisition_type="NEW",
        list_price_cents=333_333, floor_price_cents=1)
    i2 = create_available_instrument(
        serial_number="SN-R-2", category="GRAND", manufacturer="Steinway", model="M",
        year_built=2023, condition_grade="EXCELLENT", acquisition_type="NEW",
        list_price_cents=333_333, floor_price_cents=1)
    order = validate_success(api.create_sales_order(
        create_order_payload(
            customer["id"],
            [order_line(i1["id"], 333_333, 0.10), order_line(i2["id"], 333_333, 0.10)],
            trade_in_appraisal_id=appraisal["id"], tax_rate=0.08, distance_miles=30,
            stairs_count=2, climate_controlled_required=True),
        ASSOCIATE), 201)
    return order


def test_order_per_line_rounding_then_sum(api):
    """PRD §3.4: "Each line total is computed first as the line's `unit_price_cents`
    multiplied by one minus its `discount_pct`, rounded half-up to whole cents per line; the
    order's `subtotal_cents` is the sum of those rounded line totals."
    PRD §3.4: "The trade-in credit `trade_in_credit_cents` is zero when no appraisal is
    attached, and otherwise the lesser of the appraisal's `final_value_cents` and forty
    percent of the subtotal rounded half-up — the cap is inclusive, so a credit exactly
    equal to the cap is allowed."
    (333333 * 0.90 = 299999.7 -> 300000 per line; subtotal 600000; cap 240000 clamps the
    630000 appraisal.)

    Design: Difficulty/combinatorial_formula/order_total_per_line_rounding_then_sum
    """
    order = _round_family_setup(api)
    assert_sales_order(order)
    assert order["subtotal_cents"] == 600_000, (
        f"per-line round then sum must give 600000 (sum-then-round 599999 is wrong), "
        f"got {order['subtotal_cents']}")
    assert order["trade_in_credit_cents"] == 240_000, (
        f"min(630000, round(0.40 * 600000)) == 240000, got {order['trade_in_credit_cents']}")


def test_order_total_fee_and_tax_after_credit(api):
    """PRD §3.4: "`tax_cents` is zero when the `tax_rate` is zero (the natural case for a
    `tax_exempt` institution), and otherwise the taxable base multiplied by the `tax_rate`,
    rounded half-up."
    PRD §3.4: "The order's `total_cents` is the subtotal minus the trade-in credit plus the
    delivery fee plus the tax; `amount_paid_cents` starts at zero; and `balance_cents` is
    always the total minus the amount paid."
    (fee 15000 + 2*2500 stairs + 12000 distance(30mi) + 20000 climate = 52000; tax
    round(360000 * 0.08) = 28800; total 600000 - 240000 + 52000 + 28800 = 440800.)

    Design: Difficulty/combinatorial_formula/order_total_per_line_rounding_then_sum
    """
    order = _round_family_setup(api)
    assert order["delivery_fee_cents"] == 52_000, f"got {order['delivery_fee_cents']}"
    assert order["tax_cents"] == 28_800, f"got {order['tax_cents']}"
    assert order["total_cents"] == 440_800, f"got {order['total_cents']}"


def _cap_boundary_setup(api):
    """Customer with ACCEPTED 200000 appraisal + one AVAILABLE 500000 instrument."""
    customer = create_customer(full_name="Boris Bounds", email="boris@x.com")
    appraisal = create_accepted_appraisal(
        customer["id"], 20_000, 0.0, category="DIGITAL", manufacturer="Roland",
        model="RD2000", year_built=2022, condition_grade="EXCELLENT")
    instrument = create_available_instrument(
        serial_number="SN-T-1", category="UPRIGHT", manufacturer="Kawai", model="K200",
        year_built=2024, condition_grade="EXCELLENT", acquisition_type="NEW",
        list_price_cents=500_000, floor_price_cents=1)
    order = validate_success(api.create_sales_order(
        create_order_payload(customer["id"], [order_line(instrument["id"], 500_000)],
                             trade_in_appraisal_id=appraisal["id"], tax_rate=0.08,
                             distance_miles=10, stairs_count=0,
                             climate_controlled_required=False),
        ASSOCIATE), 201)
    return order


def test_trade_in_cap_inclusive_at_exactly_forty_pct(api):
    """PRD §3.4: "The trade-in credit `trade_in_credit_cents` is zero when no appraisal is
    attached, and otherwise the lesser of the appraisal's `final_value_cents` and forty
    percent of the subtotal rounded half-up — the cap is inclusive, so a credit exactly
    equal to the cap is allowed."
    (Appraisal final 200000; round(0.40 * 500000) == 200000; equality is granted in full.)

    Design: Difficulty/boundary_precision_check/trade_in_cap_inclusive_at_exactly_forty_pct
    """
    order = _cap_boundary_setup(api)
    assert order["subtotal_cents"] == 500_000
    assert order["trade_in_credit_cents"] == 200_000, (
        f"cap is inclusive: credit equal to the cap must be granted, "
        f"got {order['trade_in_credit_cents']}")


def test_trade_in_cap_inclusive_downstream_tax_and_total(api):
    """PRD §3.4: "The taxable base is the subtotal minus the trade-in credit."
    PRD §3.4: "The order's `total_cents` is the subtotal minus the trade-in credit plus the
    delivery fee plus the tax; `amount_paid_cents` starts at zero; and `balance_cents` is
    always the total minus the amount paid."
    (taxable 300000; tax 24000; fee 15000; total 500000 - 200000 + 15000 + 24000 = 339000.)

    Design: Difficulty/boundary_precision_check/trade_in_cap_inclusive_at_exactly_forty_pct
    """
    order = _cap_boundary_setup(api)
    assert order["tax_cents"] == 24_000, f"round(300000 * 0.08), got {order['tax_cents']}"
    assert order["total_cents"] == 339_000, f"got {order['total_cents']}"
    assert order["balance_cents"] == 339_000


def test_delivery_fee_distance_tier_boundaries(api):
    """PRD §3.6: "The delivery fee that §3.4 folds into order pricing is built from the
    order's delivery attributes: a flat base of 15,000 cents, plus 2,500 cents per flight of
    stairs given in `stairs_count`, plus a distance band on `distance_miles` — nothing extra
    when the one-way distance is at most 25 miles, 12,000 cents when it is over 25 and at
    most 60 miles, and 24,000 cents beyond 60 — plus a 20,000-cent surcharge when
    `climate_controlled_required` is true."

    Design: Corner/calculations/delivery_fee_distance_tier_boundaries
    """
    customer = create_customer(full_name="Miles Mercer", email="miles@x.com")
    d1 = create_available_instrument(serial_number="SN-DF-1", category="DIGITAL",
                                     manufacturer="Roland", model="FP10",
                                     list_price_cents=100_000, floor_price_cents=80_000)
    d2 = create_available_instrument(serial_number="SN-DF-2", category="DIGITAL",
                                     manufacturer="Roland", model="FP10",
                                     list_price_cents=100_000, floor_price_cents=80_000)
    order25 = create_order(customer["id"], [order_line(d1["id"], 100_000)], distance_miles=25)
    order26 = create_order(customer["id"], [order_line(d2["id"], 100_000)], distance_miles=26)
    assert order25["delivery_fee_cents"] == 15_000, "25 miles: no distance tier"
    assert order26["delivery_fee_cents"] == 27_000, "26 miles: tier-2 12000 applies"


def test_order_amend_recomputes_derived_totals(api, sales_associate_headers):
    """PRD §3.4: "While the order remains `UNPAID` the associate may amend it — replacing
    `items`, `tax_rate`, or the delivery attributes — by carrying the
    `expected_order_version` token of §2.7; a stale token is refused with
    `ERR_STALE_VERSION` (HTTP 412), pricing is fully recomputed, and the order's `version`
    increments by one."
    (distance 10 -> 70: fee 15000 -> 15000 + 24000 = 39000; total 115000 -> 139000.)

    Design: Corner/endpoints/order_amend_recomputes_derived_totals
    """
    customer = create_customer(full_name="Recompute Rae", email="rae@x.com")
    instrument = create_available_instrument(serial_number="SN-RC-9", category="DIGITAL",
                                             manufacturer="Roland", model="FP30",
                                             list_price_cents=100_000, floor_price_cents=80_000)
    order = create_order(customer["id"], [order_line(instrument["id"], 100_000)])
    assert order["total_cents"] == 115_000

    amended = validate_success(api.amend_sales_order(
        order["id"], {"expected_order_version": order["version"], "distance_miles": 70},
        sales_associate_headers), 200)
    assert amended["delivery_fee_cents"] == 39_000, f"got {amended['delivery_fee_cents']}"
    assert amended["total_cents"] == 139_000, f"got {amended['total_cents']}"
    assert amended["balance_cents"] == 139_000, "amount_paid still 0"
    assert amended["version"] == order["version"] + 1


def test_order_amend_stale_version_rejected(api, sales_associate_headers):
    """PRD §2.7: "amending a sales order requires the request to carry
    `expected_order_version` holding the `version` of the `SalesOrder` the client last read.
    If the order's current `version` has advanced since that read — each successful
    amendment legitimately supersedes the prior pricing snapshot — the amendment is rejected
    with `ERR_STALE_VERSION` (HTTP 412)."

    Design: Corner/endpoints/order_amend_occ_stale_version_rejected
    """
    customer = create_customer(full_name="Amy Amend", email="amy@x.com")
    instrument = create_available_instrument(serial_number="SN-AM-1", category="DIGITAL",
                                             manufacturer="Roland", model="FP30",
                                             list_price_cents=100_000, floor_price_cents=80_000)
    order = create_order(customer["id"], [order_line(instrument["id"], 100_000)])
    observed_version = order["version"]

    first = validate_success(api.amend_sales_order(
        order["id"], {"expected_order_version": observed_version, "stairs_count": 2},
        sales_associate_headers), 200)
    assert first["version"] == observed_version + 1
    assert first["delivery_fee_cents"] == 20_000, "15000 + 2*2500"
    assert first["total_cents"] == 120_000

    res = api.amend_sales_order(
        order["id"], {"expected_order_version": observed_version, "stairs_count": 4},
        sales_associate_headers)
    validate_error(res, "ERR_STALE_VERSION")
    after = get_order(order["id"])
    assert after["stairs_count"] == 2, "rejected amendment must not apply"
    assert after["version"] == observed_version + 1


def test_deposit_payment_reconciles_balance_immediately(api):
    """PRD §3.5: "A payment smaller than the balance moves the order from `UNPAID` to
    `DEPOSIT_PAID` (or keeps it there), adding the amount to `amount_paid_cents` and
    recomputing `balance_cents`."
    PRD §3.4: "`amount_paid_cents` starts at zero; and `balance_cents` is always the total
    minus the amount paid."

    Design: Corner/endpoints/deposit_payment_reconciles_balance_immediately
    """
    customer = create_customer(full_name="Dep Osit", email="dep@x.com")
    instrument = create_available_instrument(serial_number="SN-DP-1")
    order = create_order(customer["id"], [order_line(instrument["id"], 500_000)])
    assert order["total_cents"] == 515_000

    paid = post_payment(order["id"], 200_000, method="CASH")
    assert paid["payment_status"] == "DEPOSIT_PAID"
    assert paid["amount_paid_cents"] == 200_000
    assert paid["balance_cents"] == 315_000, "515000 - 200000, immediate reconciliation"
