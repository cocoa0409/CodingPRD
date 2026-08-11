"""Pre-built role headers for every role in the PRD (§2.1).

Entity-backed roles (Physician, MonitoringTechnician) MUST be built per-instance
with the real entity id via the make_*_headers builders whenever the call is
ownership/assignment-gated; the shared constants are safe only for calls whose
success does not depend on the caller owning the subject resource.
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    # Opaque roles — shared constant is the canonical form.
    "platform_admin_headers": build_user_headers("test-admin-1", "PlatformAdmin"),
    "enrollment_coordinator_headers": build_user_headers("test-coordinator-1", "EnrollmentCoordinator"),
    "billing_specialist_headers": build_user_headers("billing-1", "BillingSpecialist"),
    "inventory_manager_headers": build_user_headers("test-inventory-1", "InventoryManager"),
    "device_gateway_headers": build_user_headers("test-gateway-1", "DeviceGateway"),
    # Entity-backed roles — fallback constants for non-ownership tests only.
    "physician_headers": build_user_headers("test-physician-1", "Physician"),
    "monitoring_technician_headers": build_user_headers("test-technician-1", "MonitoringTechnician"),
}


def make_physician_headers(physician_id: str) -> dict:
    """Physician is entity-backed: X-User-ID must equal the acting Physician.id
    for ownership-gated calls (order cancel, report finalize/amend,
    notification-attempt acknowledge)."""
    return build_user_headers(physician_id, "Physician")


def make_technician_headers(technician_id: str) -> dict:
    """MonitoringTechnician is entity-backed: X-User-ID must equal the acting
    Technician.id for assignment-gated calls (acknowledge/release/triage/close)."""
    return build_user_headers(technician_id, "MonitoringTechnician")


def make_billing_specialist_headers(user_id: str) -> dict:
    """BillingSpecialist is opaque, but propose/approve segregation compares
    X-User-ID values; use distinct user ids for distinct billing actors."""
    return build_user_headers(user_id, "BillingSpecialist")


def make_platform_admin_headers(user_id: str = "test-admin-1") -> dict:
    return build_user_headers(user_id, "PlatformAdmin")


def make_enrollment_coordinator_headers(user_id: str = "test-coordinator-1") -> dict:
    return build_user_headers(user_id, "EnrollmentCoordinator")


def make_inventory_manager_headers(user_id: str = "test-inventory-1") -> dict:
    return build_user_headers(user_id, "InventoryManager")


def make_device_gateway_headers(user_id: str = "test-gateway-1") -> dict:
    return build_user_headers(user_id, "DeviceGateway")
