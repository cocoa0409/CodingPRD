"""Response envelope, pagination, not-found family, and intake validation surface
(PRD §2.1, §2.2, §2.3, §2.5, §2.11, §3.1)."""
import pytest

from test_helpers import (
    ApiErrorId,
    assert_application,
    create_active_bundle,
    create_application_payload,
    is_iso8601_timestamp,
    is_valid_uuid,
    make_applicant_headers,
    make_donor_headers,
    make_program_officer_headers,
    make_sponsor_admin_headers,
    validate_error,
    validate_paginated,
    validate_success,
)

UNKNOWN_UUID = "11111111-1111-4111-8111-111111111111"


class TestApplicationCreation:
    def test_application_create_success(self, api):
        """PRD §3.1: "The application is born in `DRAFT` with `submit_count` at zero,
        `applicant_user_id` anchored to the filer, and `mission_score`, `decided_model`,
        `project_id`, `agreement_id`, and `fund_account_id` all unset."
        PRD §4: "Operations that create a new resource return `201 Created`"

        Design: Corner/entities/e_application_create_success
        """
        payload = create_application_payload(
            project_name="Alpha", mission_statement="feed artists",
            requested_model="COMPREHENSIVE", budget_estimate_cents=5000000,
            contact_email="a@x.org")
        resp = api.create_application(payload, make_applicant_headers("user_c_app1"))
        data = validate_success(resp, expected_status=201)
        assert_application(data)
        assert data["status"] == "DRAFT"
        assert data["submit_count"] == 0
        assert data["requested_model"] == "COMPREHENSIVE"
        assert data["version"] == 1
        assert is_valid_uuid(data["id"])
        assert data["applicant_user_id"] == "user_c_app1"
        assert data["mission_score"] is None
        assert data["project_id"] is None

    def test_application_requested_model_default(self, api):
        """PRD §2.7: "An applicant states a `requested_model` (defaulting to
        `COMPREHENSIVE` when omitted), but the model actually granted is fixed at
        compliance approval"

        Design: Corner/entities/e_application_requested_model_default
        """
        payload = create_application_payload(
            project_name="Beta", budget_estimate_cents=1000, contact_email="b@x.org")
        payload.pop("requested_model", None)
        resp = api.create_application(payload, make_applicant_headers("user_c_app2"))
        data = validate_success(resp, expected_status=201)
        assert data["requested_model"] == "COMPREHENSIVE", (
            "omitted requested_model must default to COMPREHENSIVE")

    def test_system_fields_server_minted(self, api):
        """PRD §2.5: "The `id` is a server-minted UUID with no type prefix"
        PRD §2.5: "The `version` is an integer that starts at 1 and increments by
        exactly 1 on every mutation"
        PRD §2.5: "The `created_at` timestamp records creation as an ISO 8601 UTC
        value with three fractional digits."

        Design: Corner/entities/e_system_fields_server_minted
        """
        resp = api.create_application(
            create_application_payload(project_name="Sf", contact_email="sf@x.org"),
            make_applicant_headers("user_c_app5"))
        data = validate_success(resp, expected_status=201)
        assert is_valid_uuid(data["id"])
        assert data["version"] == 1
        assert is_iso8601_timestamp(data["created_at"])
        assert is_iso8601_timestamp(data["updated_at"])


class TestPaginationAndFilters:
    def test_pagination_filter_limit_offset(self, api):
        """PRD §2.3: "The `limit` parameter caps the number of items returned; it
        defaults to 10, with a minimum of 1 and a maximum of 100. The `offset`
        parameter skips a number of items and defaults to 0."
        PRD §3.1: "The application list supports filtering by `status` and
        `applicant_user_id`."

        Design: Corner/entities/e_pagination_filter_limit_offset
        """
        for i in range(1, 4):
            api.create_application(
                create_application_payload(project_name=f"P{i}", contact_email=f"p{i}@x.org"),
                make_applicant_headers(f"user_c_page{i}"))
        headers = make_program_officer_headers()

        page1, meta1 = validate_paginated(api.list_applications(headers, params={"limit": 2}))
        assert len(page1) == 2
        assert meta1["total_count"] == 3
        assert meta1["has_more"] is True

        page2, meta2 = validate_paginated(
            api.list_applications(headers, params={"limit": 2, "offset": 2}))
        assert len(page2) == 1
        assert meta2["total_count"] == 3
        assert meta2["has_more"] is False

        filtered, meta3 = validate_paginated(
            api.list_applications(headers, params={"status": "SUBMITTED"}))
        assert filtered == []
        assert meta3["total_count"] == 0


