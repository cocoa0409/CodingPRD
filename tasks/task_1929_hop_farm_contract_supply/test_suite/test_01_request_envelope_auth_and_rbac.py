"""Request envelope, authentication, authorization, and read consistency."""
from test_helpers import (
    validate_success, validate_error, is_iso8601_timestamp, NON_EXISTENT_UUID,
    ApiErrorId, create_field_payload, create_kiln_payload, create_contract_payload,
    create_lab_test_payload, create_field, create_kiln,
    assert_field, assert_kiln,
)


class TestAuthentication:
    def test_missing_auth_headers_rejected(self, api):
        """PRD §2.1: "A request missing either header, or presenting a role the
        system does not declare, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401)."

        Design: Corner/validations/request_missing_auth_header_returns_unauthenticated
        """
        res = api.create_field(create_field_payload(), headers={})
        validate_error(res, ApiErrorId.ERR_UNAUTHENTICATED)


class TestRoleAuthorization:
    def test_farm_manager_cannot_create_contract(self, api, farm_manager_headers):
        """PRD §2.1: "The `ContractManager` runs the sales desk — contracts and
        amendments, allocation runs and the allocation lifecycle, spot sales, and
        brewery samples." and "a role not permitted to call the endpoint is
        rejected with `ERR_FORBIDDEN` (HTTP 403)."

        Design: Corner/rbac/farm_manager_cannot_create_contract
        """
        res = api.create_contract(create_contract_payload(), farm_manager_headers)
        validate_error(res, ApiErrorId.ERR_FORBIDDEN)

    def test_contract_manager_cannot_post_lab_test(self, api, contract_manager_headers):
        """PRD §2.1: "The `LabTechnician` posts alpha-acid lab tests." and "a role
        not permitted to call the endpoint is rejected with `ERR_FORBIDDEN`
        (HTTP 403)."

        Design: Corner/rbac/contract_manager_cannot_post_lab_test
        """
        res = api.create_lab_test(
            create_lab_test_payload(NON_EXISTENT_UUID, "PROVISIONAL", 12.0),
            contract_manager_headers)
        validate_error(res, ApiErrorId.ERR_FORBIDDEN)

    def test_forbidden_precedes_not_found(self, api, farm_manager_headers):
        """PRD §2.8: "2. Role authorization — the role appears in the endpoint's
        allowed list, else `ERR_FORBIDDEN`." and "3. Path existence — every
        resource identifier in the path resolves, validated left to right, else
        `ERR_NOT_FOUND`." A FarmManager activating a non-existent contract id
        fails the role tier first.

        Design: Corner/validations/forbidden_beats_not_found
        """
        res = api.activate_contract(NON_EXISTENT_UUID, farm_manager_headers)
        validate_error(res, ApiErrorId.ERR_FORBIDDEN)


class TestRetrieval:
    def test_contract_get_not_found(self, api, contract_manager_headers):
        """PRD §2.9: "That identifier is validated for existence before any
        business rule is evaluated, and an unknown identifier is rejected with
        `ERR_NOT_FOUND` (HTTP 404)."

        Design: Corner/entities/contract_get_not_found_returns_404
        """
        res = api.get_contract(NON_EXISTENT_UUID, contract_manager_headers)
        validate_error(res, ApiErrorId.ERR_NOT_FOUND)

    def test_field_get_response_envelope(self, api, farm_manager_headers):
        """PRD §2.2: "The `api_request_id` is a server-generated unique identifier
        for the request that starts with `req_`." and "The `response_type` is
        either "object" for a single resource or "array" for a list of resources."

        Design: Corner/endpoints/field_get_response_envelope
        """
        field = create_field(name="F1", acreage=100)
        res = api.get_field(field["id"], farm_manager_headers)
        assert res.status_code == 200, f"Expected 200, got {res.status_code}: {res.text}"
        body = res.json()
        meta = body["meta"]
        assert isinstance(meta.get("api_request_id"), str) and meta["api_request_id"]
        assert meta["api_request_id"].startswith("req_"), (
            "api_request_id starts with req_")
        assert is_iso8601_timestamp(meta.get("api_request_timestamp", "")), (
            "api_request_timestamp must be ISO 8601")
        assert body["response_type"] == "object"
        data = body["data"]
        assert data["name"] == "F1"
        assert data["acreage"] == 100
        assert_field(data)

    def test_kiln_create_immediately_visible(self, api, farm_manager_headers):
        """PRD §2.2: "Unless otherwise noted, operations that create or modify a
        resource will return the created or updated resource object in the data
        field." PRD §2.4: "`version`, an integer that starts at its initial value
        on creation and increments by exactly 1 on every mutation of that
        resource."

        Design: Corner/consistency_model/immediate_visibility_on_create
        """
        res = api.create_kiln(create_kiln_payload(name="K1"), farm_manager_headers)
        kiln = validate_success(res, 201)
        assert_kiln(kiln)
        assert kiln["version"] == 1, "A new resource carries its initial version"
        fetched = validate_success(api.get_kiln(kiln["id"], farm_manager_headers), 200)
        assert fetched["name"] == "K1"
        assert fetched["version"] == 1, "Immediate read agrees with the create response"
