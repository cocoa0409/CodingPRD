"""Custom kits and assembly jobs: the pinned fee-tier rollup, structural
activation checks, and atomic FEFO component consumption."""
from test_helpers import (
    ApiErrorId,
    get_lot,
    get_success_data,
    kit_component,
    make_customer,
    make_job,
    make_kit,
    make_lot,
    make_product,
    make_warehouse,
    make_zone,
    validate_error,
    validate_success,
)
from test_helpers import TEST_USERS

OPS = TEST_USERS["ops_admin_headers"]
CATALOG = TEST_USERS["catalog_manager_headers"]
CLERK = TEST_USERS["inventory_clerk_headers"]
ACCOUNTS = TEST_USERS["account_manager_headers"]


def _kit_product(api, sku, name, unit_price_cents, **overrides):
    return make_product(
        api, sku=sku, name=name, unit_price_cents=unit_price_cents, **overrides
    )


class TestKitPriceRollup:
    def _setup_rollup_kit(self, api):
        customer = make_customer(api, name="Lab Delta")
        prod_a = _kit_product(api, "KA-01", "Kit Part A", 10000)
        prod_b = _kit_product(api, "KB-01", "Kit Part B", 5000)
        kit = make_kit(
            api,
            customer_id=customer["id"],
            name="Assay Starter Kit",
            components=[kit_component(prod_a["id"], 2), kit_component(prod_b["id"], 3)],
        )
        return kit

    def test_kit_rollup_fee_tier_keyed_on_component_sum_price(self, api):
        """PRD §3.9: "Activation also computes the kit price with a pinned evaluation order that forecloses any circularity: first the component cost is summed as each entry's `quantity_per_kit` times its product's current `unit_price_cents`; then the assembly fee is tiered on that pre-fee component cost — 1500 cents when it falls below 100000 cents, 4000 cents when it reaches 100000 but stays below 500000, and 9000 cents at 500000 or above; finally `kit_price_cents` is the component cost plus the fee."

        Design: Difficulty/combinatorial_formula/kit_rollup_fee_tier_keyed_on_component_sum
        """
        kit = self._setup_rollup_kit(api)
        resp = api.activate_kit(kit["id"], CATALOG)
        activated = validate_success(resp, 200)
        # component_cost = 2*10000 + 3*5000 = 35000 -> tier 1 fee 1500.
        assert activated["kit_price_cents"] == 36500, (
            f"the fee tier keys on the pre-fee component sum 35000: {activated}"
        )

    def test_kit_rollup_fee_tier_keyed_on_component_sum_activation(self, api):
        """PRD §3.9: "Activation also computes the kit price with a pinned evaluation order that forecloses any circularity: first the component cost is summed as each entry's `quantity_per_kit` times its product's current `unit_price_cents`; then the assembly fee is tiered on that pre-fee component cost — 1500 cents when it falls below 100000 cents, 4000 cents when it reaches 100000 but stays below 500000, and 9000 cents at 500000 or above; finally `kit_price_cents` is the component cost plus the fee. The fee tier never sees the fee-inclusive price."
        PRD §3.9: "A kit begins `DRAFT` with `kit_price_cents` null."

        Design: Difficulty/combinatorial_formula/kit_rollup_fee_tier_keyed_on_component_sum
        """
        kit = self._setup_rollup_kit(api)
        assert kit["status"] == "DRAFT"
        assert kit["kit_price_cents"] is None
        get_success_data(api.activate_kit(kit["id"], CATALOG))
        fetched = validate_success(api.get_kit(kit["id"], CATALOG), 200)
        assert fetched["status"] == "ACTIVE"
        assert fetched["kit_price_cents"] == 36500, "the rolled-up price persists on re-read"


