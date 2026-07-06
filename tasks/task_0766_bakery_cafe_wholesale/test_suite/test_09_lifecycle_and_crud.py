"""Product CRUD, defaults, computed fields, invalid transitions, and FK existence."""
from test_helpers import (
    validate_success, validate_error, validate_paginated, get_success_data,
    ApiErrorId, NON_EXISTENT_UUID, setup_committed_line, make_product, make_oven,
    make_bake_lot, make_account, make_standing_order, make_bake_plan, add_line,
    commit_plan, TEST_USERS,
)

MANAGER = TEST_USERS["manager_headers"]
CASHIER = TEST_USERS["cashier_headers"]


class TestProductCrud:
    def test_create_returns_201_and_active_status(self, api):
        """PRD 3.1: "Every product begins with status equal to ACTIVE." PRD 4: "Operations
        that create a new stand-alone resource or add a new resource to a collection return
        201 Created."

        Design: Corner/entities/product_create_returns_201_with_active_status
        """
        product = validate_success(api.create_product({
            "sku": "C-1", "name": "Rustic", "category": "BREAD",
            "base_price_cents": 500, "shelf_life_hours": 24}, MANAGER), expected_status=201)
        assert product["status"] == "ACTIVE", product
        assert product["base_price_cents"] == 500, product

    def test_get_unknown_product_returns_not_found(self, api):
        """PRD 2.8: "the first identifier in the path that does not resolve produces the
        corresponding not-found error (ERR_ROUTE_NOT_FOUND, ERR_BAKE_PLAN_NOT_FOUND, and so
        on)."

        Design: Corner/entities/get_product_not_found_returns_404
        """
        validate_error(api.get_product(NON_EXISTENT_UUID, MANAGER),
                       ApiErrorId.ERR_PRODUCT_NOT_FOUND.value)

    def test_create_missing_required_field_is_rejected(self, api):
        """PRD 2.8: "a body that is absent, missing a required field, or carrying a wrong
        type or an invalid enum value is rejected with ERR_INVALID_REQUEST."

        Design: Corner/entities/product_create_missing_required_field_returns_invalid_request
        """
        validate_error(api.create_product({
            "sku": "C-2", "name": "NoPrice", "category": "BREAD",
            "shelf_life_hours": 24}, MANAGER), ApiErrorId.ERR_INVALID_REQUEST.value)

    def test_defaults_empty_allergens_and_not_custom(self, api):
        """PRD 3.1: "A product may declare an allergens array — each entry one of GLUTEN,
        DAIRY, EGG, NUT, SOY, or SESAME, defaulting to empty — and an is_custom boolean,
        defaulting to false".

        Design: Corner/entities/product_default_status_and_empty_allergens
        """
        product = validate_success(api.create_product({
            "sku": "C-3", "name": "Plain", "category": "BREAD",
            "base_price_cents": 300, "shelf_life_hours": 12}, MANAGER), expected_status=201)
        assert product["allergens"] == [], product
        assert product["is_custom"] is False, product

    def test_invalid_category_enum_is_rejected(self, api):
        """PRD 3.1: "a category that is one of BREAD, PASTRY, CAKE, SANDWICH, or OTHER". PRD
        2.8: "carrying a wrong type or an invalid enum value is rejected with
        ERR_INVALID_REQUEST."

        Design: Corner/entities/product_invalid_category_enum_returns_invalid_request
        """
        validate_error(api.create_product({
            "sku": "C-4", "name": "Weird", "category": "FLARP",
            "base_price_cents": 300, "shelf_life_hours": 12}, MANAGER),
            ApiErrorId.ERR_INVALID_REQUEST.value)

    def test_products_list_returns_pagination_envelope(self, api):
        """PRD 2.3: "Every list response includes limit, offset, total_count, and has_more
        in the meta object of the envelope."

        Design: Corner/entities/products_list_returns_pagination_envelope
        """
        make_product(api, sku="C-6", name="Listed")
        data, meta = validate_paginated(api.list_products(MANAGER, params={"limit": 1, "offset": 0}))
        assert meta["total_count"] >= 1, meta
        assert "has_more" in meta, meta


class TestBakeLotComputedField:
    def test_best_by_is_produced_at_plus_shelf_life(self, api):
        """PRD 3.3: "On creation the lot's best_by is computed as produced_at advanced by
        the product's shelf_life_hours".

        Design: Corner/entities/bake_lot_best_by_is_computed_from_shelf_life
        """
        ctx = setup_committed_line(api, shelf_life_hours=12, par_qty=20,
                                   production_date="2026-06-20T00:00:00Z")
        oven = make_oven(api)
        lot = make_bake_lot(api, ctx["line"]["id"], oven["id"], baked_qty=10,
                            produced_at="2026-06-20T06:00:00Z",
                            slot_start="2026-06-20T02:00:00Z", slot_end="2026-06-20T03:00:00Z")
        assert lot["best_by"] == "2026-06-20T18:00:00.000Z", lot   # 06:00 + 12h
        assert lot["status"] == "FRESH", lot


