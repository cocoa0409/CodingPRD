"""Pre-built role headers for every role in the PRD (PRD §2.1).

Per PRD §2.1, X-User-ID is treated as an opaque operator identifier for every role
— none of the five roles are entity-backed. The server records the acting X-User-ID
on DemandLetter.drafted_by_user_id for the segregation-of-duties check, but does
not resolve X-User-ID to any persisted entity. The shared TEST_USERS constants are
therefore the canonical form for every role.

For tests that need to control the acting X-User-ID (e.g., segregation-of-duties
on demand letters), use `make_headers(user_id, role)` directly.
"""
from prd_bench_local_runner.testing import build_user_headers


TEST_USERS = {
    # Opaque "Anonymous" — public endpoints accept no auth header.
    "anonymous_headers": {},
    "paralegal_headers": build_user_headers("test-paralegal-1", "Paralegal"),
    "attorney_headers": build_user_headers("test-attorney-1", "Attorney"),
    "managing_partner_headers": build_user_headers("test-partner-1", "ManagingPartner"),
    "platform_admin_headers": build_user_headers("test-admin-1", "PlatformAdmin"),
}


def make_headers(user_id: str, role: str) -> dict:
    """Generic header constructor for tests that need to pin a specific X-User-ID
    (e.g., the segregation-of-duties check on DemandLetter send, which compares
    the partner's X-User-ID against the drafter's X-User-ID per PRD §3.4)."""
    return build_user_headers(user_id, role)


def make_paralegal_headers(user_id: str = "test-paralegal-1") -> dict:
    """Paralegal headers with optional pinned X-User-ID."""
    return build_user_headers(user_id, "Paralegal")


def make_attorney_headers(user_id: str = "test-attorney-1") -> dict:
    """Attorney headers with optional pinned X-User-ID."""
    return build_user_headers(user_id, "Attorney")


def make_managing_partner_headers(user_id: str = "test-partner-1") -> dict:
    """ManagingPartner headers with optional pinned X-User-ID."""
    return build_user_headers(user_id, "ManagingPartner")


def make_platform_admin_headers(user_id: str = "test-admin-1") -> dict:
    """PlatformAdmin headers."""
    return build_user_headers(user_id, "PlatformAdmin")
