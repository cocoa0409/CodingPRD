"""Pre-built role headers for every role in the PRD (§2.1)."""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe for opaque roles (PlatformAdmin, Dispatcher, Estimator,
# Adjuster), and for tests that do not exercise Technician entity ownership.
TEST_USERS = {
    # Opaque roles: shared constant is the canonical form — X-User-ID is never
    # compared to any persisted entity's id.
    "platform_admin_headers": build_user_headers("test-admin-1", "PlatformAdmin"),
    "dispatcher_headers": build_user_headers("test-dispatcher-1", "Dispatcher"),
    "estimator_headers": build_user_headers("test-estimator-1", "Estimator"),
    "adjuster_headers": build_user_headers("test-adjuster-1", "Adjuster"),
    # Technician is entity_backed:Technician — shared constant is a fallback for
    # non-ownership tests only (role-denial / not-found checks). Ownership-gated
    # calls MUST use make_technician_headers() with the actual Technician.id.
    "technician_headers": build_user_headers("test-technician-1", "Technician"),
}


def make_technician_headers(user_id: str) -> dict:
    """For Technician (entity_backed:Technician). Pass the actual dispatched
    Technician.id as user_id whenever a call is ownership-gated against a
    resource that references a Technician (PRD §2.1)."""
    return build_user_headers(user_id, "Technician")


def make_admin_headers(user_id: str = "test-admin-1") -> dict:
    """PlatformAdmin is opaque; X-User-ID is not compared to any entity."""
    return build_user_headers(user_id, "PlatformAdmin")


def make_dispatcher_headers(user_id: str = "test-dispatcher-1") -> dict:
    """Dispatcher is opaque; X-User-ID is not compared to any entity."""
    return build_user_headers(user_id, "Dispatcher")


def make_estimator_headers(user_id: str = "test-estimator-1") -> dict:
    """Estimator is opaque; X-User-ID is not compared to any entity."""
    return build_user_headers(user_id, "Estimator")


def make_adjuster_headers(user_id: str = "test-adjuster-1") -> dict:
    """Adjuster is opaque; X-User-ID is recorded as adjuster_user_id on claims
    it opens but is never compared to any entity id (PRD §2.1)."""
    return build_user_headers(user_id, "Adjuster")
