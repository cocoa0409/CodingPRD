"""Products, lines, and their creation-time contract (envelope, defaults,
system fields, and the 1:1 FryerOil child)."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    assert_line,
    assert_product,
    create_line_payload,
    create_product_payload,
    set_clock,
    validate_error,
    validate_paginated,
    validate_success,
)

PM = TEST_USERS["plant_manager_headers"]


class TestProductCreation:
    def test_product_creation_applies_defaults_and_common_fields(self, api):
        """PRD §3.1: "and `bags_per_case`, defaulting to 12 and at least 1, is
        the number of bags per finished case."
        PRD §2.2: "The `api_request_id` is a server-generated unique identifier
        for the request that starts with `req_`."
        PRD §2.5: "Every primary resource — Product, ProductionLine, FryerOil,
        Changeover, ProductionRun, Shipment, PromoWindow, DisplayCase,
        CoManufacturer, CoManAgreement, and CoManSlot — carries a standard set
        of system-managed fields"

        Design: Corner/entities/product_creation_applies_defaults_and_common_fields
        """
        set_clock("2026-08-01T00:00:00Z")
        payload = create_product_payload()
        payload.pop("bags_per_case")
        resp = api.create_product(payload, PM)
        body = resp.json()
        assert resp.status_code == 201, f"expected 201, got {resp.status_code}"
        assert body["response_type"] == "object"
        assert isinstance(body["meta"].get("api_request_id"), str)
        product = body["data"]
        assert_product(product)
        assert product["bags_per_case"] == 12, (
            f"default bags_per_case must be 12, got {product['bags_per_case']}"
        )
        assert product["version"] == 1

    def test_product_missing_required_name_returns_invalid_request(self, api):
        """PRD §2.9: "Request shape: required fields present, types valid, enum
        members valid, numeric ranges respected, duplicate entries in
        `allergen_profile` rejected, and movement-type-specific field rules
        honored (else `ERR_VALIDATION`)."

        Design: Corner/entities/product_missing_required_name_returns_invalid_request
        """
        set_clock("2026-08-01T00:00:00Z")
        payload = create_product_payload()
        payload.pop("name")
        resp = api.create_product(payload, PM)
        validate_error(resp, ApiErrorId.ERR_VALIDATION)

    def test_product_invalid_enum_returns_invalid_request(self, api):
        """PRD §3.1: "the thermal `process_type` the recipe requires — exactly
        one of `FRYER` or `OVEN`".
        PRD §3.1: "duplicate entries are rejected with `ERR_VALIDATION`, and an
        empty array denotes a plain product carrying no listed allergen."

        Design: Corner/entities/product_invalid_enum_returns_invalid_request
        """
        set_clock("2026-08-01T00:00:00Z")
        bad_enum = create_product_payload(name="Bad", process_type="AIRFRY")
        validate_error(api.create_product(bad_enum, PM), ApiErrorId.ERR_VALIDATION)
        dup_allergen = create_product_payload(
            name="Dup", allergen_profile=["DAIRY", "DAIRY"], flavor_group="CHEESE",
        )
        validate_error(
            api.create_product(dup_allergen, PM), ApiErrorId.ERR_VALIDATION,
        )

    def test_product_system_fields_input_ignored(self, api):
        """PRD §2.9: "Client-supplied system fields (`id`, `created_at`,
        `updated_at`, `version`) and undeclared extra fields are silently
        ignored, never rejected."
        PRD §2.5: "`id` (string): a server-minted UUID with no type prefix."

        Design: Corner/entities/product_system_fields_input_ignored
        """
        set_clock("2026-08-01T00:00:00Z")
        forged_id = "11111111-2222-3333-4444-555555555555"
        payload = create_product_payload()
        payload["id"] = forged_id
        payload["version"] = 99
        resp = api.create_product(payload, PM)
        product = validate_success(resp, 201)
        assert_product(product)
        assert product["id"] != forged_id, "server must mint its own id"
        assert product["version"] == 1, "client-supplied version must be ignored"


class TestLineCreation:
    def test_line_creation_creates_fryer_oil_child(self, api):
        """PRD §3.1: "Creating a line atomically creates its one-to-one
        FryerOil record: the `initial_charge_gallons` equals the line's
        `oil_capacity_gallons`, the oil starts at `tpm_pct` 0.5 in `state`
        `ACTIVE` with `total_lbs_since_replace` at zero and no observed
        purchase price, so `last_oil_price_cents_per_gal` is null."
        PRD §3.1: "The new line's `posture` initializes to `IDLE`, its
        `current_allergen_profile` to the empty array, and its
        `current_flavor_group` to `PLAIN`."
        PRD §3.1: "`cleaning_minutes_full_wash`, defaulting to 120 minutes, is
        the buffer required between two runs when the allergen matrix demands a
        full wash, and `cleaning_minutes_dry`, defaulting to 30 minutes,
        applies when a dry clean suffices"

        Design: Corner/entities/line_creation_creates_fryer_oil_child
        """
        set_clock("2026-08-01T00:00:00Z")
        resp = api.create_line(
            create_line_payload(name="Line 1", line_type="BOTH",
                                oil_capacity_gallons=100), PM,
        )
        line = validate_success(resp, 201)
        assert_line(line)
        assert line["posture"] == "IDLE"
        assert line["current_allergen_profile"] == []
        assert line["current_flavor_group"] == "PLAIN"
        assert line["cleaning_minutes_full_wash"] == 120
        assert line["cleaning_minutes_dry"] == 30

        data, meta = validate_paginated(
            api.list_fryer_oils(PM, {"line_id": line["id"]})
        )
        assert len(data) == 1 and meta["total_count"] == 1, (
            "the line must have exactly one FryerOil child"
        )
        oil = data[0]
        assert oil["line_id"] == line["id"]
        assert oil["initial_charge_gallons"] == 100
        assert oil["current_gallons"] == 100
        assert oil["tpm_pct"] == 0.5
        assert oil["state"] == "ACTIVE"
        assert oil["total_lbs_since_replace"] == 0
        assert oil["last_oil_price_cents_per_gal"] is None
