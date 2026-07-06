"""Pre-built role headers for every role in the PRD (§2.1).

All five roles carry an opaque X-User-ID. For ProgramManager, ClinicalStaff,
BillingClerk, and PatientNavigator the id is never compared to any entity.
SponsorViewer's id carries ownership meaning: it must equal the target
sponsor's viewer_user_id, so a per-instance builder is provided for it.
"""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — opaque roles use these directly.
TEST_USERS = {
    "program_manager_headers": build_user_headers("pm-1", "ProgramManager"),
    "clinical_staff_headers": build_user_headers("cs-1", "ClinicalStaff"),
    "billing_clerk_headers": build_user_headers("bc-1", "BillingClerk"),
    "patient_navigator_headers": build_user_headers("nav-1", "PatientNavigator"),
    "sponsor_viewer_headers": build_user_headers("sv-generic", "SponsorViewer"),
}


def make_sponsor_viewer_headers(viewer_user_id: str) -> dict:
    """For SponsorViewer reads: pass the target sponsor's viewer_user_id as the
    X-User-ID so the ownership check (X-User-ID == Sponsor.viewer_user_id) passes."""
    return build_user_headers(viewer_user_id, "SponsorViewer")


def make_headers(role: str, user_id: str = None) -> dict:
    """Build headers for an arbitrary role/user_id (used for unknown-role tests)."""
    return build_user_headers(user_id if user_id is not None else "u-1", role)
