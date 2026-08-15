"""Pre-built role headers for every role in the PRD (§2.1).

Four roles are entity-backed by Employee: ownership-gated calls (SoD compare,
retract-permission compare) MUST use the per-instance builders with the actual
Employee id. The shared constants are safe for VendorAdmin (opaque) and for
tests whose outcome does not depend on the caller owning a subject resource.
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    # Fallbacks for non-ownership tests only (entity-backed roles).
    "analyst_headers": build_user_headers("test-analyst-1", "CompAnalyst"),
    "manager_headers": build_user_headers("test-manager-1", "CompManager"),
    "hr_director_headers": build_user_headers("test-hrdirector-1", "HRDirector"),
    "reviewer_headers": build_user_headers("test-reviewer-1", "CompCommitteeReviewer"),
    # VendorAdmin is opaque: not tied to any persisted Employee (PRD §2.1).
    "vendor_admin_headers": build_user_headers("test-vendor-admin-1", "VendorAdmin"),
}


def make_analyst_headers(user_id: str) -> dict:
    """CompAnalyst headers bound to a real Employee.id (entity-backed)."""
    return build_user_headers(user_id, "CompAnalyst")


def make_manager_headers(user_id: str) -> dict:
    """CompManager headers bound to a real Employee.id (entity-backed)."""
    return build_user_headers(user_id, "CompManager")


def make_hr_director_headers(user_id: str) -> dict:
    """HRDirector headers bound to a real Employee.id (entity-backed)."""
    return build_user_headers(user_id, "HRDirector")


def make_reviewer_headers(user_id: str) -> dict:
    """CompCommitteeReviewer headers bound to a real Employee.id (entity-backed)."""
    return build_user_headers(user_id, "CompCommitteeReviewer")
