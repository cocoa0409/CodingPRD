"""Order drafting, draft edits with OCC, and fulfillment from-state guards."""
from test_helpers import (
    ADMIN,
    PLANNER,
    WAREHOUSE,
    ApiErrorId,
    create_location,
    create_operator,
    create_order,
    create_product,
    create_route,
    get_order,
    make_operator_manager_headers,
    setup_selling_location,
    submit_order,
    walk_order_to_delivered,
    validate_error,
    validate_success,
)

BOGUS_ORDER = "77777777-7777-7777-7777-777777777777"
BOGUS_OPERATOR = "11111111-1111-1111-1111-111111111111"


class TestDraftCreation:
    def test_order_create_computed_input_ignored(self, api):
        """PRD §3.5: "Creation is deliberately lenient: it performs existence
        checks only"
        PRD §3.5: "At creation the order copies `operator_id` and `route_id`
        from its location as a snapshot, records `source` as `MANUAL`"
        PRD §3.5: "The monetary fields begin in their zero-state:
        `order_total_cents`, `promo_discount_cents`, `amount_due_cents`, and
        `credit_applied_cents` at 0"

        Design: Corner/entities/order_create_computed_input_ignored
        """
        op = create_operator("Op Comp")
        route = create_route("R-CMP", ("MON",), 50, 0)
        loc = create_location(op["id"], route["id"], "L-Comp")
        resp = api.create_order(
            {
                "location_id": loc["id"],
                "requested_delivery_date": "2026-08-03",
                "lines": [],
                # Client-supplied computed fields must not take effect.
                "order_total_cents": 99999,
                "promo_discount_cents": 555,
            },
            make_operator_manager_headers(op["id"]),
        )
        order = validate_success(resp, 201)
        assert order["order_total_cents"] == 0
        assert order["promo_discount_cents"] == 0
        assert order["source"] == "MANUAL"
        assert order["route_id"] == route["id"], (
            "route_id is copied from the location at creation"
        )
        assert order["operator_id"] == op["id"]

    def test_order_create_zero_quantity_rejected(self, api):
        """PRD §2.8: "Required fields must be present, enum members valid,
        types correct, and integer quantities greater than zero, else
        `ERR_INVALID_REQUEST` — or `ERR_INVALID_QUANTITY` for a non-positive
        `quantity_cases`, `quantity_units`, or parts-row `quantity`
        (HTTP 400)."

        Design: Corner/validations/order_create_zero_quantity_rejected
        """
        op = create_operator("Op Qty")
        route = create_route("R-QTY", ("MON",), 50, 0)
        product = create_product(sku="QTY-1", name="Qty item")
        loc = create_location(op["id"], route["id"], "L-Qty")
        err = api.create_order(
            {
                "location_id": loc["id"],
                "requested_delivery_date": "2026-08-03",
                "lines": [{"product_id": product["id"], "quantity_cases": 0}],
            },
            make_operator_manager_headers(op["id"]),
        )
        validate_error(err, ApiErrorId.ERR_INVALID_QUANTITY)


class TestDraftEditOcc:
    def test_patch_draft_order_updates_lines_and_bumps_version(self, api):
        """PRD §3.5: "While an order remains `DRAFT`, an `OperatorManager` may
        edit its `lines` or `requested_delivery_date`" and "on success
        `total_cases` is recomputed (it is recomputed on every line mutation)
        and the order's `version` increments."
        PRD §2.4: "`version` (integer): a system-managed integer that
        increments by exactly one on every modification"

        Design: Corner/endpoints/patch_draft_order_updates_lines_and_bumps_version
        """
        world = setup_selling_location(
            products_spec=[{"sku": "PTC-1", "name": "Patch item"}],
            activate=False,
        )
        product = world["products"][0]
        order = create_order(
            world, [{"product_id": product["id"], "quantity_cases": 1}],
        )
        version_before = order["version"]

        resp = api.patch_order(
            order["id"],
            {
                "expected_order_version": version_before,
                "lines": [{"product_id": product["id"], "quantity_cases": 3}],
            },
            world["om_headers"],
        )
        patched = validate_success(resp, 200)
        assert patched["total_cases"] == 3
        assert patched["version"] == version_before + 1
        assert patched["fulfillment_status"] == "DRAFT"

    def test_order_patch_stale_version(self, api):
        """PRD §2.7: "Editing a draft order's lines or delivery date requires
        the request to carry `expected_order_version`, the client's last
        observed `version` of the order. If the order's current `version` has
        advanced beyond the supplied value — for example because a
        telemetry-driven suggestion refresh already rewrote the lines the
        client based its edit on — the request is rejected with
        `ERR_STALE_VERSION` (HTTP 412)."

        Design: Corner/cross_cutting_layers/order_patch_stale_version
        """
        world = setup_selling_location(
            products_spec=[{"sku": "OC2-1", "name": "Occ2 item"}],
            activate=False,
        )
        product = world["products"][0]
        order = create_order(
            world, [{"product_id": product["id"], "quantity_cases": 1}],
        )
        stale_version = order["version"]

        first = api.patch_order(
            order["id"],
            {
                "expected_order_version": stale_version,
                "lines": [{"product_id": product["id"], "quantity_cases": 2}],
            },
            world["om_headers"],
        )
        validate_success(first, 200)

        # Replay of the consumed version is stale.
        err = api.patch_order(
            order["id"],
            {
                "expected_order_version": stale_version,
                "lines": [{"product_id": product["id"], "quantity_cases": 5}],
            },
            world["om_headers"],
        )
        validate_error(err, ApiErrorId.ERR_STALE_VERSION)
        assert get_order(order["id"])["total_cases"] == 2, (
            "the stale patch must not apply"
        )


