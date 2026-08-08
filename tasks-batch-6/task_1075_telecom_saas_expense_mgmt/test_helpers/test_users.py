"""Pre-built role headers for every role in the PRD."""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe for opaque roles and for tests that do not exercise
# resource ownership. Sourcing, Analyst, FinanceApprover, SystemAdmin carry an
# opaque X-User-ID; CostCenterOwner and Vendor are entity_backed, so their shared
# constants are only a fallback for non-ownership tests — ownership-gated calls
# MUST use the per-instance builders below.
TEST_USERS = {
    "sourcing_headers": build_user_headers("srcg-1", "Sourcing"),
    "analyst_headers": build_user_headers("anlyst-1", "Analyst"),
    "finance_approver_headers": build_user_headers("fa_1", "FinanceApprover"),
    "system_admin_headers": build_user_headers("sysadmin-1", "SystemAdmin"),
    "cost_center_owner_headers": build_user_headers("own_a", "CostCenterOwner"),
    "vendor_headers": build_user_headers("vendor-1", "Vendor"),
}

# Empty headers for the unauthenticated case (no X-User-ID / X-User-Role).
ANONYMOUS_HEADERS: dict = {}


# ---- Per-instance builders ----

def make_sourcing_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "Sourcing")


def make_analyst_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "Analyst")


def make_finance_approver_headers(user_id: str) -> dict:
    """FinanceApprover with a specific opaque X-User-ID; needed to exercise
    separation of duties on invoice pay (approver != payer)."""
    return build_user_headers(user_id, "FinanceApprover")


def make_system_admin_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "SystemAdmin")


def make_cost_center_owner_headers(owner_user_id: str) -> dict:
    """For CostCenterOwner (entity_backed:CostCenter). Pass the cost center's
    owner_user_id so ownership checks (X-User-ID == cost_center.owner_user_id)
    pass."""
    return build_user_headers(owner_user_id, "CostCenterOwner")


def make_vendor_headers(vendor_id: str) -> dict:
    """For Vendor (entity_backed:Vendor). Pass the acting vendor's id."""
    return build_user_headers(vendor_id, "Vendor")
