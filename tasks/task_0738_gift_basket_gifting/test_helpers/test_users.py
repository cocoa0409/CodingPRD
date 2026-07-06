"""Pre-built role headers for every role in the PRD.

AccountManager is entity_backed:CorporateAccount — X-User-ID must equal the acting
CorporateAccount.id, and every ownership check against a resource that descends
from a CorporateAccount compares the resource's corporate_account_id against
X-User-ID. All other roles (PlatformAdmin, FinanceApprover, ProofApprover,
WarehouseOps, ShippingOps) are opaque operator identities never compared against
any entity id.

For any ownership-gated AccountManager call, always build per-instance headers
via make_account_manager_headers(account_id) with the real CorporateAccount.id —
never the shared constant, whose id never equals any real account's id.
"""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe for opaque roles, and for tests that don't exercise
# CorporateAccount ownership.
TEST_USERS = {
    # Opaque roles: the shared constant is the canonical form.
    "platform_admin_headers": build_user_headers("admin-op-1", "PlatformAdmin"),
    "finance_approver_headers": build_user_headers("fin-appr-1", "FinanceApprover"),
    "proof_approver_headers": build_user_headers("proof-appr-1", "ProofApprover"),
    "warehouse_ops_headers": build_user_headers("wh-ops-1", "WarehouseOps"),
    "shipping_ops_headers": build_user_headers("ship-ops-1", "ShippingOps"),
    # entity_backed AccountManager: shared constant is a fallback for non-ownership probes.
    "account_manager_headers": build_user_headers("acct-mgr-1", "AccountManager"),
    # Anonymous: no role header — trips ERR_UNAUTHENTICATED.
    "anonymous_headers": {"Content-Type": "application/json"},
}


def make_account_manager_headers(account_id: str) -> dict:
    """For the AccountManager role (entity_backed:CorporateAccount). Pass the actual
    CorporateAccount.id as user_id whenever the call is ownership-gated (own
    branding profiles, orders, imports, message proofs, recurring series)."""
    return build_user_headers(account_id, "AccountManager")


def make_finance_approver_headers(user_id: str = "fin-appr-1") -> dict:
    """FinanceApprover is opaque; the id ends up on BudgetApproval.approver_user_id
    but is never owner-matched. Pass a distinct id when the approver must differ
    from the requester (segregation of duties)."""
    return build_user_headers(user_id, "FinanceApprover")


def make_proof_approver_headers(user_id: str = "proof-appr-1") -> dict:
    """ProofApprover is opaque; the id ends up on MessageProof.decided_by_user_id
    but is never owner-matched."""
    return build_user_headers(user_id, "ProofApprover")


def make_platform_admin_headers(user_id: str = "admin-op-1") -> dict:
    """PlatformAdmin is opaque; the id is not persisted as an owner reference."""
    return build_user_headers(user_id, "PlatformAdmin")


def make_warehouse_ops_headers(user_id: str = "wh-ops-1") -> dict:
    """WarehouseOps is opaque."""
    return build_user_headers(user_id, "WarehouseOps")


def make_shipping_ops_headers(user_id: str = "ship-ops-1") -> dict:
    """ShippingOps is opaque."""
    return build_user_headers(user_id, "ShippingOps")