class TestFromStateGuards:
    def test_order_submit_twice_rejected(self, api):
        """PRD §3.5: "the from-state (the order must be `DRAFT`, else
        `ERR_ORDER_NOT_DRAFT`)"

        Design: Corner/state_machines/order_submit_twice_rejected
        """
        world = setup_selling_location(
            products_spec=[{"sku": "TWC-1", "name": "Twice item"}],
            route_code="R-TWC",
        )
        order = create_order(
            world,
            [{"product_id": world["products"][0]["id"], "quantity_cases": 1}],
        )
        submit_order(world, order["id"])

        err = api.submit_order(order["id"], world["om_headers"])
        validate_error(err, ApiErrorId.ERR_ORDER_NOT_DRAFT)

        reread = get_order(order["id"])
        assert reread["fulfillment_status"] == "SUBMITTED"
        assert reread["order_total_cents"] == 1000, (
            "the rejected submit must not recompute pricing"
        )

    def test_order_confirm_from_draft_rejected(self, api):
        """PRD §3.6: "The order must be `SUBMITTED` (`ERR_ORDER_NOT_SUBMITTED`)"

        Design: Corner/state_machines/order_confirm_from_draft_rejected
        """
        world = setup_selling_location(
            products_spec=[{"sku": "CFM-1", "name": "Cfm item"}],
            route_code="R-CFM",
            activate=False,
        )
        order = create_order(world, [])
        err = api.confirm_order(order["id"], PLANNER)
        validate_error(err, ApiErrorId.ERR_ORDER_NOT_SUBMITTED)
        assert get_order(order["id"])["fulfillment_status"] == "DRAFT"

    def test_order_mark_delivered_from_submitted_rejected(self, api):
        """PRD §3.6: "Delivery — `CONFIRMED` → `DELIVERED` by `WarehouseOps`,
        guarded by `ERR_ORDER_NOT_CONFIRMED`"

        Design: Corner/state_machines/order_mark_delivered_from_submitted_rejected
        """
        world = setup_selling_location(
            products_spec=[{"sku": "DLV-1", "name": "Dlv item"}],
            route_code="R-DLV",
        )
        order = create_order(
            world,
            [{"product_id": world["products"][0]["id"], "quantity_cases": 1}],
        )
        submit_order(world, order["id"])

        err = api.mark_order_delivered(order["id"], WAREHOUSE)
        validate_error(err, ApiErrorId.ERR_ORDER_NOT_CONFIRMED)

        reread = get_order(order["id"])
        assert reread["fulfillment_status"] == "SUBMITTED"
        assert reread["settlement_status"] == "UNINVOICED"
        assert reread["amount_due_cents"] == 0

    def test_order_cancel_after_delivered_rejected(self, api):
        """PRD §3.6: "Cancellation by an `OperatorManager` is admitted from
        `DRAFT`, `SUBMITTED`, or `CONFIRMED`; from `DELIVERED` or `CANCELLED`
        it rejects with `ERR_INVALID_STATE_TRANSITION`."

        Design: Corner/state_machines/order_cancel_after_delivered_rejected
        """
        world = setup_selling_location(
            products_spec=[{"sku": "CXL-1", "name": "Cxl item"}],
            route_code="R-CXL",
        )
        order = walk_order_to_delivered(
            world,
            [{"product_id": world["products"][0]["id"], "quantity_cases": 1}],
        )
        assert order["settlement_status"] == "OPEN"

        err = api.cancel_order(order["id"], world["om_headers"])
        validate_error(err, ApiErrorId.ERR_INVALID_STATE_TRANSITION)

        reread = get_order(order["id"])
        assert reread["fulfillment_status"] == "DELIVERED"
        assert reread["settlement_status"] == "OPEN"
        assert reread["amount_due_cents"] == 1000

    def test_submit_empty_order_rejected(self, api):
        """PRD §3.5: "then the non-empty constraint (at least one line, else
        `ERR_EMPTY_ORDER`)"

        Design: Corner/errors/submit_empty_order_rejected
        """
        world = setup_selling_location(
            products_spec=[{"sku": "EMP-1", "name": "Empt item"}],
            route_code="R-EMPT",
            min_order_cents=0,
        )
        order = create_order(world, [])
        err = api.submit_order(order["id"], world["om_headers"])
        validate_error(err, ApiErrorId.ERR_EMPTY_ORDER)

    def test_submit_nonexistent_order_returns_not_found(self, api):
        """PRD §2.8: "Identifiers in a parameterized path are validated
        sequentially from left to right; the first identifier that does not
        resolve rejects the request with its matching not-found error"
        PRD §2.1: "The `OperatorManager` ownership comparison is evaluated only
        after the target is known to exist, per the cascade in §2.8."

        Design: Corner/validations/submit_nonexistent_order_returns_not_found
        """
        err = api.submit_order(
            BOGUS_ORDER, make_operator_manager_headers(BOGUS_OPERATOR),
        )
        validate_error(err, ApiErrorId.ERR_ORDER_NOT_FOUND)


