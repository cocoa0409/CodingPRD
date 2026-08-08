"""Pre-built role headers for every role in the PRD.

Only the Taxpayer role is entity-backed: its X-User-ID must equal the acting
Taxpayer's id, and ownership checks compare a resource's taxpayer_id to it. The
other roles (TaxAdmin, TaxAuditor, AppealsOfficer) are opaque operator identities
that are recorded where a transition writes them but never compared to an entity id.
"""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe for opaque roles, and for tests that don't exercise
# Taxpayer ownership (e.g. 400-on-bad-payload, 404-on-missing-resource).
TEST_USERS = {
    "admin_headers": build_user_headers("admin-1", "TaxAdmin"),
    "auditor_headers": build_user_headers("aud-1", "TaxAuditor"),
    "officer_headers": build_user_headers("off-1", "AppealsOfficer"),
    # entity_backed Taxpayer: shared constant is a fallback for non-ownership tests only.
    "taxpayer_headers": build_user_headers("taxpayer-shared-1", "Taxpayer"),
    # Anonymous public registration: X-User-ID is not compared to any entity.
    "anonymous_headers": build_user_headers("anon-1", "Anonymous"),
}


def make_taxpayer_headers(user_id: str) -> dict:
    """For the Taxpayer role (entity_backed:Taxpayer). Pass the actual Taxpayer.id
    as user_id whenever the call is ownership-gated."""
    return build_user_headers(user_id, "Taxpayer")


def make_auditor_headers(user_id: str = "aud-1") -> dict:
    """TaxAuditor (opaque). user_id is recorded as opened_by_user_id / issued_by_user_id."""
    return build_user_headers(user_id, "TaxAuditor")


def make_officer_headers(user_id: str = "off-1") -> dict:
    """AppealsOfficer (opaque). user_id is recorded as decided_by_user_id and drives SoD."""
    return build_user_headers(user_id, "AppealsOfficer")


def make_admin_headers(user_id: str = "admin-1") -> dict:
    """TaxAdmin (opaque)."""
    return build_user_headers(user_id, "TaxAdmin")


def make_anonymous_headers() -> dict:
    return build_user_headers("anon-1", "Anonymous")
