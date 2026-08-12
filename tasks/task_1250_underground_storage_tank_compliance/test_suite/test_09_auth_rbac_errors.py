"""Authentication, role authorization, ownership, and the not-found catalogue
(PRD §2.1, §2.6, §2.7, §5)."""
import pytest
from test_helpers import (
    validate_success, validate_error, validate_paginated,
    ApiErrorId, TEST_USERS, NON_EXISTENT_UUID, make_technician_headers,
    create_facility_payload, create_tank_payload, create_technician_payload,
    create_facility, create_tank, create_technician,
)

OWNER = TEST_USERS["facility_owner_headers"]
OWNER2 = TEST_USERS["facility_owner_2_headers"]
ADMIN = TEST_USERS["contractor_admin_headers"]
READER = TEST_USERS["any_headers"]


class TestAuthContext:
    def test_missing_auth_header_rejected(self, api):
        """PRD §2.1: "All interactions with the API must be authenticated through
        two mandatory HTTP headers: `X-User-ID`, identifying the acting user, and
        `X-User-Role`, naming their operational capacity. A request in which either
        header is missing or empty is rejected with
        `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`."

        Design: Corner/validations/missing_auth_header_rejected
        """
        res = api.create_facility(
            create_facility_payload(facility_name="NoAuth"), headers={})
        validate_error(res, ApiErrorId.ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER,
                       expected_status=400)


class TestRoleAuthorization:
    def test_wrong_role_facility_create_forbidden(self, api):
        """PRD §2.1: "When the caller's role is not among the roles an endpoint
        authorizes, the request is rejected with `ERR_INSUFFICIENT_PERMISSIONS`."
        PRD §4: POST /facilities is authorized to `FacilityOwner`.

        Design: Corner/validations/wrong_role_facility_create_forbidden
        """
        tech = create_technician([], full_name="T")
        res = api.create_facility(
            create_facility_payload(facility_name="WrongRole"),
            make_technician_headers(tech["id"]))
        validate_error(res, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS, expected_status=403)

    def test_technician_cannot_create_technicians_forbidden(self, api):
        """PRD §2.1: "When the caller's role is not among the roles an endpoint
        authorizes, the request is rejected with `ERR_INSUFFICIENT_PERMISSIONS`."
        PRD §4: POST /technicians is authorized to `ContractorAdmin`.

        Design: Corner/rbac/technician_cannot_create_technicians_forbidden
        """
        first = create_technician([], full_name="First")
        res = api.create_technician(
            create_technician_payload(full_name="Second"),
            make_technician_headers(first["id"]))
        validate_error(res, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS, expected_status=403)

    def test_any_role_can_read_lists(self, api):
        """PRD §2.1: "The system recognizes six roles: `FacilityOwner`,
        `ContractorAdmin`, `Technician`, `ComplianceReviewer`, `StateRegulator`,
        and `Any` — the last being a read-only capacity shared by every
        authenticated caller across all list and detail endpoints."

        Design: Corner/rbac/any_role_can_read_lists
        """
        facility = create_facility(facility_name="Read Site")
        detail = validate_success(api.get_facility(facility["id"], READER), 200)
        assert detail["facility_name"] == "Read Site"
        data, meta = validate_paginated(
            api.list_deficiencies(READER, params={"facility_id": facility["id"]}))
        assert meta["total_count"] == 0
        data, meta = validate_paginated(
            api.list_operators(READER, params={"facility_id": facility["id"]}))
        assert meta["total_count"] == 0


class TestOwnership:
    def test_non_owner_activate_forbidden(self, api):
        """PRD §2.6: "Every operation gated to a `FacilityOwner` — tank
        registration and closure, component registration, deficiency correction,
        operator designation, monthly record keeping, release reporting, fund
        claims — requires the caller's `X-User-ID` to equal the parent facility's
        `owner_account_id`; a mismatch is rejected with `ERR_NOT_RESOURCE_OWNER`."

        Design: Corner/validations/non_owner_activate_forbidden
        """
        facility = create_facility("owner-1", facility_name="Owned")
        create_tank(facility["id"], "owner-1")  # activation precondition met
        res = api.activate_facility(facility["id"], OWNER2)
        validate_error(res, ApiErrorId.ERR_NOT_RESOURCE_OWNER, expected_status=403)