class TestKitFeeTierBoundary:
    def test_kit_fee_tier_boundary_at_100000(self, api):
        """PRD §3.9: "then the assembly fee is tiered on that pre-fee component cost — 1500 cents when it falls below 100000 cents, 4000 cents when it reaches 100000 but stays below 500000, and 9000 cents at 500000 or above; finally `kit_price_cents` is the component cost plus the fee."

        Design: Corner/calculations/kit_fee_tier_boundary_at_100000
        """
        customer = make_customer(api, name="Lab Delta")
        prod_c = _kit_product(api, "KC-10", "Kit Part C", 10000)
        prod_d = _kit_product(api, "KD-99", "Kit Part D", 99999)
        kit1 = make_kit(
            api, customer_id=customer["id"], name="Kit K1",
            components=[kit_component(prod_c["id"], 10)],
        )
        kit2 = make_kit(
            api, customer_id=customer["id"], name="Kit K2",
            components=[kit_component(prod_d["id"], 1)],
        )
        price1 = validate_success(api.activate_kit(kit1["id"], CATALOG), 200)
        # component_cost exactly 100000 reaches the second tier: 100000 + 4000.
        assert price1["kit_price_cents"] == 104000
        price2 = validate_success(api.activate_kit(kit2["id"], CATALOG), 200)
        # 99999 stays below the boundary: 99999 + 1500.
        assert price2["kit_price_cents"] == 101499


class TestKitStructuralChecks:
    def test_kit_activation_empty_components_rejected_error(self, api):
        """PRD §3.9: "the `components` array must be non-empty (`ERR_KIT_COMPONENTS_EMPTY`, HTTP 422) and all components must share one identical `storage_requirement` (`ERR_KIT_STORAGE_MIXED`, HTTP 422);"

        Design: Difficulty/boundary_precision_check/kit_activation_empty_components_rejected
        """
        customer = make_customer(api, name="Lab Delta")
        kit = make_kit(api, customer_id=customer["id"], name="Empty Kit", components=[])
        resp = api.activate_kit(kit["id"], CATALOG)
        validate_error(resp, ApiErrorId.ERR_KIT_COMPONENTS_EMPTY)
        assert resp.status_code == 422

    def test_kit_activation_empty_components_stays_draft(self, api):
        """PRD §3.9: "A kit begins `DRAFT` with `kit_price_cents` null."
        PRD §3.9: "Activation promotes the kit from `DRAFT` (any other state, `ERR_KIT_NOT_DRAFT`) and applies its checks in the global priority order: no component product may be covered by an `ISSUED` recall (`ERR_PRODUCT_UNDER_RECALL`); the `components` array must be non-empty (`ERR_KIT_COMPONENTS_EMPTY`, HTTP 422)"

        Design: Difficulty/boundary_precision_check/kit_activation_empty_components_rejected
        """
        customer = make_customer(api, name="Lab Delta")
        kit = make_kit(api, customer_id=customer["id"], name="Empty Kit", components=[])
        validate_error(api.activate_kit(kit["id"], CATALOG), ApiErrorId.ERR_KIT_COMPONENTS_EMPTY)
        fetched = validate_success(api.get_kit(kit["id"], CATALOG), 200)
        assert fetched["status"] == "DRAFT", "the rejected activation leaves the kit DRAFT"
        assert fetched["kit_price_cents"] is None

    def test_kit_duplicate_component_rejected(self, api):
        """PRD §3.9: "The same product may not appear twice in one kit — a duplicate `product_id` is rejected at creation with `ERR_KIT_DUPLICATE_COMPONENT` (HTTP 422)."

        Design: Corner/validations/kit_duplicate_component_rejected
        """
        customer = make_customer(api, name="Lab Delta")
        prod_a = _kit_product(api, "KA-01", "Kit Part A", 10000)
        resp = api.create_kit(
            {
                "customer_id": customer["id"],
                "name": "Dup Kit",
                "components": [
                    kit_component(prod_a["id"], 1),
                    kit_component(prod_a["id"], 2),
                ],
            },
            CATALOG,
        )
        validate_error(resp, ApiErrorId.ERR_KIT_DUPLICATE_COMPONENT)
        assert resp.status_code == 422

    def test_kit_storage_mixed_rejected_at_activate(self, api):
        """PRD §3.9: "the `components` array must be non-empty (`ERR_KIT_COMPONENTS_EMPTY`, HTTP 422) and all components must share one identical `storage_requirement` (`ERR_KIT_STORAGE_MIXED`, HTTP 422);"

        Design: Corner/validations/kit_storage_mixed_rejected_at_activate
        """
        customer = make_customer(api, name="Lab Delta")
        prod_a = _kit_product(api, "KA-01", "Kit Part A", 10000)
        prod_b = _kit_product(
            api, "KB-02", "Kit Part B", 5000,
            storage_requirement="REFRIGERATED_2_8", requires_cold_chain=True,
            shelf_life_days=60,
        )
        kit = make_kit(
            api,
            customer_id=customer["id"],
            name="Mixed Kit",
            components=[kit_component(prod_a["id"], 1), kit_component(prod_b["id"], 1)],
        )
        resp = api.activate_kit(kit["id"], CATALOG)
        validate_error(resp, ApiErrorId.ERR_KIT_STORAGE_MIXED)
        assert resp.status_code == 422
        fetched = validate_success(api.get_kit(kit["id"], CATALOG), 200)
        assert fetched["status"] == "DRAFT"


