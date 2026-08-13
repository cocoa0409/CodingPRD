"""Credit exposure accounting and the completion cascade: delivered quantity
tracking, invoice auto-creation, HOLD/GOOD derivation, and the OCC
stale-version rules on price-list activation and load scheduling."""
import pytest

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    create_active_price_list,
    create_customer,
    get_customer,
    get_invoice_for_order,
    get_order,
    place_order,
    publish_index,
    schedule_load,
    set_clock,
    setup_completed_load,
    setup_confirmed_order,
    setup_issued_invoice,
    setup_standard_catalog,
    validate_error,
    validate_success,
    batch_load,
    confirm_order,
)

PM = TEST_USERS["plant_manager_headers"]
DISP = TEST_USERS["dispatcher_headers"]
DRV1 = TEST_USERS["driver_headers"]
DRV2 = TEST_USERS["driver2_headers"]


class TestCompletionCascade:
    def test_complete_flips_order_delivered_creates_invoice_and_holds_customer(self, api):
        """PRD §3.7: "The order's `delivered_qty_yd3` is recomputed as the sum
        of `discharged_qty_yd3` over the order's loads in `COMPLETED`
        (returned, washed-out, and cancelled loads contribute nothing), and
        when that delivered total reaches or exceeds the ordered `qty_yd3` —
        exact equality completes the order — the order moves automatically to
        `DELIVERED`, from either `SCHEDULED` or `IN_PROGRESS`."
        PRD §3.7: "Reaching `DELIVERED` auto-creates the order's invoice in
        `DRAFT` with one `LOAD` line item per completed load priced at that
        load's `final_charge_cents`, the invoice's `total_cents` being exactly
        the sum of its line items' `amount_cents`."
        PRD §3.7: "Finally, the customer's exposure is recomputed (§2.9),
        putting the customer on `HOLD` if the exposure has reached
        `credit_limit_cents`."

        Design: Difficulty/transitive_cascade/complete_triggers_order_invoice_credit_chain
        """
        ctx, load = setup_completed_load(
            indices=[("2026-08", 115.0)],
            customer_overrides={"credit_limit_cents": 150000},
        )
        # Link 1: fulfillment recompute.
        order = get_order(ctx["order"]["id"])
        assert order["delivered_qty_yd3"] == pytest.approx(8.0)
        assert order["delivery_status"] == "DELIVERED"

        # Link 2: invoice auto-created in DRAFT.
        invoice = get_invoice_for_order(order["id"])
        assert invoice["status"] == "DRAFT"
        assert invoice["total_cents"] == 159300

        # Link 3: exposure recompute; 159300 >= 150000 -> HOLD.
        customer = get_customer(ctx["customer"]["id"])
        assert customer["credit_exposure_cents"] == 159300
        assert customer["credit_status"] == "HOLD"

    def test_mid_progress_partial_delivery_stays_in_progress(self, api):
        """PRD §3.7: "The order's `delivered_qty_yd3` is recomputed as the sum
        of `discharged_qty_yd3` over the order's loads in `COMPLETED`
        (returned, washed-out, and cancelled loads contribute nothing), and
        when that delivered total reaches or exceeds the ordered `qty_yd3` —
        exact equality completes the order — the order moves automatically to
        `DELIVERED`, from either `SCHEDULED` or `IN_PROGRESS`."

        Design: Difficulty/transitive_cascade/complete_triggers_order_invoice_credit_chain
        """
        ctx = setup_confirmed_order(
            indices=[("2026-08", 115.0)],
            order_overrides={
                "qty_yd3": 16.0,
                "pour_date": "2026-08-17",
                "pour_window_start": "07:00",
                "pour_window_end": "12:00",
            },
        )
        l1 = schedule_load(
            ctx["order"]["id"], ctx["order_version"],
            qty_yd3=8.0, truck_id=ctx["trucks"]["T1"]["id"],
        )
        batch_load(l1["id"], "2026-08-17T09:00:00Z")
        validate_success(api.depart_load(l1["id"], DRV1), 200)
        set_clock("2026-08-17T09:30:00Z")
        validate_success(api.arrive_load(l1["id"], DRV1), 200)
        set_clock("2026-08-17T10:00:00Z")
        validate_success(
            api.complete_load(l1["id"], {"discharged_qty_yd3": 8.0}, DRV1), 200
        )

        order = get_order(ctx["order"]["id"])
        assert order["delivered_qty_yd3"] == pytest.approx(8.0)
        assert order["delivery_status"] == "IN_PROGRESS", (
            "8.0 < 16.0: only exact fulfillment or more delivers the order"
        )
        invoices = validate_success(
            api.list_invoices(DISP, params={"order_id": ctx["order"]["id"]}), 200
        )
        assert invoices == [], "no invoice before the order is DELIVERED"


