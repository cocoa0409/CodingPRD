"""Pre-built role headers for every role in the PRD.

Only `Homeowner` is entity-backed: when X-User-Role is Homeowner, X-User-ID must be
the acting Homeowner's id, and ownership checks compare a resource's homeowner FK to it.
The other five roles are opaque operator identities never compared to any entity id, so
the shared constants below are the canonical form for them.
"""
from prd_bench_local_runner.testing import build_user_headers


TEST_USERS = {
    # Homeowner: entity_backed — shared constant is a fallback for non-ownership tests
    # (e.g. 403/404 checks). Ownership-gated calls must use make_homeowner_headers(id).
    "homeowner_headers": build_user_headers("test-homeowner-1", "Homeowner"),
    # Opaque operator roles — shared constant is the canonical form.
    "estimator_headers": build_user_headers("test-estimator-1", "Estimator"),
    "inspector_headers": build_user_headers("test-inspector-1", "Inspector"),
    "scheduler_headers": build_user_headers("test-scheduler-1", "Scheduler"),
    "warranty_admin_headers": build_user_headers("test-warranty-admin-1", "WarrantyAdmin"),
    "finance_partner_headers": build_user_headers("test-finance-partner-1", "FinancePartner"),
}


def make_homeowner_headers(user_id: str) -> dict:
    """For Homeowner (entity_backed:Homeowner). Pass the actual Homeowner.id as user_id
    whenever the call is ownership-gated (accept/decline quote, pay-cash, financing,
    reopen claim, file claim, GET on own resources)."""
    return build_user_headers(user_id, "Homeowner")
