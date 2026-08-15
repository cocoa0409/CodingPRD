"""Security and response envelope claims (PRD §2.1, §2.2, §4):
authentication, role-based authorization on exclusive and shared operations,
and the success/error envelope shapes.
"""
from test_helpers import (
    validate_success, validate_error,
    ApiErrorId, NON_EXISTENT_UUID,
    create_case_payload, create_housing_unit_payload,
    make_case, make_federal_report, submit_federal_report,
    make_agency_director_headers,
    setup_arrived_case, get_benchmark_by_type, make_employment_plan,
)
from test_helpers.fixtures import CM, HC, FO


class TestAuthentication:
    def test_missing_auth_headers_rejected(self, api):
        """PRD §2.1: "A request missing either header, or presenting an
        `X-User-Role` value that is not one of the five declared roles, is
        rejected with `ERR_UNAUTHENTICATED` (HTTP 401)."

        Design: Corner/validations/request_missing_auth_headers_returns_unauthenticated
        """
        resp = api.create_case(
            create_case_payload(case_number="CASE-V1"), headers=None)
        validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED)


class TestResponseEnvelope:
    def test_success_envelope_shape(self, api):
        """PRD §2.2: "The `api_request_id` is a server-generated unique
        identifier for the request that starts with `req_`." and "The
        `response_type` is either "object" for a single resource or "array"
        for a list of resources."

        Design: Corner/endpoints/response_envelope_success_and_error_shape
        """
        resp = api.create_case(create_case_payload(case_number="CASE-EP2"), CM)
        body = resp.json()
        assert resp.status_code == 201
        assert isinstance(body["meta"]["api_request_id"], str)
        assert body["meta"]["api_request_id"].startswith("req_")
        assert isinstance(body["meta"]["api_request_timestamp"], str)
        assert body["response_type"] == "object"
        assert body["data"]["id"]

    def test_error_envelope_shape(self, api):
        """PRD §2.2: "The `error_id` is a unique, machine-readable string
        that identifies the specific error. The `message` provides a
        human-readable explanation of what went wrong." and "The `meta`
        object for error responses contains only `api_request_id` and
        `api_request_timestamp`."

        Design: Corner/endpoints/response_envelope_success_and_error_shape
        """
        resp = api.get_case(NON_EXISTENT_UUID, CM)
        body = resp.json()
        assert resp.status_code == 404
        assert body["response_type"] == "error"
        assert body["data"]["error_id"] == "ERR_NOT_FOUND"
        assert isinstance(body["data"]["message"], str)
        assert len(body["data"]["message"].strip()) > 0
        assert isinstance(body["meta"]["api_request_id"], str)
        assert isinstance(body["meta"]["api_request_timestamp"], str)


class TestExclusiveOperations:
    def test_waive_denied_for_case_manager(self, api):
        """PRD §4: "POST /benchmarks/{id}/waive | Waive a `PENDING` benchmark
        (director authority) | AgencyDirector". PRD §2.1: "A request whose
        role is authenticated but not permitted on the target endpoint is
        rejected with `ERR_FORBIDDEN` (HTTP 403)."

        Design: Corner/rbac/waive_exclusive_to_director
        """
        ctx = setup_arrived_case(case_number="CASE-RB1", household_size=1)
        bm = get_benchmark_by_type(ctx["case"]["id"], "HOME_VISIT")
        assert bm["status"] == "PENDING"
        resp = api.waive_benchmark(
            bm["id"], {"reason": "Manager attempting a director-only waiver"}, CM)
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN)

    def test_review_denied_for_agency_director(self, api):
        """PRD §4: "POST /federal-reports/{id}/review | Federal review:
        `ACCEPTED` finalizes; `REJECTED` returns to `DRAFT` with
        `revision_count` incremented | FederalOfficer". PRD §2.1: "A request
        whose role is authenticated but not permitted on the target endpoint
        is rejected with `ERR_FORBIDDEN` (HTTP 403)."

        Design: Corner/rbac/review_exclusive_to_officer
        """
        report = make_federal_report("2026-10-01", "2027-01-01")
        submit_federal_report(report["id"],
                              headers=make_agency_director_headers("dir-1"))
        resp = api.review_federal_report(report["id"], {"decision": "ACCEPTED"},
                                         make_agency_director_headers("dir-9"))
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN)

    def test_housing_unit_create_denied_for_case_manager(self, api):
        """PRD §4: "POST /housing-units | Register a housing unit in the
        agency pool | HousingCoordinator". PRD §2.1: "A request whose role is
        authenticated but not permitted on the target endpoint is rejected
        with `ERR_FORBIDDEN` (HTTP 403)."

        Design: Corner/rbac/housing_units_exclusive_to_coordinator
        """
        resp = api.create_housing_unit(
            create_housing_unit_payload(address="640 Unaffiliated St",
                                        bedrooms=1), CM)
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN)

    def test_plan_patch_denied_for_case_manager(self, api):
        """PRD §4: "PATCH /employment-plans/{id} | Update income and
        employment fields of an `ACTIVE` plan | EmploymentSpecialist".
        PRD §2.1: "A request whose role is authenticated but not permitted on
        the target endpoint is rejected with `ERR_FORBIDDEN` (HTTP 403)."

        Design: Corner/rbac/plan_patch_exclusive_to_specialist
        """
        ctx = setup_arrived_case(case_number="CASE-RB4", household_size=1)
        plan = make_employment_plan(ctx["case"]["id"])
        resp = api.patch_employment_plan(plan["id"],
                                         {"monthly_income_cents": 100000}, CM)
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN)


class TestCaseNoteSharing:
    def test_note_create_denied_for_federal_officer(self, api):
        """PRD §3.4: "Notes are never edited or deleted; the
        `FederalOfficer` can read them but cannot author them." PRD §2.1:
        "A request whose role is authenticated but not permitted on the
        target endpoint is rejected with `ERR_FORBIDDEN` (HTTP 403)."

        Design: Corner/rbac/notes_denied_for_federal_officer
        """
        case = make_case(case_number="CASE-RB5", household_size=1)
        resp = api.create_case_note(
            {"case_id": case["id"], "note_type": "GENERAL",
             "body": "Officer note attempt"}, FO)
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN)

    def test_note_authored_by_housing_coordinator_stamps_role(self, api):
        """PRD §3.4: "A `CaseManager`, `HousingCoordinator`,
        `EmploymentSpecialist`, or `AgencyDirector` may append a note" and
        "The server stamps `author_role` from the request's `X-User-Role` —
        one of `CASE_MANAGER`, `HOUSING_COORDINATOR`,
        `EMPLOYMENT_SPECIALIST`, or `AGENCY_DIRECTOR`."

        Design: Corner/rbac/notes_shared_for_housing_coordinator
        """
        case = make_case(case_number="CASE-RB6", household_size=1)
        note = validate_success(api.create_case_note(
            {"case_id": case["id"], "note_type": "GENERAL",
             "body": "Unit inspected", "service_date": "2026-08-05"}, HC), 201)
        assert note["author_role"] == "HOUSING_COORDINATOR"
