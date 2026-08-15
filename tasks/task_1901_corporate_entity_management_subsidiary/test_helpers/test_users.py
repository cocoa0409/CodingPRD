"""Pre-built role headers for every role in the PRD (PRD 2.1).

`AuthorizedOfficer` and `RegisteredAgentUser` are entity-backed roles: their
`X-User-ID` must be the id of an existing Officer / RegisteredAgent record.
Use the per-instance builders for any call whose outcome depends on identity
(resign, file-resignation-notice, verify-as-officer). The shared constants for
those roles are fallbacks for tests that do not exercise ownership.
"""
from prd_bench_local_runner.testing import build_user_headers

# Opaque roles: X-User-ID is an operator identifier not tied to any record.
TEST_USERS = {
    "secretary_1_headers": build_user_headers("sec-01", "CorporateSecretary"),
    "secretary_2_headers": build_user_headers("sec-02", "CorporateSecretary"),
    "filing_coordinator_headers": build_user_headers("fc-01", "FilingCoordinator"),
    "compliance_auditor_headers": build_user_headers("aud-01", "ComplianceAuditor"),
    # Entity-backed fallbacks (non-ownership tests only).
    "authorized_officer_headers": build_user_headers("officer-unbound", "AuthorizedOfficer"),
    "registered_agent_user_headers": build_user_headers("agent-unbound", "RegisteredAgentUser"),
}


def make_officer_headers(officer_id: str) -> dict:
    """AuthorizedOfficer is entity-backed: pass the actual Officer.id whenever
    the call is ownership-gated (e.g. resigning that officer's appointment)."""
    return build_user_headers(officer_id, "AuthorizedOfficer")


def make_agent_headers(agent_id: str) -> dict:
    """RegisteredAgentUser is entity-backed: pass the actual RegisteredAgent.id
    whenever the call is ownership-gated (e.g. filing a resignation notice)."""
    return build_user_headers(agent_id, "RegisteredAgentUser")
