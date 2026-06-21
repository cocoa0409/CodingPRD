"""Pre-built role headers for every role in the PRD.

Per PRD §2.1:
- Examiner: X-User-ID is the acting Examiner entity's `id` (entity-backed).
  Ownership and segregation checks compare it to appointment.examiner_id /
  scored_by_examiner_id, so it MUST be threaded with the real examiner id.
- LicenseClerk, KnowledgeProctor, AdjudicationOfficer: X-User-ID is an opaque
  operator identifier, never compared to any entity id.
"""
from prd_bench_local_runner.testing import build_user_headers


# Shared constants — safe for opaque roles, and for non-ownership tests.
TEST_USERS = {
    "clerk_headers": build_user_headers("clerk-1", "LicenseClerk"),
    "clerk2_headers": build_user_headers("clerk-2", "LicenseClerk"),
    "proctor_headers": build_user_headers("kp-1", "KnowledgeProctor"),
    "officer_headers": build_user_headers("officer-1", "AdjudicationOfficer"),
    "officer2_headers": build_user_headers("officer-2", "AdjudicationOfficer"),
    # Examiner shared constant: a fallback only — never use for ownership-gated calls.
    "examiner_headers": build_user_headers("examiner-fallback", "Examiner"),
}


def make_clerk_headers(user_id: str = "clerk-1") -> dict:
    """LicenseClerk opaque operator id."""
    return build_user_headers(user_id, "LicenseClerk")


def make_proctor_headers(user_id: str = "kp-1") -> dict:
    """KnowledgeProctor opaque operator id."""
    return build_user_headers(user_id, "KnowledgeProctor")


def make_officer_headers(user_id: str = "officer-1") -> dict:
    """AdjudicationOfficer opaque operator id. recorded_by_officer is captured from it."""
    return build_user_headers(user_id, "AdjudicationOfficer")


def make_examiner_headers(examiner_id: str) -> dict:
    """For Examiner (entity_backed:Examiner). Pass the actual Examiner.id as user_id
    whenever the call is ownership-gated (proctor/score) so the appointment's
    examiner_id / scored_by_examiner_id comparisons resolve correctly."""
    return build_user_headers(examiner_id, "Examiner")
