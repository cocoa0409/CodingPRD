"""Customers, sites, catalog entries, and global envelope rules (PRD §2, §3.1, §3.2)."""
import pytest

from test_helpers import (
    NON_EXISTENT_UUID,
    TEST_USERS,
    ApiErrorId,
    assert_accessory_kit,
    assert_customer,
    assert_site,
    create_accessory_kit,
    create_customer,
    create_site,
    is_iso8601_timestamp,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers import (
    create_accessory_kit_payload,
    create_contract_payload,
    create_customer_payload,
    create_site_payload,
)

TEST_SALES = TEST_USERS["sales_engineer_headers"]
TEST_DEPOT = TEST_USERS["depot_manager_headers"]


class TestCustomerOnboarding:
    def test_customer_create_applies_optional_field_defaults(self, api):
        """PRD §3.1: "The `credit_status` begins at `GOOD` unless explicitly set to
        `WATCH` or `HOLD`, and it gates fiscal operations".
        PRD §3.1: "The `standby_contract` flag, defaulting to false, records whether
        the customer holds a standby emergency-response agreement".
        PRD §3.1: "For standby customers, `sla_response_minutes` states the guaranteed
        on-site response time in minutes, defaulting to 240 and required to be a
        positive integer."
        PRD §3.1: "Finally, `loyalty_discount_pct` is a fractional discount,
        defaulting to 0, that must be at least 0 and strictly less than 1".
        PRD §2.5: "At startup the logical clock reads 2026-08-01T00:00:00Z".

        Design: Corner/entities/customer_create_defaults_applied
        """
        res = api.create_customer(
            create_customer_payload(name="Default Co", billing_email="ap@default.example"),
            TEST_SALES,
        )
        customer = validate_success(res, 201)
        assert_customer(customer)
        assert customer["credit_status"] == "GOOD"
        assert customer["standby_contract"] is False
        assert customer["sla_response_minutes"] == 240
        assert customer["loyalty_discount_pct"] == 0
        assert customer["version"] == 1
        assert is_iso8601_timestamp(customer["created_at"])
        assert customer["created_at"].startswith("2026-08-01T00:00:00"), (
            "created_at must be stamped from the startup logical clock, "
            f"got {customer['created_at']!r}"
        )


class TestContractCreationValidation:
    def test_contract_create_missing_offhire_date_returns_validation(self, api):
        """PRD §3.3: "The creation payload names the renting `customer_id` and the
        deployment `site_id` (the site's jurisdiction will drive emissions screening),
        describes the electrical requirement as a `load_profile` array whose entries
        each pair a `load_type` of `CONTINUOUS`, `INTERMITTENT`, or `STANDBY` with a
        `nameplate_kw`, and fixes the rental window with `start_date` and
        `expected_offhire_date`."
        PRD §2.8: "The seventh tier checks payload and constraint well-formedness:
        malformed payloads, invalid enumerations, wrong conditional fields, and
        duplicate catalog codes (`ERR_VALIDATION`)".

        Design: Corner/entities/contract_create_missing_required_returns_validation
        """
        customer = create_customer()
        site = create_site(customer["id"])

        payload = create_contract_payload(customer["id"], site["id"])
        del payload["expected_offhire_date"]
        res = api.create_contract(payload, TEST_SALES)
        validate_error(res, ApiErrorId.ERR_VALIDATION, expected_status=400)

        data, meta = validate_paginated(
            api.list_contracts(TEST_SALES, params={"customer_id": customer["id"]})
        )
        assert meta["total_count"] == 0, "rejected create must not persist a contract"
        assert data == []

    def test_inverted_window_on_contract_create_returns_invalid_date_range(self, api):
        """PRD §3.3: "The start must be strictly before the expected end; an inverted
        or empty window is rejected with `ERR_INVALID_DATE_RANGE` (HTTP 422)."

        Design: Corner/validations/invalid_date_range_on_contract_create
        """
        customer = create_customer()
        site = create_site(customer["id"])

        res = api.create_contract(
            create_contract_payload(
                customer["id"],
                site["id"],
                start_date="2026-09-10T00:00:00Z",
                expected_offhire_date="2026-09-01T00:00:00Z",
            ),
            TEST_SALES,
        )
        validate_error(res, ApiErrorId.ERR_INVALID_DATE_RANGE, expected_status=422)

        _, meta = validate_paginated(
            api.list_contracts(TEST_SALES, params={"customer_id": customer["id"]})
        )
        assert meta["total_count"] == 0, "rejected create must not persist a contract"


class TestSiteRegistration:
    def test_site_computed_tank_level_input_ignored(self, api):
        """PRD §3.1: "A site's `tank_level_liters` is never written directly: it is a
        computed figure that starts at zero and thereafter equals the sum of all
        fuel-delivery telemetry minus all pump-out telemetry recorded over every
        contract at that site."

        Design: Corner/entities/site_computed_tank_level_input_ignored
        """
        customer = create_customer()
        res = api.create_site(
            create_site_payload(customer["id"], tank_level_liters=999),
            TEST_SALES,
        )
        site = validate_success(res, 201)
        assert_site(site)
        assert site["tank_level_liters"] == 0, (
            "client-supplied value for the computed tank level must be ignored"
        )

    def test_site_not_found_returns_404(self, api):
        """PRD §2.10: "the request is rejected with `ERR_NOT_FOUND` (HTTP 404) at the
        first identifier that does not correspond to an existing resource".

        Design: Corner/entities/site_not_found_returns_404
        """
        res = api.get_site(NON_EXISTENT_UUID, TEST_SALES)
        validate_error(res, ApiErrorId.ERR_NOT_FOUND, expected_status=404)

    def test_site_create_with_ghost_customer_returns_reference_not_found(self, api):
        """PRD §2.10: "a body reference to a non-existent resource is rejected with
        `ERR_REFERENCE_NOT_FOUND` (HTTP 422)."

        Design: Corner/errors/body_fk_reference_not_found
        """
        res = api.create_site(
            create_site_payload(NON_EXISTENT_UUID, name="Ghost Yard"),
            TEST_SALES,
        )
        validate_error(res, ApiErrorId.ERR_REFERENCE_NOT_FOUND, expected_status=422)


class TestAccessoryKitCatalog:
    def test_duplicate_kit_code_rejected_and_kit_has_light_fields(self, api):
        """PRD §3.2: "A `DepotManager` publishes each catalog entry with a unique
        `kit_code` (such as CABLE-400A) — a duplicate code is rejected with
        `ERR_VALIDATION`".
        PRD §2.4: "An accessory kit catalog entry and a telemetry event each carry
        only `id` and `created_at`: both `updated_at` and `version` are absent from
        these two resources".

        Design: Corner/entities/accessory_kit_immutable_and_unique_code
        """
        kit = create_accessory_kit(kit_code="CABLE-400A")
        assert_accessory_kit(kit)

        dup = api.create_accessory_kit(
            create_accessory_kit_payload(kit_code="CABLE-400A", description="duplicate"),
            TEST_DEPOT,
        )
        validate_error(dup, ApiErrorId.ERR_VALIDATION, expected_status=400)

        fetched = validate_success(api.get_accessory_kit(kit["id"], TEST_DEPOT), 200)
        assert is_iso8601_timestamp(fetched["created_at"])
        assert "version" not in fetched, "kit must not carry version (PRD §2.4)"
        assert "updated_at" not in fetched, "kit must not carry updated_at (PRD §2.4)"


class TestErrorEnvelope:
    def test_error_envelope_shape_on_404(self, api):
        """PRD §2.2: "The `meta` object for error responses contains only
        `api_request_id` and `api_request_timestamp`."
        PRD §2.2: "The `error_id` is a unique, machine-readable string that identifies
        the specific error."

        Design: Corner/errors/error_envelope_shape_on_404
        """
        res = api.get_equipment_unit(NON_EXISTENT_UUID, TEST_DEPOT)
        error = validate_error(res, ApiErrorId.ERR_NOT_FOUND, expected_status=404)
        assert error["message"].strip(), "error message must be present"
        body = res.json()
        assert body["response_type"] == "error"
        assert isinstance(body["meta"].get("api_request_id"), str)
        assert body["meta"]["api_request_id"] != ""