class TestNotFoundCatalogue:
    def test_result_record_not_found(self, api):
        """PRD §2.6: "the system validates existence in a strict left-to-right
        order, rejecting with the not-found error of the first missing resource
        before examining later ones" and "`ERR_RESULT_RECORD_NOT_FOUND`" names the
        resource type that failed lookup.
        PRD §2.2: "The `error_id` is a unique, machine-readable string that
        identifies the specific error." and "The `message` provides a
        human-readable explanation of what went wrong."

        Design: Corner/errors/result_record_not_found
        """
        res = api.get_result_record(NON_EXISTENT_UUID, READER)
        error = validate_error(res, ApiErrorId.ERR_RESULT_RECORD_NOT_FOUND,
                               expected_status=404)
        assert isinstance(error["message"], str) and error["message"].strip()

    def test_not_found_variants_across_resources(self, api):
        """PRD §2.6: "the system validates existence in a strict left-to-right
        order, rejecting with the not-found error of the first missing resource
        before examining later ones: `ERR_FACILITY_NOT_FOUND`,
        `ERR_TANK_SYSTEM_NOT_FOUND`, `ERR_COMPONENT_NOT_FOUND`,
        `ERR_TECHNICIAN_NOT_FOUND`, `ERR_SERVICE_ORDER_NOT_FOUND`,
        `ERR_RESULT_RECORD_NOT_FOUND`, `ERR_DEFICIENCY_NOT_FOUND`,
        `ERR_SUBMISSION_NOT_FOUND`, `ERR_RECORD_NOT_FOUND`,
        `ERR_OPERATOR_NOT_FOUND`, `ERR_TRAINING_RECORD_NOT_FOUND`,
        `ERR_RELEASE_EVENT_NOT_FOUND`, and `ERR_FUND_CLAIM_NOT_FOUND` each name the
        resource type that failed lookup."

        Design: Corner/errors/not_found_variants_across_resources
        """
        cases = [
            (lambda: api.get_tank_system(NON_EXISTENT_UUID, READER),
             ApiErrorId.ERR_TANK_SYSTEM_NOT_FOUND),
            (lambda: api.get_component(NON_EXISTENT_UUID, READER),
             ApiErrorId.ERR_COMPONENT_NOT_FOUND),
            (lambda: api.get_technician(NON_EXISTENT_UUID, READER),
             ApiErrorId.ERR_TECHNICIAN_NOT_FOUND),
            (lambda: api.get_service_order(NON_EXISTENT_UUID, READER),
             ApiErrorId.ERR_SERVICE_ORDER_NOT_FOUND),
            (lambda: api.get_deficiency(NON_EXISTENT_UUID, READER),
             ApiErrorId.ERR_DEFICIENCY_NOT_FOUND),
            (lambda: api.get_submission(NON_EXISTENT_UUID, READER),
             ApiErrorId.ERR_SUBMISSION_NOT_FOUND),
            (lambda: api.get_release_detection_record(NON_EXISTENT_UUID, READER),
             ApiErrorId.ERR_RECORD_NOT_FOUND),
            (lambda: api.get_operator(NON_EXISTENT_UUID, READER),
             ApiErrorId.ERR_OPERATOR_NOT_FOUND),
            (lambda: api.get_training_record(NON_EXISTENT_UUID, READER),
             ApiErrorId.ERR_TRAINING_RECORD_NOT_FOUND),
            (lambda: api.get_release_event(NON_EXISTENT_UUID, READER),
             ApiErrorId.ERR_RELEASE_EVENT_NOT_FOUND),
            (lambda: api.get_fund_claim(NON_EXISTENT_UUID, READER),
             ApiErrorId.ERR_FUND_CLAIM_NOT_FOUND),
        ]
        for call, expected in cases:
            validate_error(call(), expected, expected_status=404)


class TestMalformedPayloads:
    def test_missing_required_field_rejected(self, api):
        """PRD §2.7: "A payload that is malformed in its own right — a required
        field missing, a malformed value, an unrecognized enum, a bad `YYYY-MM`
        month format, an empty `expense_lines` array, or a `readings` object that
        does not match the schema of the order's service type — is rejected with
        `ERR_INVALID_REQUEST`."

        Design: Corner/errors/missing_required_field_rejected
        """
        facility = create_facility(facility_name="Req Site")
        payload = create_tank_payload(facility["id"])
        del payload["tank_tag"]
        res = api.create_tank_system(payload, OWNER)
        validate_error(res, ApiErrorId.ERR_INVALID_REQUEST, expected_status=400)
