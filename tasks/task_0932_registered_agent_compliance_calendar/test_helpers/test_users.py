"""Pre-built role headers for every role in the PRD.

Four of the five roles carry an opaque operator identifier that the server never
compares to any row's id, so a shared constant is the canonical form for them.
The fifth, ClientContact, carries the id of the acting Client, so ownership-gated
calls must use the per-instance builder with the real client id.
"""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe for the four opaque operator roles.
TEST_USERS = {
    "platform_admin_headers": build_user_headers("admin-1", "PlatformAdmin"),
    "compliance_officer_headers": build_user_headers("officer-1", "ComplianceOfficer"),
    "filing_agent_headers": build_user_headers("agent-9", "FilingAgent"),
    "sop_handler_headers": build_user_headers("sop-3", "SopHandler"),
    # ClientContact is client-backed: this constant is a fallback for tests that
    # do not exercise ownership at all.
    "client_contact_headers": build_user_headers("contact-1", "ClientContact"),
}

ADMIN = TEST_USERS["platform_admin_headers"]
OFFICER = TEST_USERS["compliance_officer_headers"]
AGENT = TEST_USERS["filing_agent_headers"]
SOP = TEST_USERS["sop_handler_headers"]


def make_platform_admin_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "PlatformAdmin")


def make_compliance_officer_headers(user_id: str) -> dict:
    """The acting X-User-ID is stored as a filing's prepared_by_user_id."""
    return build_user_headers(user_id, "ComplianceOfficer")


def make_filing_agent_headers(user_id: str) -> dict:
    """The acting X-User-ID is stored as a filing's submitted_by_user_id."""
    return build_user_headers(user_id, "FilingAgent")


def make_sop_handler_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "SopHandler")


def make_client_contact_headers(client_id: str) -> dict:
    """For ClientContact, X-User-ID is the id of the acting Client. Every
    ownership-gated call must pass the real Client id here."""
    return build_user_headers(client_id, "ClientContact")


def headers_with_role(role: str, user_id: str = "probe-1") -> dict:
    """Headers carrying an arbitrary role string, for the authentication rungs."""
    return build_user_headers(user_id, role)


NO_AUTH_HEADERS = {"Content-Type": "application/json"}
