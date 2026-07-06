"""Pre-built role headers for every role in the PRD (§2.1).

EmployerAgent is an entity-backed role: when acting on an owned resource,
X-User-ID must equal the acting Employer's id. Use make_employer_agent_headers()
with the real employer id for ownership-gated calls. The shared constant is a
fallback for calls that do not exercise ownership (e.g. POST /employers itself,
403/401/404 checks).

DOLAnalyst, USCISOfficer, and ComplianceAuditor are opaque operator identities;
their X-User-ID is not tied to any entity, so the shared constants are canonical.
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    # entity_backed role: shared constant is a fallback for non-ownership tests only.
    "employer_agent_headers": build_user_headers("test-employer-agent-1", "EmployerAgent"),
    # opaque roles: shared constant is the canonical form.
    "dol_analyst_headers": build_user_headers("test-dol-analyst-1", "DOLAnalyst"),
    "uscis_officer_headers": build_user_headers("test-uscis-officer-1", "USCISOfficer"),
    "compliance_auditor_headers": build_user_headers("test-compliance-auditor-1", "ComplianceAuditor"),
}


def make_employer_agent_headers(user_id: str) -> dict:
    """For EmployerAgent (entity_backed:Employer). Pass the acting Employer.id as
    user_id whenever the call is ownership-gated."""
    return build_user_headers(user_id, "EmployerAgent")


def make_dol_analyst_headers(user_id: str = "test-dol-analyst-1") -> dict:
    return build_user_headers(user_id, "DOLAnalyst")


def make_uscis_officer_headers(user_id: str = "test-uscis-officer-1") -> dict:
    return build_user_headers(user_id, "USCISOfficer")


def make_compliance_auditor_headers(user_id: str = "test-compliance-auditor-1") -> dict:
    return build_user_headers(user_id, "ComplianceAuditor")


def role_only_headers(role: str) -> dict:
    """Headers carrying only X-User-Role (no X-User-ID) for the missing-header
    authentication test (PRD §2.1)."""
    return {"X-User-Role": role}
