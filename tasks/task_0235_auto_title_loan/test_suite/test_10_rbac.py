"""Access control: role denial, segregation of duties on approval, and authentication."""
from test_helpers import (
    api_client,
    validate_error,
    get_success_data,
    TEST_USERS,
    setup_submitted_application,
    setup_finalized_appraisal,
    create_submitted_application,
    make_appraiser_headers,
    make_underwriter_headers,
    set_clock,
    CLOCK_ORIGIN,
)

_APPR = TEST_USERS["appraiser_headers"]


# ─────────────────────────────────────────────────────────────────────────
# Corner: Appraiser cannot approve an application (Underwriter-exclusive)
# ─────────────────────────────────────────────────────────────────────────
def test_appraiser_cannot_approve_application(api):
    """PRD §2.1: "When an authenticated user attempts an operation their role is not
    permitted to perform, the request is rejected with ERR_FORBIDDEN_ROLE."

    Design: Corner/rbac/appraiser_cannot_approve_application
    """
    set_clock(CLOCK_ORIGIN)
    borrower, vehicle, appraisal, application = setup_submitted_application(appraiser_id="appr-rc")
    res = api.approve_application(application["id"], make_appraiser_headers("appr-rc"))
    validate_error(res, "ERR_FORBIDDEN_ROLE")


# ─────────────────────────────────────────────────────────────────────────
# Corner: segregation of duties — same user finalized and approves
# ─────────────────────────────────────────────────────────────────────────
def test_segregation_appraiser_cannot_be_approving_underwriter(api):
    """PRD §2.1: "When an application is approved, the approving Underwriter's X-User-ID
    must differ from the X-User-ID of the Appraiser who finalized the appraisal backing
    that application; if they are the same user, the approval is rejected with
    ERR_SEGREGATION_OF_DUTIES."

    Design: Corner/rbac/segregation_appraiser_cannot_be_approving_underwriter
    """
    set_clock(CLOCK_ORIGIN)
    # Finalize the appraisal as user "dual-1"; then approve as Underwriter "dual-1".
    _, borrower, _, appraisal = setup_finalized_appraisal(appraiser_id="dual-1")
    application = create_submitted_application(borrower["id"], appraisal["id"])
    res = api.approve_application(application["id"], make_underwriter_headers("dual-1"))
    validate_error(res, "ERR_SEGREGATION_OF_DUTIES")


# ─────────────────────────────────────────────────────────────────────────
# Corner: missing auth headers -> ERR_UNAUTHENTICATED
# ─────────────────────────────────────────────────────────────────────────
def test_missing_auth_headers_returns_unauthenticated(api):
    """PRD §2.1: "Every request must be authenticated through two mandatory HTTP
    headers: X-User-ID, identifying the acting user, and X-User-Role, declaring the
    user's operational capacity. If either header is missing or malformed, the request
    is rejected with ERR_UNAUTHENTICATED."

    Design: Corner/rbac/missing_auth_headers_returns_unauthenticated
    """
    res = api.get_loan("00000000-0000-4000-8000-000000000001", {})
    validate_error(res, "ERR_UNAUTHENTICATED")
