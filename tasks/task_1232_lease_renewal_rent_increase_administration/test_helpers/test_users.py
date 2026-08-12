"""Pre-built role headers for every role in the PRD (§2.1).

Staff roles (PlatformAdmin, RegionalDirector, PropertyManager, LeasingAgent)
carry an opaque operator identifier (PRD §2.1), so the shared constants below
are canonical. Resident is entity-backed: ownership-gated calls MUST be made
with make_resident_headers(<Resident.id>).
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    # Opaque staff identities used throughout the suite.
    "admin_headers": build_user_headers("user_admin_1", "PlatformAdmin"),
    "rd_1_headers": build_user_headers("user_rd_1", "RegionalDirector"),
    "pm_1_headers": build_user_headers("user_pm_1", "PropertyManager"),
    "pm_2_headers": build_user_headers("user_pm_2", "PropertyManager"),
    "la_1_headers": build_user_headers("user_la_1", "LeasingAgent"),
    "la_2_headers": build_user_headers("user_la_2", "LeasingAgent"),
    # Fallback Resident identity — only for tests that do NOT exercise
    # ownership (role-denial probes). Ownership-gated calls must use
    # make_resident_headers with the real Resident.id.
    "resident_headers": build_user_headers("test-resident-1", "Resident"),
}


def make_resident_headers(user_id: str) -> dict:
    """Resident is entity-backed (PRD §2.1): X-User-ID must be the Resident.id
    whenever the call is ownership-gated (respond, sign, rescind, resident reads)."""
    return build_user_headers(user_id, "Resident")


def make_staff_headers(user_id: str, role: str) -> dict:
    """Opaque staff identity helper for attribution-sensitive flows."""
    return build_user_headers(user_id, role)
