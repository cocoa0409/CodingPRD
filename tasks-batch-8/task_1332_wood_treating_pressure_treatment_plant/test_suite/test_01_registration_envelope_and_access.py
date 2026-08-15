"""Plant registration, response envelope, pagination, auth-header and
not-found behavior, and role-based access control (PRD §2.1–§2.4, §2.8, §3.1)."""
import pytest

from test_helpers import (
    NON_EXISTENT_UUID,
    TEST_USERS,
    ApiErrorId,
    assert_plant,
    create_charge_payload,
    create_cylinder_payload,
    create_plant_payload,
    is_valid_uuid,
    setup_cylinder,
    setup_plant,
    validate_error,
    validate_paginated,
    validate_success,
)

OP = TEST_USERS["plant_operator_headers"]
LAB = TEST_USERS["lab_technician_headers"]
CO = TEST_USERS["compliance_officer_headers"]


class TestPlantRegistration:
    def test_create_plant_with_valid_fields_returns_201(self, api):
        """PRD §3.1: "The new plant starts in `LICENSED` status, its
        `compliance_score` initialized to 1000 and its
        `hazardous_waste_liability_cents` ledger to zero."

        Design: Corner/entities/create_plant_with_valid_fields_returns_201
        """
        resp = api.create_plant(
            create_plant_payload(plant_name="Cascade Treating",
                                 alsc_license_number="ALSC-CA-0042"), CO)
        data = validate_success(resp, 201)
        assert_plant(data)
        assert data["plant_name"] == "Cascade Treating"
        assert data["alsc_license_number"] == "ALSC-CA-0042"
        assert data["status"] == "LICENSED"
        assert data["compliance_score"] == 1000
        assert data["hazardous_waste_liability_cents"] == 0

    def test_create_plant_missing_required_field_returns_400(self, api):
        """PRD §2.9: "a malformed body, a missing required field, or a value
        outside a declared enum set is rejected up front with
        `ERR_INVALID_REQUEST` (400) or `ERR_INVALID_ENUM` (400)."

        Design: Corner/entities/create_plant_missing_required_field_returns_400
        """
        resp = api.create_plant({"alsc_license_number": "ALSC-1"}, CO)
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST.value)


class TestResponseEnvelope:
    def test_system_fields_input_ignored(self, api):
        """PRD §2.4: "`id` is a server-minted UUID with no type prefix."
        PRD §2.4: "`version` is a system-managed integer that increments with
        every modification to the resource, whether the mutation is
        client-driven or system-driven".

        Design: Corner/entities/system_fields_input_ignored
        """
        resp = api.create_plant(
            create_plant_payload(plant_name="P1", alsc_license_number="A1",
                                 id="spoofed-id", version=99), CO)
        data = validate_success(resp, 201)
        assert is_valid_uuid(data["id"]), "server must mint its own UUID id"
        assert data["id"] != "spoofed-id"
        assert isinstance(data["version"], int) and data["version"] != 99
        assert data["created_at"]

    def test_response_envelope_structure(self, api):
        """PRD §2.2: "All successful API responses (those with 2xx status
        codes) follow this standard envelope format in their JSON body".
        PRD §2.2: "The `response_type` is either "object" for a single
        resource or "array" for a list of resources."

        Design: Corner/endpoints/response_envelope_structure
        """
        resp = api.create_plant(create_plant_payload(plant_name="P1",
                                                     alsc_license_number="A1"), CO)
        body = resp.json()
        assert resp.status_code == 201
        assert isinstance(body["meta"]["api_request_id"], str)
        assert body["meta"]["api_request_id"].startswith("req_")
        assert isinstance(body["meta"]["api_request_timestamp"], str)
        assert body["response_type"] == "object"
        assert isinstance(body["data"], dict) and body["data"]["plant_name"] == "P1"

    def test_list_plants_pagination_defaults(self, api):
        """PRD §2.3: "`limit` sets the maximum number of items returned: it
        defaults to 10 when omitted, accepts a minimum of 1, and caps at 100.
        `offset` sets how many items to skip and defaults to 0."
        PRD §2.3: "The `meta` object of a list response carries four
        pagination fields: `limit`, `offset`, `total_count`, and `has_more`."

        Design: Corner/entities/list_plants_pagination_defaults
        """
        for i in range(3):
            setup_plant(plant_name=f"P{i}", alsc_license_number=f"A{i}")
        data, meta = validate_paginated(api.list_plants(OP))
        assert meta["limit"] == 10
        assert meta["offset"] == 0
        assert meta["total_count"] == 3
        assert meta["has_more"] is False
        assert len(data) == 3
        for plant in data:
            assert_plant(plant)


class TestAuthAndExistence:
    def test_missing_auth_header_returns_400(self, api):
        """PRD §2.1: "A request missing either header, or carrying a
        syntactically invalid header value, is rejected with
        `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (400)."

        Design: Corner/validations/missing_auth_header_returns_400
        """
        resp = api.list_plants(headers={})
        validate_error(resp, ApiErrorId.ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER.value)

    def test_plant_not_found_returns_404(self, api):
        """PRD §2.8: "the request is rejected immediately with the 404
        corresponding to the first identifier that does not resolve:
        `ERR_PLANT_NOT_FOUND`, `ERR_CYLINDER_NOT_FOUND`, ... "

        Design: Corner/validations/plant_not_found_returns_404
        """
        resp = api.get_plant(NON_EXISTENT_UUID, OP)
        validate_error(resp, ApiErrorId.ERR_PLANT_NOT_FOUND.value)

    def test_all_not_found_errors_triggerable(self, api):
        """PRD §2.8: "Each path-templated identifier — `plantId`,
        `cylinderId`, `preservativeId`, `customerId`, `chargeId`, ... — is
        resolved in order, and the request is rejected immediately with the
        404 corresponding to the first identifier that does not resolve".

        Design: Corner/errors/all_not_found_errors_triggerable
        """
        resp = api.get_plant(NON_EXISTENT_UUID, OP)
        validate_error(resp, ApiErrorId.ERR_PLANT_NOT_FOUND.value)

        plant = setup_plant()
        resp = api.get_cylinder(plant["id"], NON_EXISTENT_UUID, OP)
        validate_error(resp, ApiErrorId.ERR_CYLINDER_NOT_FOUND.value)

        resp = api.get_charge(plant["id"], NON_EXISTENT_UUID, OP)
        validate_error(resp, ApiErrorId.ERR_CHARGE_NOT_FOUND.value)


class TestRoleAccess:
    def test_plant_operator_cannot_suspend_plant(self, api):
        """PRD §2.1: "A request whose role is not permitted on the target
        endpoint is rejected with `ERR_INSUFFICIENT_PERMISSIONS` (403)."
        PRD §4: suspending a plant's license is authorized for
        ComplianceOfficer only.

        Design: Corner/rbac/plant_operator_cannot_suspend_plant
        """
        plant = setup_plant()
        resp = api.suspend_plant(plant["id"], OP)
        validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS.value)

    def test_lab_technician_cannot_load_charge(self, api):
        """PRD §2.1: "A request whose role is not permitted on the target
        endpoint is rejected with `ERR_INSUFFICIENT_PERMISSIONS` (403)."
        PRD §4: "Stage and load a new charge into a cylinder" is authorized
        for PlantOperator only.

        Design: Corner/rbac/lab_technician_cannot_load_charge
        """
        plant = setup_plant()
        cylinder = setup_cylinder(plant["id"])
        resp = api.load_charge(plant["id"], cylinder["id"],
                               create_charge_payload(), LAB)
        validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS.value)
