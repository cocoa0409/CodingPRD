"""Pre-built role headers for every role in the PRD.

All five roles use opaque identity (PRD section 2.1): ``X-User-ID`` is never
compared against any persisted entity's ``id``. Segregation-of-duties checks
compare ``X-User-ID`` values across two requests on the same entity, so the
per-role ``make_*_headers(user_id)`` builders exist for tests that must control
the acting user's identity.
"""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe because every role's identity is opaque.
TEST_USERS = {
    "platform_admin_headers": build_user_headers("test-platform-admin-1", "PlatformAdmin"),
    "shore_officer_headers": build_user_headers("test-shore-officer-1", "ShoreComplianceOfficer"),
    "vessel_master_headers": build_user_headers("test-vessel-master-1", "VesselMaster"),
    "flag_surveyor_headers": build_user_headers("test-flag-surveyor-1", "FlagSurveyor"),
    "psc_officer_headers": build_user_headers("test-psc-officer-1", "PSCOfficer"),
}


# Per-user builders — required whenever a test must pin X-User-ID (e.g.
# segregation-of-duties scenarios where the same or a different user performs
# the paired operation).
def make_platform_admin_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "PlatformAdmin")


def make_shore_officer_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "ShoreComplianceOfficer")


def make_vessel_master_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "VesselMaster")


def make_flag_surveyor_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "FlagSurveyor")


def make_psc_officer_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "PSCOfficer")
