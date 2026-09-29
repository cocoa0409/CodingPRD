"""Pre-built role headers for every role the PRD defines.

Every request carries ``X-User-ID`` and ``X-User-Role``. A SponsorAdmin's ``X-User-ID`` is the
``Sponsor.id`` it administers and a SiteSupervisor's ``X-User-ID`` is the ``Site.id`` it staffs, so
any ownership-gated call must use the per-instance builders below with the real entity id. The
StateAgencyReviewer and FieldMonitor identifiers are opaque user identifiers.
"""

from typing import Dict

from prd_bench_local_runner.testing import build_user_headers

# Shared constants. Safe for the opaque roles, and for calls whose outcome does not depend on the
# caller owning the subject resource (missing-field rejections, unknown-id lookups, role checks).
TEST_USERS: Dict[str, Dict[str, str]] = {
    "state_agency_reviewer_headers": build_user_headers("rev_1", "StateAgencyReviewer"),
    "sponsor_admin_headers": build_user_headers("sponsor-admin-unowned", "SponsorAdmin"),
    "site_supervisor_headers": build_user_headers("site-supervisor-unowned", "SiteSupervisor"),
    "field_monitor_headers": build_user_headers("mon_1", "FieldMonitor"),
}


def make_state_agency_reviewer_headers(user_id: str = "rev_1") -> Dict[str, str]:
    """Headers for a StateAgencyReviewer; the identifier is an opaque user identifier."""
    return build_user_headers(user_id, "StateAgencyReviewer")


def make_sponsor_admin_headers(sponsor_id: str) -> Dict[str, str]:
    """Headers for a SponsorAdmin. Pass the actual Sponsor.id: the PRD makes a SponsorAdmin's
    X-User-ID the identifier of the sponsor it administers."""
    return build_user_headers(sponsor_id, "SponsorAdmin")


def make_site_supervisor_headers(site_id: str) -> Dict[str, str]:
    """Headers for a SiteSupervisor. Pass the actual Site.id: the PRD makes a SiteSupervisor's
    X-User-ID the identifier of the site it staffs."""
    return build_user_headers(site_id, "SiteSupervisor")


def make_field_monitor_headers(user_id: str = "mon_1") -> Dict[str, str]:
    """Headers for a FieldMonitor. The identifier is opaque but is stamped into
    monitor_user_id, opened_by_user_id and closed_by_user_id, so tests that assert those fields
    must pass the same identifier they scheduled the visit with."""
    return build_user_headers(user_id, "FieldMonitor")


def make_headers(user_id: str, role: str) -> Dict[str, str]:
    """Escape hatch for role-permission tests that need an arbitrary user/role pair."""
    return build_user_headers(user_id, role)
