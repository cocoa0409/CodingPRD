"""Foundations: organization creation, response envelope, pagination, RBAC."""
from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    assert_company,
    assert_establishment,
    create_case,
    create_company,
    create_company_payload,
    create_employee_payload,
    create_establishment,
    create_establishment_payload,
    get_success_data,
    is_valid_uuid,
    setup_org,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.fixtures import ADMIN, COORDINATOR, OFFICER, SUPERVISOR


class TestCompanyCreation:
    def test_company_creation_success_and_defaults(self, api):
        """PRD §4: "Operations that create a new resource — a company,
        establishment, employee, case, day-count entry, investigation,
        corrective action, summary, hour log, severe-injury report,
        inspection, or citation — return `201 Created`."
        PRD §2.5: "`id` (string): a server-minted UUID with no type prefix."

        Design: Corner/entities/company_creation_success_and_defaults
        """
        resp = api.create_company(
            create_company_payload(legal_name="Corner Co",
                                   fein="11-0000001"),
            ADMIN)
        created = validate_success(resp, 201)
        assert_company(created)
        assert is_valid_uuid(created["id"])

        fetched = get_success_data(api.get_company(created["id"], ADMIN))
        assert fetched["legal_name"] == "Corner Co"
        assert fetched["fein"] == "11-0000001"

    def test_company_missing_required_field_returns_invalid_request(self, api):
        """PRD §3.1: "Creating a company requires `legal_name` and `fein`"
        PRD §2.9: "Request-body well-formedness — malformed JSON, missing
        required fields, enum values outside the declared sets, or unparsable
        ISO dates and datetimes — is rejected with `ERR_INVALID_REQUEST`"

        Design: Corner/entities/company_missing_required_field_returns_invalid_request
        """
        resp = api.create_company({"legal_name": "No Fein Co"}, ADMIN)
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)

    def test_company_duplicate_fein_rejected(self, api):
        """PRD §3.1: "the Federal Employer Identification Number must be
        unique across companies, and a duplicate submission is rejected with
        `ERR_DUPLICATE`."

        Design: Corner/entities/company_duplicate_fein_rejected
        """
        create_company(legal_name="First Co", fein="22-0000002")
        resp = api.create_company(
            create_company_payload(legal_name="Second Co",
                                   fein="22-0000002"),
            ADMIN)
        validate_error(resp, ApiErrorId.ERR_DUPLICATE)


class TestEstablishmentAndEmployeeInputs:
    def test_establishment_is_partially_exempt_default_false(self, api):
        """PRD §3.1: "An establishment in a low-hazard industry may be flagged
        `is_partially_exempt` at creation, defaulting to false"
        PRD §3.1: "A new establishment starts with `posture` `CLEAR`, a
        `risk_score` of zero, and `current_year_hours` of zero."

        Design: Corner/entities/establishment_is_partially_exempt_default_false
        """
        company = create_company(legal_name="Default Co", fein="33-0000003")
        resp = api.create_establishment(
            create_establishment_payload(company["id"], site_name="Site D"),
            ADMIN)
        created = validate_success(resp, 201)
        assert_establishment(created)
        assert created["is_partially_exempt"] is False, (
            "is_partially_exempt defaults to false when omitted")
        assert created["posture"] == "CLEAR"
        assert created["risk_score"] == 0
        assert created["current_year_hours"] == 0

    def test_employee_invalid_enum_employment_status_rejected(self, api):
        """PRD §3.1: "`employment_status` defaults to `ACTIVE` and may later
        become `SEPARATED`."
        PRD §2.9: "Request-body well-formedness — malformed JSON, missing
        required fields, enum values outside the declared sets, or unparsable
        ISO dates and datetimes — is rejected with `ERR_INVALID_REQUEST`"

        Design: Corner/entities/employee_invalid_enum_employment_status_rejected
        """
        company = create_company(legal_name="Enum Co", fein="44-0000004")
        resp = api.create_employee(
            create_employee_payload(company["id"], full_name="Bad Enum",
                                    employment_status="RETIRED"),
            COORDINATOR)
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)


