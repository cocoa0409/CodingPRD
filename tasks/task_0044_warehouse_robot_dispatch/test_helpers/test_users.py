"""Pre-built role headers.

PRD section 2.1: "All three roles use X-User-ID as an opaque operator
identifier - none of them is backed by a persisted entity, and the
server does not compare X-User-ID to the id of any Fleet, Robot, Task,
ChargingStation, or FaultIncident." Shared constants are therefore
canonical for every role; no per-instance builder is required for any
ownership comparison (none exist on this API).

Builder helpers are still provided so tests can mint alternate ids for
race/concurrency scenarios that want two distinct opaque callers.
"""
from __future__ import annotations

from typing import Dict

from prd_bench_local_runner.testing import build_user_headers


# Canonical shared header constants. The server treats X-User-ID as an
# opaque string with audit-only purpose for all three roles, so a fixed
# id is always correct.
TEST_USERS: Dict[str, Dict[str, str]] = {
    "operator_headers": build_user_headers("operator-001", "Operator"),
    "operator_headers_alt": build_user_headers(
        "operator-002", "Operator"
    ),
    "fleet_admin_headers": build_user_headers(
        "fleet-admin-001", "FleetAdmin"
    ),
    "fleet_admin_headers_alt": build_user_headers(
        "fleet-admin-002", "FleetAdmin"
    ),
    "wms_headers": build_user_headers("wms-001", "WMS"),
    "wms_headers_alt": build_user_headers("wms-002", "WMS"),
}


def make_operator_headers(operator_id: str = "operator-001") -> Dict[str, str]:
    """PRD section 2.1: 'X-User-ID is an opaque floor-operator identifier
    used only for audit attribution.'"""
    return build_user_headers(operator_id, "Operator")


def make_fleet_admin_headers(
    admin_id: str = "fleet-admin-001",
) -> Dict[str, str]:
    """PRD section 2.1: 'X-User-ID is an opaque administrator identifier
    with the same audit-only role.'"""
    return build_user_headers(admin_id, "FleetAdmin")


def make_wms_headers(wms_id: str = "wms-001") -> Dict[str, str]:
    """PRD section 2.1: 'X-User-ID is an opaque WMS-integrator
    identifier.'"""
    return build_user_headers(wms_id, "WMS")


__all__ = [
    "TEST_USERS",
    "make_operator_headers",
    "make_fleet_admin_headers",
    "make_wms_headers",
]
