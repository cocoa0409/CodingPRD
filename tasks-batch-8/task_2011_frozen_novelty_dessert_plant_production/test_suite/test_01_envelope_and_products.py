"""Envelope shape, product master data, pagination, and read-after-write."""
from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    assert_product,
    create_product,
    get_success_data,
    is_iso8601_timestamp,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.factories import create_product_payload


class TestEnvelope:
    def test_success_envelope_shape(self, api, plant_manager_headers):
        """PRD §2.2: "All successful API responses (those with 2xx status
        codes) follow this standard envelope format in their JSON body" with
        "meta", "response_type", and "data"; "The response_type is either
        "object" for a single resource or "array" for a list of resources."

        Design: Corner/endpoints/success_envelope_shape
        """
        product = create_product(sku_code="BAR-VAN-70")
        resp = api.get_product(product["id"], plant_manager_headers)
        body = resp.json()
        assert resp.status_code == 200
        assert "meta" in body and "response_type" in body and "data" in body
        assert isinstance(body["meta"]["api_request_id"], str)
        assert body["meta"]["api_request_id"].startswith("req_")
        assert is_iso8601_timestamp(body["meta"]["api_request_timestamp"])
        assert body["response_type"] == "object"
        assert body["data"]["id"] == product["id"]

    def test_error_envelope_shape(self, api, plant_manager_headers):
        """PRD §2.2: "All error API responses (4xx status codes) follow this
        standard envelope format" with "response_type": "error" and a data
        object carrying "error_id" and "message"; "The error_id is a unique,
        machine-readable string that identifies the specific error."

        Design: Corner/endpoints/error_envelope_shape
        """
        resp = api.get_product(NON_EXISTENT_UUID, plant_manager_headers)
        body = resp.json()
        assert resp.status_code == 404
        assert body["response_type"] == "error"
        assert body["data"]["error_id"] == "ERR_NOT_FOUND"
        assert isinstance(body["data"]["message"], str)
        assert len(body["data"]["message"]) > 0


class TestProductBasics:
    def test_product_creation_applies_defaults(self, api, plant_manager_headers):
        """PRD §3.1: "New products start in ACTIVE status." PRD §2.4:
        "version (an integer starting at 1, incremented by exactly 1 on every
        mutation"."

        Design: Corner/entities/product_creation_applies_defaults
        """
        payload = create_product_payload(sku_code="BAR-VAN-70")
        # co_pack_only omitted — the PRD describes it as "an optional
        # co_pack_only flag" (§3.1); the server-side default false is the
        # only default consistent with runs being allowed without a contract.
        resp = api.create_product(payload, plant_manager_headers)
        created = validate_success(resp, 201)
        assert_product(created)
        assert created["status"] == "ACTIVE"
        assert created["co_pack_only"] is False
        assert created["version"] == 1
        assert created["predecessor_product_id"] is None
        assert created["successor_product_id"] is None
        # GET agrees with the create response.
        fetched = validate_success(
            api.get_product(created["id"], plant_manager_headers))
        assert fetched["status"] == "ACTIVE"
        assert fetched["co_pack_only"] is False
        assert fetched["version"] == 1

    def test_product_missing_required_field_returns_invalid_request(
            self, api, plant_manager_headers):
        """PRD §3.1: "A PlantManager creates a Product by supplying sku_code,
        product_name, format, flavor_family, allergens,
        fill_volume_ml_per_unit, target_overrun_pct, units_per_pallet,
        shelf_life_days". PRD §5: ERR_INVALID_REQUEST covers "Missing
        required field"."

        Design: Corner/entities/product_missing_required_field_returns_invalid_request
        """
        payload = create_product_payload()
        del payload["sku_code"]
        resp = api.create_product(payload, plant_manager_headers)
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)
        # No partial row persists.
        data, meta = validate_paginated(
            api.list_products(plant_manager_headers))
        assert meta["total_count"] == 0
        assert data == []

    def test_product_get_not_found_returns_404(self, api, plant_manager_headers):
        """PRD §5 lists `ERR_NOT_FOUND` at HTTP 404 for a path id that does
        not resolve, and §4 defines GET /products/{id} "Get one product".

        Design: Corner/entities/product_get_not_found_returns_404
        """
        resp = api.get_product(NON_EXISTENT_UUID, plant_manager_headers)
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND)

    def test_product_list_pagination(self, api, plant_manager_headers):
        """PRD §2.3: "List endpoints accept limit and offset query
        parameters." "The meta block of a list response includes limit,
        offset, total_count, and has_more."

        Design: Corner/entities/product_list_pagination
        """
        create_product(sku_code="P-1", product_name="P1")
        create_product(sku_code="P-2", product_name="P2",
                       flavor_family="CHOCOLATE")
        create_product(sku_code="P-3", product_name="P3", format="BULK",
                       flavor_family="FRUIT", fill_volume_ml_per_unit=473,
                       target_overrun_pct=30)
        page1, meta1 = validate_paginated(api.list_products(
            plant_manager_headers, params={"limit": 2, "offset": 0}))
        assert len(page1) == 2
        assert meta1["total_count"] == 3
        assert meta1["has_more"] is True
        page2, meta2 = validate_paginated(api.list_products(
            plant_manager_headers, params={"limit": 2, "offset": 2}))
        assert len(page2) == 1
        assert meta2["total_count"] == 3
        assert meta2["has_more"] is False

    def test_run_create_unknown_product_reference_returns_404(
            self, api, plant_manager_headers, production_planner_headers):
        """PRD §5 lists `ERR_REFERENCE_NOT_FOUND` at HTTP 404, and §3.5: "A
        ProductionPlanner schedules a ProductionRun with run_code,
        product_id, line_id, planned_units (positive), and
        scheduled_start." A run whose product_id does not resolve is
        rejected with it.

        Design: Corner/entities/run_create_unknown_product_reference_returns_404
        """
        line = get_success_data(api.create_line(
            {"line_code": "L-1", "format": "NOVELTY",
             "rate_units_per_hour": 12000}, plant_manager_headers), 201)
        resp = api.create_production_run(
            {"run_code": "R-404", "product_id": NON_EXISTENT_UUID,
             "line_id": line["id"], "planned_units": 100,
             "scheduled_start": "2026-08-10T14:00:00Z"},
            production_planner_headers)
        validate_error(resp, ApiErrorId.ERR_REFERENCE_NOT_FOUND)
