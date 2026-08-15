"""Pre-built role headers for every role in the PRD (§2.1).

FirmAdmin and AssessorClerk use opaque identifiers not tied to any persisted
entity, so shared constants are canonical for them. TaxAnalyst, SeniorManager,
and Client are entity-backed: for ownership-gated or attribution-bearing calls
their X-User-ID must be the actual Operator.id / ClientAccount.id, so use the
per-instance builders below.
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    # Opaque roles — shared constants are the canonical form.
    "firm_admin_headers": build_user_headers("test-firm-admin-1", "FirmAdmin"),
    "assessor_clerk_headers": build_user_headers("test-assessor-clerk-1", "AssessorClerk"),
    # Entity-backed roles — fallback constants ONLY for tests that do not
    # exercise ownership, segregation-of-duties, or attribution (e.g. a 400
    # bad-payload check). Prefer the per-instance builders.
    "tax_analyst_headers": build_user_headers("test-analyst-1", "TaxAnalyst"),
    "senior_manager_headers": build_user_headers("test-manager-1", "SeniorManager"),
    "client_headers": build_user_headers("test-client-1", "Client"),
}


def make_tax_analyst_headers(operator_id: str) -> dict:
    """For TaxAnalyst (entity-backed by Operator). Pass the real Operator.id."""
    return build_user_headers(operator_id, "TaxAnalyst")


def make_senior_manager_headers(operator_id: str) -> dict:
    """For SeniorManager (entity-backed by Operator). Pass the real Operator.id."""
    return build_user_headers(operator_id, "SeniorManager")


def make_client_headers(client_id: str) -> dict:
    """For Client (entity-backed by ClientAccount). Pass the real ClientAccount.id
    whenever the call is ownership-gated (appeal resolve/close, pay-installment)."""
    return build_user_headers(client_id, "Client")
