"""Role-based access control: each exclusive operation is denied to roles
outside the authorized set.
"""
import pytest

from test_helpers import (
    validate_success,
    validate_error,
    get_success_data,
    create_applicant_payload,
    create_loan_application_payload,
    create_udaap_check_payload,
    setup_prequalified_loan_application,
    setup_applicant_and_loan_application_draft,
    TEST_USERS,
    ApiErrorId,
)


# =============================================================================
# Queue B — Corner
# =============================================================================

def test_rbac_underwriter_cannot_create_loan_application(api, lo_headers, underwriter_headers):
    """PRD §2.1: "Requests whose `X-User-Role` is not one of the recognized
    role names, or whose role lacks permission for the requested endpoint, are
    rejected with `ERR_UNAUTHORIZED`."
    PRD §4: "POST | `/loan-applications` | Create a new loan application in
    DRAFT | LoanOfficer"

    Design: Corner/rbac/rbac_underwriter_cannot_create_loan_application
    """
    applicant = validate_success(
        api.create_applicant(
            create_applicant_payload(
                full_name="U-CR",
                email="ucr.rbac@test.com",
                ssn_last4="1300",
                annual_income_cents=7_726_104,
            ),
            lo_headers,
        ),
        201,
    )
    res = api.create_loan_application(
        create_loan_application_payload(
            applicant["id"],
            requested_loan_amount_cents=30_000_000,
            property_value_cents=31_578_948,
        ),
        underwriter_headers,
    )
    validate_error(res, ApiErrorId.ERR_UNAUTHORIZED.value)


def test_rbac_loan_officer_cannot_approve(api, lo_headers):
    """PRD §2.1: "Requests whose `X-User-Role` is not one of the recognized
    role names, or whose role lacks permission for the requested endpoint, are
    rejected with `ERR_UNAUTHORIZED`."
    PRD §4: "POST | `/loan-applications/{id}/approve` | Move application from
    UNDER_REVIEW to APPROVED | Underwriter"

    Design: Corner/rbac/rbac_loan_officer_cannot_approve
    """
    applicant, app = setup_prequalified_loan_application(
        applicant_overrides={
            "full_name": "LA",
            "email": "la.rbac@test.com",
            "ssn_last4": "1310",
            "annual_income_cents": 7_726_104,
        },
    )
    res = api.approve_loan_application(app["id"], lo_headers)
    validate_error(res, ApiErrorId.ERR_UNAUTHORIZED.value)


def test_rbac_compliance_officer_can_record_udaap_check(api, lo_headers, compliance_headers):
    """PRD §4: "POST | `/udaap-checks` | Record a UDAAP compliance review
    outcome for an application | ComplianceOfficer"
    PRD §3.8: "A `ComplianceOfficer` records UDAAP review outcomes by creating
    a **UDAAPCheck** for a loan application. The record carries the
    `application_id` of the application under review, a `review_outcome` of
    either `CLEARED` or `FLAGGED`"

    Design: Corner/rbac/rbac_compliance_officer_can_record_udaap_check
    """
    applicant, app = setup_applicant_and_loan_application_draft(
        applicant_overrides={
            "full_name": "CO",
            "email": "co.rbac@test.com",
            "ssn_last4": "1320",
            "annual_income_cents": 7_726_104,
        },
    )
    res = api.create_udaap_check(
        create_udaap_check_payload(app["id"], review_outcome="CLEARED"),
        compliance_headers,
    )
    created = validate_success(res, 201)
    assert created["review_outcome"] == "CLEARED"


def test_rbac_loan_officer_cannot_record_udaap(api, lo_headers):
    """PRD §4: "POST | `/udaap-checks` | Record a UDAAP compliance review
    outcome for an application | ComplianceOfficer"
    PRD §2.1: "Requests whose `X-User-Role` is not one of the recognized role
    names, or whose role lacks permission for the requested endpoint, are
    rejected with `ERR_UNAUTHORIZED`."

    Design: Corner/rbac/rbac_loan_officer_cannot_record_udaap
    """
    applicant, app = setup_applicant_and_loan_application_draft(
        applicant_overrides={
            "full_name": "X",
            "email": "x.rbac@test.com",
            "ssn_last4": "1330",
            "annual_income_cents": 7_726_104,
        },
    )
    res = api.create_udaap_check(
        create_udaap_check_payload(app["id"], review_outcome="CLEARED"),
        lo_headers,
    )
    validate_error(res, ApiErrorId.ERR_UNAUTHORIZED.value)
