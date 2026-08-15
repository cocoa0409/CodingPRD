"""Pre-built role headers for every role in the PRD (section 2.1).

All six roles are opaque: X-User-ID is a free-form operator identifier that is
never compared to any resource's `id`. It IS compared against recorded
attribution fields (submitted_by_user_id, created_by_user_id,
contractor_signed_by, owner_signed_by) by the segregation-of-duties rules, so
the per-instance builders below exist to pick concrete operator ids per test.
"""
from prd_bench_local_runner.testing import build_user_headers


# Shared constants -- canonical operator ids used across the suite. Safe for
# all calls except those a test deliberately points at a specific operator id
# (segregation-of-duties scenarios), which use the builders below.
TEST_USERS = {
    "system_admin_headers": build_user_headers("admin-1", "SystemAdmin"),
    "superintendent_headers": build_user_headers("supt-1", "Superintendent"),
    "project_manager_headers": build_user_headers("pm-1", "ProjectManager"),
    "safety_officer_headers": build_user_headers("so-1", "SafetyOfficer"),
    "contractor_rep_headers": build_user_headers("ctr-1", "ContractorRep"),
    "owner_rep_headers": build_user_headers("owner-1", "OwnerRep"),
}


def make_system_admin_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "SystemAdmin")


def make_superintendent_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "Superintendent")


def make_project_manager_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "ProjectManager")


def make_safety_officer_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "SafetyOfficer")


def make_contractor_rep_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "ContractorRep")


def make_owner_rep_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "OwnerRep")
