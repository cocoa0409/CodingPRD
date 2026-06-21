"""Pre-built role headers for every role in the PRD.

PRD §2.1: the five roles are spelled exactly PlatformAdmin, Customer,
DispatchAgent, PlantOperator, ClaimsAdjuster. For a Customer caller, X-User-ID
is the id of the acting Customer and ownership is checked against the resource's
customer foreign key; for the other four roles X-User-ID is an opaque operator
identifier not tied to any entity.
"""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe for opaque roles and for tests that do not exercise
# Customer resource-ownership. The Customer entry here is a non-owning fallback
# only (e.g. malformed-payload / not-found probes that never reach ownership).
TEST_USERS = {
    "admin_headers": build_user_headers("op-admin-1", "PlatformAdmin"),
    "dispatch_headers": build_user_headers("op-dispatch-1", "DispatchAgent"),
    "plant_headers": build_user_headers("op-plant-1", "PlantOperator"),
    "adjuster_headers": build_user_headers("op-adjuster-1", "ClaimsAdjuster"),
    # entity_backed:Customer — shared constant is a fallback for non-ownership tests.
    "customer_headers": build_user_headers("non-owning-customer", "Customer"),
}


# Per-instance builder — REQUIRED for the entity_backed Customer role.
def make_customer_headers(customer_id: str) -> dict:
    """For the Customer role (entity_backed:Customer). Pass the real Customer.id
    so ownership-gated calls (their own orders/subscriptions/claims) pass."""
    return build_user_headers(customer_id, "Customer")


def admin_headers() -> dict:
    return TEST_USERS["admin_headers"]


def dispatch_headers() -> dict:
    return TEST_USERS["dispatch_headers"]


def plant_headers() -> dict:
    return TEST_USERS["plant_headers"]


def adjuster_headers() -> dict:
    return TEST_USERS["adjuster_headers"]
