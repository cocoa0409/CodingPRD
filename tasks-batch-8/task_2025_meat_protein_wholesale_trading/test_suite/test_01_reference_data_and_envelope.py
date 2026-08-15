"""Desk reference data: request-shape rules, the lighter resource field set,
list pagination envelope, path 404 sampling, and read-after-write visibility."""
from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    api_client,
    assert_product,
    assert_supplier,
    create_product_payload,
    create_supplier_payload,
    is_iso8601_timestamp,
    is_valid_uuid,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestSupplierCreateShape:
    def test_create_supplier_missing_contact_email_returns_invalid_request(
            self, desk_admin_headers):
        """PRD §3.1: "Each **supplier** is registered with its legal `name`, its
        USDA `establishment_number` — unique across all suppliers, with a
        collision rejected by `ERR_DUPLICATE_CODE` — and a primary
        `contact_email`."
        PRD §2.8: "Required fields are present, types are correct, enum members
        are valid, and quantities are positive; otherwise `ERR_INVALID_REQUEST`
        (HTTP 400)."
        PRD §3.1: "A supplier's `status` begins at `ACTIVE`"

        Design: Corner/entities/create_supplier_missing_required_returns_invalid_request
        """
        resp = api_client.create_supplier(
            {"name": "NoContact", "establishment_number": "EST-NC"},
            desk_admin_headers,
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)

        ok = api_client.create_supplier(
            create_supplier_payload(establishment_number="EST-FULL"),
            desk_admin_headers,
        )
        data = validate_success(ok, expected_status=201)
        assert_supplier(data)
        assert data["status"] == "ACTIVE", \
            f"a supplier's status begins at ACTIVE, got {data['status']}"


class TestProductResourceShape:
    def test_product_response_carries_no_version_or_updated_at(
            self, desk_admin_headers):
        """PRD §2.5: "Four resources are deliberately lighter. `Product`,
        `YieldSpec`, `TemperatureReading`, and `InspectionCertificate` carry
        only `id` and `created_at`; both `updated_at` and `version` are absent
        from them."

        Design: Corner/entities/product_immutable_no_version_field
        """
        created = api_client.create_product(
            create_product_payload(product_code="RIBEYE-IM"),
            desk_admin_headers,
        )
        product_id = validate_success(created, expected_status=201)["id"]

        resp = api_client.get_product(product_id, desk_admin_headers)
        data = validate_success(resp)
        assert_product(data)
        assert is_valid_uuid(data["id"])
        assert is_iso8601_timestamp(data["created_at"])
        assert "version" not in data, "Product must not carry version"
        assert "updated_at" not in data, "Product must not carry updated_at"

    def test_product_invalid_kind_enum_returns_invalid_request(
            self, desk_admin_headers):
        """PRD §3.1: "a `kind` of `CARCASS`, `PRIMAL`, or `SUBPRIMAL`".
        PRD §2.8: "Required fields are present, types are correct, enum members
        are valid, and quantities are positive; otherwise `ERR_INVALID_REQUEST`
        (HTTP 400)."

        Design: Corner/entities/product_invalid_kind_enum_returns_invalid_request
        """
        resp = api_client.create_product(
            create_product_payload(product_code="BAD-1", kind="PRIME",
                                   max_fat_pct=None),
            desk_admin_headers,
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)


class TestListPaginationEnvelope:
    def test_suppliers_list_pagination_and_envelope(self, desk_admin_headers):
        """PRD §2.3: "The `limit` parameter specifies the maximum number of
        items to return."
        PRD §2.3: "Paginated and non-paginated list-based responses include the
        following fields in the `meta` object of the response envelope:
        `limit`, `offset`, `total_count`, and `has_more`."
        PRD §2.2: "The `response_type` is either "object" for a single resource
        or "array" for a list of resources."

        Design: Corner/entities/suppliers_list_pagination_and_envelope
        """
        for code in ("EST-P1", "EST-P2", "EST-P3"):
            resp = api_client.create_supplier(
                create_supplier_payload(establishment_number=code),
                desk_admin_headers,
            )
            validate_success(resp, expected_status=201)

        page1 = api_client.list_suppliers(
            desk_admin_headers, params={"limit": 2, "offset": 0})
        data1, meta1 = validate_paginated(page1)
        assert page1.json()["response_type"] == "array"
        assert len(data1) == 2, f"page 1 must hold 2 rows, got {len(data1)}"
        assert meta1["total_count"] == 3
        assert meta1["has_more"] is True
        assert isinstance(meta1["api_request_id"], str)
        assert isinstance(meta1["api_request_timestamp"], str)

        page2 = api_client.list_suppliers(
            desk_admin_headers, params={"limit": 2, "offset": 2})
        data2, meta2 = validate_paginated(page2)
        assert len(data2) == 1, f"page 2 must hold 1 row, got {len(data2)}"
        assert meta2["has_more"] is False
        assert meta2["total_count"] == 3


