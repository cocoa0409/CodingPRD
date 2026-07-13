"""Pre-built role headers for every role in the PRD (§2.1).

Four roles carry an opaque identity (PlatformAdmin, FacilityManager,
FinanceController, SustainabilityAnalyst) — their X-User-ID is an operator
identifier that is never compared to any entity id, so a shared constant is
the canonical form.

Two roles are entity-backed: a VendorTech's X-User-ID is the id of the acting
Vendor, and a TenantRep's X-User-ID is the id of the acting Lease. Any
ownership-gated call for those roles MUST use the per-instance builder below
with the real entity id.
"""

from prd_bench_local_runner.testing import build_user_headers

# Distinct FinanceController identities, needed by the segregation-of-duties rule:
# the controller deciding a capital project must not be the one who proposed it.
FC_PROPOSER_ID = "fc-1"
FC_APPROVER_ID = "fc-2"
FC_THIRD_ID = "fc-3"

TEST_USERS = {
    # Opaque roles — the shared constant is canonical.
    "platform_admin_headers": build_user_headers("admin-1", "PlatformAdmin"),
    "facility_manager_headers": build_user_headers("fm-1", "FacilityManager"),
    "finance_controller_headers": build_user_headers(FC_PROPOSER_ID, "FinanceController"),
    "finance_approver_headers": build_user_headers(FC_APPROVER_ID, "FinanceController"),
    "sustainability_analyst_headers": build_user_headers("sa-1", "SustainabilityAnalyst"),
    # Entity-backed roles — these constants are a fallback for calls that do NOT
    # exercise ownership (e.g. plain 403-on-wrong-role or 404-on-missing-resource).
    # Ownership-gated calls must use make_vendor_tech_headers / make_tenant_rep_headers.
    "vendor_tech_headers": build_user_headers("vendor-unowned", "VendorTech"),
    "tenant_rep_headers": build_user_headers("lease-unowned", "TenantRep"),
}


def make_vendor_tech_headers(vendor_id: str) -> dict:
    """For VendorTech. X-User-ID must be the acting Vendor's id."""
    return build_user_headers(vendor_id, "VendorTech")


def make_tenant_rep_headers(lease_id: str) -> dict:
    """For TenantRep. X-User-ID must be the acting Lease's id."""
    return build_user_headers(lease_id, "TenantRep")


def make_finance_controller_headers(user_id: str) -> dict:
    """For FinanceController. The opaque X-User-ID is recorded on capital projects
    as proposed_by_user_id / approved_by_user_id, so distinct identities matter."""
    return build_user_headers(user_id, "FinanceController")


def make_facility_manager_headers(user_id: str) -> dict:
    """For FacilityManager (opaque identity)."""
    return build_user_headers(user_id, "FacilityManager")


NO_AUTH_HEADERS = {"Content-Type": "application/json"}
