"""Acting identities for the six roles described in PRD section 2.1.

`X-User-ID` is an opaque actor identifier that is never compared against any
entity id, so a small pool of fixed identities is sufficient. Several distinct
identities per role are provided because separation of duties (PRD 2.7)
compares the acting `X-User-ID` values of two different operations.
"""

from prd_bench_local_runner.testing import build_user_headers

from .constants import (
    ROLE_COMPLIANCE_AUDITOR,
    ROLE_ISSUANCE_OPERATOR,
    ROLE_POLICY_ADMIN,
    ROLE_REVOCATION_OFFICER,
    ROLE_VALIDATION_OFFICER,
    ROLE_VETTING_APPROVER,
)

# --- identities ------------------------------------------------------------
USER_POLICY_ADMIN = "u_pol_1"
USER_POLICY_ADMIN_2 = "u_pol_2"

USER_VALIDATION_OFFICER = "u_val_1"
USER_VALIDATION_OFFICER_2 = "u_val_2"
USER_VALIDATION_OFFICER_3 = "u_val_3"

USER_VETTING_APPROVER = "u_appr_1"
USER_VETTING_APPROVER_2 = "u_appr_2"

USER_ISSUANCE_OPERATOR = "u_iss_1"
USER_ISSUANCE_OPERATOR_2 = "u_iss_2"
USER_ISSUANCE_OPERATOR_3 = "u_iss_3"
USER_ISSUANCE_OPERATOR_9 = "u_iss_9"

USER_REVOCATION_OFFICER = "u_rev_1"
USER_REVOCATION_OFFICER_2 = "u_rev_2"

USER_COMPLIANCE_AUDITOR = "u_aud_1"
USER_COMPLIANCE_AUDITOR_2 = "u_aud_2"

# --- ready-made header sets ------------------------------------------------
POLICY_ADMIN = build_user_headers(USER_POLICY_ADMIN, ROLE_POLICY_ADMIN)
POLICY_ADMIN_2 = build_user_headers(USER_POLICY_ADMIN_2, ROLE_POLICY_ADMIN)

VALIDATION_OFFICER = build_user_headers(USER_VALIDATION_OFFICER, ROLE_VALIDATION_OFFICER)
VALIDATION_OFFICER_2 = build_user_headers(
    USER_VALIDATION_OFFICER_2, ROLE_VALIDATION_OFFICER
)
VALIDATION_OFFICER_3 = build_user_headers(
    USER_VALIDATION_OFFICER_3, ROLE_VALIDATION_OFFICER
)

VETTING_APPROVER = build_user_headers(USER_VETTING_APPROVER, ROLE_VETTING_APPROVER)
VETTING_APPROVER_2 = build_user_headers(USER_VETTING_APPROVER_2, ROLE_VETTING_APPROVER)

ISSUANCE_OPERATOR = build_user_headers(USER_ISSUANCE_OPERATOR, ROLE_ISSUANCE_OPERATOR)
ISSUANCE_OPERATOR_2 = build_user_headers(
    USER_ISSUANCE_OPERATOR_2, ROLE_ISSUANCE_OPERATOR
)
ISSUANCE_OPERATOR_3 = build_user_headers(
    USER_ISSUANCE_OPERATOR_3, ROLE_ISSUANCE_OPERATOR
)
ISSUANCE_OPERATOR_9 = build_user_headers(
    USER_ISSUANCE_OPERATOR_9, ROLE_ISSUANCE_OPERATOR
)

REVOCATION_OFFICER = build_user_headers(USER_REVOCATION_OFFICER, ROLE_REVOCATION_OFFICER)
REVOCATION_OFFICER_2 = build_user_headers(
    USER_REVOCATION_OFFICER_2, ROLE_REVOCATION_OFFICER
)

COMPLIANCE_AUDITOR = build_user_headers(USER_COMPLIANCE_AUDITOR, ROLE_COMPLIANCE_AUDITOR)
COMPLIANCE_AUDITOR_2 = build_user_headers(
    USER_COMPLIANCE_AUDITOR_2, ROLE_COMPLIANCE_AUDITOR
)

# A default identity per role, for tests that only care about the role.
HEADERS_BY_ROLE = {
    ROLE_POLICY_ADMIN: POLICY_ADMIN,
    ROLE_VALIDATION_OFFICER: VALIDATION_OFFICER,
    ROLE_VETTING_APPROVER: VETTING_APPROVER,
    ROLE_ISSUANCE_OPERATOR: ISSUANCE_OPERATOR,
    ROLE_REVOCATION_OFFICER: REVOCATION_OFFICER,
    ROLE_COMPLIANCE_AUDITOR: COMPLIANCE_AUDITOR,
}


def headers_for(role, user_id=None):
    """Build headers for an arbitrary role / actor pair."""
    if user_id is None:
        return dict(HEADERS_BY_ROLE[role])
    return build_user_headers(user_id, role)


def headers_without_user_id(role):
    """Headers that carry a role but no `X-User-ID` at all."""
    headers = build_user_headers("placeholder", role)
    headers.pop("X-User-ID", None)
    return headers


def headers_with_empty_user_id(role):
    """Headers whose `X-User-ID` is present but empty."""
    headers = build_user_headers("placeholder", role)
    headers["X-User-ID"] = ""
    return headers


def headers_without_role(user_id=USER_POLICY_ADMIN):
    """Headers that carry an actor but no `X-User-Role` at all."""
    headers = build_user_headers(user_id, ROLE_POLICY_ADMIN)
    headers.pop("X-User-Role", None)
    return headers


def headers_with_empty_role(user_id=USER_POLICY_ADMIN):
    """Headers whose `X-User-Role` is present but empty."""
    headers = build_user_headers(user_id, ROLE_POLICY_ADMIN)
    headers["X-User-Role"] = ""
    return headers


def headers_with_unknown_role(user_id=USER_POLICY_ADMIN, role="ROOT_OPERATOR"):
    """Headers whose `X-User-Role` is not one of the six declared roles."""
    return build_user_headers(user_id, role)
