"""Master data creation defaults, request-shape validation, auth, pagination,
and the response envelope."""
from test_helpers import (
    NON_EXISTENT_UUID,
    TEST_USERS,
    advance_clock,
    assert_fleet_account,
    assert_service_call,
    assert_van_stock_item,
    create_fleet_account_payload,
    create_rate_card_payload,
    create_standard_rate_card,
    create_technician,
    create_technician_payload,
    create_vehicle,
    create_vehicle_payload,
    intake_call,
    triage_call,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers import ApiErrorId

OPS = TEST_USERS["ops_admin_headers"]
DISPATCHER = TEST_USERS["dispatcher_headers"]


class TestFleetAccountCreationDefaults:
    def test_create_fleet_account_applies_defaults(self, api):
        """PRD: "A fleet may also declare `payment_terms_days` (defaulting to 30
        when omitted)" and "New fleets begin `ACTIVE` with `suspension_reason`
        `NONE` and a `month_to_date_spend_cents` of zero."

        Design: Corner/entities/create_fleet_account_applies_defaults
        """
        create_standard_rate_card()
        resp = api.create_fleet_account(
            create_fleet_account_payload(account_number="ACCT-9001"), OPS)
        assert resp.status_code == 201, resp.text
        fleet = validate_success(resp, 201)
        assert_fleet_account(fleet)
        assert fleet["payment_terms_days"] == 30, (
            "omitted payment_terms_days must default to 30")
        assert fleet["status"] == "ACTIVE"
        assert fleet["suspension_reason"] == "NONE"
        assert fleet["month_to_date_spend_cents"] == 0
        assert fleet["effective_discount_tier"] == "STANDARD", (
            "zero month-to-date spend earns the STANDARD tier")


class TestVanStockDefaults:
    def test_van_stock_reorder_point_default_applied(self, api):
        """PRD: "a `reorder_point` defaulting to 2" for van stock items.

        Design: Corner/entities/van_stock_reorder_point_default_applied
        """
        tech, _headers = create_technician()
        resp = api.create_van_stock_item(
            tech["id"],
            {"part_number": "ALT-104", "description": "Alternator",
             "part_class": "ENGINE", "qty_on_hand": 5,
             "unit_cost_cents": 21000, "unit_retail_cents": 34999},
            OPS)
        assert resp.status_code == 201, resp.text
        item = validate_success(resp, 201)
        assert_van_stock_item(item)
        assert item["reorder_point"] == 2, (
            "omitted reorder_point must default to 2")
        assert item["restock_pending"] is False, (
            "no restock request exists at stocking, so the flag is clear")


class TestUniquenessAndExistence:
    def test_create_vehicle_duplicate_vin_rejected(self, api):
        """PRD: "A duplicate `account_number` at creation is rejected with
        `ERR_DUPLICATE_VIN` — the shared uniqueness error that also guards
        vehicle VINs and technician employee codes."

        Design: Corner/entities/create_vehicle_duplicate_vin_rejected
        """
        create_vehicle(vin="1FUJHHDR1LLLW0002")
        resp = api.create_vehicle(
            create_vehicle_payload(vin="1FUJHHDR1LLLW0002",
                                   unit_number="R-02", odometer_miles=50000),
            DISPATCHER)
        validate_error(resp, ApiErrorId.ERR_DUPLICATE_VIN)
        data, meta = validate_paginated(api.list_vehicles(DISPATCHER))
        assert meta["total_count"] == 1, (
            "the rejected duplicate must not create a second vehicle row")

    def test_get_missing_vehicle_returns_not_found(self, api):
        """PRD: "the request is rejected immediately with `ERR_NOT_FOUND` at
        the first identifier that does not resolve to an existing resource."

        Design: Corner/entities/get_missing_vehicle_returns_not_found
        """
        resp = api.get_vehicle(NON_EXISTENT_UUID, DISPATCHER)
        assert resp.status_code == 404
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND)


class TestRequestShapeValidation:
    def test_vehicle_create_missing_vin_rejected(self, api):
        """PRD: "then request-shape validation (missing required fields,
        mistyped values, unknown fields, non-positive quantities, inverted
        windows) with `ERR_VALIDATION`"

        Design: Corner/entities/vehicle_create_missing_vin_rejected
        """
        payload = create_vehicle_payload()
        del payload["vin"]
        resp = api.create_vehicle(payload, DISPATCHER)
        validate_error(resp, ApiErrorId.ERR_VALIDATION)

    def test_unknown_payload_field_rejected(self, api):
        """PRD: "then request-shape validation (missing required fields,
        mistyped values, unknown fields, non-positive quantities, inverted
        windows) with `ERR_VALIDATION`"

        Design: Corner/entities/unknown_payload_field_rejected
        """
        payload = create_vehicle_payload(nickname="Old Blue")
        resp = api.create_vehicle(payload, DISPATCHER)
        validate_error(resp, ApiErrorId.ERR_VALIDATION)

    def test_technician_create_invalid_enum_rejected(self, api):
        """PRD: "then enum membership with `ERR_INVALID_ENUM`" — a
        certification outside the declared set is not a shape error but an
        enum-membership failure.

        Design: Corner/entities/technician_create_invalid_enum_rejected
        """
        resp = api.create_technician(
            create_technician_payload(full_name="Bad Cert",
                                      employee_code="T-199",
                                      certifications=["ROCKET"]),
            OPS)
        validate_error(resp, ApiErrorId.ERR_INVALID_ENUM)


