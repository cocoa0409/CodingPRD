"""Pre-built role headers for every role in the PRD.

PRD §2.1 distinguishes roles by identity binding:

- PlatformAdmin, CentralKitchenPlanner, FinanceController, Driver:
  X-User-ID is an opaque operator identifier not tied to a persisted
  entity row. The shared TEST_USERS constant is canonical for these
  except Driver (see below).

- StoreManager: entity-backed on Store. PRD §2.1: 'When X-User-Role is
  StoreManager, X-User-ID is the id of the acting Store. Every store-
  scoped resource the manager touches ... carries a store_id field, and
  the server compares that field to X-User-ID; on mismatch the request
  is rejected with ERR_FORBIDDEN.' Ownership-gated calls MUST use
  make_storemanager_headers(store_id) with the actual Store.id.

- Driver identity: opaque, but ownership-gated against
  DeliveryRoute.driver_user_id for depart/complete/raise-exception.
  Use make_driver_headers(driver_user_id) where driver_user_id matches
  the DeliveryRoute.driver_user_id stored at planning time.
"""
from __future__ import annotations
from typing import Dict

from prd_bench_local_runner.testing import build_user_headers


# Shared constants. For opaque roles these are canonical. For StoreManager
# (entity-backed on Store) the constant is a fallback for non-ownership
# tests; ownership-gated tests must call make_storemanager_headers(store_id).
TEST_USERS: Dict[str, Dict[str, str]] = {
    # Opaque roles — shared constants are canonical.
    "platform_admin_headers": build_user_headers(
        "admin-001", "PlatformAdmin"
    ),
    "platform_admin_headers_alt": build_user_headers(
        "admin-002", "PlatformAdmin"
    ),
    "planner_headers": build_user_headers(
        "planner-001", "CentralKitchenPlanner"
    ),
    "planner_headers_alt": build_user_headers(
        "planner-002", "CentralKitchenPlanner"
    ),
    "finance_headers": build_user_headers(
        "finance-001", "FinanceController"
    ),
    "finance_headers_alt": build_user_headers(
        "finance-002", "FinanceController"
    ),
    # Driver fallback — used only for tests that don't exercise the
    # driver_user_id ownership comparison (e.g., RBAC ERR_FORBIDDEN).
    "driver_headers": build_user_headers("driver-fallback-001", "Driver"),
    # StoreManager fallback — used only for tests that don't depend on
    # ownership comparison (e.g., RBAC tests where role itself is rejected).
    "store_manager_headers": build_user_headers(
        "store-fallback-001", "StoreManager"
    ),
}


# ---------------------------------------------------------------------------
# Per-instance builders
# ---------------------------------------------------------------------------
def make_platform_admin_headers(
    admin_id: str = "admin-001",
) -> Dict[str, str]:
    """PlatformAdmin headers; identity is opaque per PRD §2.1."""
    return build_user_headers(admin_id, "PlatformAdmin")


def make_planner_headers(
    planner_id: str = "planner-001",
) -> Dict[str, str]:
    """CentralKitchenPlanner headers; identity is opaque per PRD §2.1."""
    return build_user_headers(planner_id, "CentralKitchenPlanner")


def make_finance_headers(
    finance_id: str = "finance-001",
) -> Dict[str, str]:
    """FinanceController headers; identity is opaque per PRD §2.1."""
    return build_user_headers(finance_id, "FinanceController")


def make_driver_headers(driver_user_id: str) -> Dict[str, str]:
    """Driver headers. PRD §2.1: 'When X-User-Role is Driver, X-User-ID
    is an opaque operator identifier not tied to a persisted entity. The
    server compares it to DeliveryRoute.driver_user_id for the depart,
    complete, and raise-exception actions; on mismatch the request is
    rejected with ERR_DRIVER_MISMATCH.'

    Pass the same string used as driver_user_id when planning the route.
    """
    return build_user_headers(driver_user_id, "Driver")


def make_storemanager_headers(store_id: str) -> Dict[str, str]:
    """StoreManager headers. PRD §2.1: 'When X-User-Role is StoreManager,
    X-User-ID is the id of the acting Store. Every store-scoped resource
    the manager touches ... carries a store_id field, and the server
    compares that field to X-User-ID; on mismatch the request is rejected
    with ERR_FORBIDDEN.'

    Pass the actual Store.id whenever the call is ownership-gated (which
    is every StoreManager-exclusive endpoint except RBAC negative tests).
    """
    return build_user_headers(store_id, "StoreManager")


__all__ = [
    "TEST_USERS",
    "make_platform_admin_headers",
    "make_planner_headers",
    "make_finance_headers",
    "make_driver_headers",
    "make_storemanager_headers",
]
