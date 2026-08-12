"""Resource creation/retrieval basics, error envelope, and authentication."""
from test_helpers import (
    NON_EXISTENT_UUID,
    NO_HEADERS,
    TEST_USERS,
    api_client,
    assert_region,
    create_corporate_account_payload,
    create_region,
    create_region_payload,
    is_valid_uuid,
    validate_error,
    validate_success,
)


class TestRegionCreation:
    def test_create_region_returns_201_and_system_fields(self, api):
        """PRD §4: "Operations that create a new resource — a region, corporate
        account, wellness program, therapist, license, event booking,
        materialized occurrence, draft invoice, sign-up claim, waiver, or
        satisfaction survey — return a `201 Created` status code."
        PRD §3.1: "A region's `is_active` flag defaults to true; an inactive
        region refuses to let new bookings open scheduling, surfacing
        `ERR_REGION_INACTIVE` (§3.3)."
        PRD §2.5: "`version` (integer): a system-managed integer that
        increments with every modification to the resource, including
        modifications caused by derived-field recomputation, and which
        underpins the optimistic concurrency rules of §2.7."

        Design: Corner/entities/create_region_returns_201_and_system_fields
        """
        payload = create_region_payload(code="SF", name="SF")
        resp = api.create_region(payload, TEST_USERS["platform_admin_headers"])
        assert resp.status_code == 201, f"Expected 201, got {resp.status_code}: {resp.text}"
        region = validate_success(resp, expected_status=201)
        assert_region(region)
        assert is_valid_uuid(region["id"])
        assert region["version"] == 1, f"Fresh region must have version 1, got {region['version']}"
        assert region["is_active"] is True, "is_active must default to true when omitted"

    def test_get_region_by_id_returns_stored_data(self, api):
        """PRD §2.2: "Unless otherwise noted, operations that create or modify
        a resource will return the created or updated resource object in the
        data field."
        PRD §4: "| GET | `/chair-massage/regions/{id}` | Fetch a region |
        PlatformAdmin, Organizer, Therapist |"

        Design: Corner/entities/get_region_by_id_returns_stored_data
        """
        region = create_region(code="SF", name="SF")
        resp = api.get_region(region["id"], TEST_USERS["platform_admin_headers"])
        fetched = validate_success(resp, expected_status=200)
        assert fetched["id"] == region["id"]
        assert fetched["code"] == "SF"
        assert fetched["name"] == "SF"
        assert fetched["base_mileage_rate_cents"] == region["base_mileage_rate_cents"]

    def test_get_region_missing_id_returns_404(self, api):
        """PRD §2.10: "Each identifier must resolve to an existing resource
        before the next is examined, and the request is rejected with
        `ERR_NOT_FOUND` (HTTP 404) at the first identifier that fails to
        resolve."

        Design: Corner/entities/get_region_missing_id_returns_404
        """
        resp = api.get_region(NON_EXISTENT_UUID, TEST_USERS["platform_admin_headers"])
        validate_error(resp, "ERR_NOT_FOUND", expected_status=404)

    def test_create_corporate_account_missing_billing_email_returns_400(self, api):
        """PRD §3.1: "Corporate customers are onboarded as accounts carrying
        the legal `company_name`, the `billing_email` that receives invoices,
        the `region_id` of the account's home region, and a
        `credit_limit_cents` ceiling — zero or greater — on outstanding
        invoiced balance."
        PRD §2.8: "Finally, field-shape validation — an enum outside its
        allowed set, a malformed date, an integer outside its permitted range
        — is reported as `ERR_INVALID_REQUEST` (HTTP 400), except that a
        window duration that does not divide evenly by the session length is
        reported under `ERR_WINDOW_NOT_DIVISIBLE` instead."

        Design: Corner/entities/create_corporate_account_missing_billing_email_returns_400
        """
        region = create_region()
        payload = create_corporate_account_payload(region_id=region["id"])
        del payload["billing_email"]
        resp = api.create_corporate_account(payload, TEST_USERS["platform_admin_headers"])
        validate_error(resp, "ERR_INVALID_REQUEST", expected_status=400)


class TestErrorEnvelopeAndAuth:
    def test_error_envelope_shape(self, api):
        """PRD §2.2: "The `meta` object for error responses contains only
        `api_request_id` and `api_request_timestamp`."
        PRD §2.2: "The `error_id` is a unique, machine-readable string that
        identifies the specific error."

        Design: Corner/errors/error_envelope_shape
        """
        resp = api.get_region(NON_EXISTENT_UUID, TEST_USERS["platform_admin_headers"])
        assert resp.status_code == 404
        body = resp.json()
        assert body["response_type"] == "error"
        assert body["data"]["error_id"] == "ERR_NOT_FOUND"
        assert isinstance(body["data"]["message"], str) and body["data"]["message"]
        assert body["meta"]["api_request_id"], "meta.api_request_id must be present"
        assert body["meta"]["api_request_timestamp"], "meta.api_request_timestamp must be present"

    def test_missing_auth_headers_returns_401(self, api):
        """PRD §2.1: "A request missing either header, or carrying an empty
        value for one, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401)."

        Design: Corner/validations/missing_auth_headers_returns_401
        """
        resp = api_client.get_region(NON_EXISTENT_UUID, NO_HEADERS)
        validate_error(resp, "ERR_UNAUTHENTICATED", expected_status=401)
