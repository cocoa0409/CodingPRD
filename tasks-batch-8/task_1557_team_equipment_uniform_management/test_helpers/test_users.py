"""Pre-built role headers for every role in the PRD.

All three roles are opaque identities per the PRD: X-User-ID is an opaque
operator identifier not tied to any persisted entity, so the shared
constants below are the canonical form for every call.
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    "equipment_manager_headers": build_user_headers("test-em-1", "EquipmentManager"),
    "team_admin_headers": build_user_headers("test-admin-1", "TeamAdmin"),
    "laundry_vendor_headers": build_user_headers("test-vendor-1", "LaundryVendor"),
}


def make_equipment_manager_headers(user_id: str = "test-em-1") -> dict:
    return build_user_headers(user_id, "EquipmentManager")


def make_team_admin_headers(user_id: str = "test-admin-1") -> dict:
    return build_user_headers(user_id, "TeamAdmin")


def make_laundry_vendor_headers(user_id: str = "test-vendor-1") -> dict:
    return build_user_headers(user_id, "LaundryVendor")
