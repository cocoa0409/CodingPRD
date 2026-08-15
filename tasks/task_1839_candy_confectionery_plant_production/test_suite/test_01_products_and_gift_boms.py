"""Product master data and gift-set bill-of-material rules."""
from test_helpers import (
    NON_EXISTENT_UUID,
    PLANNER,
    ApiErrorId,
    add_gift_component,
    assert_gift_component,
    create_packaging_component,
    create_product,
    create_product_payload,
    create_recipe,
    is_valid_uuid,
    parse_instant,
    set_clock,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestProductSystemFields:
    def test_injected_id_and_version_are_ignored(self, api):
        """PRD §2.4: "`id` (string): a server-minted UUID, with no type prefix."
        PRD §2.4: "`version` (integer): a system-managed integer that increments
        by one on every modification of the resource."

        Design: Corner/entities/product_system_fields_input_ignored
        """
        set_clock("2026-08-15T10:00:00Z")
        component = create_packaging_component(qty_on_hand=1000)
        payload = create_product_payload(
            component["id"], sku_code="TRUFFLE-24", name="Truffle 24pc",
            product_type="SEASONAL", brand="OWN", base_price_cents=1000,
            unit_weight_grams=240, shelf_life_days=180)
        payload["id"] = NON_EXISTENT_UUID
        payload["version"] = 99

        data = validate_success(api.create_product(payload, PLANNER), 201)
        assert is_valid_uuid(data["id"]), "server must mint the id"
        assert data["id"] != NON_EXISTENT_UUID, "client-injected id must be ignored"
        assert isinstance(data["version"], int)
        assert data["version"] != 99, "client-injected version must be ignored"

    def test_created_at_stamped_from_logical_clock(self, api):
        """PRD §2.5: "Every time-dependent rule in the system reads a server-side
        logical clock, never the host's wall clock."
        PRD §2.4: "`created_at` (string): an ISO 8601 UTC timestamp with three
        fractional digits, recording when the resource was created."

        Design: Corner/entities/product_system_fields_input_ignored
        """
        set_clock("2026-08-15T10:00:00Z")
        component = create_packaging_component(qty_on_hand=1000)
        payload = create_product_payload(
            component["id"], sku_code="TRUFFLE-24", name="Truffle 24pc",
            product_type="SEASONAL", brand="OWN", base_price_cents=1000,
            unit_weight_grams=240, shelf_life_days=180)

        data = validate_success(api.create_product(payload, PLANNER), 201)
        assert parse_instant(data["created_at"]) == parse_instant(
            "2026-08-15T10:00:00Z"), "created_at must be stamped from the logical clock"


class TestProductRequiredFields:
    def test_missing_sku_code_rejected(self, api):
        """PRD §3.1: "Each product carries a `sku_code` — a unique sellable-unit
        code such as TRUFFLE-24, required and unique across all products"
        PRD §2.7: "the payload must be well-formed: required fields present, enum
        values legal, and cross-field shape rules satisfied (`ERR_INVALID_REQUEST`,
        HTTP 400)."

        Design: Corner/entities/product_missing_required_sku_rejected
        """
        component = create_packaging_component(qty_on_hand=1000)
        payload = {
            "name": "No SKU", "product_type": "STANDARD", "brand": "OWN",
            "base_price_cents": 100, "unit_weight_grams": 10,
            "shelf_life_days": 90, "packaging_component_id": component["id"],
        }
        validate_error(api.create_product(payload, PLANNER),
                       ApiErrorId.ERR_INVALID_REQUEST)

        products, meta = validate_paginated(api.list_products(PLANNER))
        assert products == [], "nothing may be persisted by a rejected create"
        assert meta["total_count"] == 0


class TestProductFetch:
    def test_get_missing_product_returns_404(self, api):
        """PRD §2.6: "the request is rejected with `ERR_NOT_FOUND` (HTTP 404) at
        the first identifier that does not correspond to an existing resource"

        Design: Corner/entities/product_get_not_found_returns_404
        """
        validate_error(api.get_product(NON_EXISTENT_UUID, PLANNER),
                       ApiErrorId.ERR_NOT_FOUND)


class TestGiftGraphAcyclicity:
    def test_transitive_back_edge_and_self_loop_rejected(self, api):
        """PRD §3.1: "the resulting graph must stay acyclic: any new edge that
        would close a cycle, including the degenerate self-loop where
        `gift_product_id` equals `component_product_id`, is rejected with
        `ERR_GIFT_CYCLE`."

        Design: Corner/entities/gift_component_cycle_rejected
        """
        component = create_packaging_component(qty_on_hand=1000)
        g1 = create_product(component["id"], sku_code="G1", name="Gift 1",
                            product_type="GIFT_SET", base_price_cents=5000,
                            unit_weight_grams=500, shelf_life_days=120)
        g2 = create_product(component["id"], sku_code="G2", name="Gift 2",
                            product_type="GIFT_SET", base_price_cents=3000,
                            unit_weight_grams=300, shelf_life_days=120)
        cx = create_product(component["id"], sku_code="CX", name="Component X",
                            product_type="STANDARD", base_price_cents=300,
                            unit_weight_grams=50, shelf_life_days=200)
        add_gift_component(g1["id"], cx["id"], 1)
        add_gift_component(g1["id"], g2["id"], 1)

        # Back-edge: G1 already contains G2, so adding G1 into G2 closes a cycle.
        resp_cycle = api.create_gift_component(
            {"gift_product_id": g2["id"], "component_product_id": g1["id"],
             "qty_per_set": 1}, PLANNER)
        validate_error(resp_cycle, ApiErrorId.ERR_GIFT_CYCLE)

        # Self-loop: G1 containing itself.
        resp_self = api.create_gift_component(
            {"gift_product_id": g1["id"], "component_product_id": g1["id"],
             "qty_per_set": 1}, PLANNER)
        validate_error(resp_self, ApiErrorId.ERR_GIFT_CYCLE)

        rows, _ = validate_paginated(api.list_product_gift_components(g2["id"], PLANNER))
        for row in rows:
            assert not (row["gift_product_id"] == g2["id"]
                        and row["component_product_id"] == g1["id"]), (
                            "the rejected back-edge must not be persisted")


class TestGiftComponentImmutability:
    def test_gift_component_carries_only_id_and_created_at(self, api):
        """PRD §2.4: "A gift-component row is immutable after creation — the API
        offers no update endpoint for it — and therefore carries only `id` and
        `created_at`; both `updated_at` and `version` are absent from that
        resource."

        Design: Corner/entities/gift_component_immutable_no_version
        """
        component = create_packaging_component(qty_on_hand=1000)
        gs = create_product(component["id"], sku_code="GS", name="Gift Set",
                            product_type="GIFT_SET", base_price_cents=5000,
                            unit_weight_grams=700, shelf_life_days=120)
        cx = create_product(component["id"], sku_code="CX", name="Component X",
                            product_type="STANDARD", base_price_cents=300,
                            unit_weight_grams=50, shelf_life_days=200)

        data = validate_success(api.create_gift_component(
            {"gift_product_id": gs["id"], "component_product_id": cx["id"],
             "qty_per_set": 2}, PLANNER), 201)
        assert_gift_component(data)

        rows, _ = validate_paginated(api.list_product_gift_components(gs["id"], PLANNER))
        match = [r for r in rows if r["id"] == data["id"]]
        assert len(match) == 1
        assert match[0]["qty_per_set"] == 2


class TestGiftAllergenDeclaration:
    def test_undeclared_allergen_rejected(self, api):
        """PRD §3.1: "the union of allergens across the component product's
        recipes must be a subset of the union of allergens across the gift
        product's recipes, otherwise the row is rejected with
        `ERR_UNDECLARED_ALLERGEN`."

        Design: Corner/validations/gift_component_undeclared_allergen_rejected
        """
        component = create_packaging_component(qty_on_hand=1000)
        cp = create_product(component["id"], sku_code="CP", name="Peanut Cup",
                            product_type="STANDARD", base_price_cents=300,
                            unit_weight_grams=50, shelf_life_days=200)
        gf = create_product(component["id"], sku_code="GF", name="Milk Gift",
                            product_type="GIFT_SET", base_price_cents=5000,
                            unit_weight_grams=700, shelf_life_days=120)
        create_recipe(cp["id"], name="Peanut mass", shape_code="CUP",
                      allergens=["PEANUT"])
        create_recipe(gf["id"], name="GF assembly", shape_code="BAR",
                      allergens=["MILK"], standard_yield_pct=1.0)

        resp = api.create_gift_component(
            {"gift_product_id": gf["id"], "component_product_id": cp["id"],
             "qty_per_set": 2}, PLANNER)
        validate_error(resp, ApiErrorId.ERR_UNDECLARED_ALLERGEN)

        rows, _ = validate_paginated(api.list_product_gift_components(gf["id"], PLANNER))
        assert rows == [], "the rejected bill-of-material row must not be persisted"
