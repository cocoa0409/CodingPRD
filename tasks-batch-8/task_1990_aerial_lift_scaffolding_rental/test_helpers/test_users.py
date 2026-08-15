"""Pre-built role headers for every role in the PRD (§2.1).

Four roles are opaque operators: the server never compares their X-User-ID
to an entity id, though a Driver's identifier must equal the trip's assigned
driver_id, and inspector/certifier identities are compared by the
segregation-of-duties rule — those tests use the per-instance builders.

The Customer role is entity-backed: X-User-ID is the acting customer account's
id. Any ownership-gated call (off-rent, re-rent, claim create/dispute, self
reads) MUST use make_customer_headers(customer["id"]) — the shared constant's
X-User-ID never equals any real account id.
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    # Opaque roles — canonical shared constants.
    "branch_manager_headers": build_user_headers("test-bm-1", "BranchManager"),
    "rental_coordinator_headers": build_user_headers("test-rc-1", "RentalCoordinator"),
    "driver_headers": build_user_headers("drv-1", "Driver"),
    "yard_technician_headers": build_user_headers("yt-1", "YardTechnician"),
    # Entity-backed role — fallback for tests that do not exercise ownership.
    "customer_headers": build_user_headers("test-customer-1", "Customer"),
}


def make_branch_manager_headers(user_id: str) -> dict:
    """BranchManager headers with a specific X-User-ID (e.g. a certifier id
    distinct from the inspector for the segregation-of-duties rule)."""
    return build_user_headers(user_id, "BranchManager")


def make_rental_coordinator_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "RentalCoordinator")


def make_driver_headers(user_id: str) -> dict:
    """Driver headers with a specific X-User-ID. For start/complete/fail the
    id MUST equal the trip's assigned driver_id."""
    return build_user_headers(user_id, "Driver")


def make_yard_technician_headers(user_id: str) -> dict:
    """YardTechnician headers with a specific X-User-ID (the id is stamped
    into inspector_id / trainer_id)."""
    return build_user_headers(user_id, "YardTechnician")


def make_customer_headers(user_id: str) -> dict:
    """Customer headers for the entity-backed role. Pass the actual
    CustomerAccount.id whenever the call is ownership-gated."""
    return build_user_headers(user_id, "Customer")
