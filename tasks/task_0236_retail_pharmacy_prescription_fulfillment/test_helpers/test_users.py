"""Pre-built role headers for every role in the PRD (§2.1).

All four roles (PharmacyAdmin, Pharmacist, Technician, Cashier) have OPAQUE
identity: the server never compares X-User-ID to any resource id. Shared
constants are therefore the canonical form. The per-id builders below exist for
the separation-of-duties workflow, where the same X-User-ID must be reused
across a technician's create and a pharmacist's dispense to trip the check.
"""
from prd_bench_local_runner.testing import build_user_headers


TEST_USERS = {
    "admin_headers": build_user_headers("admin-1", "PharmacyAdmin"),
    "pharmacist_headers": build_user_headers("pharmacist-1", "Pharmacist"),
    "technician_headers": build_user_headers("technician-1", "Technician"),
    "cashier_headers": build_user_headers("cashier-1", "Cashier"),
}


def make_admin_headers(user_id: str = "admin-1") -> dict:
    """PharmacyAdmin (opaque)."""
    return build_user_headers(user_id, "PharmacyAdmin")


def make_pharmacist_headers(user_id: str = "pharmacist-1") -> dict:
    """Pharmacist (opaque). Pass a specific user_id for separation-of-duties tests."""
    return build_user_headers(user_id, "Pharmacist")


def make_technician_headers(user_id: str = "technician-1") -> dict:
    """Technician (opaque). Pass a specific user_id for separation-of-duties tests."""
    return build_user_headers(user_id, "Technician")


def make_cashier_headers(user_id: str = "cashier-1") -> dict:
    """Cashier (opaque)."""
    return build_user_headers(user_id, "Cashier")


def make_anonymous_headers() -> dict:
    """No auth headers — triggers ERR_MISSING_USER_CONTEXT."""
    return {}
