"""Clinic onboarding, product catalog, and response envelope shape (PRD §2.2, §3.1, §3.2)."""
from test_helpers import (
    ACCOUNT_MANAGER,
    NON_EXISTENT_UUID,
    OFFICER,
    PLANNER,
    ApiErrorId,
    assert_clinic,
    assert_lot_conservation,
    assert_order,
    assert_product,
    assert_three_fractional_digits,
    create_active_clinic,
    create_clinic,
    create_clinic_payload,
    create_lot,
    create_order,
    create_product,
    create_product_payload,
    get_success_data,
    is_valid_uuid,
    make_clinic_buyer_headers,
    order_line_spec,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestClinicCreation:
    def test_clinic_creation_initial_state_and_computed(self, api):
        """PRD §3.1: "A new clinic starts in `PENDING_VERIFICATION` with
        `credit_used_cents` at zero and `version` at 1."
        PRD §3.1: "it is optional at onboarding and defaults to null, but its
        absence blocks controlled-substance orders later."
        PRD §2.5: "`created_at` (string): an ISO 8601 UTC timestamp with three
        fractional digits, set at creation."

        Design: Corner/entities/clinic_creation_initial_state_and_computed
        """
        resp = api.create_clinic(create_clinic_payload(
            clinic_name="Clinic N",
            license_number="LIC-N1",
            ship_to_address="21 Mews St",
            credit_limit_cents=100000,
            minimum_order_value_cents=5000,
            delivery_frequency_per_week=2,
            free_freight_threshold_cents=75000,
        ), ACCOUNT_MANAGER)
        clinic = validate_success(resp, 201)
        assert_clinic(clinic)
        assert clinic["status"] == "PENDING_VERIFICATION", (
            f"Expected PENDING_VERIFICATION, got {clinic['status']}")
        assert clinic["credit_used_cents"] == 0
        assert clinic["version"] == 1
        assert clinic["dea_registration_number"] is None, (
            "dea_registration_number defaults to null when omitted")
        assert is_valid_uuid(clinic["id"])
        assert_three_fractional_digits(clinic["created_at"])
        assert_three_fractional_digits(clinic["updated_at"])


class TestProductCatalog:
    def test_product_create_computed_cold_chain_ignores_client_input(self, api):
        """PRD §2.10: "A Product's `requires_cold_chain` flag is computed: it is
        true exactly when `product_type` is `VACCINE`, and any client-supplied
        value for it is ignored."
        PRD §2.5: "`id` (string): a server-minted UUID with no type prefix."
        PRD §3.2: "The product's `requires_cold_chain` derives from its type per
        §2.10, and its `status` starts at `LISTED`."

        Design: Corner/entities/product_create_system_and_computed_input_ignored
        """
        supplied_id = "11111111-1111-1111-1111-111111111111"
        resp = api.create_product(create_product_payload(
            sku="CONS-IG",
            product_name="Towel Pack",
            manufacturer_code="GEN",
            product_type="CONSUMABLE",
            unit_price_cents=2500,
            requires_cold_chain=True,
            id=supplied_id,
        ), PLANNER)
        product = validate_success(resp, 201)
        assert_product(product)
        assert product["requires_cold_chain"] is False, (
            "requires_cold_chain must be computed from product_type CONSUMABLE; "
            "client input ignored")
        assert product["id"] != supplied_id, "id must be server-minted"
        assert is_valid_uuid(product["id"])
        assert product["status"] == "LISTED"

    def test_product_retrieval_and_not_found(self, api):
        """PRD §2.8: "Resource identifiers referenced in the path and body are
        resolved strictly left to right, and the first identifier that does not
        resolve produces the 404 for its resource type: `ERR_CLINIC_NOT_FOUND`,
        `ERR_PRODUCT_NOT_FOUND`, ..."

        Design: Corner/entities/product_retrieval_and_not_found
        """
        product = create_product(sku="VAC-NF", product_name="FVRCP 10ds",
                                 product_type="VACCINE", unit_price_cents=5000)

        got = validate_success(api.get_product(product["id"], ACCOUNT_MANAGER))
        assert_product(got)
        assert got["sku"] == "VAC-NF"
        assert got["requires_cold_chain"] is True, (
            "VACCINE products compute requires_cold_chain true (PRD §2.10)")

        resp = api.get_product(NON_EXISTENT_UUID, ACCOUNT_MANAGER)
        validate_error(resp, ApiErrorId.ERR_PRODUCT_NOT_FOUND)

    def test_not_found_sweep_all_path_resources(self, api):
        """PRD §2.8: "Resource identifiers referenced in the path and body are
        resolved strictly left to right, and the first identifier that does not
        resolve produces the 404 for its resource type: `ERR_CLINIC_NOT_FOUND`,
        `ERR_PRODUCT_NOT_FOUND`, `ERR_AUTHORIZATION_NOT_FOUND`, `ERR_LOT_NOT_FOUND`,
        `ERR_ORDER_NOT_FOUND`, `ERR_ORDER_LINE_NOT_FOUND`,
        `ERR_BACKORDER_LINE_NOT_FOUND`, `ERR_SHIPMENT_NOT_FOUND`,
        `ERR_PROGRAM_NOT_FOUND`, `ERR_ENROLLMENT_NOT_FOUND`, or
        `ERR_CREDIT_NOT_FOUND`."

        Design: Corner/entities/not_found_sweep_all_path_resources
        """
        cases = [
            (api.get_clinic(NON_EXISTENT_UUID, ACCOUNT_MANAGER),
             ApiErrorId.ERR_CLINIC_NOT_FOUND),
            (api.get_authorization(NON_EXISTENT_UUID, ACCOUNT_MANAGER),
             ApiErrorId.ERR_AUTHORIZATION_NOT_FOUND),
            (api.get_lot(NON_EXISTENT_UUID, PLANNER),
             ApiErrorId.ERR_LOT_NOT_FOUND),
            (api.get_order(NON_EXISTENT_UUID, ACCOUNT_MANAGER),
             ApiErrorId.ERR_ORDER_NOT_FOUND),
            (api.get_order_line(NON_EXISTENT_UUID, ACCOUNT_MANAGER),
             ApiErrorId.ERR_ORDER_LINE_NOT_FOUND),
            (api.get_shipment(NON_EXISTENT_UUID, PLANNER),
             ApiErrorId.ERR_SHIPMENT_NOT_FOUND),
            (api.get_bundle_program(NON_EXISTENT_UUID, ACCOUNT_MANAGER),
             ApiErrorId.ERR_PROGRAM_NOT_FOUND),
            (api.get_bundle_enrollment(NON_EXISTENT_UUID, ACCOUNT_MANAGER),
             ApiErrorId.ERR_ENROLLMENT_NOT_FOUND),
            (api.get_short_date_credit(NON_EXISTENT_UUID, OFFICER),
             ApiErrorId.ERR_CREDIT_NOT_FOUND),
            (api.cancel_backorder_line(NON_EXISTENT_UUID, ACCOUNT_MANAGER),
             ApiErrorId.ERR_BACKORDER_LINE_NOT_FOUND),
        ]
        for resp, expected in cases:
            validate_error(resp, expected)

    def test_product_duplicate_sku_conflict(self, api):
        """PRD §3.2: "Creating a product takes a `sku` (unique across all
        products — a duplicate is rejected with `ERR_DUPLICATE_SKU`)..."

        Design: Corner/entities/product_duplicate_sku_conflict
        """
        create_product(sku="SKU-DUP", product_name="First", unit_price_cents=1000)
        resp = api.create_product(create_product_payload(
            sku="SKU-DUP", product_name="Second", unit_price_cents=2000), PLANNER)
        validate_error(resp, ApiErrorId.ERR_DUPLICATE_SKU)

    def test_product_listing_pagination_defaults(self, api):
        """PRD §2.3: "The `limit` parameter sets the maximum number of items
        returned; it defaults to 10, with a minimum of 1 and a maximum of 100.
        The `offset` parameter sets the number of items skipped and defaults to
        0. Unless otherwise specified, every list endpoint returns resources
        sorted by `created_at` in ascending order. The `meta` object of a list
        response carries `limit`, `offset`, `total_count`, and `has_more`."

        Design: Corner/entities/product_listing_pagination_defaults
        """
        create_product(sku="PG-1", product_name="Page One", unit_price_cents=1000)
        create_product(sku="PG-2", product_name="Page Two", unit_price_cents=1000)

        bare_resp = api.list_products(ACCOUNT_MANAGER)
        assert bare_resp.json()["response_type"] == "array"
        data, meta = validate_paginated(bare_resp)
        assert meta["total_count"] == 2
        assert meta["limit"] == 10, "bare list applies the default limit of 10"
        assert meta["offset"] == 0
        assert meta["has_more"] is False
        assert len(data) == 2

        page1, meta1 = validate_paginated(
            api.list_products(ACCOUNT_MANAGER, params={"limit": 1, "offset": 0}))
        assert len(page1) == 1
        assert meta1["has_more"] is True
        assert meta1["total_count"] == 2

        page2, meta2 = validate_paginated(
            api.list_products(ACCOUNT_MANAGER, params={"limit": 1, "offset": 1}))
        assert len(page2) == 1
        assert meta2["has_more"] is False
        assert page1[0]["id"] != page2[0]["id"], "pages must be disjoint"


class TestEnvelopeShape:
    def test_response_envelope_shape_on_success_and_error(self, api):
        """PRD §2.2: "The `api_request_id` is a server-generated unique
        identifier for the request that starts with `req_`."
        PRD §2.2: "The `response_type` is either "object" for a single resource
        or "array" for a list of resources."
        PRD §2.2: "The `meta` object for error responses contains only
        `api_request_id` and `api_request_timestamp`."
        PRD §2.2: "The `message` provides a human-readable explanation of what
        went wrong."

        Design: Corner/endpoints/response_envelope_shape_on_success_and_error
        """
        product = create_product(sku="ENV-1", product_name="Envelope",
                                 unit_price_cents=1000)

        ok_resp = api.get_product(product["id"], ACCOUNT_MANAGER)
        ok_body = ok_resp.json()
        data = validate_success(ok_resp)
        assert data["id"] == product["id"]
        assert ok_body["response_type"] == "object"
        assert ok_body["meta"]["api_request_id"].startswith("req_")
        assert_three_fractional_digits(ok_body["meta"]["api_request_timestamp"])

        err_resp = api.get_product(NON_EXISTENT_UUID, ACCOUNT_MANAGER)
        err_body = err_resp.json()
        validate_error(err_resp, ApiErrorId.ERR_PRODUCT_NOT_FOUND)
        assert err_body["response_type"] == "error"
        assert set(err_body["meta"].keys()) <= {
            "api_request_id", "api_request_timestamp"}
        assert err_body["data"]["message"].strip(), "error message must be non-empty"


class TestProductDiscontinue:
    def test_product_discontinue_valid_then_invalid(self, api):
        """PRD §3.2: "Discontinuing moves a `LISTED` product to `DISCONTINUED` —
        its terminal state — and is rejected with `ERR_PRODUCT_INVALID_STATE`
        from anywhere else."
        PRD §2.5: "`version` (integer): starts at 1 when the resource is created
        and increments by one on every modification."

        Design: Corner/state_machines/product_discontinue_valid_then_invalid
        """
        product = create_product(sku="CONS-DISC", product_name="Old SKU",
                                 unit_price_cents=1000)

        first = validate_success(api.discontinue_product(product["id"], PLANNER))
        assert first["status"] == "DISCONTINUED"
        assert first["version"] == product["version"] + 1

        resp = api.discontinue_product(product["id"], PLANNER)
        validate_error(resp, ApiErrorId.ERR_PRODUCT_INVALID_STATE)
        assert get_success_data(
            api.get_product(product["id"], ACCOUNT_MANAGER))["status"] == "DISCONTINUED"

    def test_discontinued_product_blocked_at_submit(self, api):
        """PRD §3.2: "Discontinuation is forward-looking only: existing orders
        are untouched, but submitting a new order containing a `DISCONTINUED`
        product fails with `ERR_PRODUCT_DISCONTINUED`."

        Design: Corner/state_machines/discontinued_product_blocked_at_submit
        """
        clinic = create_active_clinic()
        product = create_product(sku="CONS-DP", product_name="Legacy Wrap",
                                 unit_price_cents=2500)
        order = create_order(clinic["id"], [order_line_spec(product["id"], 1)])
        get_success_data(api.discontinue_product(product["id"], PLANNER))

        resp = api.submit_order(order["id"], make_clinic_buyer_headers(clinic["id"]))
        validate_error(resp, ApiErrorId.ERR_PRODUCT_DISCONTINUED)
        assert get_success_data(
            api.get_order(order["id"], ACCOUNT_MANAGER))["status"] == "DRAFT"


class TestClinicLifecycle:
    def test_clinic_double_activate_returns_invalid_state(self, api):
        """PRD §3.1: "Verification moves the clinic from `PENDING_VERIFICATION`
        to `ACTIVE`; attempting activation from any other state is rejected with
        `ERR_CLINIC_INVALID_STATE`."
        PRD §2.5: "`version` (integer): starts at 1 when the resource is created
        and increments by one on every modification."

        Design: Corner/state_machines/clinic_double_activate_returns_invalid_state
        """
        clinic = create_clinic(clinic_name="Clinic DA", license_number="LIC-DA")
        activated = get_success_data(api.activate_clinic(clinic["id"], ACCOUNT_MANAGER))
        assert activated["status"] == "ACTIVE"
        assert activated["version"] == 2

        resp = api.activate_clinic(clinic["id"], ACCOUNT_MANAGER)
        validate_error(resp, ApiErrorId.ERR_CLINIC_INVALID_STATE)

        after = get_success_data(api.get_clinic(clinic["id"], ACCOUNT_MANAGER))
        assert after["status"] == "ACTIVE"
        assert after["version"] == 2, (
            "A rejected transition must not mutate the record")
