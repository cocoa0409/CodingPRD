"""Invoice rounding order, volume-discount tiers, provisional/final true-up,
payment gates, void, and the order's parallel payment axis (PRD §3.4, §3.5)."""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    confirm_order,
    create_driver,
    create_order,
    create_pricing_period,
    create_product,
    create_trip,
    deliver_order,
    delivered_line,
    get_invoice_for_order,
    make_distributor_owner_headers,
    make_store_receiver_headers,
    order_line,
    pay_invoice,
    precool_and_depart,
    publish_announcement,
    set_clock,
    setup_delivered_order,
    setup_route_with_store,
    setup_two_delivery_scenario,
    validate_error,
    validate_success,
)

TM = TEST_USERS["territory_manager_headers"]

REGULATED = {
    "regulated": True,
    "weight_lbs_per_unit": 8.6,
    "margin_cents_per_unit": 30,
    "units_per_case": 1,
    "shelf_life_days": 14,
}
# 2095c/cwt on 8.6 lb -> milk cost 180.17c; +30c margin.
PROV_299 = {"base": 2000, "assessment": 35, "hauling": 60, "diesel": 299}


def _setup_three_line_order(api, prefix):
    """Three regulated products with identical pricing on one CONFIRMED order
    of 3 units each, trip departed, ready to deliver."""
    refs = setup_route_with_store(prefix=prefix)
    d_id = refs["distributor"]["id"]
    products = [
        create_product(f"MILK-{prefix}-{letter}", **dict(REGULATED))
        for letter in "ABC"
    ]
    driver = create_driver(d_id, name=f"Driver {prefix}")
    period = create_pricing_period("2026-08")
    publish_announcement(period["id"], kind="PROVISIONAL", base=2000,
                         assessment=35, hauling=60, diesel=300)
    trip = create_trip(refs["route"]["id"], driver["id"], d_id)
    order = create_order(
        refs["store"]["id"], trip["id"],
        [order_line(p["id"], 3) for p in products],
        d_id,
        delivery_window_start="2026-08-10T08:00:00Z",
        delivery_window_end="2026-08-10T08:30:00Z",
    )
    confirm_order(order["id"], d_id)
    precool_and_depart(trip["id"], driver["id"], "2026-08-10")
    set_clock("2026-08-10T09:00:00Z")
    refs.update({"products": products, "driver": driver, "trip": trip,
                 "order": order, "period": period})
    return refs


class TestInvoiceRoundingPerLineThenSum:
    def test_per_line_rounding_then_sum(self, api):
        """PRD §3.4: "a `line_amount_cents` computed as `delivered_units`
        times `unit_price_cents` rounded half-up to integer cents — per-line
        rounding is pinned, and summing raw products then rounding once at
        invoice level is forbidden because it produces different cents"
        PRD §3.5: "`subtotal_cents` is the exact integer sum of the per-line
        `line_amount_cents` values, each already rounded half-up to integer
        cents at delivery (§3.4)."

        Design: Difficulty/combinatorial_formula/invoice_rounding_per_line_then_sum
        """
        refs = _setup_three_line_order(api, "RD")
        delivered = deliver_order(
            refs["order"]["id"], refs["driver"]["id"],
            [delivered_line(p["id"], 3, "2026-08-20") for p in refs["products"]],
        )
        assert delivered["subtotal_cents"] == 1917, (
            "3 x round(3 x 212.873) = 3 x 639; sum-then-round would give 1916"
        )
        invoice = get_invoice_for_order(refs["order"]["id"])
        assert invoice["subtotal_cents"] == 1917
        assert invoice["discount_cents"] == 0
        assert invoice["total_cents"] == 1917

    def test_zero_unit_line_contributes_zero(self, api):
        """PRD §3.4: "A line delivered with zero units contributes zero."
        PRD §3.4: "per-line rounding is pinned, and summing raw products then
        rounding once at invoice level is forbidden because it produces
        different cents"

        Design: Difficulty/combinatorial_formula/invoice_rounding_per_line_then_sum
        """
        refs = _setup_three_line_order(api, "RZ")
        pa, pb, pc = refs["products"]
        delivered = deliver_order(
            refs["order"]["id"], refs["driver"]["id"],
            [
                delivered_line(pa["id"], 0, "2026-08-20"),
                delivered_line(pb["id"], 3, "2026-08-20"),
                delivered_line(pc["id"], 3, "2026-08-20"),
            ],
        )
        assert delivered["subtotal_cents"] == 1278, (
            "0-unit line contributes 0; 2 x 639 = 1278"
        )
        invoice = get_invoice_for_order(refs["order"]["id"])
        assert invoice["subtotal_cents"] == 1278
        assert invoice["total_cents"] == 1278


