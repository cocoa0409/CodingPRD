"""Pre-built role headers for every role in the PRD (Section 2.1).

Every role's X-User-ID is an opaque operator identifier (PRD Section 2.1:
"the X-User-ID header is an opaque operator identifier that is not tied to
any persisted entity"), so a single shared constant per role is safe. Tests
that exercise segregation of duties (PRD Section 2.9) build distinct users
via make_user_headers.
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    "registration_principal_headers": build_user_headers(
        "rp-default-1", "RegistrationPrincipal"
    ),
    "compliance_officer_headers": build_user_headers(
        "co-default-1", "ComplianceOfficer"
    ),
    "finance_clerk_headers": build_user_headers("fc-default-1", "FinanceClerk"),
    "system_operator_headers": build_user_headers("so-default-1", "SystemOperator"),
    "regulator_headers": build_user_headers("reg-default-1", "Regulator"),
}


def make_user_headers(user_id: str, role: str) -> dict:
    """Build headers for a specific user id in a specific role.

    Segregation-of-duties tests (PRD Section 2.9) use this to give the
    filer and the reviewer distinct — or deliberately identical — user ids.
    """
    return build_user_headers(user_id, role)


def make_registration_principal_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "RegistrationPrincipal")


def make_compliance_officer_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "ComplianceOfficer")
