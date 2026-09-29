"""Pre-built role headers for every role the PRD declares.

Both X-User-ID and X-User-Role are always sent. PlatformAdmin, Clerk and
FiscalOfficer are opaque identities, so the shared constants below are the
canonical form for them. Member, Drafter, ReviewCounsel and AgencyAnalyst are
backed by a real row (Member.id, Drafter.id and Agency.id respectively), so
ownership-gated calls MUST use the per-instance builders with the real id.
"""
from typing import Dict

from prd_bench_local_runner.testing import build_user_headers

TEST_USERS: Dict[str, Dict[str, str]] = {
    # Opaque identities: the shared constant is the canonical form.
    "platform_admin_headers": build_user_headers("test-platform-admin-1", "PlatformAdmin"),
    "clerk_headers": build_user_headers("test-clerk-1", "Clerk"),
    "fiscal_officer_headers": build_user_headers("test-fiscal-officer-1", "FiscalOfficer"),
    # Entity-backed identities: fallback only for tests that do not exercise ownership.
    "member_headers": build_user_headers("test-member-1", "Member"),
    "drafter_headers": build_user_headers("test-drafter-1", "Drafter"),
    "review_counsel_headers": build_user_headers("test-review-counsel-1", "ReviewCounsel"),
    "agency_analyst_headers": build_user_headers("test-agency-analyst-1", "AgencyAnalyst"),
}


def make_platform_admin_headers(user_id: str = "test-platform-admin-1") -> Dict[str, str]:
    """PlatformAdmin acts under an opaque identity."""
    return build_user_headers(user_id, "PlatformAdmin")


def make_clerk_headers(user_id: str = "test-clerk-1") -> Dict[str, str]:
    """Clerk acts under an opaque identity."""
    return build_user_headers(user_id, "Clerk")


def make_fiscal_officer_headers(user_id: str = "test-fiscal-officer-1") -> Dict[str, str]:
    """FiscalOfficer acts under an opaque identity."""
    return build_user_headers(user_id, "FiscalOfficer")


def make_member_headers(user_id: str) -> Dict[str, str]:
    """Member identity resolves to a Member row: pass the real Member.id."""
    return build_user_headers(user_id, "Member")


def make_drafter_headers(user_id: str) -> Dict[str, str]:
    """Drafter identity resolves to a Drafter row: pass the real Drafter.id."""
    return build_user_headers(user_id, "Drafter")


def make_review_counsel_headers(user_id: str) -> Dict[str, str]:
    """ReviewCounsel is backed by the same Drafter table: pass the real Drafter.id
    of a drafter whose is_senior is true."""
    return build_user_headers(user_id, "ReviewCounsel")


def make_agency_analyst_headers(user_id: str) -> Dict[str, str]:
    """AgencyAnalyst identity resolves to an Agency row: pass the real Agency.id."""
    return build_user_headers(user_id, "AgencyAnalyst")


def make_headers(role: str, user_id: str) -> Dict[str, str]:
    """Generic builder for role-matrix tests."""
    return build_user_headers(user_id, role)


ALL_ROLES = [
    "PlatformAdmin",
    "Clerk",
    "FiscalOfficer",
    "Member",
    "Drafter",
    "ReviewCounsel",
    "AgencyAnalyst",
]