class TestCreditExposureRules:
    def test_confirm_blocked_when_customer_on_hold(self, api):
        """PRD §3.3: "the customer's `credit_status` must not be `HOLD`
        (otherwise `ERR_CREDIT_HOLD`, HTTP 402)".

        Design: Difficulty/cross_entity_state_dependency/confirm_blocked_by_customer_credit_hold
        """
        catalog = setup_standard_catalog(
            customer_overrides={"credit_limit_cents": 100000}
        )
        order_a = place_order(
            catalog["plant"]["id"], catalog["mix"]["id"], catalog["customer"]["id"]
        )
        confirm_order(order_a["id"])  # provisional 145200 >= 100000
        validate_success(api.credit_review(catalog["customer"]["id"], PM), 200)
        assert get_customer(catalog["customer"]["id"])["credit_status"] == "HOLD"

        order_b = place_order(
            catalog["plant"]["id"], catalog["mix"]["id"], catalog["customer"]["id"],
            qty_yd3=4.0, pour_date="2026-08-16", slump_in=4.0,
        )
        res = api.confirm_order(order_b["id"], DISP)
        validate_error(res, ApiErrorId.ERR_CREDIT_HOLD.value)
        after = get_order(order_b["id"])
        assert after["delivery_status"] == "PLACED"
        assert after["billing_status"] == "UNPRICED"

    def test_confirm_unblocked_after_hold_lifts_via_cancel(self, api):
        """PRD §3.3: "When such a cancel succeeds, billing moves `PRICED →
        VOID` (the provisional pricing is voided as compensation), the
        customer's exposure is recomputed, and `credit_status` returns to
        `GOOD` if and only if the exposure is now strictly below
        `credit_limit_cents`."
        PRD §3.3: "the customer's `credit_status` must not be `HOLD`
        (otherwise `ERR_CREDIT_HOLD`, HTTP 402)".

        Design: Difficulty/cross_entity_state_dependency/confirm_blocked_by_customer_credit_hold
        """
        catalog = setup_standard_catalog(
            customer_overrides={"credit_limit_cents": 100000}
        )
        order_a = place_order(
            catalog["plant"]["id"], catalog["mix"]["id"], catalog["customer"]["id"]
        )
        confirm_order(order_a["id"])  # provisional 145200 >= 100000
        validate_success(api.credit_review(catalog["customer"]["id"], PM), 200)
        assert get_customer(catalog["customer"]["id"])["credit_status"] == "HOLD"

        order_b = place_order(
            catalog["plant"]["id"], catalog["mix"]["id"], catalog["customer"]["id"],
            qty_yd3=4.0, pour_date="2026-08-16", slump_in=4.0,
        )
        res = api.confirm_order(order_b["id"], DISP)
        validate_error(res, ApiErrorId.ERR_CREDIT_HOLD.value)

        # Cancelling the priced order voids its provisional pricing; exposure
        # drops to 0 and the hold lifts, so the same confirm now succeeds.
        cancelled = validate_success(api.cancel_order(order_a["id"], DISP), 200)
        assert cancelled["billing_status"] == "VOID"
        customer = get_customer(catalog["customer"]["id"])
        assert customer["credit_exposure_cents"] == 0
        assert customer["credit_status"] == "GOOD"

        confirmed_b = validate_success(api.confirm_order(order_b["id"], DISP), 200)
        assert confirmed_b["delivery_status"] == "CONFIRMED"
        assert confirmed_b["billing_status"] == "PRICED"
        assert confirmed_b["provisional_total_cents"] is not None

    def test_exposure_at_exact_limit_puts_customer_on_hold(self, api):
        """PRD §2.9: "The customer is on `HOLD` if and only if the exposure is
        greater than or equal to `credit_limit_cents` — exact equality puts
        the customer on hold."

        Design: Corner/cross_cutting_layers/credit_hold_at_exact_limit_threshold
        """
        set_clock("2026-07-15T09:00:00Z")
        catalog = setup_standard_catalog(
            indices=[("2026-07", 110.0)],
            customer_overrides={"credit_limit_cents": 145200},
        )
        order = place_order(
            catalog["plant"]["id"], catalog["mix"]["id"], catalog["customer"]["id"]
        )
        confirmed = confirm_order(order["id"])
        # 8 x 16500 = 132000 concrete + 13200 Saturday = 145200 provisional.
        assert confirmed["provisional_total_cents"] == 145200

        validate_success(api.credit_review(catalog["customer"]["id"], PM), 200)
        customer = get_customer(catalog["customer"]["id"])
        assert customer["credit_exposure_cents"] == 145200
        assert customer["credit_exposure_cents"] == customer["credit_limit_cents"]
        assert customer["credit_status"] == "HOLD", (
            ">= boundary: equality trips the threshold"
        )

    def test_exposure_just_below_limit_stays_good(self, api):
        """PRD §2.9: "The customer is on `HOLD` if and only if the exposure is
        greater than or equal to `credit_limit_cents` — exact equality puts
        the customer on hold."

        Design: Corner/cross_cutting_layers/credit_hold_at_exact_limit_threshold
        """
        set_clock("2026-07-15T09:00:00Z")
        catalog = setup_standard_catalog(
            indices=[("2026-07", 110.0)],
            customer_overrides={"credit_limit_cents": 145201},
        )
        order = place_order(
            catalog["plant"]["id"], catalog["mix"]["id"], catalog["customer"]["id"]
        )
        confirm_order(order["id"])  # provisional 145200
        validate_success(api.credit_review(catalog["customer"]["id"], PM), 200)
        customer = get_customer(catalog["customer"]["id"])
        assert customer["credit_exposure_cents"] == 145200
        assert customer["credit_status"] == "GOOD", "145200 < 145201 stays GOOD"

    def test_paid_invoice_and_placed_order_drop_out_of_exposure(self, api):
        """PRD §2.9: "Exposure is forward-looking: it is the sum of
        `provisional_total_cents` over the customer's orders whose
        `delivery_status` is `CONFIRMED`, `SCHEDULED`, or `IN_PROGRESS`, plus
        the sum of `total_cents` over the customer's invoices whose status is
        `DRAFT`, `ISSUED`, or `DISPUTED`. Paid and void invoices drop out of
        exposure; placed and cancelled orders never enter it."

        Design: Corner/calculations/credit_exposure_input_set_filtering
        """
        ctx, load, invoice = setup_issued_invoice(
            indices=[("2026-08", 115.0)],
            order_overrides={
                "pour_date": "2026-08-17",
                "pour_window_start": "07:00",
                "pour_window_end": "10:00",
            },
            batch_time="2026-08-17T09:00:00Z",
            arrive_at="2026-08-17T09:30:00Z",
            complete_at="2026-08-17T10:00:00Z",
            start_pour=False,
            customer_overrides={"credit_limit_cents": 1},
        )
        # Pay the Monday invoice exactly (138000) -> PAID drops out.
        from test_helpers import make_customer_headers

        paid = validate_success(
            api.pay_invoice(
                invoice["id"], {"amount_cents": 138000},
                make_customer_headers(ctx["customer"]["id"]),
            ),
            200,
        )
        assert paid["status"] == "PAID"

        # A second order left PLACED (never confirmed) contributes nothing.
        place_order(
            ctx["plant"]["id"], ctx["mix"]["id"], ctx["customer"]["id"],
            qty_yd3=9.0, pour_date="2026-08-18", slump_in=4.0,
        )

        reviewed = validate_success(
            api.credit_review(ctx["customer"]["id"], PM), 200
        )
        assert reviewed["credit_exposure_cents"] == 0
        assert reviewed["credit_status"] == "GOOD", (
            "exposure 0 stays GOOD even with a 1-cent limit"
        )


