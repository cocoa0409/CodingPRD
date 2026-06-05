"""Pre-built role headers for every role in the PRD (§2.1).

Two entity_backed roles exist: Rider (X-User-ID == Rider.id) and Technician
(X-User-ID == Technician.id). For ownership-gated calls, build per-instance
headers with the real entity id via make_rider_headers / make_technician_headers.
The shared TEST_USERS constants are safe only for opaque roles and for tests
that do not exercise ownership (e.g. 400/403/404 paths, admin/regulator calls).
"""
from prd_bench_local_runner.testing import build_user_headers


TEST_USERS = {
    # Opaque operator/consumer roles — shared constants are the canonical form.
    "admin_headers": build_user_headers("admin-1", "PlatformAdmin"),
    "regulator_headers": build_user_headers("regulator-1", "CityRegulator"),
    "anonymous_headers": build_user_headers("anon-1", "Anonymous"),
    # entity_backed roles — shared constant is a NON-ownership fallback only.
    "rider_headers": build_user_headers("rider-shared-1", "Rider"),
    "technician_headers": build_user_headers("tech-shared-1", "Technician"),
}


def make_rider_headers(user_id: str) -> dict:
    """For the Rider role (entity_backed:Rider). Pass the actual Rider.id as
    user_id whenever the call is ownership-gated (own trip/fine/application/wallet)."""
    return build_user_headers(user_id, "Rider")


def make_technician_headers(user_id: str) -> dict:
    """For the Technician role (entity_backed:Technician). Pass the actual
    Technician.id as user_id whenever the call is ownership-gated (own task complete)."""
    return build_user_headers(user_id, "Technician")


def make_admin_headers(user_id: str = "admin-1") -> dict:
    """For PlatformAdmin (opaque). X-User-ID is not compared to any entity."""
    return build_user_headers(user_id, "PlatformAdmin")


def make_regulator_headers(user_id: str = "regulator-1") -> dict:
    """For CityRegulator (opaque). X-User-ID is not compared to any entity."""
    return build_user_headers(user_id, "CityRegulator")


def make_anonymous_headers(user_id: str = "anon-1") -> dict:
    """For Anonymous (opaque). Only capability is self-registering a Rider."""
    return build_user_headers(user_id, "Anonymous")
