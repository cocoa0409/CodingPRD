"""Recurring supply: standing-order window buffers, clock-driven run
generation, consignment window overlap, per-record billing, replenishment,
and the immutable ConsumptionRecord shape."""
from test_helpers import (
    ApiErrorId,
    assert_consumption_record,
    get_customer,
    get_order_lines,
    make_agreement,
    make_customer,
    make_customer_headers,
    make_lot,
    make_product,
    make_standing_order,
    make_warehouse,
    make_zone,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers import TEST_USERS

OPS = TEST_USERS["ops_admin_headers"]
CATALOG = TEST_USERS["catalog_manager_headers"]
CLERK = TEST_USERS["inventory_clerk_headers"]
ACCOUNTS = TEST_USERS["account_manager_headers"]


def _base_trio(api):
    warehouse = make_warehouse(api)
    product = make_product(api, sku="CS-500", name="Consigned Stain", unit_price_cents=500)
    customer = make_customer(api, name="Lab Kappa")
    return warehouse, product, customer


class TestConsignmentWindowOverlap:
    def test_consignment_window_half_open_overlap_rejected(self, api):
        """PRD §3.8: "Agreements for the same customer and product may not overlap: considering existing agreements in `ACTIVE` or `SUSPENDED`, overlap exists when the existing window begins before the new window ends and the new window begins before the existing window ends, while mere adjacency — a new window starting exactly when the existing one ends — is allowed; an overlap is rejected with `ERR_CONSIGNMENT_WINDOW_OVERLAP`."

        Design: Difficulty/resource_temporal_overlap/consignment_window_half_open_overlap
        """
        warehouse, product, customer = _base_trio(api)
        make_agreement(
            api, customer_id=customer["id"], product_id=product["id"],
            ceiling_quantity=100, reorder_point=0, contract_unit_price_cents=500,
            replenishment_warehouse_id=warehouse["id"],
            effective_from="2026-05-01", effective_until="2026-06-01",
        )
        resp = api.create_agreement(
            {
                "customer_id": customer["id"],
                "product_id": product["id"],
                "ceiling_quantity": 50,
                "reorder_point": 0,
                "contract_unit_price_cents": 500,
                "replenishment_warehouse_id": warehouse["id"],
                "effective_from": "2026-05-15",
                "effective_until": "2026-07-01",
            },
            ACCOUNTS,
        )
        validate_error(resp, ApiErrorId.ERR_CONSIGNMENT_WINDOW_OVERLAP)

    def test_consignment_window_adjacency_allowed(self, api):
        """PRD §3.8: "while mere adjacency — a new window starting exactly when the existing one ends — is allowed; an overlap is rejected with `ERR_CONSIGNMENT_WINDOW_OVERLAP`."
        PRD §3.8: "a half-open window from `effective_from` inclusive to `effective_until` exclusive, the latter strictly after the former."

        Design: Difficulty/resource_temporal_overlap/consignment_window_half_open_overlap
        """
        warehouse, product, customer = _base_trio(api)
        make_agreement(
            api, customer_id=customer["id"], product_id=product["id"],
            ceiling_quantity=100, reorder_point=0, contract_unit_price_cents=500,
            replenishment_warehouse_id=warehouse["id"],
            effective_from="2026-05-01", effective_until="2026-06-01",
        )
        resp = api.create_agreement(
            {
                "customer_id": customer["id"],
                "product_id": product["id"],
                "ceiling_quantity": 50,
                "reorder_point": 0,
                "contract_unit_price_cents": 500,
                "replenishment_warehouse_id": warehouse["id"],
                "effective_from": "2026-06-01",
                "effective_until": "2026-07-01",
            },
            ACCOUNTS,
        )
        created = validate_success(resp, 201)
        assert created["id"], (
            "from == existing until is adjacency, not overlap, under half-open semantics"
        )


class TestStandingOrderWindowBuffer:
    def test_standing_order_window_buffer_gap_rejected(self, api):
        """PRD §3.8: "Standing orders for the same customer and product respect a buffer rule against existing `ACTIVE` or `PAUSED` standing orders: the new window must clear every existing window by at least seven days in one direction — beginning no earlier than seven days after the existing window's end, or ending no later than seven days before the existing window's start. A gap of exactly seven days passes; a six-day gap or any overlap is rejected with `ERR_STANDING_ORDER_WINDOW_CONFLICT`."

        Design: Difficulty/resource_temporal_overlap/standing_order_window_buffer_gap
        """
        warehouse, product, customer = _base_trio(api)
        make_standing_order(
            api, customer_id=customer["id"], product_id=product["id"],
            warehouse_id=warehouse["id"], quantity_per_run=2, interval_days=7,
            effective_from="2026-05-01", effective_until="2026-06-01",
        )
        # Existing window ends 2026-06-01 inclusive; 2026-06-05 begins only 4 days later.
        resp = api.create_standing_order(
            {
                "customer_id": customer["id"],
                "product_id": product["id"],
                "warehouse_id": warehouse["id"],
                "quantity_per_run": 2,
                "interval_days": 7,
                "effective_from": "2026-06-05",
                "effective_until": "2026-08-01",
            },
            make_customer_headers(customer["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_STANDING_ORDER_WINDOW_CONFLICT)

    def test_standing_order_window_buffer_exactly_seven_days_passes(self, api):
        """PRD §3.8: "A gap of exactly seven days passes; a six-day gap or any overlap is rejected with `ERR_STANDING_ORDER_WINDOW_CONFLICT`."

        Design: Difficulty/resource_temporal_overlap/standing_order_window_buffer_gap
        """
        warehouse, product, customer = _base_trio(api)
        make_standing_order(
            api, customer_id=customer["id"], product_id=product["id"],
            warehouse_id=warehouse["id"], quantity_per_run=2, interval_days=7,
            effective_from="2026-05-01", effective_until="2026-06-01",
        )
        # 2026-06-08 begins exactly seven days after the existing 2026-06-01 end.
        resp = api.create_standing_order(
            {
                "customer_id": customer["id"],
                "product_id": product["id"],
                "warehouse_id": warehouse["id"],
                "quantity_per_run": 2,
                "interval_days": 7,
                "effective_from": "2026-06-08",
                "effective_until": "2026-08-01",
            },
            make_customer_headers(customer["id"]),
        )
        created = validate_success(resp, 201)
        assert created["id"], "a gap of exactly 7 days satisfies the >= 7 buffer"


class TestStandingOrderGeneration:
    def test_standing_order_catchup_generates_three_runs(self, api):
        """PRD §3.8: "Each time the clock is set, the system processes `ACTIVE` standing orders in ascending `created_at` order (ties broken by their per-system creation counter, ascending), and for each, while its `next_run_date` is on or before both the current logical date and its `effective_until`, it generates one order — for its customer, product, and warehouse, at its `quantity_per_run`, with fulfillment mode `ANY`, `STANDARD` shipping, and `requested_ship_date` equal to that run date — and auto-submits it."
        PRD §3.8: "otherwise `generated_order_count` grows by one and `next_run_date` advances by `interval_days`."
        PRD §3.8: "Catch-up after a long clock jump generates at most one order per due run date, in date order."

        Design: Corner/calculations/standing_order_catchup_generates_three_runs
        """
        warehouse = make_warehouse(api)
        zone = make_zone(api, warehouse["id"], zone_class="AMBIENT", capacity_units=500)
        product = make_product(api, sku="CS-500", name="Consigned Stain", unit_price_cents=500)
        customer = make_customer(api, name="Lab Kappa")
        make_lot(api, product["id"], warehouse["id"], zone["id"], quantity_received=100)
        standing = make_standing_order(
            api, customer_id=customer["id"], product_id=product["id"],
            warehouse_id=warehouse["id"], quantity_per_run=2, interval_days=7,
            effective_from="2026-05-03", effective_until="2026-12-31",
        )

        resp = api.set_clock({"to_iso8601": "2026-05-20T00:00:00Z"}, OPS)
        sweep = validate_success(resp, 200)
        assert sweep["orders_generated"] == 3, (
            "due runs 2026-05-03, 05-10, 05-17 fire; 05-24 is after the clock"
        )
        assert sweep["standing_orders_run"] == 1

        after = validate_success(
            api.get_standing_order(standing["id"], OPS), 200
        )
        assert after["next_run_date"] == "2026-05-24"
        assert after["generated_order_count"] == 3

        orders, meta = validate_paginated(
            api.list_orders(OPS, params={"customer_id": customer["id"]})
        )
        assert meta["total_count"] == 3
        assert orders[0]["status"] == "ALLOCATED", (
            "each generated order auto-submits against the stocked lot"
        )


class TestConsignmentBilling:
    def test_consignment_charge_rounds_half_up_per_record(self, api):
        """PRD §3.8: "A passing record snapshots the agreement's `contract_unit_price_cents` into its own `unit_price_cents`, computes `charge_cents` as the quantity times that price times one minus the `discount_pct`, rounded half up per record — never summed and rounded across records — and stamps `recorded_at` from the logical clock, carrying its `agreement_id`. The charge posts to the customer's `outstanding_balance_cents` and the agreement's `consumed_quantity` grows by the quantity."

        Design: Corner/calculations/consignment_charge_rounds_half_up_per_record
        """
        warehouse, product, customer = _base_trio(api)
        agreement = make_agreement(
            api, customer_id=customer["id"], product_id=product["id"],
            ceiling_quantity=100, reorder_point=0, contract_unit_price_cents=105,
            discount_pct=0.10, replenishment_warehouse_id=warehouse["id"],
            initial_stocked_quantity=100,
            effective_from="2026-05-01", effective_until="2027-05-01",
        )
        resp = api.record_consumption(agreement["id"], {"quantity": 1}, ACCOUNTS)
        record = validate_success(resp, 201)
        assert record["unit_price_cents"] == 105, "the contract price is snapshotted"
        assert record["charge_cents"] == 95, (
            f"round_half_up(1 * 105 * 0.9) = round_half_up(94.5) = 95: {record}"
        )
        assert get_customer(api, customer["id"])["outstanding_balance_cents"] == 95

    def test_consumption_record_has_no_version_or_updated_at(self, api):
        """PRD §2.4: "One resource is deliberately lighter: a `ConsumptionRecord` is an immutable billing fact and carries only `id` and `created_at` — `updated_at` and `version` are absent from it entirely."

        Design: Corner/entities/consumption_record_has_no_version_or_updated_at
        """
        warehouse, product, customer = _base_trio(api)
        agreement = make_agreement(
            api, customer_id=customer["id"], product_id=product["id"],
            ceiling_quantity=100, reorder_point=0, contract_unit_price_cents=500,
            replenishment_warehouse_id=warehouse["id"], initial_stocked_quantity=100,
            effective_from="2026-05-01", effective_until="2027-05-01",
        )
        resp = api.record_consumption(agreement["id"], {"quantity": 3}, ACCOUNTS)
        record = validate_success(resp, 201)
        fetched = validate_success(api.get_consumption_record(record["id"], OPS), 200)
        assert_consumption_record(fetched)
        assert fetched["quantity"] == 3
        assert fetched["charge_cents"] == 1500


class TestConsignmentReplenishment:
    def test_consignment_replenishment_fires_at_reorder_point(self, api):
        """PRD §3.8: "Replenishment is then evaluated: when the on-hand at customer — stocked minus consumed — falls to the `reorder_point` or below, with equality triggering, and the agreement is `ACTIVE`, the system creates a replenishment order for the agreement's customer at its `replenishment_warehouse_id` with quantity equal to the ceiling minus the current on-hand, fulfillment mode `ANY`, `STANDARD` shipping, and `requested_ship_date` set to the day after the current logical date, and auto-submits it in the standing-order style."

        Design: Corner/calculations/consignment_replenishment_fires_at_reorder_point
        """
        warehouse = make_warehouse(api)
        zone = make_zone(api, warehouse["id"], zone_class="AMBIENT", capacity_units=500)
        product = make_product(api, sku="CS-500", name="Consigned Stain", unit_price_cents=500)
        customer = make_customer(api, name="Lab Kappa")
        make_lot(api, product["id"], warehouse["id"], zone["id"], quantity_received=100)
        agreement = make_agreement(
            api, customer_id=customer["id"], product_id=product["id"],
            ceiling_quantity=100, reorder_point=20, contract_unit_price_cents=500,
            replenishment_warehouse_id=warehouse["id"], initial_stocked_quantity=30,
            effective_from="2026-05-01", effective_until="2027-05-01",
        )
        # on-hand 30 - 15 = 15 <= reorder_point 20 -> replenishment fires.
        resp = api.record_consumption(agreement["id"], {"quantity": 15}, ACCOUNTS)
        record = validate_success(resp, 201)
        assert record["charge_cents"] == 7500, "15 x 500 with no discount"

        orders, meta = validate_paginated(
            api.list_orders(OPS, params={"customer_id": customer["id"]})
        )
        assert meta["total_count"] == 1, "exactly one replenishment order is generated"
        replenishment = orders[0]
        assert replenishment["status"] == "ALLOCATED", (
            "the replenishment order auto-submits against stocked inventory"
        )
        lines = get_order_lines(api, replenishment["id"])
        assert len(lines) == 1
        assert lines[0]["quantity"] == 85, (
            "top-up quantity equals ceiling 100 minus current on-hand 15"
        )
        after = validate_success(api.get_agreement(agreement["id"], ACCOUNTS), 200)
        assert after["consumed_quantity"] == 15


class TestStandingOrderLifecycleGuard:
    def test_standing_order_resume_from_active_rejected(self, api):
        """PRD §3.8: "The customer may also steer the subscription directly: pausing from `ACTIVE` (`ERR_STANDING_ORDER_NOT_ACTIVE`), resuming from `PAUSED` (`ERR_STANDING_ORDER_NOT_PAUSED`), and cancelling from either `ACTIVE` or `PAUSED` into the terminal `CANCELLED` (`ERR_STANDING_ORDER_TERMINAL` once cancelled)."

        Design: Corner/state_machines/standing_order_resume_from_active_rejected
        """
        warehouse, product, customer = _base_trio(api)
        standing = make_standing_order(
            api, customer_id=customer["id"], product_id=product["id"],
            warehouse_id=warehouse["id"], quantity_per_run=2, interval_days=7,
            effective_from="2026-05-01", effective_until="2026-06-01",
        )
        resp = api.resume_standing_order(
            standing["id"], make_customer_headers(customer["id"])
        )
        validate_error(resp, ApiErrorId.ERR_STANDING_ORDER_NOT_PAUSED)
        after = validate_success(api.get_standing_order(standing["id"], OPS), 200)
        assert after["status"] == "ACTIVE"