class TestAuthAndValidationOrder:
    def test_missing_auth_headers_returns_unauthenticated(self, api):
        """PRD: "a request missing either header, or carrying a blank value in
        either, is rejected with `ERR_UNAUTHENTICATED`."

        Design: Corner/validations/missing_auth_headers_returns_unauthenticated
        """
        resp = api.create_vehicle(create_vehicle_payload(), headers={})
        assert resp.status_code == 401
        validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED)

    def test_existence_beats_shape_on_missing_resource(self, api):
        """PRD: "Across a whole request, checks are evaluated in a fixed
        priority order so that earlier failures are never masked by later
        ones." — existence resolution is "followed by" request-shape
        validation, so a triage call naming a non-existent call with a body
        that also lacks the required severity reports ERR_NOT_FOUND.

        Design: Corner/validations/existence_beats_shape_on_missing_resource
        """
        resp = api.triage_service_call(NON_EXISTENT_UUID, {}, DISPATCHER)
        assert resp.status_code == 404
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND)


class TestLogicalClock:
    def test_clock_regression_rejected(self, api):
        """PRD: "the clock may only move forward, and an attempt to set it to
        an earlier instant than the current value is rejected with
        `ERR_CLOCK_REGRESSION`."

        Design: Corner/validations/clock_regression_rejected
        """
        advance_clock("2026-08-05T12:00:00Z")
        resp = api.set_clock("2026-08-05T11:59:59Z", OPS)
        assert resp.status_code == 422
        validate_error(resp, ApiErrorId.ERR_CLOCK_REGRESSION)


class TestListPagination:
    def test_list_pagination_envelope_and_filtering(self, api):
        """PRD: "Paginated and non-paginated list-based responses include the
        following fields in the `meta` object of the response envelope:
        `limit`, `offset`, `total_count`, and `has_more`."

        Design: Corner/entities/list_pagination_envelope_and_filtering
        """
        for year in (2024, 2025, 2026):
            api_resp = api.create_rate_card(
                create_rate_card_payload(
                    name=f"Y{year}",
                    effective_from=f"{year}-01-01T00:00:00Z",
                    effective_to=f"{year}-12-31T23:59:59Z"),
                OPS)
            assert api_resp.status_code == 201, api_resp.text

        page1, meta1 = validate_paginated(
            api.list_rate_cards(DISPATCHER, params={"limit": 2, "offset": 0}))
        assert len(page1) == 2
        assert meta1["total_count"] == 3
        assert meta1["has_more"] is True
        assert meta1["limit"] == 2 and meta1["offset"] == 0

        page2, meta2 = validate_paginated(
            api.list_rate_cards(DISPATCHER, params={"limit": 2, "offset": 2}))
        assert len(page2) == 1
        assert meta2["total_count"] == 3
        assert meta2["has_more"] is False


class TestErrorEnvelope:
    def test_error_envelope_shape_on_business_rejection(self, api):
        """PRD: "The `meta` object for error responses contains only
        `api_request_id` and `api_request_timestamp`." and the error body
        carries `error_id` plus a human-readable `message`.

        Design: Corner/errors/error_envelope_shape_on_business_rejection
        """
        veh = create_vehicle()
        call = intake_call(veh["id"], symptom_category="LIGHTING")
        triage_call(call["id"], severity="DEFERRED")
        # A second triage is not a declared transition -> business rejection.
        resp = api.triage_service_call(call["id"], {"severity": "BLOCKING"},
                                       DISPATCHER)
        assert resp.status_code == 409
        body = resp.json()
        assert body["response_type"] == "error"
        assert set(body["meta"].keys()) == {"api_request_id",
                                            "api_request_timestamp"}, (
            "error meta must contain only api_request_id and "
            "api_request_timestamp")
        assert isinstance(body["meta"]["api_request_id"], str)
        assert body["data"]["error_id"] == "ERR_INVALID_STATE"
        assert isinstance(body["data"]["message"], str) and \
            body["data"]["message"].strip()


class TestServiceCallReadback:
    def test_get_endpoints_return_computed_fields(self, api):
        """PRD: "Priority follows severity directly: `BLOCKING` calls become
        `P1_EMERGENCY`, `DRIVABLE` become `P2_URGENT`, and `DEFERRED` become
        `P3_STANDARD`." — the triage-derived fields are returned verbatim by
        the single-resource read.

        Design: Corner/endpoints/get_endpoints_return_computed_fields
        """
        advance_clock("2026-08-05T09:00:00Z")
        veh = create_vehicle()
        call = intake_call(veh["id"])
        triage_call(call["id"], severity="DRIVABLE")

        data = validate_success(api.get_service_call(call["id"], DISPATCHER))
        assert_service_call(data)
        assert data["priority"] == "P2_URGENT"
        assert data["after_hours"] is False
        assert data["required_certification"] == "ENGINE"
        assert data["required_part_class"] == "ENGINE"
        assert data["status"] == "TRIAGED"
