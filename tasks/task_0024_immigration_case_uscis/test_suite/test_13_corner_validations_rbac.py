"""Corner (validations + rbac) — auth presence, role recognition, ownership,
appointment lead-time, and peer-role denials."""
import pytest

from test_helpers import (
    api_client,
    validate_error,
    set_clock,
    register_applicant,
    create_draft_case,
    file_case,
    setup_under_review_i130,
    make_headers,
    make_applicant_headers,
    make_officer_headers,
    create_biometrics_payload,
    issue_rfe_payload,
    visa_bulletin_payload,
    TEST_USERS,
)


class TestMissingAuthHeaders:

    def test_missing_x_user_role_returns_unauthenticated(self, api):
        """PRD §2.1: "If either header is missing on a protected endpoint, the request
        is rejected with `ERR_UNAUTHENTICATED`."

        Design: Corner/validations/missing_x_user_role_header_returns_unauthenticated
        """
        # GET /uscis/cases is a protected endpoint; call it with no headers.
        res = api.list_cases({})
        validate_error(res, "ERR_UNAUTHENTICATED")


class TestInvalidRoleValue:

    def test_unknown_role_value_returns_invalid_role(self, api):
        """PRD §2.1: "any value outside this set is rejected with `ERR_INVALID_ROLE`"

        Design: Corner/validations/invalid_x_user_role_value_returns_invalid_role
        """
        # Carry both headers but with a role name that isn't in the recognized set.
        headers = make_headers("janitor-1", "Janitor")
        res = api.list_cases(headers)
        validate_error(res, "ERR_INVALID_ROLE")


class TestApptTooSoonRejected:

    def test_biometrics_5_days_in_future_rejected_with_appt_too_soon(self, api):
        """PRD §3.3: "The `scheduled_at` value must be at least seven days after
        `ClockState.current_utc`; otherwise the request is rejected with `ERR_APPT_TOO_SOON`."

        Design: Corner/validations/appt_too_soon_5_days_rejected
        """
        set_clock("2026-06-15T00:00:00Z")
        applicant = register_applicant()
        case = create_draft_case(applicant, case_type="I-485")
        filed = file_case(case, applicant)
        officer = make_officer_headers(filed["assigned_officer_id"])
        # 5 days ahead — fails the 7-day window.
        res = api.schedule_biometrics(
            filed["id"],
            create_biometrics_payload("2026-06-20T15:00:00Z", "ASC-SF-30"),
            officer,
        )
        validate_error(res, "ERR_APPT_TOO_SOON")


class TestFileCaseOwnership:

    def test_file_by_non_owner_applicant_returns_ownership_violation(self, api):
        """PRD §2.1: "When an applicant or attorney attempts to act on a case that is not
        their own (for an applicant, a case whose `applicant_id` does not match
        `X-User-ID`; for an attorney, a case whose `attorney_id` does not match),
        the request is rejected with `ERR_OWNERSHIP_VIOLATION`."

        Design: Corner/validations/file_case_by_wrong_applicant_owner_returns_ownership_violation
        """
        applicant_a = register_applicant()
        applicant_b = register_applicant()
        # A creates a case; B tries to file it.
        case = create_draft_case(applicant_a, case_type="I-130",
                                 preference_category="IR")
        # B's headers (entity-backed: must use B's id as X-User-ID).
        b_headers = make_applicant_headers(applicant_b["id"])
        res = api.file_case(case["id"], b_headers)
        validate_error(res, "ERR_OWNERSHIP_VIOLATION")


class TestApplicantCannotIssueRfe:

    def test_applicant_calling_officer_endpoint_returns_forbidden(self, api):
        """PRD §2.1: "If the role is recognised but is not in the called endpoint's
        authorised set, the request is rejected with `ERR_FORBIDDEN`."

        Design: Corner/rbac/applicant_cannot_issue_rfe_returns_forbidden
        """
        applicant, case_ur, _officer_headers = setup_under_review_i130()
        # Now try the Officer-only POST /cases/{id}/rfes as the Applicant.
        applicant_headers = make_applicant_headers(applicant["id"])
        res = api.issue_rfe(
            case_ur["id"],
            issue_rfe_payload(["birth_cert"]),
            applicant_headers,
        )
        validate_error(res, "ERR_FORBIDDEN")


class TestOfficerCannotPublishVisaBulletin:

    def test_officer_calling_admin_only_publish_returns_forbidden(self, api):
        """PRD §4: "`POST /uscis/visa-bulletin` ... FieldOfficeAdmin"
        PRD §2.1: "If the role is recognised but is not in the called endpoint's
        authorised set, the request is rejected with `ERR_FORBIDDEN`."

        Design: Corner/rbac/officer_cannot_publish_visa_bulletin
        """
        officer = TEST_USERS["officer_headers"]
        res = api.publish_visa_bulletin(
            visa_bulletin_payload("2026-06", "F1", "WORLDWIDE",
                                  "FINAL_ACTION", "2024-01-01"),
            officer,
        )
        validate_error(res, "ERR_FORBIDDEN")
