"""Pre-built role headers for every role in the PRD.

Grazier, CattleOwner and RangeConsultant are entity-backed: their `X-User-ID`
must be the id of a real row of the matching type, so ownership-gated calls
MUST use the per-instance builders below. PlatformAdmin is opaque, so the
shared constant is the canonical form for it.
"""

from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    # entity_backed roles: these shared constants never resolve to a real row,
    # so they are only useful where the test expects ERR_PARTY_NOT_FOUND.
    "grazier_headers": build_user_headers("test-grazier-1", "Grazier"),
    "cattle_owner_headers": build_user_headers("test-cattle-owner-1", "CattleOwner"),
    "range_consultant_headers": build_user_headers("test-consultant-1", "RangeConsultant"),
    # opaque role: the shared constant IS the canonical form.
    "platform_admin_headers": build_user_headers("test-admin-1", "PlatformAdmin"),
}

ADMIN_HEADERS = TEST_USERS["platform_admin_headers"]

# A request carrying no X-User-Role header at all.
ANONYMOUS_HEADERS = {"Content-Type": "application/json"}


def make_grazier_headers(user_id: str) -> dict:
    """Headers for a Grazier. Pass the actual Grazier id."""
    return build_user_headers(user_id, "Grazier")


def make_cattle_owner_headers(user_id: str) -> dict:
    """Headers for a CattleOwner. Pass the actual CattleOwner id."""
    return build_user_headers(user_id, "CattleOwner")


def make_range_consultant_headers(user_id: str) -> dict:
    """Headers for a RangeConsultant. Pass the actual RangeConsultant id."""
    return build_user_headers(user_id, "RangeConsultant")


def make_platform_admin_headers(user_id: str = "test-admin-1") -> dict:
    """Headers for the opaque PlatformAdmin operator."""
    return build_user_headers(user_id, "PlatformAdmin")


def make_headers_without_role(user_id: str) -> dict:
    """An otherwise well-formed request with the X-User-Role header omitted."""
    return {"X-User-ID": user_id, "Content-Type": "application/json"}
