"""Pre-built role headers for every role in the PRD (§2.1).

- ``Chief`` is an *opaque* operator identity; its ``X-User-ID`` is never compared
  to any persisted entity, so the shared constant is the canonical form.
- ``Officer`` and ``Member`` are *entity-backed by a Member*: ``X-User-ID`` is the
  acting member's ``id``. Ownership-gated calls (a Member checking in their own
  assignment) MUST pass the real member id via the per-instance builders below.
"""
from prd_bench_local_runner.testing import build_user_headers


TEST_USERS = {
    # opaque role — shared constant is canonical.
    "chief_headers": build_user_headers("chief-operator-1", "Chief"),
    # entity_backed roles — shared constants are only a fallback for tests that do
    # NOT exercise ownership (e.g. 401/403/404 shape checks). Ownership-gated calls
    # must use make_officer_headers / make_member_headers with the real member id.
    "officer_headers": build_user_headers("officer-fallback-1", "Officer"),
    "member_headers": build_user_headers("member-fallback-1", "Member"),
}

CHIEF = TEST_USERS["chief_headers"]


def make_officer_headers(user_id: str) -> dict:
    """Headers for an Officer whose X-User-ID is the acting Member's id."""
    return build_user_headers(user_id, "Officer")


def make_member_headers(user_id: str) -> dict:
    """Headers for a rank-and-file Member whose X-User-ID is that member's id.

    Required for the check-in ownership gate (PRD §2.1, §3.4)."""
    return build_user_headers(user_id, "Member")
