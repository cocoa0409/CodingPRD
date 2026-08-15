"""Plant master data: plant, product, store defaults and read surface (PRD §3.1)."""
from test_helpers import (
    NON_EXISTENT_UUID,
    TEST_USERS,
    assert_plant,
    assert_product,
    assert_store,
    create_plant,
    create_plant_payload,
    create_product_payload,
    create_store_payload,
    validate_error,
    validate_success,
)


class TestPlantCreation:
    def test_plant_creation_defaults(self, api):
        """PRD §3.1: "Creating a plant requires a `name` plus the two
        cost-pass-through baselines, `baseline_flour_index` and
        `baseline_butter_index`, which anchor all later surcharge deltas; the
        new plant's `day_index` starts at 0."
        PRD §2.5: "`version` (integer): a system-managed integer that
        increments by 1 on every mutation of the resource."

        Design: Corner/entities/plant_creation_defaults
        """
        resp = api.create_plant(
            create_plant_payload(name="Plant One", baseline_flour_index=400,
                                 baseline_butter_index=600),
            TEST_USERS["admin_headers"],
        )
        plant = validate_success(resp, expected_status=201)
        assert_plant(plant)
        assert plant["day_index"] == 0, (
            f"new plant day_index must start at 0, got {plant['day_index']}"
        )
        assert plant["version"] == 1, (
            f"new plant version must begin at 1, got {plant['version']}"
        )
        assert plant["name"] == "Plant One"


class TestProductCreation:
    def test_product_computed_surcharge_defaults_to_zero(self, api):
        """PRD §3.1: "A product's `current_surcharge_cents` starts at 0 and is
        thereafter maintained only by the pass-through machinery of §3.9."
        PRD §2.5: "`version` (integer): a system-managed integer that
        increments by 1 on every mutation of the resource."

        Design: Corner/entities/product_computed_surcharge_defaults_to_zero
        """
        plant = create_plant()
        resp = api.create_product(
            create_product_payload(plant["id"], sku="SKU-A", name="White Pan 500"),
            TEST_USERS["admin_headers"],
        )
        product = validate_success(resp, expected_status=201)
        assert_product(product)
        assert product["current_surcharge_cents"] == 0, (
            f"current_surcharge_cents must start at 0, got {product['current_surcharge_cents']}"
        )
        assert product["version"] == 1, (
            f"new product version must begin at 1, got {product['version']}"
        )

    def test_product_get_not_found_returns_404(self, api):
        """PRD §2.9 step 3: "Existence — every identifier named in the path
        and body (plant, product, store, driver, line, order, plan, batch,
        cycle, route, stop, return, sale, index, schedule) exists; failure
        yields `ERR_NOT_FOUND` (HTTP 404)."

        Design: Corner/entities/product_get_not_found_returns_404
        """
        resp = api.get_product(NON_EXISTENT_UUID, TEST_USERS["admin_headers"])
        validate_error(resp, "ERR_NOT_FOUND", expected_status=404)

    def test_product_invalid_enum_rejected(self, api):
        """PRD §3.1: "an `allergen_class` of `NONE`, `SESAME`, `TREE_NUT`, or
        `PEANUT` that drives segregation on the lines."
        PRD §2.9 step 4: "Request shape — required fields are present, enums
        are valid, quantities, prices, and capacities are positive,
        datetimes parse, and `batch_ids` is non-empty where required;
        failure yields `ERR_INVALID_REQUEST` (HTTP 400)."

        Design: Corner/entities/product_invalid_enum_rejected
        """
        plant = create_plant()
        payload = create_product_payload(
            plant["id"], sku="SKU-X", name="Rye", allergen_class="GLUTEN"
        )
        resp = api.create_product(payload, TEST_USERS["admin_headers"])
        validate_error(resp, "ERR_INVALID_REQUEST", expected_status=400)


class TestStoreCreation:
    def test_store_default_tier_applied(self, api):
        """PRD §3.1: "an optional `stale_credit_tier` of `STANDARD` or
        `LIMITED` that defaults to `STANDARD`." And: "A new store's `status`
        is `ACTIVE` and its `credit_balance_cents` is 0." And: "`stale_ratio`
        is the ratio of `lifetime_stale_units` to `lifetime_delivered_units`,
        with the denominator treated as at least 1 so a store with no
        deliveries has ratio 0."

        Design: Corner/entities/store_default_tier_applied
        """
        plant = create_plant()
        payload = create_store_payload(plant["id"], name="Store S")
        payload.pop("stale_credit_tier")  # exercise the optional-field default
        resp = api.create_store(payload, TEST_USERS["admin_headers"])
        store = validate_success(resp, expected_status=201)
        assert_store(store)
        assert store["stale_credit_tier"] == "STANDARD", (
            f"omitting stale_credit_tier must apply STANDARD, got {store['stale_credit_tier']}"
        )
        assert store["credit_balance_cents"] == 0
        assert store["stale_ratio"] == 0
        assert store["status"] == "ACTIVE"


class TestStoreOrderCreate:
    def test_store_order_missing_required_lines(self, api):
        """PRD §3.2: "A `Planner` — or a `PlantAdmin` acting in that capacity
        — places a store order by supplying the `store_id`, a `delivery_date`
        in `YYYY-MM-DD` form, and the order `lines`."
        PRD §2.9 step 4: "Request shape — required fields are present, enums
        are valid, quantities, prices, and capacities are positive,
        datetimes parse, and `batch_ids` is non-empty where required;
        failure yields `ERR_INVALID_REQUEST` (HTTP 400)."

        Design: Corner/entities/store_order_missing_required_lines
        """
        plant = create_plant()
        store_resp = api.create_store(
            create_store_payload(plant["id"]), TEST_USERS["admin_headers"]
        )
        store = validate_success(store_resp, expected_status=201)
        resp = api.create_store_order(
            {"store_id": store["id"], "delivery_date": "2026-08-10"},
            TEST_USERS["planner_headers"],
        )
        validate_error(resp, "ERR_INVALID_REQUEST", expected_status=400)
