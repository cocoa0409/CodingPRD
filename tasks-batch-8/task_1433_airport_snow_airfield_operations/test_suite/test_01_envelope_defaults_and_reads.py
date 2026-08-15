"""Envelope shape, creation defaults, computed/system fields, 404s, pagination."""
from test_helpers import (
    NON_EXISTENT_UUID,
    ApiErrorId,
    assert_snow_event,
    create_snow_event_payload,
    create_surface_payload,
    is_iso8601_timestamp,
    is_valid_uuid,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestEnvelopeShape:
    def test_success_envelope_shape_on_create(self, api,
                                              ops_controller_headers):
        """PRD §2.2: "The `api_request_id` is a server-generated unique
        identifier for the request that starts with `req_`."
        PRD §3.1: "The new event starts with `status` = `FORECAST`,
        `closure_status` = `NONE`, `airline_acknowledged` = `false`,
        `activated_at` unset, and all three computed counters —
        `estimated_cost_cents`, `actual_cost_cents`, `chemical_used_lbs` — at
        zero."

        Design: Corner/endpoints/success_envelope_shape_on_create
        """
        resp = api.create_snow_event(
            create_snow_event_payload(event_code="SNOW-E1"),
            ops_controller_headers)
        assert resp.status_code == 201, resp.text
        body = resp.json()
        assert body["response_type"] == "object"
        assert isinstance(body["meta"]["api_request_id"], str)
        assert body["meta"]["api_request_id"].startswith("req_")
        assert is_iso8601_timestamp(body["meta"]["api_request_timestamp"])
        data = body["data"]
        assert is_valid_uuid(data["id"])
        assert data["status"] == "FORECAST"
        assert_snow_event(data)

    def test_error_envelope_shape_on_failure(self, api, ops_controller_headers):
        """PRD §2.2: "The `error_id` is a unique, machine-readable string that
        identifies the specific error." and "The `message` provides a
        human-readable explanation of what went wrong."
        PRD §2.7: "Each missing reference yields the resource-specific 404
        variant: `ERR_EVENT_NOT_FOUND`, `ERR_SURFACE_NOT_FOUND`,
        `ERR_PRODUCT_NOT_FOUND`, `ERR_EQUIPMENT_NOT_FOUND`,
        `ERR_REPORT_NOT_FOUND`, `ERR_ASSESSMENT_NOT_FOUND`,
        `ERR_NOTAM_NOT_FOUND`, `ERR_APPLICATION_NOT_FOUND`, or
        `ERR_SHIFT_NOT_FOUND`."

        Design: Corner/endpoints/error_envelope_shape_on_failure
        """
        resp = api.get_snow_event(NON_EXISTENT_UUID, ops_controller_headers)
        assert resp.status_code == 404, resp.text
        body = resp.json()
        assert body["response_type"] == "error"
        error = validate_error(resp, ApiErrorId.ERR_EVENT_NOT_FOUND, 404)
        assert isinstance(error["message"], str) and error["message"].strip()


class TestCreationDefaultsAndFields:
    def test_snow_event_create_applies_server_defaults(
            self, api, ops_controller_headers):
        """PRD §3.1: "The new event starts with `status` = `FORECAST`,
        `closure_status` = `NONE`, `airline_acknowledged` = `false`,
        `activated_at` unset, and all three computed counters —
        `estimated_cost_cents`, `actual_cost_cents`, `chemical_used_lbs` — at
        zero."
        PRD §2.4: "`version` (an integer that starts at `1` on creation and
        increments by exactly `1` on every state transition or mutation".

        Design: Corner/entities/snow_event_create_applies_server_defaults
        """
        resp = api.create_snow_event(
            create_snow_event_payload(event_code="SNOW-D1"),
            ops_controller_headers)
        data = validate_success(resp, 201)
        assert data["status"] == "FORECAST"
        assert data["closure_status"] == "NONE"
        assert data["airline_acknowledged"] is False
        assert data["estimated_cost_cents"] == 0
        assert data["actual_cost_cents"] == 0
        assert data["chemical_used_lbs"] == 0
        assert data["version"] == 1
        assert data.get("activated_at") is None

    def test_snow_event_missing_required_field_returns_invalid_request(
            self, api, ops_controller_headers):
        """PRD §2.9: "Request well-formedness: required fields present,
        enum membership valid, numeric ranges satisfied (`mu_value`
        between `0.00` and `1.00` inclusive; `coverage_pct` between `0`
        and `100` inclusive; `depth_inches` at least `0`; `worked_hours`
        greater than `0`; lengths greater than `0`; `effective_from`
        strictly before `effective_until`; `start_utc` strictly before
        `end_utc`; `observed_at` and `measured_at` not ahead of the
        logical clock) (else `ERR_VALIDATION`)."

        Design: Corner/entities/snow_event_missing_required_field_returns_invalid_request
        """
        payload = create_snow_event_payload()
        payload.pop("event_code")
        resp = api.create_snow_event(payload, ops_controller_headers)
        validate_error(resp, ApiErrorId.ERR_VALIDATION, 400)
        data, meta = validate_paginated(
            api.list_snow_events(ops_controller_headers))
        assert meta["total_count"] == 0, (
            f"nothing should be persisted after a rejected create, "
            f"got total_count {meta['total_count']}")

    def test_surface_create_with_invalid_enum_rejected(
            self, api, system_admin_headers):
        """PRD §2.9: "Request well-formedness: required fields present,
        enum membership valid, numeric ranges satisfied (`mu_value`
        between `0.00` and `1.00` inclusive; `coverage_pct` between `0`
        and `100` inclusive; `depth_inches` at least `0`; `worked_hours`
        greater than `0`; lengths greater than `0`; `effective_from`
        strictly before `effective_until`; `start_utc` strictly before
        `end_utc`; `observed_at` and `measured_at` not ahead of the
        logical clock) (else `ERR_VALIDATION`)."
        PRD §3.3: "a `surface_type` of `RUNWAY`, `TAXIWAY`, or `APRON`".

        Design: Corner/entities/surface_create_with_invalid_enum_rejected
        """
        resp = api.create_surface(
            create_surface_payload(surface_code="HEL-01",
                                   surface_type="HELIPAD", length_ft=100,
                                   width_ft=100, priority_rank=9),
            system_admin_headers)
        validate_error(resp, ApiErrorId.ERR_VALIDATION, 400)

    def test_surface_area_computed_field_input_ignored(
            self, api, system_admin_headers):
        """PRD §3.3: "The server computes `area_sqft` as `length_ft`
        multiplied by `width_ft`; any client-supplied value for `area_sqft` is
        ignored."

        Design: Corner/entities/surface_area_computed_field_input_ignored
        """
        resp = api.create_surface(
            create_surface_payload(surface_code="RWY-09L", length_ft=5000,
                                   width_ft=150, priority_rank=1,
                                   area_sqft=1),
            system_admin_headers)
        data = validate_success(resp, 201)
        assert data["area_sqft"] == 750000, (
            f"area_sqft must be 5000 x 150 = 750000, got {data['area_sqft']}")

    def test_system_fields_input_ignored_on_create(
            self, api, ops_controller_headers):
        """PRD §2.4: "The `id` is a server-minted UUID with no type prefix —
        it does not embed the entity name or any namespace." and "`version`
        (an integer that starts at `1` on creation and increments by exactly
        `1` on every state transition or mutation".

        Design: Corner/entities/system_fields_input_ignored_on_create
        """
        resp = api.create_snow_event(
            create_snow_event_payload(
                event_code="SNOW-D2",
                id="00000000-0000-0000-0000-000000000000", version=99),
            ops_controller_headers)
        data = validate_success(resp, 201)
        assert data["id"] != "00000000-0000-0000-0000-000000000000"
        assert is_valid_uuid(data["id"])
        assert data["version"] == 1, (
            f"client-supplied version 99 must be ignored, got "
            f"{data['version']}")


class TestResourceNotFound:
    def test_snow_event_get_not_found_returns_404(
            self, api, ops_controller_headers):
        """PRD §2.7: "Each missing reference yields the resource-specific 404
        variant: `ERR_EVENT_NOT_FOUND`, `ERR_SURFACE_NOT_FOUND`,
        `ERR_PRODUCT_NOT_FOUND`, `ERR_EQUIPMENT_NOT_FOUND`,
        `ERR_REPORT_NOT_FOUND`, `ERR_ASSESSMENT_NOT_FOUND`,
        `ERR_NOTAM_NOT_FOUND`, `ERR_APPLICATION_NOT_FOUND`, or
        `ERR_SHIFT_NOT_FOUND`."

        Design: Corner/entities/snow_event_get_not_found_returns_404
        """
        resp = api.get_snow_event(NON_EXISTENT_UUID, ops_controller_headers)
        validate_error(resp, ApiErrorId.ERR_EVENT_NOT_FOUND, 404)

    def test_surface_get_not_found_returns_404(self, api,
                                               system_admin_headers):
        """PRD §2.7: "Each missing reference yields the resource-specific 404
        variant: `ERR_EVENT_NOT_FOUND`, `ERR_SURFACE_NOT_FOUND`,
        `ERR_PRODUCT_NOT_FOUND`, `ERR_EQUIPMENT_NOT_FOUND`,
        `ERR_REPORT_NOT_FOUND`, `ERR_ASSESSMENT_NOT_FOUND`,
        `ERR_NOTAM_NOT_FOUND`, `ERR_APPLICATION_NOT_FOUND`, or
        `ERR_SHIFT_NOT_FOUND`."

        Design: Corner/entities/surface_get_not_found_returns_404
        """
        resp = api.get_surface(NON_EXISTENT_UUID, system_admin_headers)
        validate_error(resp, ApiErrorId.ERR_SURFACE_NOT_FOUND, 404)

    def test_report_get_not_found_returns_404(self, api,
                                              airfield_inspector_headers):
        """PRD §2.7: "Each missing reference yields the resource-specific 404
        variant: `ERR_EVENT_NOT_FOUND`, `ERR_SURFACE_NOT_FOUND`,
        `ERR_PRODUCT_NOT_FOUND`, `ERR_EQUIPMENT_NOT_FOUND`,
        `ERR_REPORT_NOT_FOUND`, `ERR_ASSESSMENT_NOT_FOUND`,
        `ERR_NOTAM_NOT_FOUND`, `ERR_APPLICATION_NOT_FOUND`, or
        `ERR_SHIFT_NOT_FOUND`."

        Design: Corner/entities/report_get_not_found_returns_404
        """
        resp = api.get_condition_report(NON_EXISTENT_UUID,
                                        airfield_inspector_headers)
        validate_error(resp, ApiErrorId.ERR_REPORT_NOT_FOUND, 404)

    def test_assessment_get_not_found_returns_404(
            self, api, airfield_inspector_headers):
        """PRD §2.7: "Each missing reference yields the resource-specific 404
        variant: `ERR_EVENT_NOT_FOUND`, `ERR_SURFACE_NOT_FOUND`,
        `ERR_PRODUCT_NOT_FOUND`, `ERR_EQUIPMENT_NOT_FOUND`,
        `ERR_REPORT_NOT_FOUND`, `ERR_ASSESSMENT_NOT_FOUND`,
        `ERR_NOTAM_NOT_FOUND`, `ERR_APPLICATION_NOT_FOUND`, or
        `ERR_SHIFT_NOT_FOUND`."

        Design: Corner/entities/assessment_get_not_found_returns_404
        """
        resp = api.get_friction_assessment(NON_EXISTENT_UUID,
                                           airfield_inspector_headers)
        validate_error(resp, ApiErrorId.ERR_ASSESSMENT_NOT_FOUND, 404)

    def test_notam_get_not_found_returns_404(self, api,
                                             ops_controller_headers):
        """PRD §2.7: "Each missing reference yields the resource-specific 404
        variant: `ERR_EVENT_NOT_FOUND`, `ERR_SURFACE_NOT_FOUND`,
        `ERR_PRODUCT_NOT_FOUND`, `ERR_EQUIPMENT_NOT_FOUND`,
        `ERR_REPORT_NOT_FOUND`, `ERR_ASSESSMENT_NOT_FOUND`,
        `ERR_NOTAM_NOT_FOUND`, `ERR_APPLICATION_NOT_FOUND`, or
        `ERR_SHIFT_NOT_FOUND`."

        Design: Corner/entities/notam_get_not_found_returns_404
        """
        resp = api.get_notam(NON_EXISTENT_UUID, ops_controller_headers)
        validate_error(resp, ApiErrorId.ERR_NOTAM_NOT_FOUND, 404)

    def test_product_get_not_found_returns_404(self, api,
                                               system_admin_headers):
        """PRD §2.7: "Each missing reference yields the resource-specific 404
        variant: `ERR_EVENT_NOT_FOUND`, `ERR_SURFACE_NOT_FOUND`,
        `ERR_PRODUCT_NOT_FOUND`, `ERR_EQUIPMENT_NOT_FOUND`,
        `ERR_REPORT_NOT_FOUND`, `ERR_ASSESSMENT_NOT_FOUND`,
        `ERR_NOTAM_NOT_FOUND`, `ERR_APPLICATION_NOT_FOUND`, or
        `ERR_SHIFT_NOT_FOUND`."

        Design: Corner/entities/product_get_not_found_returns_404
        """
        resp = api.get_chemical_product(NON_EXISTENT_UUID,
                                        system_admin_headers)
        validate_error(resp, ApiErrorId.ERR_PRODUCT_NOT_FOUND, 404)

    def test_application_get_not_found_returns_404(
            self, api, maintenance_lead_headers):
        """PRD §2.7: "Each missing reference yields the resource-specific 404
        variant: `ERR_EVENT_NOT_FOUND`, `ERR_SURFACE_NOT_FOUND`,
        `ERR_PRODUCT_NOT_FOUND`, `ERR_EQUIPMENT_NOT_FOUND`,
        `ERR_REPORT_NOT_FOUND`, `ERR_ASSESSMENT_NOT_FOUND`,
        `ERR_NOTAM_NOT_FOUND`, `ERR_APPLICATION_NOT_FOUND`, or
        `ERR_SHIFT_NOT_FOUND`."

        Design: Corner/entities/application_get_not_found_returns_404
        """
        resp = api.get_chemical_application(NON_EXISTENT_UUID,
                                            maintenance_lead_headers)
        validate_error(resp, ApiErrorId.ERR_APPLICATION_NOT_FOUND, 404)

    def test_shift_get_not_found_returns_404(self, api,
                                             ops_controller_headers):
        """PRD §2.7: "Each missing reference yields the resource-specific 404
        variant: `ERR_EVENT_NOT_FOUND`, `ERR_SURFACE_NOT_FOUND`,
        `ERR_PRODUCT_NOT_FOUND`, `ERR_EQUIPMENT_NOT_FOUND`,
        `ERR_REPORT_NOT_FOUND`, `ERR_ASSESSMENT_NOT_FOUND`,
        `ERR_NOTAM_NOT_FOUND`, `ERR_APPLICATION_NOT_FOUND`, or
        `ERR_SHIFT_NOT_FOUND`."

        Design: Corner/entities/shift_get_not_found_returns_404
        """
        resp = api.get_operator_shift(NON_EXISTENT_UUID,
                                      ops_controller_headers)
        validate_error(resp, ApiErrorId.ERR_SHIFT_NOT_FOUND, 404)


class TestPaginationAndClock:
    def test_surface_list_pagination_envelope(self, api,
                                              system_admin_headers):
        """PRD §2.3: "The default `limit` is `10`, the minimum accepted value
        is `1`, the maximum accepted value is `100`, and the default `offset`
        is `0`." and "Unless an endpoint specifies otherwise, list results are
        sorted by `created_at` ascending."

        Design: Corner/entities/surface_list_pagination_envelope
        """
        from test_helpers import create_surface
        create_surface("RWY-09L", priority_rank=1)
        create_surface("RWY-09R", priority_rank=2)

        data1, meta1 = validate_paginated(
            api.list_surfaces(system_admin_headers, params={"limit": 1}))
        assert len(data1) == 1
        assert data1[0]["surface_code"] == "RWY-09L", (
            "created_at ascending puts the first-registered surface first")
        assert meta1["limit"] == 1
        assert meta1["total_count"] == 2
        assert meta1["has_more"] is True

        data2, meta2 = validate_paginated(
            api.list_surfaces(system_admin_headers,
                              params={"limit": 1, "offset": 1}))
        assert len(data2) == 1
        assert data2[0]["surface_code"] == "RWY-09R"
        assert meta2["offset"] == 1
        assert meta2["has_more"] is False
