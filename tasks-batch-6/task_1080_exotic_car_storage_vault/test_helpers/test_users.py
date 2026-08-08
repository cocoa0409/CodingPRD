"""Pre-built role headers for every role in the PRD (§2.1)."""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe for opaque roles, and for tests that don't exercise
# Member ownership. VaultManager, ConciergeTech, BillingAdmin are opaque roles:
# X-User-ID is not matched against any entity id, so a constant is canonical.
TEST_USERS = {
    # entity_backed role: shared constant is a fallback for non-ownership tests only.
    "member_headers": build_user_headers("test-member-1", "Member"),
    # opaque roles: shared constant is the canonical form.
    "vault_manager_headers": build_user_headers("test-vaultmanager-1", "VaultManager"),
    "concierge_tech_headers": build_user_headers("test-concierge-1", "ConciergeTech"),
    "billing_admin_headers": build_user_headers("test-billing-1", "BillingAdmin"),
}


def make_member_headers(user_id: str) -> dict:
    """For Member (entity_backed:Member). Pass the actual Member.id as user_id
    whenever the call is ownership-gated (create vehicle/agreement action, claim,
    pay own invoice, etc.)."""
    return build_user_headers(user_id, "Member")


def make_vault_manager_headers(user_id: str = "test-vaultmanager-1") -> dict:
    return build_user_headers(user_id, "VaultManager")


def make_concierge_headers(user_id: str = "test-concierge-1") -> dict:
    return build_user_headers(user_id, "ConciergeTech")


def make_billing_headers(user_id: str = "test-billing-1") -> dict:
    return build_user_headers(user_id, "BillingAdmin")
