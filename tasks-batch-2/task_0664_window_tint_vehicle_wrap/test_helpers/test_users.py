"""Pre-built role headers for every role in the PRD (§2.1).

Two roles are opaque (ShopManager, ComplianceOfficer): their X-User-ID is not
compared to any persisted entity, so a shared constant is the canonical form.
Three roles are entity-backed (Customer -> VehicleProfile.customer_user_id,
Installer -> Installer.installer_user_id, FleetManager ->
FleetAccount.fleet_manager_user_id): for ownership-gated calls a per-instance
builder MUST be used so X-User-ID equals the owning principal recorded on the
entity.
"""
from prd_bench_local_runner.testing import build_user_headers


# Shared constants — safe for opaque roles, and for tests that don't exercise
# ownership (e.g. 400-on-bad-payload, 404-on-missing-resource, RBAC denials).
TEST_USERS = {
    "shop_manager_headers": build_user_headers("test-shop-manager-1", "ShopManager"),
    "compliance_officer_headers": build_user_headers("test-compliance-1", "ComplianceOfficer"),
    # Entity-backed fallbacks: only valid where the call is NOT ownership-gated.
    "customer_headers": build_user_headers("test-customer-1", "Customer"),
    "installer_headers": build_user_headers("test-installer-1", "Installer"),
    "fleet_manager_headers": build_user_headers("test-fleet-manager-1", "FleetManager"),
}


# Per-instance builders — required for every entity-backed role.
def make_shop_manager_headers(user_id: str = "test-shop-manager-1") -> dict:
    """For ShopManager (opaque). Any operator id is accepted."""
    return build_user_headers(user_id, "ShopManager")


def make_compliance_officer_headers(user_id: str = "test-compliance-1") -> dict:
    """For ComplianceOfficer (opaque). Any operator id is accepted."""
    return build_user_headers(user_id, "ComplianceOfficer")


def make_customer_headers(user_id: str) -> dict:
    """For Customer (entity-backed via VehicleProfile.customer_user_id). Pass the
    VehicleProfile's customer_user_id when the call is ownership-gated."""
    return build_user_headers(user_id, "Customer")


def make_installer_headers(user_id: str) -> dict:
    """For Installer (entity-backed via Installer.installer_user_id). Pass the
    Installer's installer_user_id when the call is ownership-gated."""
    return build_user_headers(user_id, "Installer")


def make_fleet_manager_headers(user_id: str) -> dict:
    """For FleetManager (entity-backed via FleetAccount.fleet_manager_user_id).
    Pass the FleetAccount's fleet_manager_user_id when ownership-gated."""
    return build_user_headers(user_id, "FleetManager")