class TestInvoiceVolumeDiscountPreDiscountTier:
    def test_subtotal_500000_takes_2_5_percent_despite_total_below_floor(self, api):
        """PRD §3.5: "a subtotal of exactly 500,000 yields a total of 487,500,
        which sits below the 500,000 tier floor, yet the 2.5 percent rate
        still applies because the tier was selected before the discount."

        Design: Difficulty/combinatorial_formula/invoice_volume_discount_pre_discount_tier
        """
        refs = setup_delivered_order(prefix="E", quantity_units=2000,
                                     code_date="2026-09-01")
        invoice = refs["invoice"]
        assert invoice["subtotal_cents"] == 500000
        assert invoice["discount_cents"] == 12500, "2.5% of pre-discount 500000"
        assert invoice["total_cents"] == 487500
        assert invoice["amount_due_cents"] == 487500

    def test_tier_1_boundary_200000_and_below(self, api):
        """PRD §3.5: "a subtotal below 200,000 cents earns no discount; from
        200,000 up to but not including 500,000 cents the rate is 1.5 percent
        — 200,000 exactly earns the 1.5 percent rate"

        Design: Difficulty/combinatorial_formula/invoice_volume_discount_pre_discount_tier
        """
        refs = setup_two_delivery_scenario(
            prefix="E2", first_units=800, second_units=799,
        )
        inv_a = refs["invoice"]
        assert inv_a["subtotal_cents"] == 200000
        assert inv_a["discount_cents"] == 3000, "1.5% at the inclusive floor"
        assert inv_a["total_cents"] == 197000

        inv_b = refs["invoice_b"]
        assert inv_b["subtotal_cents"] == 199750
        assert inv_b["discount_cents"] == 0, "below 200000 earns no discount"
        assert inv_b["total_cents"] == 199750


class TestOrderParallelFulfillmentPaymentAxes:
    def test_partial_payment_moves_payment_axis_only(self, api):
        """PRD §3.5: "a partial payment moves it to `PARTIALLY_PAID`"
        PRD §3.4: delivery moves "the order's `payment_status` moves to
        `INVOICED`" while the fulfillment axis is terminally `DELIVERED`.

        Design: Difficulty/non_linear_state_machine/order_parallel_fulfillment_payment_axes
        """
        refs = setup_delivered_order(prefix="F", quantity_units=10)
        order = refs["order"]
        assert order["fulfillment_status"] == "DELIVERED"
        assert order["payment_status"] == "INVOICED"

        pay_invoice(refs["invoice"]["id"], refs["store"]["id"], 900)
        mid = validate_success(api.get_order(order["id"], TM), 200)
        assert mid["fulfillment_status"] == "DELIVERED"
        assert mid["payment_status"] == "PARTIALLY_PAID"
        invoice = validate_success(api.get_invoice(refs["invoice"]["id"], TM), 200)
        assert invoice["amount_due_cents"] == 1600

    def test_full_payoff_settles_invoice_and_pays_order(self, api):
        """PRD §3.5: "When payments, credits, or a true-up drive
        `amount_due_cents` to exactly zero, the invoice auto-settles to
        `SETTLED` and its order's `payment_status` becomes `PAID`."

        Design: Difficulty/non_linear_state_machine/order_parallel_fulfillment_payment_axes
        """
        refs = setup_delivered_order(prefix="F2", quantity_units=10)
        pay_invoice(refs["invoice"]["id"], refs["store"]["id"], 900)
        pay_invoice(refs["invoice"]["id"], refs["store"]["id"], 1600)

        end = validate_success(api.get_order(refs["order"]["id"], TM), 200)
        assert end["fulfillment_status"] == "DELIVERED"
        assert end["payment_status"] == "PAID"
        invoice = validate_success(api.get_invoice(refs["invoice"]["id"], TM), 200)
        assert invoice["status"] == "SETTLED"
        assert invoice["amount_due_cents"] == 0