NOT_FOUND_PROBES = [
    ("application", "ERR_APPLICATION_NOT_FOUND"),
    ("project", "ERR_PROJECT_NOT_FOUND"),
    ("agreement", "ERR_AGREEMENT_NOT_FOUND"),
    ("fund_account", "ERR_FUND_ACCOUNT_NOT_FOUND"),
    ("donation", "ERR_DONATION_NOT_FOUND"),
    ("receipt", "ERR_RECEIPT_NOT_FOUND"),
    ("disbursement", "ERR_DISBURSEMENT_NOT_FOUND"),
    ("engagement", "ERR_ENGAGEMENT_NOT_FOUND"),
    ("review", "ERR_REVIEW_NOT_FOUND"),
    ("incident", "ERR_INCIDENT_NOT_FOUND"),
    ("exit_plan", "ERR_EXIT_PLAN_NOT_FOUND"),
    ("tranche", "ERR_TRANCHE_NOT_FOUND"),
    ("assessment", "ERR_ASSESSMENT_NOT_FOUND"),
    ("ledger_entry", "ERR_LEDGER_ENTRY_NOT_FOUND"),
]


class TestNotFoundFamily:
    @pytest.mark.parametrize("resource,error_id", NOT_FOUND_PROBES, ids=[r for r, _ in NOT_FOUND_PROBES])
    def test_unknown_id_returns_domain_404(self, api, resource, error_id):
        """PRD §2.11: "Sixth, path identifiers are resolved left to right: the first
        path id that does not resolve to an existing resource produces that resource's
        not-found error"

        Design: Corner/entities/e_not_found_family
        """
        headers = make_sponsor_admin_headers()
        getter = {
            "application": api.get_application,
            "project": api.get_project,
            "agreement": api.get_agreement,
            "fund_account": api.get_fund_account,
            "donation": api.get_donation,
            "receipt": api.get_receipt,
            "disbursement": api.get_disbursement,
            "engagement": api.get_staff_engagement,
            "review": api.get_compliance_review,
            "incident": api.get_risk_incident,
            "exit_plan": api.get_exit_plan,
            "tranche": api.get_grant_tranche,
            "assessment": api.get_fee_assessment,
            "ledger_entry": api.get_ledger_entry,
        }[resource]
        resp = getter(UNKNOWN_UUID, headers)
        validate_error(resp, ApiErrorId(error_id))

    def test_donation_under_unknown_project_rejected(self, api):
        """PRD §2.11: "Sixth, path identifiers are resolved left to right: the first
        path id that does not resolve to an existing resource produces that resource's
        not-found error"

        Design: Corner/entities/e_fk_integrity_donation_unknown_project
        """
        resp = api.create_donation(
            "22222222-2222-4222-8222-222222222222",
            {"amount_cents": 5000, "donor_name": "D", "donor_email": "d@x.org",
             "payment_method": "CARD"},
            make_donor_headers())
        validate_error(resp, ApiErrorId.ERR_PROJECT_NOT_FOUND)


