"""Pre-built role headers for every role in the PRD (§2.1).

Three roles are opaque operator identities (CaseWorker, FinanceOfficer,
Supervisor): X-User-ID is not matched against any persisted record, so the
shared constant is the canonical form.

Two roles are entity-backed (Employer -> Employer.id, CustodialParty ->
CustodialParty.id): ownership checks compare the resource's foreign key to
X-User-ID. For ownership-gated calls use the per-instance builder with the
real entity id; the shared constant is a fallback for non-ownership tests
(401/403/404 paths) only.
"""
from prd_bench_local_runner.testing import build_user_headers


TEST_USERS = {
    # Opaque operator roles — shared constant is canonical.
    "case_worker_headers": build_user_headers("test-caseworker-1", "CaseWorker"),
    "finance_officer_headers": build_user_headers("test-financeofficer-1", "FinanceOfficer"),
    "supervisor_headers": build_user_headers("test-supervisor-1", "Supervisor"),
    # Entity-backed roles — shared constant is a non-ownership fallback only.
    "employer_headers": build_user_headers("test-employer-1", "Employer"),
    "custodial_party_headers": build_user_headers("test-custodialparty-1", "CustodialParty"),
}


def make_employer_headers(user_id: str) -> dict:
    """For Employer (entity_backed:Employer). Pass the actual Employer.id as
    user_id whenever the call is ownership-gated."""
    return build_user_headers(user_id, "Employer")


def make_custodial_party_headers(user_id: str) -> dict:
    """For CustodialParty (entity_backed:CustodialParty). Pass the actual
    CustodialParty.id as user_id whenever the call is ownership-gated."""
    return build_user_headers(user_id, "CustodialParty")
