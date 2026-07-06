"""Pre-built role headers for every role in the PRD (§2.1).

AgencyAdmin and AccountManager are OPAQUE operators: X-User-ID is an opaque
identifier never matched against any entity id, so shared constants are correct
for them in every test.

Reseller and Client are ENTITY-BACKED: X-User-ID must be the acting Reseller.id
or Client.id, respectively. For ownership-gated calls, tests/fixtures MUST use
make_reseller_headers(reseller["id"]) / make_client_headers(client["id"]) with
the real entity id — never the shared constant, which would never own any
resource and would trip every ownership check.
"""
from prd_bench_local_runner.testing import build_user_headers


# Shared constants — opaque roles use these everywhere; entity-backed shared
# constants are a fallback for non-ownership tests only (e.g. 401/403/404 paths).
TEST_USERS = {
    "agency_admin_headers": build_user_headers("op-admin-1", "AgencyAdmin"),
    "account_manager_headers": build_user_headers("op-am-1", "AccountManager"),
    "reseller_headers": build_user_headers("test-reseller-1", "Reseller"),
    "client_headers": build_user_headers("test-client-1", "Client"),
}


def make_reseller_headers(user_id: str) -> dict:
    """For Reseller (entity_backed:Reseller). Pass the actual Reseller.id when
    the call is ownership-gated."""
    return build_user_headers(user_id, "Reseller")


def make_client_headers(user_id: str) -> dict:
    """For Client (entity_backed:Client). Pass the actual Client.id when the call
    is ownership-gated (sign/approve/request_revision/withdraw, own-client reads)."""
    return build_user_headers(user_id, "Client")
