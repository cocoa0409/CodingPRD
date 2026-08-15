"""Role-based access control and authentication header enforcement."""
from test_helpers import (
    ApiErrorId,
    create_academic_year_payload,
    create_open_year,
    create_submitted_portfolio,
    get_success_data,
    setup_active_enrollment,
    validate_error,
)
from test_helpers import TEST_USERS

REGISTRAR = TEST_USERS["registrar_headers"]
REVIEWER = TEST_USERS["reviewer_headers"]
AUDITOR = TEST_USERS["auditor_headers"]


def test_rbac_cross_role_denials(api):
    """PRD §2.1: "Each endpoint admits a defined set of roles (§4); a caller
    whose role is not admitted is rejected with `ERR_FORBIDDEN_ROLE`
    (HTTP 403)."
    PRD §4: 'Where the Authorized Role(s) column reads "All roles", every
    API-facing role (`Parent`, `Reviewer`, `Registrar`, `AcademicDirector`,
    `StateAuditor`) may call the endpoint; otherwise the admitted roles are
    listed exactly.'

    Design: Corner/rbac/rbac_cross_role_denials
    """
    year = create_open_year()
    ctx = setup_active_enrollment(year["id"], 4, family_name="Fam Rb",
                                  district_code="D-80")
    portfolio = create_submitted_portfolio(ctx["enrollment"], ctx["family"])

    # Reviewer attempting the AcademicDirector-only year creation.
    resp1 = api.create_academic_year(
        create_academic_year_payload(label="2027-2028", start_date="2027-08-01",
                                     end_date="2028-05-31",
                                     notice_filing_deadline="2027-09-15T00:00:00Z",
                                     portfolio_due_date="2028-04-30T00:00:00Z",
                                     state_report_due_date="2028-06-15T00:00:00Z",
                                     mid_year_date="2028-01-15"),
        REVIEWER,
    )
    validate_error(resp1, ApiErrorId.ERR_FORBIDDEN_ROLE)

    # StateAuditor attempting the AcademicDirector-only standing override.
    resp2 = api.create_standing_override(
        ctx["enrollment"]["id"],
        {"standing": "PROBATION", "reason": "auditor overreach"},
        AUDITOR,
    )
    validate_error(resp2, ApiErrorId.ERR_FORBIDDEN_ROLE)

    # Registrar attempting the Reviewer-only portfolio evaluation.
    resp3 = api.create_evaluation(
        portfolio["id"],
        {
            "overall_outcome": "ACCEPTED",
            "subject_scores": [
                {"subject": "READING", "score": 3},
                {"subject": "WRITING", "score": 3},
                {"subject": "MATH", "score": 3},
                {"subject": "SCIENCE", "score": 3},
                {"subject": "SOCIAL_STUDIES", "score": 3},
            ],
        },
        REGISTRAR,
    )
    validate_error(resp3, ApiErrorId.ERR_FORBIDDEN_ROLE)


def test_missing_auth_header_returns_400(api):
    """PRD §2.1: "Every request carries `X-User-ID` to identify the acting party
    and `X-User-Role` to declare the capacity in which they act. A request
    missing either header, or carrying an empty value for either, is rejected
    with `ERR_MISSING_OR_INVALID_AUTH_HEADER` (HTTP 400)."

    Design: Corner/validations/missing_auth_header_returns_400
    """
    year = get_success_data(
        api.create_academic_year(create_academic_year_payload(),
                                 TEST_USERS["director_headers"])
    )
    # Neither X-User-ID nor X-User-Role is sent, even on a read endpoint.
    resp = api.get_academic_year(year["id"], headers=None)
    validate_error(resp, ApiErrorId.ERR_MISSING_OR_INVALID_AUTH_HEADER)