class TestDerivedFieldReconciliation:
    def test_fulfillment_exposure_and_payment_reconcile_across_lifecycle(self, api):
        """PRD §3.7: "when that delivered total reaches or exceeds the ordered
        `qty_yd3` — exact equality completes the order — the order moves
        automatically to `DELIVERED`, from either `SCHEDULED` or `IN_PROGRESS`."
        PRD §3.9: "Payment is exact-change only: the owning `Customer` pays an
        issued invoice by supplying `amount_cents`, which must equal the
        invoice's `total_cents` exactly, otherwise
        `ERR_PAYMENT_AMOUNT_MISMATCH` (HTTP 422). A successful payment moves
        the invoice `ISSUED → PAID` and the order's billing `INVOICED → PAID`;
        the paid invoice drops out of the exposure sum, exposure is
        recomputed, and `credit_status` returns to `GOOD` if and only if the
        remaining exposure is strictly below `credit_limit_cents`."

        Design: Corner/cross_cutting_layers/derived_fields_reconcile_through_delivery_and_payment
        """
        from test_helpers import make_customer_headers

        ctx = setup_confirmed_order(
            indices=[("2026-08", 115.0)],
            customer_overrides={"credit_limit_cents": 200000},
            order_overrides={
                "qty_yd3": 12.0,
                "pour_date": "2026-08-17",
                "pour_window_start": "07:00",
                "pour_window_end": "12:00",
            },
            truck_fleet_numbers=("T1", "T2"),
        )
        l1 = schedule_load(
            ctx["order"]["id"], ctx["order_version"],
            qty_yd3=6.0, truck_id=ctx["trucks"]["T1"]["id"],
        )
        l2 = schedule_load(
            ctx["order"]["id"], get_order(ctx["order"]["id"])["version"],
            qty_yd3=6.0, truck_id=ctx["trucks"]["T2"]["id"],
        )
        batch_load(l1["id"], "2026-08-17T09:00:00Z")
        batch_load(l2["id"], "2026-08-17T09:30:00Z")
        validate_success(api.depart_load(l1["id"], DRV1), 200)
        validate_success(api.depart_load(l2["id"], DRV2), 200)
        set_clock("2026-08-17T09:30:00Z")
        validate_success(api.arrive_load(l1["id"], DRV1), 200)
        set_clock("2026-08-17T10:00:00Z")
        validate_success(
            api.complete_load(l1["id"], {"discharged_qty_yd3": 6.0}, DRV1), 200
        )

        mid = get_order(ctx["order"]["id"])
        assert mid["delivered_qty_yd3"] == pytest.approx(6.0)
        assert mid["delivery_status"] == "IN_PROGRESS", "6.0 < 12.0"

        validate_success(api.arrive_load(l2["id"], DRV2), 200)
        set_clock("2026-08-17T10:30:00Z")
        validate_success(
            api.complete_load(l2["id"], {"discharged_qty_yd3": 6.0}, DRV2), 200
        )

        done = get_order(ctx["order"]["id"])
        assert done["delivered_qty_yd3"] == pytest.approx(12.0)
        assert done["delivery_status"] == "DELIVERED", "equality completes"

        invoice = get_invoice_for_order(done["id"])
        assert invoice["total_cents"] == 207000, "2 loads x 103500"
        issued = validate_success(api.issue_invoice(invoice["id"], PM), 200)
        validate_success(api.credit_review(ctx["customer"]["id"], PM), 200)
        held = get_customer(ctx["customer"]["id"])
        assert held["credit_exposure_cents"] == 207000
        assert held["credit_status"] == "HOLD", "207000 >= 200000"

        paid = validate_success(
            api.pay_invoice(
                issued["id"], {"amount_cents": 207000},
                make_customer_headers(ctx["customer"]["id"]),
            ),
            200,
        )
        assert paid["status"] == "PAID"
        validate_success(api.credit_review(ctx["customer"]["id"], PM), 200)
        cleared = get_customer(ctx["customer"]["id"])
        assert cleared["credit_exposure_cents"] == 0
        assert cleared["credit_status"] == "GOOD", (
            "paid invoice drops out of the input set"
        )


