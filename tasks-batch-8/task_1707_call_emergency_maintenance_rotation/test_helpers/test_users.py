"""Pre-built role headers for every role in the PRD (§2.1).

Opaque roles (PropertyAdmin, Dispatcher) use the shared constants directly.
Entity-backed roles (OnCallTechnician -> Technician, MaintenanceSupervisor ->
Technician, Vendor -> Vendor) MUST use the per-instance builders with the real
entity id whenever the call is ownership/capability-gated (arrive, mitigate,
submit, assign, invoice, ...); the shared constants exist only for tests that
never exercise ownership (400-on-bad-payload, 404-on-missing-resource).
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    # Opaque roles — canonical form.
    "property_admin_headers": build_user_headers("test-admin-1", "PropertyAdmin"),
    "dispatcher_headers": build_user_headers("test-dispatcher-1", "Dispatcher"),
    # Entity-backed roles — fallback for non-ownership tests ONLY.
    "technician_headers": build_user_headers("test-tech-1", "OnCallTechnician"),
    "supervisor_headers": build_user_headers("test-sup-1", "MaintenanceSupervisor"),
    "vendor_headers": build_user_headers("test-vendor-1", "Vendor"),
}


def make_property_admin_headers(user_id: str = "test-admin-1") -> dict:
    """PropertyAdmin (opaque identity)."""
    return build_user_headers(user_id, "PropertyAdmin")


def make_dispatcher_headers(user_id: str = "test-dispatcher-1") -> dict:
    """Dispatcher (opaque identity)."""
    return build_user_headers(user_id, "Dispatcher")


def make_technician_headers(user_id: str) -> dict:
    """OnCallTechnician (entity-backed: Technician). Pass the real
    Technician.id for any ownership-gated call (arrive, mitigate, begin,
    shift start/complete, incident submit/revise, self-authorization)."""
    return build_user_headers(user_id, "OnCallTechnician")


def make_supervisor_headers(user_id: str) -> dict:
    """MaintenanceSupervisor (entity-backed: Technician). Pass the real id of
    a Technician whose capability is SUPERVISOR for any capability-gated call
    (assign, verify, reopen, begin-review, return, finalize, relocation
    activate/end, ...)."""
    return build_user_headers(user_id, "MaintenanceSupervisor")


def make_vendor_headers(user_id: str) -> dict:
    """Vendor (entity-backed: Vendor). Pass the real Vendor.id for invoice and
    vendor-engaged work-order completion."""
    return build_user_headers(user_id, "Vendor")