class TestInvoiceProvisionalVsFinalTrueUp:
    def _setup_provisional_invoice(self, api, prefix):
        refs = setup_delivered_order(
            prefix=prefix, quantity_units=10, code_date="2026-08-20",
            product_overrides=dict(REGULATED),
            announcement=dict(PROV_299),
        )
        return refs

    def test_final_publish_reprices_open_provisional_invoice(self, api):
        """PRD §3.5: "Each such invoice is recomputed line by line with the
        final announcement's figures per §3.3, re-rounded per the pinned line
        rounding, and re-discounted per the volume tiers; the
        `true_up_delta_cents` records the new total minus the old total (which
        may be zero); the `amount_due_cents` becomes the new total minus
        existing credits and payments; an invoice driven to exactly zero
        settles and flips its order's `payment_status` to `PAID`; and the
        invoice's `pricing_basis` flips to `FINAL`."
        PRD §3.3: "an invoice priced off a provisional announcement carries
        `pricing_basis` = `PROVISIONAL` and is subject to true-up repricing
        when the final announcement lands"

        Design: Difficulty/dual_variant_calc/invoice_provisional_vs_final_true_up
        """
        refs = self._setup_provisional_invoice(api, "A")
        invoice = refs["invoice"]
        assert invoice["total_cents"] == 2102, "10 x 210.170 rounded per line"
        assert invoice["pricing_basis"] == "PROVISIONAL"

        publish_announcement(refs["period"]["id"], kind="FINAL", base=2100,
                             assessment=35, hauling=60, diesel=299)
        after = validate_success(api.get_invoice(invoice["id"], TM), 200)
        assert after["pricing_basis"] == "FINAL"
        assert after["true_up_delta_cents"] == 86, "2188 - 2102"
        assert after["subtotal_cents"] == 2188
        assert after["discount_cents"] == 0
        assert after["total_cents"] == 2188
        assert after["amount_due_cents"] == 2188
        assert after["status"] == "OPEN"

    def test_repriced_amount_due_drives_settlement(self, api):
        """PRD §3.5: "the `amount_due_cents` becomes the new total minus
        existing credits and payments"
        PRD §3.5: "A recorded payment increases `payments_applied_cents` by
        the amount, recomputes `amount_due_cents`, settles the invoice at
        exactly zero (flipping the order's `payment_status` to `PAID`; a
        partial payment moves it to `PARTIALLY_PAID`), and recomputes the
        store's `open_ar_cents`."

        Design: Difficulty/dual_variant_calc/invoice_provisional_vs_final_true_up
        """
        refs = self._setup_provisional_invoice(api, "A2")
        publish_announcement(refs["period"]["id"], kind="FINAL", base=2100,
                             assessment=35, hauling=60, diesel=299)
        pay_invoice(refs["invoice"]["id"], refs["store"]["id"], 2188)

        invoice = validate_success(api.get_invoice(refs["invoice"]["id"], TM), 200)
        assert invoice["status"] == "SETTLED"
        assert invoice["amount_due_cents"] == 0
        order = validate_success(api.get_order(refs["order"]["id"], TM), 200)
        assert order["payment_status"] == "PAID"


def test_invoice_void_and_payment_gates(api):
    """PRD §3.5: "the invoice must be `OPEN` (else `ERR_INVOICE_NOT_OPEN`),
    the amount must be positive, and an amount greater than the invoice's
    `amount_due_cents` is rejected with `ERR_PAYMENT_EXCEEDS_DUE` (HTTP 402) —
    fiscal checks run last on the priority ladder."
    PRD §3.5: "A `TerritoryManager` may void an `OPEN` invoice, but only while
    both `payments_applied_cents` and `credits_applied_cents` are zero —
    otherwise `ERR_INVOICE_NOT_VOIDABLE`; from a non-`OPEN` state the same
    error applies."

    Design: Corner/state_machines/invoice_void_and_payment_gates
    """
    refs = setup_two_delivery_scenario(prefix="AI", first_units=4, second_units=4)
    inv_a = refs["invoice"]
    inv_b = refs["invoice_b"]
    s1 = refs["store"]["id"]
    assert inv_a["amount_due_cents"] == 1000 and inv_b["amount_due_cents"] == 1000

    err1 = api.pay_invoice(inv_a["id"], {"amount_cents": 1001},
                           make_store_receiver_headers(s1))
    validate_error(err1, ApiErrorId.ERR_PAYMENT_EXCEEDS_DUE)

    settled = pay_invoice(inv_a["id"], s1, 1000)
    assert settled["status"] == "SETTLED"

    err3 = api.pay_invoice(inv_a["id"], {"amount_cents": 1},
                           make_store_receiver_headers(s1))
    validate_error(err3, ApiErrorId.ERR_INVOICE_NOT_OPEN)

    pay_invoice(inv_b["id"], s1, 400)
    err2 = api.void_invoice(inv_b["id"], TM)
    validate_error(err2, ApiErrorId.ERR_INVOICE_NOT_VOIDABLE)


def test_invoice_void_happy_path_reverts_order_payment(api):
    """PRD §3.5: "Voiding moves the invoice to `VOID`, reverts its order's
    `payment_status` to `UNINVOICED`, and recomputes the store's
    `open_ar_cents`."

    Design: Corner/state_machines/invoice_void_happy_path_reverts_order_payment
    """
    refs = setup_delivered_order(prefix="AJ", quantity_units=4)
    invoice = refs["invoice"]
    assert invoice["amount_due_cents"] == 1000

    voided = validate_success(api.void_invoice(invoice["id"], TM), 200)
    assert voided["status"] == "VOID"

    order = validate_success(api.get_order(refs["order"]["id"], TM), 200)
    assert order["payment_status"] == "UNINVOICED"
    store = validate_success(api.get_store(refs["store"]["id"], TM), 200)
    assert store["open_ar_cents"] == 0