class TestResponseEnvelope:
    def test_response_envelope_shape(self, api, program_officer_headers):
        """PRD §2.2: "All successful API responses (those with 2xx status codes) follow
        this standard envelope format in their JSON body"
        PRD §2.2 error shape: "The `meta` object for error responses contains only
        `api_request_id` and `api_request_timestamp`."
        PRD §2.3: "The `meta` object of a list response carries the pagination fields
        `limit`, `offset`, `total_count`, and `has_more`."

        Design: Corner/endpoints/ep_response_envelope_shape
        """
        created = validate_success(api.create_application(
            create_application_payload(project_name="EV", contact_email="ev@x.org"),
            make_applicant_headers("user_c_e2")), expected_status=201)

        obj = api.get_application(created["id"], program_officer_headers).json()
        assert obj["meta"]["api_request_id"].startswith("req_")
        assert is_iso8601_timestamp(obj["meta"]["api_request_timestamp"])
        assert obj["response_type"] == "object"
        assert obj["data"]["id"] == created["id"]

        lst = api.list_applications(program_officer_headers).json()
        assert lst["response_type"] == "array"
        for field in ("limit", "offset", "total_count", "has_more"):
            assert field in lst["meta"], f"list meta must carry {field}"
        assert lst["meta"]["limit"] == 10
        assert lst["meta"]["offset"] == 0

        err = api.get_application(
            "33333333-3333-4333-8333-333333333333", program_officer_headers)
        err_body = err.json()
        assert err.status_code == 404
        assert err_body["response_type"] == "error"
        assert err_body["data"]["error_id"] == "ERR_APPLICATION_NOT_FOUND"
        assert isinstance(err_body["data"]["message"], str) and err_body["data"]["message"]


class TestIntakeValidationAndAuth:
    def test_missing_required_field_returns_400(self, api):
        """PRD §2.11: "First, body schema: required fields present — including
        conditionally required ones such as `sponsorship_model` on an approving
        compliance decision — JSON types correct, and integer-cent fields integral,
        else `ERR_VALIDATION` (HTTP 400)."

        Design: Corner/validations/v_missing_required_field_returns_400
        """
        payload = {"project_name": "NoMission", "budget_estimate_cents": 1000,
                   "contact_email": "nm@x.org"}
        resp = api.create_application(payload, make_applicant_headers("user_c_v1"))
        validate_error(resp, ApiErrorId.ERR_VALIDATION)

    def test_invalid_enum_returns_400(self, api):
        """PRD §2.11: "Second, enum membership: every enum field must carry a declared
        member, else `ERR_INVALID_ENUM` (HTTP 400)."
        PRD §3.1: the action is "`ADVANCE` or `RETURN`".

        Design: Corner/validations/v_invalid_enum_returns_400
        """
        created = validate_success(api.create_application(
            create_application_payload(project_name="IE", contact_email="ie@x.org"),
            make_applicant_headers("user_c_v2")), expected_status=201)
        validate_success(api.submit_application(
            created["id"], make_applicant_headers("user_c_v2")))
        resp = api.score_mission(
            created["id"],
            {"purpose_pts": 50, "benefit_pts": 50, "capacity_pts": 100,
             "risk_pts": 0, "action": "MAYBE"},
            make_program_officer_headers())
        validate_error(resp, ApiErrorId.ERR_INVALID_ENUM)
        after = validate_success(api.get_application(created["id"], make_program_officer_headers()))
        assert after["status"] == "SUBMITTED"

    def test_missing_auth_headers_unauthenticated(self, api):
        """PRD §2.1: "A request missing either header, presenting a blank value, or
        naming a role outside this set is rejected with `ERR_UNAUTHENTICATED` (HTTP 401)."

        Design: Corner/validations/v_missing_auth_headers_unauthenticated
        """
        resp = api.list_projects(headers={})
        validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED)

    def test_donor_cannot_read_project(self, api):
        """PRD §2.1: "`Donor` is write-only on its two gift-related operations and is
        not authorized on any read endpoint."

        Design: Corner/rbac/rbac_donor_cannot_read_project
        """
        bundle = create_active_bundle("user_c_b7", model="COMPREHENSIVE",
                                      project_name="RB7", contact_email="rb7@x.org")
        resp = api.get_project(bundle["project_id"], make_donor_headers())
        validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED_ROLE)