class TestNotFoundAndErrorEnvelope:
    def test_get_nonexistent_case_returns_not_found(self, api):
        """PRD §2.9: "the first identifier that does not resolve, or that does
        not belong to the declared parent chain within the establishment
        scope, fails with `ERR_NOT_FOUND`."

        Design: Corner/entities/get_nonexistent_case_returns_not_found
        """
        resp = api.get_case(NON_EXISTENT_UUID, OFFICER)
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND)

    def test_error_envelope_shape(self, api):
        """PRD §2.2: "The `meta` object for error responses contains only
        `api_request_id` and `api_request_timestamp`."
        PRD §2.2: "The `error_id` is a unique, machine-readable string that
        identifies the specific error."

        Design: Corner/endpoints/error_envelope_shape
        """
        resp = api.get_case(NON_EXISTENT_UUID, OFFICER)
        assert resp.status_code == 404
        body = resp.json()
        assert body["response_type"] == "error"
        assert set(body["meta"].keys()) == {
            "api_request_id", "api_request_timestamp"}, (
            "Error meta must contain only api_request_id and "
            "api_request_timestamp")
        assert body["data"]["error_id"] == "ERR_NOT_FOUND"
        assert isinstance(body["data"]["message"], str)
        assert body["data"]["message"].strip()


class TestPagination:
    def test_pagination_defaults_on_list_endpoint(self, api):
        """PRD §2.3: "The `limit` parameter caps the number of returned items:
        it defaults to 10, with a minimum of 1 and a maximum of 100. The
        `offset` parameter skips that many items from the start of the result
        set and defaults to 0."
        PRD §2.3: "Paginated list responses carry `limit`, `offset`,
        `total_count`, and `has_more` in the `meta` object of the envelope."

        Design: Corner/endpoints/pagination_defaults_on_list_endpoint
        """
        company = create_company(legal_name="Page Co", fein="09-0000028")
        create_establishment(company["id"], site_name="P1")
        resp = api.list_company_establishments(company["id"], ADMIN)
        data, meta = validate_paginated(resp)
        assert meta["total_count"] == 1
        assert meta["has_more"] is False
        assert meta["limit"] == 10
        assert meta["offset"] == 0
        assert len(data) == 1


class TestRbacAndAuthentication:
    def test_missing_auth_headers_unauthenticated(self, api):
        """PRD §2.1: "A request missing either header, or naming a role
        outside this declared set, is rejected with `ERR_UNAUTHENTICATED`."

        Design: Corner/roles/missing_auth_headers_unauthenticated
        """
        resp = api.get_company(NON_EXISTENT_UUID, headers={})
        validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED)

    def test_recordkeeping_coordinator_cannot_classify_case(self, api):
        """PRD §3.2: "The recordability determination itself is a
        `SafetyOfficer` duty performed against a case in `PENDING_REVIEW`"
        PRD §2.1: "an authenticated operator attempting an operation outside
        their role's grant is rejected with `ERR_FORBIDDEN`."

        Design: Corner/roles/recordkeeping_coordinator_cannot_classify_case
        """
        _, establishment, employee = setup_org(fein="14-0000033")
        case = create_case(establishment["id"], employee["id"],
                           "2026-07-30T10:00:00Z")
        resp = api.classify_case(
            case["id"],
            {"classification": "MEDICAL_TREATMENT",
             "expected_case_version": case["version"]},
            COORDINATOR)
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN)

    def test_investigating_supervisor_cannot_create_hour_logs(self, api):
        """PRD §3.7: "A `RecordkeepingCoordinator` files one log per
        establishment per month"
        PRD §2.1: "an authenticated operator attempting an operation outside
        their role's grant is rejected with `ERR_FORBIDDEN`."

        Design: Corner/roles/investigating_supervisor_cannot_create_hour_logs
        """
        company = create_company(legal_name="RB2 Co", fein="15-0000034")
        establishment = create_establishment(company["id"],
                                             site_name="RB2 Site")
        resp = api.create_hour_log(
            {"establishment_id": establishment["id"], "year": 2026,
             "month": 1, "hours_worked": 100, "employment_count": 5},
            SUPERVISOR)
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN)
