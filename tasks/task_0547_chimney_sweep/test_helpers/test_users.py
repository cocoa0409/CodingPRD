"""Pre-built role headers for every role in the PRD (§2.1)."""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants.
#  - Dispatcher and BillingClerk are opaque operator identities: the shared
#    constant is the canonical form (the server never matches X-User-ID to an entity).
#  - Technician is entity-backed: the shared constant is a fallback for tests that
#    do NOT exercise the appointment-ownership identity check. For ownership-gated
#    appointment transitions, use make_technician_headers(technician_id) instead.
TEST_USERS = {
    "dispatcher_headers": build_user_headers("test-dispatcher-1", "Dispatcher"),
    "billing_clerk_headers": build_user_headers("test-billing-1", "BillingClerk"),
    "technician_headers": build_user_headers("test-technician-1", "Technician"),
}


def make_technician_headers(user_id: str) -> dict:
    """For the Technician role (entity-backed). Pass the acting Technician.id as
    user_id. Mandatory whenever the call is an ownership-gated appointment
    transition (X-User-ID must equal the appointment's technician_id, §2.1)."""
    return build_user_headers(user_id, "Technician")


def make_dispatcher_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "Dispatcher")


def make_billing_clerk_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "BillingClerk")
