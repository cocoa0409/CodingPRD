"""Content state guards, enum shape validation, code uniqueness, license
referential guards, open-assignment uniqueness."""
import pytest

from test_helpers import (
    ApiErrorId,
    create_approved_content,
    create_assignment,
    create_content_payload,
    create_license,
    create_rep,
    get_success_data,
    make_admin_headers,
    validate_error,
    validate_success,
)


class TestContentStateGuards:
    def test_reject_draft_content_rejected(self, api, admin_headers, officer_headers):
        """PRD §3.2: "Approval belongs to a `ComplianceOfficer` and requires
        the content to be in `PENDING_APPROVAL` — approving or rejecting
        content in any other status is rejected with
        `ERR_CONTENT_NOT_PENDING_APPROVAL`."

        Design: Corner/state_machines/c_reject_draft_content_returns_409
        """
        from test_helpers import create_draft_content, create_reject_payload
        content = create_draft_content(code="REJ-DRAFT")
        resp = api.reject_content(
            content["id"], create_reject_payload(reason="not ready for review"),
            officer_headers)
        validate_error(resp, ApiErrorId.ERR_CONTENT_NOT_PENDING_APPROVAL)

        data = validate_success(api.get_content(content["id"], officer_headers))
        assert data["content_status"] == "DRAFT", (
            f"rejected reject must leave the content DRAFT, "
            f"got {data['content_status']}")

    def test_retire_retired_content_rejected(self, api, officer_headers):
        """PRD §3.2: "A `ComplianceOfficer` may retire content that is
        `APPROVED`; retiring content in any other status is rejected with
        `ERR_CONTENT_NOT_RETIRABLE`. ... `RETIRED` is terminal."

        Design: Corner/state_machines/c_retire_retired_content_returns_409
        """
        content = create_approved_content(code="RET-1")
        get_success_data(api.retire_content(content["id"], officer_headers))
        resp = api.retire_content(content["id"], officer_headers)
        validate_error(resp, ApiErrorId.ERR_CONTENT_NOT_RETIRABLE)

    def test_edit_pending_content_rejected(self, api, admin_headers):
        """PRD §3.2: "While content is in `DRAFT` or `REJECTED`, the author may
        edit it; edits against content in any other status are rejected with
        `ERR_CONTENT_NOT_EDITABLE`."

        Design: Corner/errors/c_edit_pending_content_returns_409
        """
        author = make_admin_headers("ta-1")
        content = get_success_data(
            api.create_content(create_content_payload(code="EDP-1"), author))
        content = get_success_data(api.submit_content(content["id"], author))
        # PENDING_APPROVAL content: fresh OCC version, but the state guard fires.
        resp = api.update_content(
            content["id"],
            {"expected_content_version": content["version"],
             "title": "Edit While Pending"},
            author)
        validate_error(resp, ApiErrorId.ERR_CONTENT_NOT_EDITABLE)


class TestEnumValidation:
    def test_invalid_ce_category_returns_400(self, api, admin_headers):
        """PRD §2.6: "Required fields are present, enum values are valid, a
        completion `score` lies between 0 and 100 inclusive, an enrollment
        create carries exactly one of `content_id` or `session_id`, a void's
        `justification` is at least ten characters long, and similar shape
        rules hold — violations yield `ERR_INVALID_REQUEST` (HTTP 400)."
        PRD §3.2: "a `ce_category` of `REGULATORY_ELEMENT`, `FIRM_ELEMENT`,
        `PRODUCT`, or `STATE_INSURANCE`."

        Design: Corner/entities/c_content_invalid_enum_returns_400
        """
        payload = create_content_payload(code="BAD-ENUM", ce_category="BOGUS")
        resp = api.create_content(payload, admin_headers)
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)


class TestContentCodeUniqueness:
    def test_duplicate_content_code_rejected(self, api):
        """PRD §3.2: "A `TrainingAdmin` authors a course by supplying a unique
        `code` ... Reusing an existing course code is rejected with
        `ERR_DUPLICATE_CONTENT_CODE`."

        Design: Corner/errors/c_duplicate_content_code_returns_409
        """
        author = make_admin_headers("ta-1")
        other = make_admin_headers("ta-2")
        get_success_data(
            api.create_content(create_content_payload(code="DUP-C"), author))
        resp = api.create_content(
            create_content_payload(
                code="DUP-C", ce_category="STATE_INSURANCE",
                delivery_format="INSTRUCTOR_LED", credit_hours=2.0,
                min_passing_score=80),
            other)
        validate_error(resp, ApiErrorId.ERR_DUPLICATE_CONTENT_CODE)


class TestOpenAssignmentUniqueness:
    def test_second_open_assignment_rejected(self, api, admin_headers):
        """PRD §3.5: "A rep may hold at most one open assignment at a time:
        creating one while the rep already has an assignment in `ASSIGNED`,
        `OVERDUE`, or `LAPSED` is rejected with `ERR_OPEN_ASSIGNMENT_EXISTS`."

        Design: Corner/validations/c_open_assignment_exists_returns_409
        """
        rep = create_rep(crd_number="CRD-C23")
        create_assignment(rep["id"], cycle_year=2026)
        resp = api.create_regulatory_assignment(
            {"rep_id": rep["id"], "cycle_year": 2027}, admin_headers)
        validate_error(resp, ApiErrorId.ERR_OPEN_ASSIGNMENT_EXISTS)


class TestLicenseGuards:
    def test_license_for_non_insurance_rep_rejected(self, api, admin_headers):
        """PRD §3.8: "The rep must be flagged `insurance_licensed`, otherwise
        `ERR_REP_NOT_INSURANCE_LICENSED`."

        Design: Corner/validations/c_license_for_non_insurance_rep_returns_409
        """
        rep = create_rep(crd_number="CRD-C27", insurance_licensed=False)
        resp = api.create_state_ce_license(
            {"rep_id": rep["id"], "state_code": "NY", "required_hours": 24,
             "period_start": "2026-01-01T00:00:00Z",
             "period_end": "2027-01-01T00:00:00Z"},
            admin_headers)
        validate_error(resp, ApiErrorId.ERR_REP_NOT_INSURANCE_LICENSED)

    def test_duplicate_license_state_rejected(self, api, admin_headers):
        """PRD §3.8: "a rep may hold only one license per state, otherwise
        `ERR_DUPLICATE_LICENSE_STATE`."

        Design: Corner/errors/c_duplicate_license_state_returns_409
        """
        rep = create_rep(
            crd_number="CRD-DLS", insurance_licensed=True,
            resident_state_code="CA")
        create_license(
            rep["id"], state_code="CA", required_hours=24,
            period_start="2026-01-01T00:00:00Z",
            period_end="2027-01-01T00:00:00Z")
        resp = api.create_state_ce_license(
            {"rep_id": rep["id"], "state_code": "CA", "required_hours": 12,
             "period_start": "2027-01-01T00:00:00Z",
             "period_end": "2028-01-01T00:00:00Z"},
            admin_headers)
        validate_error(resp, ApiErrorId.ERR_DUPLICATE_LICENSE_STATE)