class TestSubmitReviseCycle:
    def _cycle_world(self, api):
        world = setup_selling_location(
            products_spec=[{"sku": "CYC-1", "name": "Cycle item",
                            "category": "BEVERAGE"}],
            slots_spec=[{"slot_code": "A1", "product_index": 0,
                         "par_level_units": 40, "vend_price_cents": 150}],
            route_code="R-CYC",
        )
        order = create_order(
            world,
            [{"product_id": world["products"][0]["id"], "quantity_cases": 2}],
        )
        submitted = submit_order(world, order["id"])
        assert submitted["order_total_cents"] == 2000
        return world, order

    def test_revise_unpins_pricing(self, api):
        """PRD §3.5: "Revision unpins pricing: `order_total_cents` and
        `promo_discount_cents` reset to 0,
        `provisional_margin_per_vend_cents` resets to null, and the order's
        `version` increments; the next submission reprices from scratch."

        Design: Difficulty/non_linear_state_machine/order_submit_revise_cycle
        """
        world, order = self._cycle_world(api)
        revised = validate_success(
            api.revise_order(order["id"], world["om_headers"]), 200,
        )
        assert revised["fulfillment_status"] == "DRAFT"
        assert revised["order_total_cents"] == 0
        assert revised["promo_discount_cents"] == 0
        assert revised["provisional_margin_per_vend_cents"] is None

    def test_resubmit_reprices_after_edit(self, api):
        """PRD §3.5: "A submitted order can be sent back for revision —
        `SUBMITTED` → `DRAFT` by an `OperatorManager`, with any other
        from-state rejected as `ERR_ORDER_NOT_SUBMITTED`. Revision unpins
        pricing: ... the next submission reprices from scratch."
        PRD §3.5: "`provisional_margin_per_vend_cents` is that retail value
        minus `order_total_cents`, divided by the total vend units, rounded
        half up."

        Design: Difficulty/non_linear_state_machine/order_submit_revise_cycle
        """
        world, order = self._cycle_world(api)
        revised = validate_success(
            api.revise_order(order["id"], world["om_headers"]), 200,
        )
        product = world["products"][0]
        patched = validate_success(
            api.patch_order(
                order["id"],
                {
                    "expected_order_version": revised["version"],
                    "lines": [{"product_id": product["id"], "quantity_cases": 3}],
                },
                world["om_headers"],
            ),
            200,
        )
        resubmitted = validate_success(
            api.submit_order(order["id"], world["om_headers"]), 200,
        )
        assert resubmitted["fulfillment_status"] == "SUBMITTED"
        assert resubmitted["order_total_cents"] == 3000
        # round_half_up((150*10*3 - 3000)/30) == 50
        assert resubmitted["provisional_margin_per_vend_cents"] == 50
