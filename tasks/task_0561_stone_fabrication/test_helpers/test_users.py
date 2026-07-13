"""Pre-built role headers for every role in the PRD.

All four roles are opaque operator identities: the server never ties X-User-ID to a
persisted entity and never infers ownership from it (PRD §2.1). Shared constants are
therefore the canonical form for every role — no per-instance builders are required.
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    "shopmanager_headers": build_user_headers("test-shopmanager-1", "ShopManager"),
    "salesrep_headers": build_user_headers("test-salesrep-1", "SalesRep"),
    "fabricator_headers": build_user_headers("test-fabricator-1", "Fabricator"),
    "installer_headers": build_user_headers("test-installer-1", "Installer"),
}
