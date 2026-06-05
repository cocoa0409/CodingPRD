"""Pre-built role headers for every role in the PRD (§2.1).

- RentalAgent and DepositAdjuster carry opaque operator IDs not tied to any
  persisted entity, so a shared constant is the canonical form.
- Customer's X-User-ID must equal the acting Customer entity's id for ownership
  checks to pass; use make_customer_headers(customer_id) for ownership-gated calls.
"""
from prd_bench_local_runner.testing import build_user_headers


# Shared constants.
# RentalAgent / DepositAdjuster: opaque — these IDs are never compared to any entity.
# customer_headers: a fallback for tests that do NOT exercise ownership (e.g. the
# anonymous/unauthorized cases); ownership-gated calls MUST use make_customer_headers.
TEST_USERS = {
    "rental_agent_headers": build_user_headers("agent-001", "RentalAgent"),
    "deposit_adjuster_headers": build_user_headers("adjuster-001", "DepositAdjuster"),
    "customer_headers": build_user_headers("customer-unowned", "Customer"),
}


def make_customer_headers(user_id: str) -> dict:
    """For Customer (entity_backed:Customer). Pass the actual Customer.id as
    user_id whenever the call is ownership-gated (own order/venue mutations)."""
    return build_user_headers(user_id, "Customer")


def make_rental_agent_headers(user_id: str = "agent-001") -> dict:
    """RentalAgent is opaque; any id authenticates and no ownership check applies."""
    return build_user_headers(user_id, "RentalAgent")


def make_deposit_adjuster_headers(user_id: str = "adjuster-001") -> dict:
    """DepositAdjuster is opaque; any id authenticates and no ownership check applies."""
    return build_user_headers(user_id, "DepositAdjuster")


def anonymous_headers() -> dict:
    """Headers with no role/id — used to exercise ERR_UNAUTHENTICATED."""
    return {"Content-Type": "application/json"}
