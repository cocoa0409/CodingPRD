"""Pre-built role headers for every role in the PRD (§2.1).

Customer is entity-backed: when X-User-Role is Customer, X-User-ID must be the
acting Customer's id for ownership-gated calls (design approve / revision,
delivery confirmation, warranty claims, storage return confirmation). Use
make_customer_headers(customer["id"]) for those calls; the shared constant is
only safe for negative RBAC probes. The other four roles are opaque operator
identities and use the shared constants.
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    "loft_manager_headers": build_user_headers("loft-manager-1", "LoftManager"),
    "sailmaker_headers": build_user_headers("sailmaker-1", "Sailmaker"),
    "measurer_headers": build_user_headers("measurer-1", "Measurer"),
    "rigger_headers": build_user_headers("rigger-1", "Rigger"),
    # entity_backed:Customer — fallback for non-ownership probes only.
    "customer_headers": build_user_headers("customer-orphan-1", "Customer"),
}


def make_customer_headers(customer_id: str) -> dict:
    """Customer is entity-backed by Customer: pass the acting customer's id
    whenever the call is ownership-gated."""
    return build_user_headers(customer_id, "Customer")
