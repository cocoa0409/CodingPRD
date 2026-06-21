"""Pre-built role headers for every role in the PRD (§2.1).

There are exactly four roles: AgencyAdmin, Producer, AccountManager, TrustAccountant.

- AgencyAdmin, AccountManager, TrustAccountant are OPAQUE: X-User-ID is an operator
  identifier not tied to any persisted entity, so a shared constant is the canonical form.
- Producer is ENTITY-BACKED: X-User-ID must equal the acting Producer.id, and ownership
  checks compare the resource's producer foreign-key to X-User-ID. Any ownership-gated
  Producer call MUST use make_producer_headers(producer["id"]).
"""
from prd_bench_local_runner.testing import build_user_headers


# Shared constants — safe for opaque roles, and for tests that do not exercise ownership.
TEST_USERS = {
    "agency_admin_headers": build_user_headers("test-agency-admin-1", "AgencyAdmin"),
    "account_manager_headers": build_user_headers("test-account-manager-1", "AccountManager"),
    "trust_accountant_headers": build_user_headers("test-trust-accountant-1", "TrustAccountant"),
    # Fallback constant for Producer — ONLY for non-ownership tests (403/404/400 paths).
    "producer_headers": build_user_headers("test-producer-1", "Producer"),
}


def make_producer_headers(producer_id: str) -> dict:
    """For the Producer role (entity_backed:Producer). Pass the actual Producer.id as
    user_id whenever the call is ownership-gated (e.g. binding a policy whose
    writing_producer_id equals this producer)."""
    return build_user_headers(producer_id, "Producer")
