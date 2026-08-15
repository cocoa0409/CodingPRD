"""Pre-built role headers for every role in the PRD.

Seven acting roles use opaque operator identifiers: RevenueCycleAdmin,
HIMCoordinator, AppealsSpecialist, DepartmentDirector, PFSAccountant,
ComplianceOfficer, and InternalAuditor. PayerAgent is entity-backed by Payer:
its X-User-ID MUST equal the id of the Payer it acts for, so every
ownership-gated PayerAgent call MUST use make_payer_agent_headers(payer_id)
with the real Payer.id — never the shared fallback constant.

The shared reader_headers entry (an ordinary HIMCoordinator identity) is used
for plain GET reads, which the PRD opens to any authenticated caller.
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    "admin_headers": build_user_headers("test-admin-1", "RevenueCycleAdmin"),
    "him_headers": build_user_headers("test-him-1", "HIMCoordinator"),
    "specialist_headers": build_user_headers("test-specialist-1", "AppealsSpecialist"),
    "director_headers": build_user_headers("test-director-1", "DepartmentDirector"),
    "accountant_headers": build_user_headers("test-accountant-1", "PFSAccountant"),
    "compliance_headers": build_user_headers("test-co-1", "ComplianceOfficer"),
    "auditor_headers": build_user_headers("test-ia-1", "InternalAuditor"),
    # entity_backed role: shared constant is a fallback for non-ownership
    # tests only (it never equals any real Payer.id).
    "payer_agent_headers": build_user_headers("test-payer-agent-1", "PayerAgent"),
    # plain reader identity for the open GET endpoints
    "reader_headers": build_user_headers("test-reader-1", "HIMCoordinator"),
}


def make_admin_headers(user_id: str = "test-admin-1") -> dict:
    return build_user_headers(user_id, "RevenueCycleAdmin")


def make_him_headers(user_id: str = "test-him-1") -> dict:
    return build_user_headers(user_id, "HIMCoordinator")


def make_specialist_headers(user_id: str = "test-specialist-1") -> dict:
    return build_user_headers(user_id, "AppealsSpecialist")


def make_director_headers(user_id: str = "test-director-1") -> dict:
    return build_user_headers(user_id, "DepartmentDirector")


def make_accountant_headers(user_id: str = "test-accountant-1") -> dict:
    return build_user_headers(user_id, "PFSAccountant")


def make_compliance_headers(user_id: str = "co-1") -> dict:
    return build_user_headers(user_id, "ComplianceOfficer")


def make_auditor_headers(user_id: str = "ia-1") -> dict:
    return build_user_headers(user_id, "InternalAuditor")


def make_payer_agent_headers(payer_id: str) -> dict:
    """For PayerAgent (entity_backed:Payer). Pass the acting Payer.id whenever
    the call is ownership-gated (review, determination, decision, demand
    create/adjust, remittance create)."""
    return build_user_headers(payer_id, "PayerAgent")
