"""Pre-built role headers for every role in PRD §2.1.

All four roles use opaque operator identities — X-User-ID is never an entity
id and the server performs no ownership scoping. Shared constants are the
canonical form for every role here.
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    "court_headers": build_user_headers("court-clerk-1", "Court"),
    "receiver_headers": build_user_headers("receiver-op-1", "Receiver"),
    "creditor_headers": build_user_headers("creditor-acct-1", "Creditor"),
    "system_admin_headers": build_user_headers("sysadmin-1", "SystemAdmin"),
}

# Header sets for negative authentication probes.
UNKNOWN_ROLE_HEADERS = {
    "X-User-ID": "anon-1",
    "X-User-Role": "Nobody",
    "Content-Type": "application/json",
}
NO_ROLE_HEADERS = {"X-User-ID": "anon-1", "Content-Type": "application/json"}