class TestInvalidTransitions:
    def test_commit_already_committed_plan_is_rejected(self, api):
        """PRD 2.8: "State legality: the target must be in a state from which the requested
        transition is defined, else ERR_INVALID_STATE". PRD 3.2: "a Manager advances the
        plan from DRAFT to COMMITTED, a transition defined only when the plan is DRAFT".

        Design: Corner/state_machines/commit_already_committed_plan_returns_invalid_state
        """
        ctx = setup_committed_line(api, production_date="2026-06-21T00:00:00Z")
        validate_error(api.commit_bake_plan(ctx["plan"]["id"], MANAGER),
                       ApiErrorId.ERR_INVALID_STATE.value)

    def test_reconcile_draft_plan_is_rejected(self, api):
        """PRD 3.5: "a Manager reconciles a BAKED plan, advancing it to RECONCILED". PRD
        2.8: "the target must be in a state from which the requested transition is defined,
        else ERR_INVALID_STATE".

        Design: Corner/state_machines/reconcile_draft_plan_returns_invalid_state
        """
        product = make_product(api)
        plan = make_bake_plan(api, production_date="2026-06-22T00:00:00Z")
        add_line(api, plan["id"], product["id"], 10)
        validate_error(api.reconcile_bake_plan(plan["id"], MANAGER),
                       ApiErrorId.ERR_INVALID_STATE.value)

    def test_cancel_already_cancelled_standing_order_is_rejected(self, api):
        """PRD 3.6: "Cancelling a standing order — permitted from either ACTIVE or PAUSED —
        sets it to CANCELLED". PRD 2.8: transition must be defined "else ERR_INVALID_STATE".

        Design: Corner/state_machines/cancel_already_cancelled_standing_order_returns_invalid_state
        """
        account = make_account(api)
        product = make_product(api)
        so = make_standing_order(api, account["id"], product["id"])
        validate_success(api.cancel_standing_order(so["id"], MANAGER))
        validate_error(api.cancel_standing_order(so["id"], MANAGER),
                       ApiErrorId.ERR_INVALID_STATE.value)

    def test_suspend_already_suspended_account_is_rejected(self, api):
        """PRD 3.9: "A Manager may suspend an ACTIVE account to SUSPENDED". PRD 2.8: the
        target "must be in a state from which the requested transition is defined, else
        ERR_INVALID_STATE".

        Design: Corner/state_machines/suspend_already_suspended_account_returns_invalid_state
        """
        account = make_account(api)
        validate_success(api.suspend_account(account["id"], MANAGER))
        validate_error(api.suspend_account(account["id"], MANAGER),
                       ApiErrorId.ERR_INVALID_STATE.value)

    def test_expire_fresh_lot_moves_to_expired(self, api):
        """PRD 3.4: "A Baker or Manager may also expire a lot outright, moving it from FRESH
        or MARKED_DOWN to EXPIRED, which removes it from floor stock."

        Design: Corner/state_machines/expire_fresh_lot_transitions_to_expired
        """
        ctx = setup_committed_line(api, par_qty=20, production_date="2026-06-23T00:00:00Z")
        oven = make_oven(api)
        lot = make_bake_lot(api, ctx["line"]["id"], oven["id"], baked_qty=5,
                            produced_at="2026-06-23T06:00:00Z",
                            slot_start="2026-06-23T02:00:00Z", slot_end="2026-06-23T03:00:00Z")
        expired = validate_success(api.expire_bake_lot(lot["id"], MANAGER))
        assert expired["status"] == "EXPIRED", expired


class TestInventoryAndFk:
    def test_retail_sale_exceeding_remaining_is_rejected(self, api):
        """PRD 3.4: "A sale whose quantity exceeds the lot's remaining_qty is refused with
        ERR_INSUFFICIENT_INVENTORY".

        Design: Corner/errors/retail_sale_exceeds_remaining_returns_insufficient_inventory
        """
        ctx = setup_committed_line(api, par_qty=20, production_date="2026-06-29T00:00:00Z")
        oven = make_oven(api)
        lot = make_bake_lot(api, ctx["line"]["id"], oven["id"], baked_qty=5,
                            produced_at="2026-06-29T06:00:00Z",
                            slot_start="2026-06-29T02:00:00Z", slot_end="2026-06-29T03:00:00Z")
        validate_error(api.create_retail_sale({"bake_lot_id": lot["id"], "qty": 6}, CASHIER),
                       ApiErrorId.ERR_INSUFFICIENT_INVENTORY.value)

    def test_create_order_with_unknown_line_returns_not_found(self, api):
        """PRD 2.8: "foreign keys carried in the request body are resolved in their declared
        order, each producing its own resource-specific not-found error: ...
        ERR_BAKE_PLAN_LINE_NOT_FOUND".

        Design: Corner/endpoints/create_order_nonexistent_line_returns_not_found
        """
        product = make_product(api)
        account = make_account(api)
        validate_error(api.create_delivery_order({
            "wholesale_account_id": account["id"], "product_id": product["id"],
            "bake_plan_line_id": NON_EXISTENT_UUID, "delivery_date": "2026-07-02T10:00:00Z",
            "qty": 1}, MANAGER), ApiErrorId.ERR_BAKE_PLAN_LINE_NOT_FOUND.value)
