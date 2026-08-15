"""Customer onboarding, formula intake, catalogue reads, and intake-time
validation rules (PRD §2.1, §2.3, §2.5, §2.7, §3.1)."""
from test_helpers import (
    NON_EXISTENT_UUID,
    ApiErrorId,
    api_client,
    assert_customer_account,
    assert_formula,
    create_customer,
    create_customer_payload,
    create_formula,
    create_formula_payload,
    create_ingredient_supply_payload,
    get_ingredient_supply,
    make_customer_headers,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers import TEST_USERS

OPS = TEST_USERS["ops_admin_headers"]


class TestCustomerOnboarding:

    def test_customer_create_applies_copacker_default(self):
        """PRD §3.1: "The account's `default_disposition_owner` — either
        `CUSTOMER` or `COPACKER` — decides who will be allowed to disposition
        quality holds raised against that customer's runs; when omitted at
        creation it defaults to `COPACKER`. Every account begins with an
        `outstanding_billed_cents` of zero."

        Design: Corner/entities/customer_create_applies_defaults
        """
        resp = api_client.create_customer(
            create_customer_payload(
                brand_name="Nuevo Brands",
                contact_email="hola@nuevo.example",
                credit_limit_cents=5000,
            ),
            OPS,
        )
        data = validate_success(resp, expected_status=201)
        assert_customer_account(data)
        assert data["default_disposition_owner"] == "COPACKER", (
            f"omitted default_disposition_owner must default to COPACKER, "
            f"got {data['default_disposition_owner']}"
        )
        assert data["outstanding_billed_cents"] == 0


class TestFormulaIntakeValidation:

    def test_formula_create_missing_sku_code_rejected(self):
        """PRD §2.7: "Required fields must be present, types must be valid, enum values must be members of their declared sets, quantities must be strictly positive where required, `scheduled_end` must be strictly after `scheduled_start`, `unit_cost_cents` must be present when a supply's `sourcing_mode` is `COPACKER_SUPPLIED`, `measured_ph` must be present when a hold's `reason_category` is `PH_DEVIATION`, `measured_water_activity` must be present when it is `AW_DEVIATION`, and consignment receipts are accepted only for `CUSTOMER_SUPPLIED` lines. Any violation is `ERR_INVALID_REQUEST` (HTTP 400)."
        PRD §3.1: "A new **Formula** records the owning `customer_id`, a `product_name`, the customer's `sku_code`, a `process_category` of `ACIDIFIED`, `LOW_ACID`, or `ACID`, an `allergen_class` of `NONE`, `GLUTEN`, `SOY`, `NUT`, or `DAIRY`, the contractual `min_run_units` of at least one, and a `unit_rate_cents` co-pack fee of zero or more per billed unit."

        Design: Corner/entities/formula_create_missing_required_sku_code
        """
        customer = create_customer()
        payload = create_formula_payload(customer["id"])
        del payload["sku_code"]
        resp = api_client.create_formula(payload, OPS)
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)

    def test_formula_create_invalid_process_category_rejected(self):
        """PRD §3.1: "A new **Formula** records the owning `customer_id`, a `product_name`, the customer's `sku_code`, a `process_category` of `ACIDIFIED`, `LOW_ACID`, or `ACID`, an `allergen_class` of `NONE`, `GLUTEN`, `SOY`, `NUT`, or `DAIRY`, the contractual `min_run_units` of at least one, and a `unit_rate_cents` co-pack fee of zero or more per billed unit."
        PRD §2.7: "Required fields must be present, types must be valid, enum values must be members of their declared sets, quantities must be strictly positive where required, `scheduled_end` must be strictly after `scheduled_start`, `unit_cost_cents` must be present when a supply's `sourcing_mode` is `COPACKER_SUPPLIED`, `measured_ph` must be present when a hold's `reason_category` is `PH_DEVIATION`, `measured_water_activity` must be present when it is `AW_DEVIATION`, and consignment receipts are accepted only for `CUSTOMER_SUPPLIED` lines. Any violation is `ERR_INVALID_REQUEST` (HTTP 400)."

        Design: Corner/entities/formula_create_invalid_enum_rejected
        """
        customer = create_customer()
        payload = create_formula_payload(customer["id"], process_category="SPICY")
        resp = api_client.create_formula(payload, OPS)
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)

    def test_receive_rejected_on_copacker_supplied_line(self):
        """PRD §3.1: "Receipts are rejected with `ERR_INVALID_REQUEST` when
        the target line is not `CUSTOMER_SUPPLIED` — co-packer-procured
        ingredients have no consignment balance."

        Design: Corner/validations/receive_on_copacker_supplied_rejected
        """
        customer = create_customer()
        formula = create_formula(customer["id"])
        supply_resp = api_client.create_ingredient_supply(
            create_ingredient_supply_payload(
                formula["id"],
                ingredient_name="White vinegar",
                sourcing_mode="COPACKER_SUPPLIED",
                quantity_per_unit=0.8,
                unit_cost_cents=300,
            ),
            OPS,
        )
        supply = validate_success(supply_resp, expected_status=201)

        resp = api_client.receive_ingredient_supply(
            supply["id"], {"quantity": 100}, OPS
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)
        after = get_ingredient_supply(supply["id"])
        assert after["consigned_units_on_hand"] == 0, (
            f"rejected receipt must not credit consignment, got "
            f"{after['consigned_units_on_hand']}"
        )


