"""Pre-built role headers for every role in the PRD (§2.1).

Identity binding (PRD §2.1):
- Taxpayer is entity-backed: X-User-ID must equal the acting Owner's id for
  ownership-gated calls (submit-evidence, withdraw, deferral payment). Use
  make_taxpayer_headers(owner_id) in those cases.
- Assessor, Reviewer, HearingOfficer, Anonymous are opaque: X-User-ID is an
  operator identifier not tied to any persisted entity.
"""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe for opaque roles and for tests that don't exercise
# Taxpayer ownership.
TEST_USERS = {
    "assessor_headers": build_user_headers("assessor-op-1", "Assessor"),
    "reviewer_headers": build_user_headers("reviewer-op-1", "Reviewer"),
    "hearing_officer_headers": build_user_headers("hearing-officer-1", "HearingOfficer"),
    # Fallback Taxpayer constant — only for non-ownership Taxpayer tests.
    "taxpayer_headers": build_user_headers("taxpayer-fallback-1", "Taxpayer"),
    "anonymous_headers": build_user_headers("anon-1", "Anonymous"),
}


def make_assessor_headers(user_id: str) -> dict:
    """Opaque Assessor headers with an explicit operator id (e.g. for the
    segregation-of-duties noticing operator)."""
    return build_user_headers(user_id, "Assessor")


def make_reviewer_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "Reviewer")


def make_hearing_officer_headers(user_id: str) -> dict:
    """Opaque HearingOfficer headers with an explicit operator id (used for the
    accept/hold/decide officer identity and segregation-of-duties checks)."""
    return build_user_headers(user_id, "HearingOfficer")


def make_taxpayer_headers(owner_id: str) -> dict:
    """For Taxpayer (entity_backed:Owner). Pass the actual Owner.id as user_id
    whenever the call is ownership-gated (submit-evidence, withdraw, pay)."""
    return build_user_headers(owner_id, "Taxpayer")
