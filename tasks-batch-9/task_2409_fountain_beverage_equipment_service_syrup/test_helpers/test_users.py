"""Pre-built role headers.

Every request carries both ``X-User-ID`` and ``X-User-Role``. For an
``OutletManager`` the ``X-User-ID`` value must be the id of the Outlet the
manager speaks for, so that role gets a per-instance builder rather than a
fixed shared constant.
"""

from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    "admin_headers": build_user_headers("admin-001", "NetworkAdmin"),
    "admin_alt_headers": build_user_headers("admin-002", "NetworkAdmin"),
    "planner_headers": build_user_headers("planner-001", "SupplyPlanner"),
    "planner_alt_headers": build_user_headers("planner-002", "SupplyPlanner"),
    "driver_headers": build_user_headers("driver-001", "RouteDriver"),
    "driver_alt_headers": build_user_headers("driver-002", "RouteDriver"),
    "technician_headers": build_user_headers("tech-001", "ServiceTechnician"),
    "technician_alt_headers": build_user_headers("tech-002", "ServiceTechnician"),
    "officer_headers": build_user_headers("officer-001", "ComplianceOfficer"),
    "officer_alt_headers": build_user_headers("officer-002", "ComplianceOfficer"),
    # OutletManager identity is the Outlet id; this placeholder exists only for
    # tests that deliberately supply a user id which is not an outlet.
    "outlet_manager_headers": build_user_headers(
        "00000000-0000-0000-0000-000000000000", "OutletManager"
    ),
}


def make_admin_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "NetworkAdmin")


def make_supply_planner_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "SupplyPlanner")


def make_route_driver_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "RouteDriver")


def make_service_technician_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "ServiceTechnician")


def make_compliance_officer_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "ComplianceOfficer")


def make_outlet_manager_headers(outlet_id: str) -> dict:
    """Headers for the manager of ``outlet_id`` — X-User-ID *is* the Outlet id."""
    return build_user_headers(outlet_id, "OutletManager")
