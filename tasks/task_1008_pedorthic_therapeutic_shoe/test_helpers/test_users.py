"""Pre-built role headers for every role in the PRD (§2.1)."""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants.
# StoreManager and BillingSpecialist have opaque identities (X-User-ID not tied to
# any entity), so a shared constant is the canonical form for them.
# Fitter and Customer are entity_backed; the shared constant is only a fallback for
# tests/setup that do NOT exercise ownership (e.g. RBAC-denial, 404, or measurement
# recording, which carries no fitter foreign key).
TEST_USERS = {
    "store_manager_headers": build_user_headers("00000000-0000-4000-8000-00000000ma01", "StoreManager"),
    "billing_specialist_headers": build_user_headers("00000000-0000-4000-8000-00000000bs01", "BillingSpecialist"),
    "fitter_headers": build_user_headers("00000000-0000-4000-8000-00000000fi01", "Fitter"),
    "customer_headers": build_user_headers("00000000-0000-4000-8000-00000000cu01", "Customer"),
    # Unknown role -> triggers ERR_UNAUTHENTICATED.
    "ghost_headers": build_user_headers("00000000-0000-4000-8000-0000000ghost", "Ghost"),
}


def make_fitter_headers(user_id: str) -> dict:
    """For the Fitter role (entity_backed:Fitter). Pass the acting Fitter's id as
    user_id whenever the call touches a resource that carries a fitter foreign key
    (sales, appointments and their lifecycle), so the ownership check compares equal."""
    return build_user_headers(user_id, "Fitter")


def make_customer_headers(user_id: str) -> dict:
    """For the Customer role (entity_backed:Customer). Pass the acting Customer's id
    as user_id whenever the call is scoped to the caller's own records."""
    return build_user_headers(user_id, "Customer")
