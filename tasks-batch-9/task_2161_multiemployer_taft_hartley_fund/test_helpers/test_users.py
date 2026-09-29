"""Pre-built role headers for the five roles the PRD declares.

Three roles carry an opaque operator identifier that the server records but
never compares against any row's ``id``: ``FundAdministrator``,
``PayrollAuditor`` and ``Actuary``.  Two are entity-backed: a
``ContributingEmployer`` call carries the acting Employer's own ``id``, and a
``Trustee`` call carries the acting Trustee's own ``id``.  Ownership-gated
calls for those two MUST be built with the per-instance builders below.
"""

from prd_bench_local_runner.testing import build_user_headers

ADMIN_USER_ID = "admin-001"
SECOND_ADMIN_USER_ID = "admin-002"
AUDITOR_USER_ID = "auditor-001"
SECOND_AUDITOR_USER_ID = "auditor-002"
THIRD_AUDITOR_USER_ID = "auditor-003"
ACTUARY_USER_ID = "actuary-001"

TEST_USERS = {
    "fund_administrator_headers": build_user_headers(ADMIN_USER_ID, "FundAdministrator"),
    "second_administrator_headers": build_user_headers(
        SECOND_ADMIN_USER_ID, "FundAdministrator"
    ),
    "payroll_auditor_headers": build_user_headers(AUDITOR_USER_ID, "PayrollAuditor"),
    "second_auditor_headers": build_user_headers(
        SECOND_AUDITOR_USER_ID, "PayrollAuditor"
    ),
    "actuary_headers": build_user_headers(ACTUARY_USER_ID, "Actuary"),
    # Placeholders only.  A ContributingEmployer or Trustee call that touches an
    # ownership check must use the builders below with a real row id.
    "contributing_employer_headers": build_user_headers(
        "employer-unbound", "ContributingEmployer"
    ),
    "trustee_headers": build_user_headers("trustee-unbound", "Trustee"),
}


def make_employer_headers(employer_id: str) -> dict:
    """Headers for the ContributingEmployer whose Employer id is given."""
    return build_user_headers(employer_id, "ContributingEmployer")


def make_trustee_headers(trustee_id: str) -> dict:
    """Headers for the Trustee whose Trustee id is given."""
    return build_user_headers(trustee_id, "Trustee")


def make_administrator_headers(user_id: str) -> dict:
    """Headers for a named FundAdministrator operator identity."""
    return build_user_headers(user_id, "FundAdministrator")


def make_auditor_headers(user_id: str) -> dict:
    """Headers for a named PayrollAuditor operator identity."""
    return build_user_headers(user_id, "PayrollAuditor")


def make_actuary_headers(user_id: str) -> dict:
    """Headers for a named Actuary operator identity."""
    return build_user_headers(user_id, "Actuary")


def make_headers_with_unknown_role(user_id: str = "someone") -> dict:
    """Headers naming a role outside the five the PRD declares."""
    return {
        "X-User-ID": user_id,
        "X-User-Role": "Bookkeeper",
        "Content-Type": "application/json",
    }


NO_AUTH_HEADERS = {"Content-Type": "application/json"}
