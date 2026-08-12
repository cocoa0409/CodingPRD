"""Pre-built role headers for every role in the PRD."""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe for the opaque roles, and for Vendor-role tests whose
# success does not depend on owning the subject resource (e.g., role denials).
TEST_USERS = {
    "director_headers": build_user_headers("dir-1", "FestivalDirector"),
    # A second director: segregation-of-duties waiver scenarios.
    "director2_headers": build_user_headers("dir-2", "FestivalDirector"),
    "vendor_manager_headers": build_user_headers("vm-1", "VendorManager"),
    "ops_headers": build_user_headers("ops-1", "OperationsLead"),
    "health_inspector_headers": build_user_headers("hi-1", "HealthInspector"),
    "sustainability_headers": build_user_headers("sus-1", "SustainabilityOfficer"),
    # Two finance leads: reconciler != finalizer (segregation of duties).
    "finance_headers": build_user_headers("fin-1", "FinanceLead"),
    "finance2_headers": build_user_headers("fin-2", "FinanceLead"),
    # Fallback for non-ownership Vendor contexts; prefer make_vendor_headers.
    "vendor_headers": build_user_headers("test-vendor-1", "Vendor"),
}


def make_vendor_headers(vendor_id: str) -> dict:
    """For Vendor (entity_backed:Vendor). Pass the actual Vendor.id as user_id
    whenever the call is ownership-gated (application submit/withdraw, POS report,
    reservation book/cancel, settlement dispute, fine respond, review respond)."""
    return build_user_headers(vendor_id, "Vendor")


def make_finance_headers(user_id: str) -> dict:
    """FinanceLead with an explicit operator id (SoD reconciler/finalizer split)."""
    return build_user_headers(user_id, "FinanceLead")


def make_director_headers(user_id: str) -> dict:
    """FestivalDirector with an explicit operator id (SoD fine-waiver split)."""
    return build_user_headers(user_id, "FestivalDirector")
