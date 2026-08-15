"""Pre-built role headers for every role in the PRD (§2.1).

OpsAdmin is an opaque role: its X-User-ID is not tied to any persisted entity,
so a shared constant is canonical. All other roles are entity-backed by a User
row — ownership checks compare a resource's foreign key to X-User-ID — so
fixtures MUST build per-instance headers with the created user's id via the
make_*_headers builders below.
"""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe for the opaque OpsAdmin role, and as fallbacks for
# tests that never exercise ownership (400/404 probes, role-denial probes).
TEST_USERS = {
    "ops_admin_headers": build_user_headers("test-ops-admin-1", "OpsAdmin"),
    # Fallbacks for non-ownership probes only (these ids resolve to no User row).
    "contract_analyst_headers": build_user_headers("test-contract-analyst-1", "ContractAnalyst"),
    "business_owner_headers": build_user_headers("test-business-owner-1", "BusinessOwner"),
    "legal_counsel_headers": build_user_headers("test-legal-counsel-1", "LegalCounsel"),
    "finance_controller_headers": build_user_headers("test-finance-controller-1", "FinanceController"),
    "chief_counsel_headers": build_user_headers("test-chief-counsel-1", "ChiefCounsel"),
    "signatory_headers": build_user_headers("test-signatory-1", "Signatory"),
}


# Per-instance builders — required for every entity_backed role.
def make_contract_analyst_headers(user_id: str) -> dict:
    """For ContractAnalyst (entity_backed:User). Pass the actual User.id."""
    return build_user_headers(user_id, "ContractAnalyst")


def make_business_owner_headers(user_id: str) -> dict:
    """For BusinessOwner (entity_backed:User). Pass the actual User.id."""
    return build_user_headers(user_id, "BusinessOwner")


def make_legal_counsel_headers(user_id: str) -> dict:
    """For LegalCounsel (entity_backed:User). Pass the actual User.id."""
    return build_user_headers(user_id, "LegalCounsel")


def make_finance_controller_headers(user_id: str) -> dict:
    """For FinanceController (entity_backed:User). Pass the actual User.id."""
    return build_user_headers(user_id, "FinanceController")


def make_chief_counsel_headers(user_id: str) -> dict:
    """For ChiefCounsel (entity_backed:User). Pass the actual User.id."""
    return build_user_headers(user_id, "ChiefCounsel")


def make_signatory_headers(user_id: str) -> dict:
    """For Signatory (entity_backed:User). Pass the actual User.id."""
    return build_user_headers(user_id, "Signatory")


def make_ops_admin_headers(user_id: str = "test-ops-admin-1") -> dict:
    """For OpsAdmin (opaque): the id is not tied to any persisted entity."""
    return build_user_headers(user_id, "OpsAdmin")