class TestFormulaCatalogReads:

    def test_formula_get_unknown_id_returns_404(self):
        """PRD §2.7: "Path identifiers are validated left to right, each mapping to its resource-specific 404 — `ERR_CUSTOMER_NOT_FOUND`, `ERR_FORMULA_NOT_FOUND`, `ERR_INGREDIENT_SUPPLY_NOT_FOUND`, `ERR_PILOT_CELL_NOT_FOUND`, `ERR_TRIAL_NOT_FOUND`, `ERR_LETTER_NOT_FOUND`, `ERR_KETTLE_LINE_NOT_FOUND`, `ERR_COMPONENT_NOT_FOUND`, `ERR_RUN_NOT_FOUND`, `ERR_HOLD_NOT_FOUND`, or `ERR_LABEL_NOT_FOUND`."

        Design: Corner/entities/formula_get_not_found
        """
        resp = api_client.get_formula(NON_EXISTENT_UUID, OPS)
        validate_error(resp, ApiErrorId.ERR_FORMULA_NOT_FOUND)

    def test_formulas_list_paginates_with_limit_offset(self):
        """PRD §2.3: "The `limit` parameter specifies the maximum number of
        items to return. If not provided, it defaults to 10, with a minimum of
        1 and a maximum of 100. The `offset` parameter specifies the number of
        items to skip and defaults to 0."
        PRD §2.3: "Paginated list responses include the following fields in
        the `meta` object of the response envelope: `limit`, `offset`,
        `total_count`, and `has_more`."

        Design: Corner/entities/formulas_list_pagination
        """
        customer = create_customer()
        for i in range(3):
            create_formula(
                customer["id"],
                product_name=f"Sauce {i + 1}",
                sku_code=f"S{i + 1}",
                process_category="ACID",
                min_run_units=100,
                unit_rate_cents=100,
            )
        page1, meta1 = validate_paginated(api_client.list_formulas(OPS, params={"limit": 2, "offset": 0}))
        assert len(page1) == 2, f"page 1 must hold 2 rows, got {len(page1)}"
        assert meta1["total_count"] == 3
        assert meta1["has_more"] is True
        assert meta1["limit"] == 2
        assert meta1["offset"] == 0

        page2, meta2 = validate_paginated(api_client.list_formulas(OPS, params={"limit": 2, "offset": 2}))
        assert len(page2) == 1, f"page 2 must hold 1 row, got {len(page2)}"
        assert meta2["total_count"] == 3
        assert meta2["has_more"] is False
        assert meta2["offset"] == 2

    def test_formula_created_in_draft_with_revision_one(self):
        """PRD §3.1: "A formula is born in `DRAFT` status with `revision` 1."

        Design: Corner/state_machines/formula_initial_state
        """
        customer = create_customer()
        resp = api_client.create_formula(
            create_formula_payload(customer["id"]), OPS
        )
        data = validate_success(resp, expected_status=201)
        assert_formula(data)
        assert data["status"] == "DRAFT"
        assert data["revision"] == 1


class TestFormulaOptimisticConcurrency:

    def test_formula_update_rejects_stale_expected_version(self):
        """PRD §2.5: "Updating a formula's specification requires the
        non-optional input field `expected_formula_version`, carrying the
        client's last observed `version` of that `Formula`. If the formula's
        current `version` no longer matches the supplied value — because
        another write has advanced it since the client last read the
        resource — the update is rejected with `ERR_STALE_VERSION` (HTTP 412),
        rather than overwriting changes the client never saw."

        Design: Corner/cross_cutting_layers/formula_put_stale_version_rejected
        """
        customer = create_customer()
        formula = create_formula(customer["id"])
        observed_version = formula["version"]

        first = api_client.update_formula(
            formula["id"],
            {
                "product_name": "Ghost Pepper Sauce v2",
                "expected_formula_version": observed_version,
            },
            OPS,
        )
        updated = validate_success(first, expected_status=200)
        assert updated["version"] == observed_version + 1, (
            f"successful update must increment version {observed_version} -> "
            f"{observed_version + 1}, got {updated['version']}"
        )
        assert updated["product_name"] == "Ghost Pepper Sauce v2"

        replay = api_client.update_formula(
            formula["id"],
            {
                "unit_rate_cents": 130,
                "expected_formula_version": observed_version,
            },
            OPS,
        )
        validate_error(replay, ApiErrorId.ERR_STALE_VERSION)

        from test_helpers import get_formula

        current = get_formula(formula["id"])
        assert current["unit_rate_cents"] == 120, (
            f"stale write must not clobber unit_rate_cents, got "
            f"{current['unit_rate_cents']}"
        )
        assert current["version"] == observed_version + 1


class TestCustomerOwnershipIsolation:

    def test_customer_cannot_read_other_customers_formula(self):
        """PRD §2.1: "When `X-User-Role` is `Customer`, `X-User-ID` is the
        `id` of the acting `CustomerAccount`; ownership checks on any resource
        that references a `CustomerAccount` compare the resource's
        customer-chain foreign key to `X-User-ID`."
        PRD §2.1: "Acting on a resource outside the chain is rejected with
        `ERR_FORBIDDEN`."

        Design: Corner/rbac/customer_cannot_read_other_customers_formula
        """
        customer_a = create_customer()
        customer_b = create_customer(
            brand_name="Nuevo Brands", contact_email="hola@nuevo.example"
        )
        formula_a = create_formula(customer_a["id"])

        resp = api_client.get_formula(
            formula_a["id"], make_customer_headers(customer_b["id"])
        )
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN)