class TestKitAssemblyExecution:
    def test_kit_assembly_execute_consumes_components_fefo(self, api):
        """PRD §3.9: "Execution is atomic and FEFO-driven: from a `PLANNED` job (`ERR_JOB_NOT_EXECUTABLE` otherwise), the system checks for every component that the FEFO waterfall over that product's `AVAILABLE` lots at the job's warehouse can cover `quantity_per_kit` times `quantity_to_build`; if any component falls short, the entire execution is rejected with `ERR_KIT_COMPONENT_SHORTAGE` and all stock is left untouched. On success, each component's requirement is consumed down the waterfall — decrementing each lot's `quantity_on_hand` and incrementing its `quantity_consumed`, flipping lots emptied to exactly zero from `AVAILABLE` to `DEPLETED`, and recomputing the touched zones' occupancy — then `kits_built` is set equal to `quantity_to_build` and the `consumption_summary` is recorded as a map from each component `product_id` to the list of lot-and-quantity pairs consumed."

        Design: Corner/state_machines/kit_assembly_execute_consumes_components_fefo
        """
        warehouse = make_warehouse(api)
        zone = make_zone(
            api, warehouse["id"], zone_class="AMBIENT", capacity_units=500,
            rotation_policy="FEFO",
        )
        prod_a = _kit_product(api, "KA-01", "Kit Part A", 10000)
        customer = make_customer(api, name="Lab Delta")
        lot1 = make_lot(api, prod_a["id"], warehouse["id"], zone["id"],
                        quantity_received=10, manufacture_date="2026-01-15")
        lot2 = make_lot(api, prod_a["id"], warehouse["id"], zone["id"],
                        quantity_received=10, manufacture_date="2026-02-15")
        kit = make_kit(
            api, customer_id=customer["id"], name="Triple-A Kit",
            components=[kit_component(prod_a["id"], 3)],
        )
        get_success_data(api.activate_kit(kit["id"], CATALOG))
        job = make_job(api, kit_id=kit["id"], warehouse_id=warehouse["id"],
                       quantity_to_build=2)

        resp = api.execute_job(job["id"], CLERK)
        executed = validate_success(resp, 200)
        assert executed["status"] == "COMPLETED"
        assert executed["kits_built"] == 2

        # 2 kits x 3 per kit = 6 units; FEFO drains the earliest-expiry lot first.
        lot1_after = get_lot(api, lot1["id"])
        assert lot1_after["quantity_on_hand"] == 4
        assert lot1_after["quantity_consumed"] == 6
        lot2_after = get_lot(api, lot2["id"])
        assert lot2_after["quantity_on_hand"] == 10, "the later-expiry lot stays untouched"

        summary = executed["consumption_summary"]
        assert prod_a["id"] in summary, "the summary keys on the component product_id"
        entries = summary[prod_a["id"]]
        assert len(entries) == 1
        assert entries[0]["lot_id"] == lot1["id"]
        assert entries[0]["quantity"] == 6
