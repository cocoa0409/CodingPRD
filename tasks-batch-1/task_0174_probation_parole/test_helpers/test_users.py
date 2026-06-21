"""Pre-built role headers for every role in the PRD (§2.1).

Three roles exist: Officer, SupervisingJudge, CompactAdministrator.

- Officer is ENTITY-BACKED by the Officer entity: its X-User-ID must equal the
  acting Officer's id. Ownership and segregation-of-duties checks compare a
  stored officer-id foreign key (e.g. a violation's filed_by_officer_id) to
  X-User-ID. Use make_officer_headers(officer_id) whenever the call is
  ownership-gated or its filing officer matters. The shared constant is only a
  fallback for tests that don't exercise ownership (401/403/404/400 shapes).
- SupervisingJudge and CompactAdministrator are OPAQUE: their X-User-ID is an
  operator identifier not tied to any persisted row, so the shared constant is
  canonical. Distinct opaque ids can be minted via the make_*_headers builders
  when a test needs the judge id to differ from a filing officer.
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    # Officer entity_backed shared fallback — only for non-ownership tests.
    "officer_headers": build_user_headers("officer-fallback", "Officer"),
    # Opaque roles — shared constant is canonical.
    "judge_headers": build_user_headers("judge-1", "SupervisingJudge"),
    "compact_admin_headers": build_user_headers("compact-admin-1", "CompactAdministrator"),
}


def make_officer_headers(officer_id: str) -> dict:
    """Officer (entity_backed:Officer). Pass the actual Officer.id as user_id
    whenever the call is ownership-gated (open case, file/appeal violation,
    record payment) or when the acting officer's id is recorded (e.g.
    filed_by_officer_id on a mark-missed auto-violation)."""
    return build_user_headers(officer_id, "Officer")


def make_judge_headers(user_id: str = "judge-1") -> dict:
    """SupervisingJudge (opaque). Vary user_id to make the sustaining judge's
    id differ from (or equal) a violation's filed_by_officer_id for the
    segregation-of-duties rule."""
    return build_user_headers(user_id, "SupervisingJudge")


def make_compact_admin_headers(user_id: str = "compact-admin-1") -> dict:
    """CompactAdministrator (opaque)."""
    return build_user_headers(user_id, "CompactAdministrator")
