"""Role headers.

Two roles are opaque operator identities: FinanceAnalyst and ComplianceOfficer.
Their `X-User-ID` is any stable operator handle, and the suite deliberately uses
several distinct handles so that the two segregation-of-duties controls (which
compare `X-User-ID`) can be exercised.

Three roles are entity-backed: ProducerAgent, Insurer and Insured.  For those
the `X-User-ID` must equal the id of the corresponding row, so tests MUST build
their headers per-instance with the real entity id rather than reuse a constant.
"""

from typing import Dict

from prd_bench_local_runner.testing import build_user_headers

from .types import Role

# ---------------------------------------------------------------------------
# Opaque operator handles.  Distinct handles matter:
#   * originating an agreement and approving its rate exception must differ
#   * issuing a cancellation notice and executing it must differ
# ---------------------------------------------------------------------------
ANALYST_ORIGIN_USER_ID = "analyst-origin"
ANALYST_NOTICE_USER_ID = "analyst-notice"
ANALYST_POA_USER_ID = "analyst-poa"
ANALYST_EXECUTOR_USER_ID = "analyst-executor"
ANALYST_SERVICING_USER_ID = "analyst-servicing"
COMPLIANCE_USER_ID = "compliance-officer"
COMPLIANCE_APPROVER_USER_ID = "compliance-approver"
COMPLIANCE_WAIVER_USER_ID = "compliance-waiver"

# ---------------------------------------------------------------------------
# Pre-built headers for the two opaque roles.
# ---------------------------------------------------------------------------
ANALYST = build_user_headers(ANALYST_ORIGIN_USER_ID, Role.FINANCE_ANALYST.value)
ANALYST_ORIGIN = ANALYST
ANALYST_NOTICE = build_user_headers(
    ANALYST_NOTICE_USER_ID, Role.FINANCE_ANALYST.value
)
ANALYST_POA = build_user_headers(ANALYST_POA_USER_ID, Role.FINANCE_ANALYST.value)
ANALYST_EXECUTOR = build_user_headers(
    ANALYST_EXECUTOR_USER_ID, Role.FINANCE_ANALYST.value
)
ANALYST_SERVICING = build_user_headers(
    ANALYST_SERVICING_USER_ID, Role.FINANCE_ANALYST.value
)
COMPLIANCE = build_user_headers(COMPLIANCE_USER_ID, Role.COMPLIANCE_OFFICER.value)
COMPLIANCE_APPROVER = build_user_headers(
    COMPLIANCE_APPROVER_USER_ID, Role.COMPLIANCE_OFFICER.value
)
COMPLIANCE_WAIVER = build_user_headers(
    COMPLIANCE_WAIVER_USER_ID, Role.COMPLIANCE_OFFICER.value
)


# ---------------------------------------------------------------------------
# Per-instance builders for the three entity-backed roles.
# ---------------------------------------------------------------------------
def make_producer_agent_headers(user_id: str) -> Dict[str, str]:
    """Headers for a ProducerAgent whose X-User-ID is that agency's own id."""
    return build_user_headers(user_id, Role.PRODUCER_AGENT.value)


def make_insurer_headers(user_id: str) -> Dict[str, str]:
    """Headers for an Insurer whose X-User-ID is that carrier's own id."""
    return build_user_headers(user_id, Role.INSURER.value)


def make_insured_headers(user_id: str) -> Dict[str, str]:
    """Headers for an Insured whose X-User-ID is that borrower's own id."""
    return build_user_headers(user_id, Role.INSURED.value)


def make_analyst_headers(user_id: str) -> Dict[str, str]:
    """Headers for a FinanceAnalyst under an arbitrary operator handle."""
    return build_user_headers(user_id, Role.FINANCE_ANALYST.value)


def make_compliance_headers(user_id: str) -> Dict[str, str]:
    """Headers for a ComplianceOfficer under an arbitrary operator handle."""
    return build_user_headers(user_id, Role.COMPLIANCE_OFFICER.value)


def make_headers(user_id: str, role: str) -> Dict[str, str]:
    """Headers for any (user id, role) pair, including unknown role strings."""
    return build_user_headers(user_id, role)


# Headers with no identity at all: both header fields omitted.
NO_AUTH_HEADERS: Dict[str, str] = {"Content-Type": "application/json"}

# Headers that name a role the API does not recognise.
UNKNOWN_ROLE_HEADERS = build_user_headers("stranger-1", "Underwriter")
