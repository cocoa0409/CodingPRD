"""Pre-built role headers for every role in the PRD.

Five roles (PRD §2.1): PetParent is the only entity-backed role — its ``X-User-ID`` must equal
the acting Account's ``id`` for ownership-gated calls, so use ``make_pet_parent_headers(account_id)``.
The other four roles are opaque operator identities; their shared constants are the canonical form.
"""
from prd_bench_local_runner.testing import build_user_headers


# Shared constants.
#   - The four opaque roles: canonical form (no ownership comparison server-side).
#   - pet_parent_headers: a FALLBACK only for tests that do NOT exercise ownership
#     (e.g. 401/400/404 paths, or RBAC-forbidden checks). Ownership-gated calls MUST
#     use make_pet_parent_headers(account_id) instead.
TEST_USERS = {
    "pet_parent_headers": build_user_headers("test-pet-parent-1", "PetParent"),
    "nutrition_vet_headers": build_user_headers("test-nutrition-vet-1", "NutritionVet"),
    "billing_admin_headers": build_user_headers("test-billing-admin-1", "BillingAdmin"),
    "fulfillment_ops_headers": build_user_headers("test-fulfillment-ops-1", "FulfillmentOps"),
    "anonymous_headers": build_user_headers("test-anonymous-1", "Anonymous"),
}


def make_pet_parent_headers(account_id: str) -> dict:
    """For PetParent (entity_backed:Account). Pass the actual Account.id as the user id
    whenever the call is ownership-gated (any operation on that account's pets, weight logs,
    subscriptions, orders, or referral credits)."""
    return build_user_headers(account_id, "PetParent")


def make_anonymous_headers() -> dict:
    """Anonymous capacity (registration, redeem-preview, clock read)."""
    return TEST_USERS["anonymous_headers"]