class TestPathNotFoundSampling:
    def test_unknown_path_ids_return_domain_specific_404s(
            self, desk_admin_headers):
        """PRD §2.8: "Resource identifiers in the URL path exist, validated
        strictly left to right; the first missing identifier produces that
        resource's not-found error (HTTP 404): `ERR_SUPPLIER_NOT_FOUND`,
        `ERR_CUSTOMER_NOT_FOUND`, `ERR_WAREHOUSE_NOT_FOUND`,
        `ERR_PRODUCT_NOT_FOUND`, `ERR_PRICE_SHEET_NOT_FOUND`,
        `ERR_PRICE_SHEET_LINE_NOT_FOUND`, `ERR_YIELD_SPEC_NOT_FOUND`,
        `ERR_PURCHASE_ORDER_NOT_FOUND`, `ERR_LOT_NOT_FOUND`,
        `ERR_FABRICATION_BATCH_NOT_FOUND`, `ERR_FORWARD_CONTRACT_NOT_FOUND`,
        `ERR_ALLOCATION_NOT_FOUND`, `ERR_SHIPMENT_NOT_FOUND`,
        `ERR_CLAIM_NOT_FOUND`, or `ERR_CERTIFICATE_NOT_FOUND`."

        Design: Corner/errors/not_found_sampling_all_collections
        """
        cases = [
            (api_client.get_supplier, ApiErrorId.ERR_SUPPLIER_NOT_FOUND),
            (api_client.get_product, ApiErrorId.ERR_PRODUCT_NOT_FOUND),
            (api_client.get_warehouse, ApiErrorId.ERR_WAREHOUSE_NOT_FOUND),
            (api_client.get_yield_spec, ApiErrorId.ERR_YIELD_SPEC_NOT_FOUND),
            (api_client.get_price_sheet, ApiErrorId.ERR_PRICE_SHEET_NOT_FOUND),
            (api_client.get_price_sheet_line,
             ApiErrorId.ERR_PRICE_SHEET_LINE_NOT_FOUND),
            (api_client.get_purchase_order,
             ApiErrorId.ERR_PURCHASE_ORDER_NOT_FOUND),
            (api_client.get_inventory_lot, ApiErrorId.ERR_LOT_NOT_FOUND),
            (api_client.get_fabrication_batch,
             ApiErrorId.ERR_FABRICATION_BATCH_NOT_FOUND),
            (api_client.get_forward_contract,
             ApiErrorId.ERR_FORWARD_CONTRACT_NOT_FOUND),
            (api_client.get_allocation, ApiErrorId.ERR_ALLOCATION_NOT_FOUND),
            (api_client.get_shipment, ApiErrorId.ERR_SHIPMENT_NOT_FOUND),
            (api_client.get_claim, ApiErrorId.ERR_CLAIM_NOT_FOUND),
            (api_client.get_inspection_certificate,
             ApiErrorId.ERR_CERTIFICATE_NOT_FOUND),
            (api_client.get_customer, ApiErrorId.ERR_CUSTOMER_NOT_FOUND),
        ]
        for getter, error_id in cases:
            resp = getter(NON_EXISTENT_UUID, desk_admin_headers)
            assert resp.status_code == 404, \
                f"{error_id} should be HTTP 404, got {resp.status_code}"
            assert resp.json()["response_type"] == "error"
            validate_error(resp, error_id)


class TestImmediateVisibility:
    def test_created_supplier_readable_immediately_by_any_role(
            self, desk_admin_headers, trader_headers):
        """PRD §2.2: "Unless otherwise noted, operations that create or modify
        a resource will return the created or updated resource object in the
        data field."
        PRD §2.1: "Every role may use every read endpoint"

        Design: Corner/consistency/immediate_visibility_after_write
        """
        resp = api_client.create_supplier(
            create_supplier_payload(name="Immed",
                                    establishment_number="EST-IM",
                                    contact_email="ops@immed.example"),
            desk_admin_headers,
        )
        created = validate_success(resp, expected_status=201)

        got = api_client.get_supplier(created["id"], trader_headers)
        data = validate_success(got)
        assert_supplier(data)
        assert data["name"] == "Immed", \
            f"write must be visible immediately, got {data['name']}"
        assert data["establishment_number"] == "EST-IM"
        assert data["contact_email"] == "ops@immed.example"
        assert data["status"] == "ACTIVE"
