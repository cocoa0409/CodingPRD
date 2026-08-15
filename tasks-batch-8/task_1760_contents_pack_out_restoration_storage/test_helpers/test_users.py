"""Pre-built role headers for every role in the PRD (§2.1).

For five roles the X-User-ID is an opaque operator identifier. For
SubcontractorContact the X-User-ID IS the acting Subcontractor's id, so
ownership-gated calls must use make_subcontractor_contact_headers(sub["id"]).
"""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe for opaque roles and for tests that do not exercise
# referral ownership.
TEST_USERS = {
    "project_manager_headers": build_user_headers("test-pm-0", "ProjectManager"),
    "inventory_technician_headers": build_user_headers("test-tech-0", "InventoryTechnician"),
    "billing_clerk_headers": build_user_headers("test-clerk-0", "BillingClerk"),
    "claims_adjuster_headers": build_user_headers("test-adj-0", "ClaimsAdjuster"),
    "carrier_representative_headers": build_user_headers("test-carrier-0", "CarrierRepresentative"),
    # Fallback for non-ownership calls only; NEVER pass this to RECEIVE/RETURN.
    "subcontractor_contact_headers": build_user_headers("test-sub-0", "SubcontractorContact"),
    # Named identities used by segregation-of-duties scenarios.
    "pm1_headers": build_user_headers("pm-1", "ProjectManager"),
    "pm9_headers": build_user_headers("pm-9", "ProjectManager"),
    "tech1_headers": build_user_headers("tech-1", "InventoryTechnician"),
    "adj1_headers": build_user_headers("adj-1", "ClaimsAdjuster"),
    "adj2_headers": build_user_headers("adj-2", "ClaimsAdjuster"),
}

# Anonymous: no auth headers at all (only content type).
ANONYMOUS_HEADERS = {"Content-Type": "application/json"}


def make_project_manager_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "ProjectManager")


def make_inventory_technician_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "InventoryTechnician")


def make_billing_clerk_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "BillingClerk")


def make_claims_adjuster_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "ClaimsAdjuster")


def make_carrier_representative_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "CarrierRepresentative")


def make_subcontractor_contact_headers(subcontractor_id: str) -> dict:
    """For SubcontractorContact (identity is the Subcontractor's id). Pass the
    actual subcontractor id whenever the call is referral-ownership-gated."""
    return build_user_headers(subcontractor_id, "SubcontractorContact")
