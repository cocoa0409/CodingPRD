"""Pre-built role headers for every role in the PRD.

OpsAdmin, Dispatcher, BillingClerk, WarrantyAdministrator, and SafetyOfficer
are opaque identities: X-User-ID is not tied to any persisted entity.
Technician is entity-backed by Technician and FleetManager is entity-backed
by FleetAccount — ownership-gated calls MUST use the per-instance builders
with the real entity id, never the shared constant.
"""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe for opaque roles, and for tests that do not exercise
# ownership (400-on-bad-payload, 404-on-missing-resource, wrong-role checks).
TEST_USERS = {
    "ops_admin_headers": build_user_headers("ops-admin-1", "OpsAdmin"),
    "dispatcher_headers": build_user_headers("dispatcher-1", "Dispatcher"),
    "billing_clerk_headers": build_user_headers("billing-clerk-1", "BillingClerk"),
    "warranty_admin_headers": build_user_headers(
        "warranty-admin-1", "WarrantyAdministrator"),
    "safety_officer_headers": build_user_headers(
        "safety-officer-1", "SafetyOfficer"),
    # entity_backed roles: shared constants are fallbacks for non-ownership
    # tests only (the X-User-ID below matches no persisted entity).
    "technician_headers": build_user_headers("test-technician-1", "Technician"),
    "fleet_manager_headers": build_user_headers("test-fleet-1", "FleetManager"),
}


def make_ops_admin_headers(user_id: str = "ops-admin-1") -> dict:
    """Opaque role; distinct user ids matter for invoice issue/void
    segregation-of-duties scenarios."""
    return build_user_headers(user_id, "OpsAdmin")


def make_dispatcher_headers(user_id: str = "dispatcher-1") -> dict:
    return build_user_headers(user_id, "Dispatcher")


def make_billing_clerk_headers(user_id: str = "billing-clerk-1") -> dict:
    """Opaque role; distinct user ids matter for issue/void segregation."""
    return build_user_headers(user_id, "BillingClerk")


def make_warranty_admin_headers(user_id: str = "warranty-admin-1") -> dict:
    return build_user_headers(user_id, "WarrantyAdministrator")


def make_safety_officer_headers(user_id: str = "safety-officer-1") -> dict:
    return build_user_headers(user_id, "SafetyOfficer")


def make_technician_headers(technician_id: str) -> dict:
    """For Technician (entity_backed:Technician). Pass the acting
    Technician.id whenever the call is ownership-gated."""
    return build_user_headers(technician_id, "Technician")


def make_fleet_manager_headers(fleet_account_id: str) -> dict:
    """For FleetManager (entity_backed:FleetAccount). Pass the acting
    FleetAccount.id whenever the call is ownership-gated."""
    return build_user_headers(fleet_account_id, "FleetManager")