class TestOptimisticConcurrency:
    def test_stale_plant_version_on_price_list_activation_rejected(self, api):
        """PRD §2.7: "Creating a price list with `activate` set to true
        requires `expected_plant_version`, carrying the client's last observed
        `version` of the target plant. If the plant's current `version` no
        longer equals the supplied value — because, for example, another price
        list was activated against the same plant in the meantime — the
        request is rejected with `ERR_STALE_VERSION` (HTTP 412)."

        Design: Corner/cross_cutting_layers/occ_price_list_stale_version_rejected
        """
        from test_helpers import (
            create_draft_mix,
            create_plant,
            create_price_list_payload,
        )

        plant, plant_version = create_plant()
        mix = create_draft_mix(plant["id"], admixtures=[])

        pl1 = create_active_price_list(plant["id"], mix["id"], plant_version)
        assert pl1["status"] == "ACTIVE"

        # Second create carrying the pre-activation version is stale.
        stale = api.create_price_list(
            create_price_list_payload(
                plant["id"], mix["id"], plant_version, base_price_per_yd3_cents=16000
            ),
            PM,
        )
        validate_error(stale, ApiErrorId.ERR_STALE_VERSION.value)

        # Re-read and resubmit with the fresh version.
        fresh_plant = validate_success(api.get_plant(plant["id"], PM), 200)
        pl2 = create_active_price_list(
            plant["id"], mix["id"], fresh_plant["version"],
            base_price_per_yd3_cents=16000,
        )
        assert pl2["status"] == "ACTIVE"

        pl1_after = validate_success(api.get_price_list(pl1["id"], PM), 200)
        assert pl1_after["status"] == "SUPERSEDED", (
            "activating a newer list supersedes the prior ACTIVE list"
        )

    def test_stale_order_version_on_schedule_rejected(self, api):
        """PRD §2.7: "Scheduling a load onto an order requires
        `expected_order_version`, carrying the client's last observed
        `version` of the order. Scheduling legitimately succeeds many times
        against the same confirmed order, and each successful schedule bumps
        the order's `version`; a request whose `expected_order_version` no
        longer matches the order's current `version` is rejected with
        `ERR_STALE_VERSION` (HTTP 412), because the writer's view of the
        rotation is stale."

        Design: Corner/cross_cutting_layers/occ_load_schedule_stale_version_rejected
        """
        ctx = setup_confirmed_order(
            order_overrides={
                "qty_yd3": 16.0,
                "pour_date": "2026-08-17",
                "pour_window_start": "07:00",
                "pour_window_end": "12:00",
            },
            truck_fleet_numbers=("T1", "T2"),
        )
        stale_version = ctx["order_version"]
        l1 = schedule_load(
            ctx["order"]["id"], stale_version,
            qty_yd3=8.0, truck_id=ctx["trucks"]["T1"]["id"],
        )
        assert l1["status"] == "SCHEDULED"

        res = api.schedule_load(
            ctx["order"]["id"],
            {
                "qty_yd3": 8.0,
                "expected_order_version": stale_version,
                "truck_id": ctx["trucks"]["T2"]["id"],
            },
            DISP,
        )
        validate_error(res, ApiErrorId.ERR_STALE_VERSION.value)

        fresh = get_order(ctx["order"]["id"])
        l2 = schedule_load(
            ctx["order"]["id"], fresh["version"],
            qty_yd3=8.0, truck_id=ctx["trucks"]["T2"]["id"],
        )
        assert l2["status"] == "SCHEDULED"
        after = get_order(ctx["order"]["id"])
        assert after["version"] == fresh["version"] + 1, (
            "each successful schedule bumps the order version"
        )
