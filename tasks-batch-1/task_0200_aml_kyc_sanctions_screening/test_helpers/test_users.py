"""Pre-built role headers for every role in the PRD (§2.1).

All five roles use an opaque identity model (PRD §2.1): X-User-ID is an opaque
operator identifier never compared to any entity id for ownership. The shared
constants below are therefore the canonical form for every role; no entity_backed
per-instance builders are needed.
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    "compliance_officer_headers": build_user_headers("co-1", "ComplianceOfficer"),
    "analyst_headers": build_user_headers("an-1", "Analyst"),
    "quality_reviewer_headers": build_user_headers("qr-1", "QualityReviewer"),
    "system_feed_headers": build_user_headers("sf-1", "SystemFeed"),
    "platform_admin_headers": build_user_headers("pa-1", "PlatformAdmin"),
}


def make_headers(user_id: str, role: str) -> dict:
    """Build headers for a specific opaque operator id + role.

    Used when a test needs to pin a particular X-User-ID (e.g. the four-eyes
    segregation check, which compares prepared_by_user_id to approved_by_user_id).
    """
    return build_user_headers(user_id, role)
