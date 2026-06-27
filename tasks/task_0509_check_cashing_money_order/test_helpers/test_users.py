"""Pre-built role headers for every role in the PRD (§2.1).

Both roles use an OPAQUE identity (PRD §2.1): X-User-ID is an opaque operator
identifier never matched against any entity's id. It IS, however, recorded as a
transaction's creating Teller and compared against the resolving StoreManager's
X-User-ID for segregation-of-duties (PRD §2.7). Tests that exercise SoD therefore
need distinct operator ids — use make_teller_headers(...) / make_store_manager_headers(...)
with explicit ids.
"""
from prd_bench_local_runner.testing import build_user_headers


# Shared constants — canonical form for opaque roles. The default teller id
# "teller-1" and manager id "manager-9" deliberately differ so SoD is satisfied
# whenever a manager built from the shared constant resolves a teller-1-created txn.
TEST_USERS = {
    "teller_headers": build_user_headers("teller-1", "Teller"),
    "store_manager_headers": build_user_headers("manager-9", "StoreManager"),
}


def make_teller_headers(user_id: str = "teller-1") -> dict:
    """For Teller (opaque). user_id is recorded as a transaction's creating Teller
    for later segregation-of-duties enforcement (PRD §2.7)."""
    return build_user_headers(user_id, "Teller")


def make_store_manager_headers(user_id: str = "manager-9") -> dict:
    """For StoreManager (opaque). user_id is the SoD subject when releasing/rejecting
    a held check or voiding a transaction (PRD §2.7)."""
    return build_user_headers(user_id, "StoreManager")
