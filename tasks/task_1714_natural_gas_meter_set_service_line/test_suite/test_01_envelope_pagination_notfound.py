"""Response envelope, pagination, authentication, and per-entity 404 coverage."""
from test_helpers import (
    NON_EXISTENT_UUID,
    ApiErrorId,
    create_builder_payload,
    setup_draft_app,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestPaginationEnvelope:
    def test_builders_list_pagination_first_page(self, api, rep_headers):
        """PRD §2.3: "The `limit` parameter caps the number of items returned; it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter skips a number of items from the start of the result set and defaults to 0."
        PRD §2.3: "List responses carry the pagination fields `limit`, `offset`, `total_count`, and `has_more` in the `meta` object of the envelope."

        Design: Corner/endpoints/builders_pagination_envelope
        """
        for i in (1, 2, 3):
            resp = api.create_builder(
                create_builder_payload(
                    company_name=f"B{i}", contact_email=f"b{i}@x.example",
                    license_number=f"L{i}",
                ),
                rep_headers,
            )
            validate_success(resp, expected_status=201)

        resp = api.list_builders(rep_headers, params={"limit": 2, "offset": 0})
        data, meta = validate_paginated(resp)
        assert len(data) == 2, f"page 1 must carry 2 items, got {len(data)}"
        assert meta["total_count"] == 3, f"total_count must be 3, got {meta['total_count']}"
        assert meta["has_more"] is True, "page 1 of 3 with limit 2 must have has_more true"
        assert meta["limit"] == 2 and meta["offset"] == 0
        assert isinstance(meta.get("api_request_id"), str)
        assert isinstance(meta.get("api_request_timestamp"), str)

    def test_builders_list_pagination_last_page(self, api, rep_headers):
        """PRD §2.3: "List responses carry the pagination fields `limit`, `offset`, `total_count`, and `has_more` in the `meta` object of the envelope."

        Design: Corner/endpoints/builders_pagination_envelope
        """
        for i in (1, 2, 3):
            resp = api.create_builder(
                create_builder_payload(
                    company_name=f"B{i}", contact_email=f"b{i}@x.example",
                    license_number=f"L{i}",
                ),
                rep_headers,
            )
            validate_success(resp, expected_status=201)

        resp = api.list_builders(rep_headers, params={"limit": 2, "offset": 2})
        data, meta = validate_paginated(resp)
        assert len(data) == 1, f"page at offset 2 must carry 1 item, got {len(data)}"
        assert meta["has_more"] is False, "last page must have has_more false"
        assert meta["total_count"] == 3


class TestErrorEnvelope:
    def test_error_envelope_shape_on_submit_without_loads(self, api, rep_headers):
        """PRD §2.2: "All error API responses (4xx status codes) follow this standard envelope format"
        PRD §2.2: "The `meta` object for error responses contains only `api_request_id` and `api_request_timestamp`."
        PRD §3.1: "Submitting requires that the acting builder own the application (`ERR_FORBIDDEN_OWNER`), that the builder still be `ACTIVE`, and that at least one appliance load row exist — an empty load sheet is rejected with `ERR_NO_APPLIANCE_LOADS` (HTTP 422)."

        Design: Corner/endpoints/error_envelope_shape
        """
        ctx = setup_draft_app()
        resp = api.submit_application(ctx["app"]["id"], ctx["builder_headers"])
        assert resp.status_code == 422, f"expected 422, got {resp.status_code}"
        body = resp.json()
        assert body.get("response_type") == "error"
        assert body["data"]["error_id"] == ApiErrorId.ERR_NO_APPLIANCE_LOADS
        assert isinstance(body["data"].get("message"), str) and body["data"]["message"].strip()
        assert isinstance(body["meta"].get("api_request_id"), str)
        assert isinstance(body["meta"].get("api_request_timestamp"), str)


class TestNotFound:
    def test_meter_set_not_found_returns_entity_404(self, api, rep_headers):
        """PRD §2.10: "The first unresolved reference aborts the request with the 404 specific to that entity, and every entity family has its own: `ERR_BUILDER_NOT_FOUND`, `ERR_APPLICATION_NOT_FOUND`, `ERR_LOAD_NOT_FOUND`, `ERR_MAIN_EXTENSION_NOT_FOUND`, `ERR_INVOICE_NOT_FOUND`, `ERR_PAYMENT_NOT_FOUND`, `ERR_PERMIT_NOT_FOUND`, `ERR_CREW_NOT_FOUND`, `ERR_BOOKING_NOT_FOUND`, `ERR_INSPECTOR_NOT_FOUND`, `ERR_INSPECTION_NOT_FOUND`, `ERR_METER_SET_NOT_FOUND`, `ERR_TEST_NOT_FOUND`, `ERR_TURN_ON_NOT_FOUND`, `ERR_COMMITMENT_NOT_FOUND`, and `ERR_GIS_NOT_FOUND`."

        Design: Corner/entities/meter_set_not_found_returns_404
        """
        resp = api.get_meter_set(NON_EXISTENT_UUID, rep_headers)
        validate_error(resp, ApiErrorId.ERR_METER_SET_NOT_FOUND, expected_status=404)

    def test_not_found_family_sweep(self, api, rep_headers):
        """PRD §2.10: "The first unresolved reference aborts the request with the 404 specific to that entity, and every entity family has its own: `ERR_BUILDER_NOT_FOUND`, `ERR_APPLICATION_NOT_FOUND`, `ERR_LOAD_NOT_FOUND`, `ERR_MAIN_EXTENSION_NOT_FOUND`, `ERR_INVOICE_NOT_FOUND`, `ERR_PAYMENT_NOT_FOUND`, `ERR_PERMIT_NOT_FOUND`, `ERR_CREW_NOT_FOUND`, `ERR_BOOKING_NOT_FOUND`, `ERR_INSPECTOR_NOT_FOUND`, `ERR_INSPECTION_NOT_FOUND`, `ERR_METER_SET_NOT_FOUND`, `ERR_TEST_NOT_FOUND`, `ERR_TURN_ON_NOT_FOUND`, `ERR_COMMITMENT_NOT_FOUND`, and `ERR_GIS_NOT_FOUND`."

        Design: Corner/errors/not_found_family_sweep
        """
        cases = [
            (api.get_builder, ApiErrorId.ERR_BUILDER_NOT_FOUND),
            (api.get_service_application, ApiErrorId.ERR_APPLICATION_NOT_FOUND),
            (api.get_appliance_load, ApiErrorId.ERR_LOAD_NOT_FOUND),
            (api.get_main_extension, ApiErrorId.ERR_MAIN_EXTENSION_NOT_FOUND),
            (api.get_ciac_invoice, ApiErrorId.ERR_INVOICE_NOT_FOUND),
            (api.get_ciac_payment, ApiErrorId.ERR_PAYMENT_NOT_FOUND),
            (api.get_permit, ApiErrorId.ERR_PERMIT_NOT_FOUND),
            (api.get_field_crew, ApiErrorId.ERR_CREW_NOT_FOUND),
            (api.get_crew_booking, ApiErrorId.ERR_BOOKING_NOT_FOUND),
            (api.get_inspector, ApiErrorId.ERR_INSPECTOR_NOT_FOUND),
            (api.get_inspection, ApiErrorId.ERR_INSPECTION_NOT_FOUND),
            (api.get_meter_set, ApiErrorId.ERR_METER_SET_NOT_FOUND),
            (api.get_purge_leak_test, ApiErrorId.ERR_TEST_NOT_FOUND),
            (api.get_turn_on_event, ApiErrorId.ERR_TURN_ON_NOT_FOUND),
            (api.get_timeline_commitment, ApiErrorId.ERR_COMMITMENT_NOT_FOUND),
            (api.get_gis_as_built, ApiErrorId.ERR_GIS_NOT_FOUND),
        ]
        for getter, error_id in cases:
            resp = getter(NON_EXISTENT_UUID, rep_headers)
            validate_error(resp, error_id, expected_status=404)


class TestAuthentication:
    def test_missing_auth_headers_returns_401(self, api, rep_headers):
        """PRD §2.1: "Every request must carry two HTTP headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, naming the caller's operational capacity. A request missing either header, or carrying a role string the system does not recognize, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401)."

        Design: Corner/rbac/missing_auth_header_returns_401
        """
        resp = api.create_builder(create_builder_payload(), rep_headers)
        validate_success(resp, expected_status=201)

        resp = api.list_builders(headers={})
        validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED, expected_status=401)
