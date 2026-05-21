"""Pre-built role headers for every role in the food delivery platform.

Two forms are provided for each role:

- **Shared-constant entries in TEST_USERS** — safe for tests whose success does NOT depend
  on the caller owning the subject resource. Opaque roles (PlatformAdmin, CustomerService)
  use the shared constant as their canonical form.

- **Per-instance builders make_<role>_headers(user_id)** — mandatory for every role whose
  identity is entity-backed (Customer, Restaurant, Rider). Ownership checks compare
  X-User-ID to the resource's owner id, so the fixture must mint an X-User-ID that equals
  the actual entity's id.
"""

from typing import Dict

from prd_bench_local_runner.testing import build_user_headers


# ──────────────────────────────────────────────────────────
# Shared constants — safe for opaque roles, and for tests that don't exercise ownership
# (for example, auth-failure tests, plain 404 probes, forbidden-role probes).
# ──────────────────────────────────────────────────────────

TEST_USERS: Dict[str, Dict[str, str]] = {
    # Opaque roles — X-User-ID is never compared to any entity id per PRD §2.1.
    "admin_headers": build_user_headers("test-admin-1", "PlatformAdmin"),
    "cs_headers": build_user_headers("test-cs-1", "CustomerService"),
    # Entity-backed role fallbacks — only for tests that do NOT exercise ownership.
    "customer_headers": build_user_headers("test-customer-fallback", "Customer"),
    "restaurant_headers": build_user_headers("test-restaurant-fallback", "Restaurant"),
    "rider_headers": build_user_headers("test-rider-fallback", "Rider"),
}


# ──────────────────────────────────────────────────────────
# Per-instance builders — REQUIRED for every entity-backed role whenever the call is
# ownership-gated. Pass the actual entity id as user_id so the ownership check on the
# server can resolve X-User-ID to the owning row.
# ──────────────────────────────────────────────────────────

def make_customer_headers(customer_id: str) -> Dict[str, str]:
    """Build Customer headers where X-User-ID == Customer.id. PRD §2.1: when X-User-Role
    is Customer, X-User-ID is the id of the acting Customer."""
    return build_user_headers(customer_id, "Customer")


def make_restaurant_headers(restaurant_id: str) -> Dict[str, str]:
    """Build Restaurant headers where X-User-ID == Restaurant.id. PRD §2.1: ownership
    checks compare the resource's restaurant_id to X-User-ID."""
    return build_user_headers(restaurant_id, "Restaurant")


def make_rider_headers(rider_id: str) -> Dict[str, str]:
    """Build Rider headers where X-User-ID == Rider.id. PRD §2.1: ownership checks
    compare the resource's rider_id to X-User-ID."""
    return build_user_headers(rider_id, "Rider")


def make_admin_headers(admin_id: str = "test-admin-1") -> Dict[str, str]:
    """Build PlatformAdmin headers. X-User-ID is opaque for admins per PRD §2.1."""
    return build_user_headers(admin_id, "PlatformAdmin")


def make_cs_headers(cs_id: str = "test-cs-1") -> Dict[str, str]:
    """Build CustomerService headers. X-User-ID is opaque for CS operators per PRD §2.1."""
    return build_user_headers(cs_id, "CustomerService")
