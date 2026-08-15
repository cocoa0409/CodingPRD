"""Pre-built role headers for every role in the PRD (§2.1).

Opaque roles (SponsorAdmin, Monitor, Investigator) use shared constants.
Entity-backed roles (Pharmacist, UnblindedPharmacist) MUST be built per-instance
with the actual PharmacyStaff id via the make_*_headers builders — the shared
constants below exist only as fallbacks for tests that do not exercise
ownership or entity-backed authentication.
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    # Opaque roles: canonical shared form.
    "sponsor_admin_headers": build_user_headers("test-sponsor-admin-1", "SponsorAdmin"),
    "monitor_headers": build_user_headers("test-monitor-1", "Monitor"),
    "investigator_headers": build_user_headers("test-investigator-1", "Investigator"),
    # Entity-backed roles: fallback only (never passes authentication, since
    # X-User-ID must resolve to an existing PharmacyStaff record).
    "pharmacist_headers": build_user_headers("test-pharmacist-1", "Pharmacist"),
    "unblinded_pharmacist_headers": build_user_headers("test-unblinded-1", "UnblindedPharmacist"),
}


def make_pharmacist_headers(staff_id: str) -> dict:
    """Blinded pharmacist headers; staff_id must be a PharmacyStaff id whose
    is_unblinded flag is false (PRD §2.1)."""
    return build_user_headers(staff_id, "Pharmacist")


def make_unblinded_pharmacist_headers(staff_id: str) -> dict:
    """Unblinded pharmacist headers; staff_id must be a PharmacyStaff id whose
    is_unblinded flag is true (PRD §2.1)."""
    return build_user_headers(staff_id, "UnblindedPharmacist")
