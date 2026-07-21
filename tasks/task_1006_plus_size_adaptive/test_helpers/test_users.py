"""Pre-built role headers for every role in the PRD.

Two identity models are in play (PRD §2.1):
 - Customer and FitSpecialist are entity-backed: X-User-ID must equal the acting
   entity's id, so ownership-gated calls MUST use the per-instance builders below
   with the real entity id.
 - StoreManager and Anonymous are opaque: a shared constant id is the canonical form.
"""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants.
#  - StoreManager / Anonymous: opaque ids, canonical.
#  - Customer / FitSpecialist entries: fallback for non-ownership tests only
#    (e.g. 401/403/404 probes). Ownership-gated calls must use the builders.
TEST_USERS = {
    "store_manager_headers": build_user_headers("ops-manager-1", "StoreManager"),
    "anonymous_headers": build_user_headers("anon-visitor-1", "Anonymous"),
    "customer_headers": build_user_headers("test-customer-1", "Customer"),
    "fit_specialist_headers": build_user_headers("test-specialist-1", "FitSpecialist"),
}


def make_customer_headers(user_id: str) -> dict:
    """Headers for a Customer (entity_backed:Customer). Pass the real Customer.id
    whenever the call is ownership-gated (own orders/returns/appointments/etc.)."""
    return build_user_headers(user_id, "Customer")


def make_fit_specialist_headers(user_id: str) -> dict:
    """Headers for a FitSpecialist (entity_backed:FitSpecialist). Pass the real
    FitSpecialist.id whenever the call is ownership-gated (own appointments)."""
    return build_user_headers(user_id, "FitSpecialist")


def make_anonymous_headers(user_id: str = "anon-visitor-1") -> dict:
    return build_user_headers(user_id, "Anonymous")


def store_manager_headers() -> dict:
    return TEST_USERS["store_manager_headers"]
