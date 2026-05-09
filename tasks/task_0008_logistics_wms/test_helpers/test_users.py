"""Pre-built role headers. All three roles have opaque identity per the PRD —
the server never compares X-User-ID against a persisted entity, so shared
constants are PRD-faithful for all roles. The single exception is segregation
of duties on cycle counts, where the approver's X-User-ID must differ from
the submitter's; for that case we expose distinct USER_IDs as separate
constants and tests construct headers explicitly via build_user_headers().
"""
from prd_bench_local_runner.testing import build_user_headers


# Distinct user-ids for segregation-of-duties scenarios
STAFF_USER_ID = "test-staff-1"
STAFF_USER_ID_ALT = "test-staff-2"
AUDITOR_USER_ID = "test-auditor-1"
AUDITOR_USER_ID_ALT = "test-auditor-2"
MANAGER_USER_ID = "test-manager-1"


TEST_USERS = {
    "staff_headers": build_user_headers(STAFF_USER_ID, "WarehouseStaff"),
    "staff_headers_alt": build_user_headers(STAFF_USER_ID_ALT, "WarehouseStaff"),
    "auditor_headers": build_user_headers(AUDITOR_USER_ID, "Auditor"),
    "auditor_headers_alt": build_user_headers(AUDITOR_USER_ID_ALT, "Auditor"),
    "manager_headers": build_user_headers(MANAGER_USER_ID, "WarehouseManager"),
}


def make_staff_headers(user_id: str) -> dict:
    """Build WarehouseStaff headers with a custom X-User-ID — used for SoD scenarios."""
    return build_user_headers(user_id, "WarehouseStaff")


def make_auditor_headers(user_id: str) -> dict:
    """Build Auditor headers with a custom X-User-ID — used for SoD scenarios."""
    return build_user_headers(user_id, "Auditor")


def make_manager_headers(user_id: str) -> dict:
    """Build WarehouseManager headers with a custom X-User-ID."""
    return build_user_headers(user_id, "WarehouseManager")
