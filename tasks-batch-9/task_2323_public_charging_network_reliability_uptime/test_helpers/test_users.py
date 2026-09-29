"""Pre-built role headers for every role declared by the PRD.

Five of the six roles carry an opaque operator identifier in `X-User-ID`; the
shared constants below are the canonical form for them.  `HostSiteManager` is
different: for that role `X-User-ID` is the `id` of the acting host site, so
ownership-gated calls MUST use `make_host_site_manager_headers(host_site_id)`
with the real host site id.
"""
from typing import Dict

from prd_bench_local_runner.testing import build_user_headers

# ---------------------------------------------------------------------------
# Named operator identities reused across setup chains.  Keeping them as
# constants makes segregation-of-duties assertions readable.
# ---------------------------------------------------------------------------
OPERATOR_1 = "op-1"
OPERATOR_2 = "op-2"
TECHNICIAN_1 = "tech-1"
TECHNICIAN_2 = "tech-2"
TECHNICIAN_3 = "tech-3"
TECHNICIAN_L2 = "tech-l2-1"
TECHNICIAN_HV = "tech-hv-1"
TECHNICIAN_UNASSIGNED = "tech-9"
AUDITOR_1 = "auditor-1"
AUDITOR_2 = "auditor-2"
PROGRAM_ADMIN_1 = "pa-1"
PROGRAM_ADMIN_2 = "pa-2"
SUPPORT_AGENT_1 = "csa-1"
UNKNOWN_USER = "u-9"

# ---------------------------------------------------------------------------
# Shared constants.  Safe for the five opaque roles and for any test that does
# not exercise host-site ownership.
# ---------------------------------------------------------------------------
TEST_USERS: Dict[str, Dict[str, str]] = {
    "network_operator_headers": build_user_headers(OPERATOR_1, "NetworkOperator"),
    "field_technician_headers": build_user_headers(TECHNICIAN_1, "FieldTechnician"),
    "compliance_auditor_headers": build_user_headers(AUDITOR_1, "ComplianceAuditor"),
    "program_administrator_headers": build_user_headers(PROGRAM_ADMIN_1, "ProgramAdministrator"),
    "customer_support_agent_headers": build_user_headers(SUPPORT_AGENT_1, "CustomerSupportAgent"),
    # Fallback only — never use for an ownership-gated host site amendment.
    "host_site_manager_headers": build_user_headers("test-host-site-manager", "HostSiteManager"),
}


# ---------------------------------------------------------------------------
# Per-instance builders.
# ---------------------------------------------------------------------------
def make_host_site_manager_headers(host_site_id: str) -> Dict[str, str]:
    """For HostSiteManager, whose X-User-ID is the id of the acting host site.

    Pass the real HostSite id whenever the call is ownership-gated.
    """
    return build_user_headers(host_site_id, "HostSiteManager")


def make_network_operator_headers(user_id: str) -> Dict[str, str]:
    return build_user_headers(user_id, "NetworkOperator")


def make_field_technician_headers(user_id: str) -> Dict[str, str]:
    return build_user_headers(user_id, "FieldTechnician")


def make_compliance_auditor_headers(user_id: str) -> Dict[str, str]:
    return build_user_headers(user_id, "ComplianceAuditor")


def make_program_administrator_headers(user_id: str) -> Dict[str, str]:
    return build_user_headers(user_id, "ProgramAdministrator")


def make_customer_support_agent_headers(user_id: str) -> Dict[str, str]:
    return build_user_headers(user_id, "CustomerSupportAgent")


def make_headers(user_id: str, role: str) -> Dict[str, str]:
    """Generic builder for role-authorisation tests that sweep every role."""
    return build_user_headers(user_id, role)


# Convenient aliases for the five opaque roles.
OPERATOR_HEADERS = TEST_USERS["network_operator_headers"]
TECHNICIAN_HEADERS = TEST_USERS["field_technician_headers"]
AUDITOR_HEADERS = TEST_USERS["compliance_auditor_headers"]
PROGRAM_ADMIN_HEADERS = TEST_USERS["program_administrator_headers"]
SUPPORT_HEADERS = TEST_USERS["customer_support_agent_headers"]
