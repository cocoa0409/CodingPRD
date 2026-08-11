"""Orders and allocation: creation shape, pinned per-line pricing, rotation
policies, sequential lot runs, the shelf-life gate, submit-time guards,
backorder cycling, reservation release compensation, and reallocate OCC."""
from test_helpers import (
    ApiErrorId,
    assert_lot_quantity_conservation,
    get_line_reservations,
    get_lot,
    get_order,
    get_order_lines,
    get_success_data,
    make_customer,
    make_customer_headers,
    make_lot,
    make_order,
    make_product,
    make_warehouse,
    make_zone,
    order_line,
    setup_ambient_order,
    submit_order,
    validate_error,
    validate_success,
)
from test_helpers import TEST_USERS

OPS = TEST_USERS["ops_admin_headers"]
CATALOG = TEST_USERS["catalog_manager_headers"]
CLERK = TEST_USERS["inventory_clerk_headers"]
ACCOUNTS = TEST_USERS["account_manager_headers"]
QUALITY = TEST_USERS["quality_manager_headers"]


class TestOrderCreation:
    def test_order_create_initial_state_draft_and_lines_pending(self, api):
        """PRD §3.4: "Creation materializes each entry as an order line owned by the order via its `order_id`, starting `PENDING`, with `allocated_quantity` at 0 and `unit_price_cents` and `line_total_cents` still null. The order itself begins `DRAFT`, with `product_total_cents` and `submission_seq` null until its first successful submission."

        Design: Corner/state_machines/order_create_initial_state_draft_and_lines_pending
        """
        warehouse = make_warehouse(api)
        product = make_product(api, sku="CH-1000", unit_price_cents=1000)
        customer = make_customer(api)
        resp = api.create_order(
            {
                "customer_id": customer["id"],
                "warehouse_id": warehouse["id"],
                "shipping_service": "STANDARD",
                "requested_ship_date": "2026-05-10",
                "lines": [order_line(product["id"], 4, "ANY")],
            },
            make_customer_headers(customer["id"]),
        )
        order = validate_success(resp, 201)
        assert order["status"] == "DRAFT"
        assert order["product_total_cents"] is None, (
            "product_total_cents stays null until the first successful submission"
        )
        lines = get_order_lines(api, order["id"])
        assert len(lines) == 1
        assert lines[0]["status"] == "PENDING"
        assert lines[0]["allocated_quantity"] == 0

    def test_order_create_with_system_version_field_rejected(self, api):
        """PRD §2.6: "required fields present, types correct, enum members valid, integer fields positive where declared, ISO dates parseable, `effective_until` after `effective_from` where applicable, and no unknown fields, else `ERR_INVALID_REQUEST`."
        PRD §2.4: "`version` (integer): a system-managed integer that increments by exactly 1 on every mutation of the resource, including system-driven state transitions applied by cascades."

        Design: Corner/entities/order_create_with_system_version_field_rejected
        """
        warehouse = make_warehouse(api)
        customer = make_customer(api)
        resp = api.create_order(
            {
                "customer_id": customer["id"],
                "warehouse_id": warehouse["id"],
                "shipping_service": "STANDARD",
                "requested_ship_date": "2026-05-10",
                "lines": [],
                "version": 99,
            },
            make_customer_headers(customer["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)


class TestPerLinePricing:
    def _setup_two_line_order(self, api):
        """Two qty-1 lines of one 105-cent product; customer discount 10%."""
        warehouse = make_warehouse(api)
        zone = make_zone(api, warehouse["id"], zone_class="AMBIENT", capacity_units=500)
        product = make_product(api, sku="CH-105", name="Buffer Salt", unit_price_cents=105)
        customer = make_customer(
            api, name="Lab Gamma", volume_discount_pct=0.10, hazmat_endorsement="NONE"
        )
        make_lot(api, product["id"], warehouse["id"], zone["id"], quantity_received=10)
        order = make_order(
            api,
            customer["id"],
            warehouse["id"],
            [order_line(product["id"], 1, "ANY"), order_line(product["id"], 1, "ANY")],
        )
        return customer, order

    def test_order_pricing_round_per_line_then_sum_order_total(self, api):
        """PRD §3.4: "A passing submission prices the order with a pinned rounding order: each line snapshots `unit_price_cents` from the product's current catalog price, then computes `line_total_cents` as the quantity times that unit price times one minus the customer's `volume_discount_pct`, rounded half up to whole cents per line; the order's `product_total_cents` is the sum of those rounded line totals. Sum-then-round is forbidden — two lines of quantity 1 at 105 cents with a 10% discount yield 95 + 95 = 190 cents, never 189."

        Design: Difficulty/combinatorial_formula/order_pricing_round_per_line_then_sum
        """
        customer, order = self._setup_two_line_order(api)
        resp = api.submit_order(order["id"], make_customer_headers(customer["id"]))
        data = validate_success(resp, 200)
        assert data["status"] == "ALLOCATED"
        assert data["product_total_cents"] == 190, (
            f"per-line round-then-sum must give 95 + 95 = 190, not 189: {data}"
        )

    def test_order_pricing_round_per_line_then_sum_line_totals(self, api):
        """PRD §3.4: "Sum-then-round is forbidden — two lines of quantity 1 at 105 cents with a 10% discount yield 95 + 95 = 190 cents, never 189."
        PRD §3.4: "each line snapshots `unit_price_cents` from the product's current catalog price, then computes `line_total_cents` as the quantity times that unit price times one minus the customer's `volume_discount_pct`, rounded half up to whole cents per line"

        Design: Difficulty/combinatorial_formula/order_pricing_round_per_line_then_sum
        """
        customer, order = self._setup_two_line_order(api)
        submit_order(api, order["id"], customer["id"])
        lines = get_order_lines(api, order["id"])
        assert len(lines) == 2
        for line in lines:
            assert line["unit_price_cents"] == 105, "each line snapshots the catalog price"
            assert line["line_total_cents"] == 95, (
                f"round_half_up(1 * 105 * 0.9) == 95 per line: {line}"
            )
        assert sum(l["line_total_cents"] for l in lines) == 190


class TestAllocationPolicies:
    def test_fefo_prefers_earliest_expiry_lot(self, api):
        """PRD §3.4: "For `ANY` lines, eligible lots are ranked by the rotation policy of their zone — under `FEFO` by earliest `expiry_date`, ties broken by earlier `received_at` then lower `lot_sequence_number`;"
        PRD §3.4: "Candidate lots must be `AVAILABLE`, belong to the line's `product_id` and the order's `warehouse_id`, sit in a zone at least as cold as the product's `storage_requirement`, and pass the shelf-life gate: the span from the order's `requested_ship_date` to the lot's `expiry_date` must be at least the product's `min_remaining_shelf_life_days`, with equality allocatable and one day less not."

        Design: Corner/calculations/fefo_prefers_earliest_expiry_lot
        """
        warehouse = make_warehouse(api)
        zone = make_zone(
            api, warehouse["id"], zone_class="REFRIGERATED_2_8", capacity_units=1000,
            rotation_policy="FEFO",
        )
        product = make_product(
            api, sku="RG-100", name="Enzyme Mix", storage_requirement="REFRIGERATED_2_8",
            unit_price_cents=20000, requires_cold_chain=True, shelf_life_days=60,
        )
        customer = make_customer(
            api, name="Lab Alpha", hazmat_endorsement="FULL", cold_chain_certified=True
        )
        # L1 is received first (manufacture 2026-03-01, expiry 2026-04-30 — already
        # short of the gate against ship date 2026-05-10); L2 is received second
        # (manufacture 2026-04-01, expiry 2026-05-31 — passes the gate).
        lot1 = make_lot(api, product["id"], warehouse["id"], zone["id"],
                        quantity_received=10, manufacture_date="2026-03-01")
        lot2 = make_lot(api, product["id"], warehouse["id"], zone["id"],
                        quantity_received=10, manufacture_date="2026-04-01")
        order = make_order(
            api, customer["id"], warehouse["id"],
            [order_line(product["id"], 3, "ANY")],
            shipping_service="EXPRESS",
        )
        submit_order(api, order["id"], customer["id"])

        lines = get_order_lines(api, order["id"])
        reservations = get_line_reservations(api, lines[0]["id"])
        assert len(reservations) == 1
        assert reservations[0]["lot_id"] == lot2["id"], (
            "the reservation must land on the lot that is eligible under the gate"
        )
        assert reservations[0]["quantity"] == 3
        lot1_after = get_lot(api, lot1["id"])
        assert lot1_after["quantity_on_hand"] == 10, "the gate-failing lot stays untouched"

    def test_sequential_mode_allocates_consecutive_run(self, api):
        """PRD §3.4: "For `SEQUENTIAL` lines the system instead considers candidate runs — sets of eligible lots whose `lot_sequence_number` values are strictly consecutive, each exactly one greater than the previous — and among runs whose summed on-hand covers the line's `quantity`, prefers the run with the fewest lots, breaking ties toward the lowest starting sequence number and then the earliest expiry date of the run's first lot. Consumption within the chosen run proceeds from the lowest sequence number upward, again taking the lesser of remaining need and on-hand per lot."

        Design: Corner/cross_cutting_layers/sequential_mode_allocates_consecutive_run
        """
        warehouse = make_warehouse(api)
        zone = make_zone(
            api, warehouse["id"], zone_class="REFRIGERATED_2_8", capacity_units=1000,
            rotation_policy="FEFO",
        )
        product = make_product(
            api, sku="RG-100", name="Enzyme Mix", storage_requirement="REFRIGERATED_2_8",
            unit_price_cents=20000, requires_cold_chain=True, shelf_life_days=300,
        )
        customer = make_customer(
            api, name="Lab Alpha", hazmat_endorsement="FULL", cold_chain_certified=True
        )
        lot1 = make_lot(api, product["id"], warehouse["id"], zone["id"],
                        quantity_received=3, manufacture_date="2026-01-15")
        lot2 = make_lot(api, product["id"], warehouse["id"], zone["id"],
                        quantity_received=3, manufacture_date="2026-02-15")
        order = make_order(
            api, customer["id"], warehouse["id"],
            [order_line(product["id"], 5, "SEQUENTIAL")],
            shipping_service="EXPRESS",
        )
        resp = api.submit_order(order["id"], make_customer_headers(customer["id"]))
        data = validate_success(resp, 200)
        assert data["status"] == "ALLOCATED"

        lines = get_order_lines(api, order["id"])
        assert lines[0]["allocated_quantity"] == 5
        reservations = get_line_reservations(api, lines[0]["id"])
        by_lot = {r["lot_id"]: r["quantity"] for r in reservations}
        assert by_lot == {lot1["id"]: 3, lot2["id"]: 2}, (
            f"run {{seq 1, seq 2}} fills lowest sequence first (3 + 2): {by_lot}"
        )
        lot1_after = get_lot(api, lot1["id"])
        assert lot1_after["status"] == "DEPLETED", (
            "a lot driven to exactly zero on-hand flips itself to DEPLETED"
        )
        lot2_after = get_lot(api, lot2["id"])
        assert lot2_after["quantity_on_hand"] == 1

    def test_sequential_no_consecutive_run_backorders_empty_pool(self, api):
        """PRD §3.4: "A sequential line for which no run suffices receives no reservations at all and stays `PENDING` — sequential lines never partially allocate."
        PRD §3.4: "When every line is fully covered the order lands `ALLOCATED`; when at least one line fell short it lands `BACKORDERED`, with whatever partial `HELD` reservations were gathered persisting in place."

        Design: Corner/cross_cutting_layers/sequential_no_consecutive_run_backorders_empty_pool
        """
        warehouse = make_warehouse(api)
        zone = make_zone(
            api, warehouse["id"], zone_class="REFRIGERATED_2_8", capacity_units=1000,
            rotation_policy="FEFO",
        )
        product = make_product(
            api, sku="RG-100", name="Enzyme Mix", storage_requirement="REFRIGERATED_2_8",
            unit_price_cents=20000, requires_cold_chain=True, shelf_life_days=300,
        )
        customer = make_customer(
            api, name="Lab Alpha", hazmat_endorsement="FULL", cold_chain_certified=True
        )
        make_lot(api, product["id"], warehouse["id"], zone["id"],
                 quantity_received=2, manufacture_date="2026-01-15")
        lot2 = make_lot(api, product["id"], warehouse["id"], zone["id"],
                        quantity_received=5, manufacture_date="2026-02-15")
        make_lot(api, product["id"], warehouse["id"], zone["id"],
                 quantity_received=4, manufacture_date="2026-03-15")
        # Quarantining seq 2 breaks the consecutive run: eligible {1 (qty 2), 3 (qty 4)}.
        get_success_data(api.quarantine_lot(lot2["id"], QUALITY))

        order = make_order(
            api, customer["id"], warehouse["id"],
            [order_line(product["id"], 5, "SEQUENTIAL")],
            shipping_service="EXPRESS",
        )
        resp = api.submit_order(order["id"], make_customer_headers(customer["id"]))
        data = validate_success(resp, 200)
        assert data["status"] == "BACKORDERED", (
            "no consecutive run covers 5 units, so the order backorders"
        )
        lines = get_order_lines(api, order["id"])
        assert lines[0]["status"] == "PENDING"
        assert lines[0]["allocated_quantity"] == 0
        assert get_line_reservations(api, lines[0]["id"]) == [], (
            "sequential lines never partially allocate"
        )


class TestSubmitGuards:
    def test_shelf_life_gate_hard_failure_with_stock_present(self, api):
        """PRD §3.4: "The gate has a submit-time hard edge: when at least one `AVAILABLE` lot of a line's product with positive on-hand exists at the order's warehouse but every such lot fails the gate, the submit is rejected outright with `ERR_SHELF_LIFE_TOO_SHORT` rather than silently backordering; otherwise gate-failing lots are simply skipped."

        Design: Corner/validations/shelf_life_gate_hard_failure_with_stock_present
        """
        # Lot expiry 2026-05-31 vs requested_ship_date 2026-05-25: 6 days < 7 required.
        warehouse = make_warehouse(api)
        zone = make_zone(
            api, warehouse["id"], zone_class="REFRIGERATED_2_8", capacity_units=100
        )
        product = make_product(
            api, sku="RG-100", name="Enzyme Mix", storage_requirement="REFRIGERATED_2_8",
            unit_price_cents=20000, requires_cold_chain=True, shelf_life_days=60,
        )
        customer = make_customer(
            api, name="Lab Alpha", hazmat_endorsement="FULL", cold_chain_certified=True
        )
        make_lot(api, product["id"], warehouse["id"], zone["id"],
                 quantity_received=10, manufacture_date="2026-04-01")
        order = make_order(
            api, customer["id"], warehouse["id"],
            [order_line(product["id"], 2, "ANY")],
            shipping_service="EXPRESS", requested_ship_date="2026-05-25",
        )
        resp = api.submit_order(order["id"], make_customer_headers(customer["id"]))
        validate_error(resp, ApiErrorId.ERR_SHELF_LIFE_TOO_SHORT)
        assert get_order(api, order["id"])["status"] == "DRAFT"
        lines = get_order_lines(api, order["id"])
        for line in lines:
            assert get_line_reservations(api, line["id"]) == []

    def test_discontinued_product_blocked_at_submit(self, api):
        """PRD §3.4: "every line's product must be `LISTED` (`ERR_PRODUCT_NOT_LISTED`)"
        PRD §3.1: "A product enters the catalog `LISTED`; discontinuation moves it to the terminal `DISCONTINUED` from either `LISTED` or `UNDER_RECALL` — attempting it in any other state is rejected with `ERR_PRODUCT_NOT_LISTED`."

        Design: Corner/state_machines/discontinued_product_blocked_at_submit
        """
        ctx = setup_ambient_order(api, quantity=1, lot_quantity=10, submit=False)
        get_success_data(api.discontinue_product(ctx["product"]["id"], CATALOG))
        resp = api.submit_order(
            ctx["order"]["id"], make_customer_headers(ctx["customer"]["id"])
        )
        validate_error(resp, ApiErrorId.ERR_PRODUCT_NOT_LISTED)
        assert get_order(api, ctx["order"]["id"])["status"] == "DRAFT"

    def test_endorsement_insufficient_for_toxic_product(self, api):
        """PRD §3.4: "the customer's `hazmat_endorsement` must cover every line product's `hazard_class` per the ladder of §2.10 (`ERR_HAZMAT_ENDORSEMENT_INSUFFICIENT`)"
        PRD §2.10: "`NONE` permits only `NON_HAZARDOUS` product; `LIMITED` additionally covers `FLAMMABLE` and `CORROSIVE`; `FULL` covers everything, adding `TOXIC` and `OXIDIZER`."

        Design: Corner/validations/endorsement_insufficient_for_toxic_product
        """
        warehouse = make_warehouse(api, name="WH-HZ", region_code="US-SW")
        zone = make_zone(api, warehouse["id"], zone_class="AMBIENT", capacity_units=500)
        product = make_product(
            api, sku="TX-10", name="Toxin Reagent", hazard_class="TOXIC",
            unit_haz_factor=1, max_qty_per_shipment=100, unit_price_cents=1000,
        )
        customer = make_customer(api, name="Lab Lim", hazmat_endorsement="LIMITED")
        make_lot(api, product["id"], warehouse["id"], zone["id"], quantity_received=10)
        order = make_order(
            api, customer["id"], warehouse["id"], [order_line(product["id"], 1, "ANY")]
        )
        resp = api.submit_order(order["id"], make_customer_headers(customer["id"]))
        validate_error(resp, ApiErrorId.ERR_HAZMAT_ENDORSEMENT_INSUFFICIENT)

    def test_cold_chain_uncertified_customer_rejected(self, api):
        """PRD §3.4: "when any line's product has `requires_cold_chain` true, the customer must be `cold_chain_certified` (`ERR_COLD_CHAIN_NOT_CERTIFIED`)"

        Design: Corner/validations/cold_chain_uncertified_customer_rejected
        """
        warehouse = make_warehouse(api)
        zone = make_zone(
            api, warehouse["id"], zone_class="REFRIGERATED_2_8", capacity_units=100
        )
        product = make_product(
            api, sku="RG-100", name="Enzyme Mix", storage_requirement="REFRIGERATED_2_8",
            unit_price_cents=20000, requires_cold_chain=True, shelf_life_days=60,
        )
        customer = make_customer(
            api, name="Lab Warm", hazmat_endorsement="FULL", cold_chain_certified=False
        )
        make_lot(api, product["id"], warehouse["id"], zone["id"],
                 quantity_received=10, manufacture_date="2026-04-01")
        order = make_order(
            api, customer["id"], warehouse["id"],
            [order_line(product["id"], 1, "ANY")],
            shipping_service="EXPRESS",
        )
        resp = api.submit_order(order["id"], make_customer_headers(customer["id"]))
        validate_error(resp, ApiErrorId.ERR_COLD_CHAIN_NOT_CERTIFIED)


class TestStateBeatsFiscal:
    def _setup_cancelled_low_credit_order(self, api):
        warehouse = make_warehouse(api)
        product = make_product(api, sku="CH-1000", unit_price_cents=1000)
        customer = make_customer(api, name="Lab Tiny", credit_limit_cents=100)
        order = make_order(
            api, customer["id"], warehouse["id"], [order_line(product["id"], 1, "ANY")]
        )
        get_success_data(api.cancel_order(order["id"], make_customer_headers(customer["id"])))
        return customer, order

    def test_state_beats_fiscal_on_cancelled_order_submit_error(self, api):
        """PRD §2.6: "All requests are evaluated against a fixed validation priority chain, and a higher-priority failure always masks lower-priority ones — the caller sees exactly one error, from the earliest failing stage:"
        PRD §2.6: "7. **State-machine validity** — the attempted transition's from-state preconditions, else the per-transition 409 (for example `ERR_ORDER_NOT_SUBMITTABLE`, `ERR_LOT_NOT_QUARANTINED`)."
        PRD §2.6: "8. **Business rules** — hazmat, cold-chain, recall, temporal, capacity, fiscal, and referential rules, in the domain-priority order stated with each workflow in §3."

        Design: Difficulty/priority_pair_validation_conflict/state_beats_fiscal_on_cancelled_order_submit
        """
        customer, order = self._setup_cancelled_low_credit_order(api)
        resp = api.submit_order(order["id"], make_customer_headers(customer["id"]))
        # The order is CANCELLED (state, earlier stage) and the projected total
        # 1800 exceeds credit_limit 100 (fiscal, later stage): state must win.
        validate_error(resp, ApiErrorId.ERR_ORDER_NOT_SUBMITTABLE)
        assert resp.status_code == 409, "the state error is a 409, never the fiscal 402"

    def test_state_beats_fiscal_on_cancelled_order_submit_unchanged(self, api):
        """PRD §2.6: "All requests are evaluated against a fixed validation priority chain, and a higher-priority failure always masks lower-priority ones — the caller sees exactly one error, from the earliest failing stage:"
        PRD §3.4: "`DELIVERED`, `CANCELLED`, and `REFUNDED` are the order's terminal states."

        Design: Difficulty/priority_pair_validation_conflict/state_beats_fiscal_on_cancelled_order_submit
        """
        customer, order = self._setup_cancelled_low_credit_order(api)
        resp = api.submit_order(order["id"], make_customer_headers(customer["id"]))
        validate_error(resp, ApiErrorId.ERR_ORDER_NOT_SUBMITTABLE)
        assert get_order(api, order["id"])["status"] == "CANCELLED", (
            "the rejected submit must leave the terminal order untouched"
        )


class TestBackorderCycle:
    def _setup_short_order(self, api):
        """Cold-chain order of 10 against a lot of only 5."""
        warehouse = make_warehouse(api)
        zone = make_zone(
            api, warehouse["id"], zone_class="REFRIGERATED_2_8", capacity_units=1000,
            rotation_policy="FEFO",
        )
        product = make_product(
            api, sku="RG-100", name="Enzyme Mix", storage_requirement="REFRIGERATED_2_8",
            unit_price_cents=20000, requires_cold_chain=True, shelf_life_days=60,
        )
        customer = make_customer(
            api, name="Lab Alpha", hazmat_endorsement="FULL", cold_chain_certified=True
        )
        lot1 = make_lot(api, product["id"], warehouse["id"], zone["id"],
                        quantity_received=5, manufacture_date="2026-04-01")
        order = make_order(
            api, customer["id"], warehouse["id"],
            [order_line(product["id"], 10, "ANY")],
            shipping_service="EXPRESS",
        )
        return warehouse, zone, product, customer, lot1, order

    def test_backorder_submit_with_partial_hold(self, api):
        """PRD §3.4: "Lines then settle into their allocation states: full coverage moves a line from `PENDING` to `ALLOCATED`, partial coverage moves it to `PARTIALLY_ALLOCATED`, and every one of these line transitions increments the line's `version`. When every line is fully covered the order lands `ALLOCATED`; when at least one line fell short it lands `BACKORDERED`, with whatever partial `HELD` reservations were gathered persisting in place."
        PRD §3.2: "Whenever any flow — allocation, dispatch, adjustment, or kit assembly — drives a lot's `quantity_on_hand` to exactly zero, the lot transitions itself from `AVAILABLE` to `DEPLETED`."

        Design: Difficulty/non_linear_state_machine/order_backorder_cycle_on_stock_arrival
        """
        _wh, _zone, _prod, customer, lot1, order = self._setup_short_order(api)
        resp = api.submit_order(order["id"], make_customer_headers(customer["id"]))
        data = validate_success(resp, 200)
        assert data["status"] == "BACKORDERED", (
            "partial allocation persists as a backorder, not a rejection"
        )
        lines = get_order_lines(api, order["id"])
        assert lines[0]["status"] == "PARTIALLY_ALLOCATED"
        assert lines[0]["allocated_quantity"] == 5
        lot1_after = get_lot(api, lot1["id"])
        assert lot1_after["status"] == "DEPLETED"
        assert lot1_after["quantity_on_hand"] == 0
        assert lot1_after["quantity_reserved"] == 5

    def test_backorder_cycle_topup_on_stock_arrival(self, api):
        """PRD §3.4: "Every lot receipt triggers a system waitlist retry over all `BACKORDERED` orders in ascending `submission_seq` order, allocating only each line's remaining shortfall against the newly available lots while keeping the order's existing `HELD` reservations; a retry that fully covers every line promotes the order to `ALLOCATED` (and a line it completes moves from `PARTIALLY_ALLOCATED` to `ALLOCATED`)."

        Design: Difficulty/non_linear_state_machine/order_backorder_cycle_on_stock_arrival
        """
        warehouse, zone, product, customer, lot1, order = self._setup_short_order(api)
        submit_order(api, order["id"], customer["id"])
        assert get_order(api, order["id"])["status"] == "BACKORDERED"

        lot2 = make_lot(api, product["id"], warehouse["id"], zone["id"],
                        quantity_received=10, manufacture_date="2026-04-15")
        assert get_order(api, order["id"])["status"] == "ALLOCATED", (
            "the receipt's waitlist top-up completes the cycle BACKORDERED -> ALLOCATED"
        )
        lines = get_order_lines(api, order["id"])
        assert lines[0]["status"] == "ALLOCATED"
        assert lines[0]["allocated_quantity"] == 10
        assert get_lot(api, lot1["id"])["status"] == "DEPLETED"
        lot2_after = get_lot(api, lot2["id"])
        assert lot2_after["quantity_on_hand"] == 5
        assert lot2_after["quantity_reserved"] == 5


class TestReservationReleaseCompensation:
    def _setup_held_reservation(self, api):
        ctx = setup_ambient_order(api, quantity=8, lot_quantity=20, unit_price_cents=1000)
        lines = get_order_lines(api, ctx["order"]["id"])
        reservations = get_line_reservations(api, lines[0]["id"])
        assert len(reservations) == 1
        ctx["line"] = lines[0]
        ctx["reservation"] = reservations[0]
        return ctx

    def test_reservation_release_restores_lot_quantities(self, api):
        """PRD §3.4: "Individual reservations may also be released by hand, by the owning `Customer` or an `InventoryClerk`. Only a `HELD` reservation can be released — otherwise `ERR_RESERVATION_NOT_HELD` — and the release hands its quantity back to the lot (`quantity_reserved` down, `quantity_on_hand` up), recomputes the zone's `occupied_units`, and triggers the parent line and order's allocation recompute with the same possible demotions as the cascade."

        Design: Difficulty/compensating_invariant/reservation_release_restores_lot_quantities
        """
        ctx = self._setup_held_reservation(api)
        lot_before = get_lot(api, ctx["lot"]["id"])
        assert (lot_before["quantity_on_hand"], lot_before["quantity_reserved"]) == (12, 8)

        resp = api.release_reservation(
            ctx["reservation"]["id"], make_customer_headers(ctx["customer"]["id"])
        )
        released = validate_success(resp, 200)
        assert released["status"] == "RELEASED"

        lot_after = get_lot(api, ctx["lot"]["id"])
        assert lot_after["quantity_on_hand"] == 20
        assert lot_after["quantity_reserved"] == 0
        assert lot_after["quantity_consumed"] == 0
        assert_lot_quantity_conservation(lot_after)

    def test_reservation_release_demotes_line_and_order(self, api):
        """PRD §3.4: "Reservation loss also flows the other way: the quarantine, expiry, and recall cascades demote lines — from `ALLOCATED` to `PENDING` when released reservations leave nothing remaining, or from `PARTIALLY_ALLOCATED` to `PENDING` when the cascade strips the rest — and an `ALLOCATED` order demoted by such a cascade falls back to `BACKORDERED`."

        Design: Difficulty/compensating_invariant/reservation_release_restores_lot_quantities
        """
        ctx = self._setup_held_reservation(api)
        resp = api.release_reservation(
            ctx["reservation"]["id"], make_customer_headers(ctx["customer"]["id"])
        )
        validate_success(resp, 200)

        lines = get_order_lines(api, ctx["order"]["id"])
        assert lines[0]["status"] == "PENDING", (
            "releasing the only reservation leaves nothing remaining on the line"
        )
        assert lines[0]["allocated_quantity"] == 0
        assert get_order(api, ctx["order"]["id"])["status"] == "BACKORDERED", (
            "the demoted line drags its ALLOCATED order back to BACKORDERED"
        )


class TestReallocateOcc:
    def test_occ_reallocate_stale_version_rejected(self, api):
        """PRD §2.7: "`POST /lab/orders/{orderId}/reallocate` requires `expected_order_version`. When it no longer matches the order's current `version` — because an earlier submit, cascade, or reallocate already advanced it — the re-plan is rejected with `ERR_STALE_ORDER_VERSION` (HTTP 412), so allocations are never rebuilt from an outdated view of the order."
        PRD §3.4: "The customer may alternatively request a manual re-plan from either `BACKORDERED` or `ALLOCATED` — any other order state yields `ERR_ORDER_NOT_REALLOCATABLE`."

        Design: Corner/cross_cutting_layers/occ_reallocate_stale_version_rejected
        """
        ctx = setup_ambient_order(api, quantity=8, lot_quantity=20)
        observed_version = ctx["order"]["version"]

        first = api.reallocate_order(
            ctx["order"]["id"],
            {"expected_order_version": observed_version},
            make_customer_headers(ctx["customer"]["id"]),
        )
        realloced = validate_success(first, 200)
        assert realloced["status"] == "ALLOCATED"
        assert realloced["version"] == observed_version + 1

        second = api.reallocate_order(
            ctx["order"]["id"],
            {"expected_order_version": observed_version},
            make_customer_headers(ctx["customer"]["id"]),
        )
        validate_error(second, ApiErrorId.ERR_STALE_ORDER_VERSION)
