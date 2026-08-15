"""Pre-built role headers for every role in the PRD.

Two kinds of entries live here:
- Shared constants in TEST_USERS, safe for opaque roles (ContestLead,
  SafetyOfficer, StageManager, Treasurer, Anonymous) and for tests whose
  outcome does not depend on caller ownership of a specific resource.
- Per-instance builders for entity-backed roles (Contestant, Judge): pass the
  actual entity id as user_id whenever the call is ownership-gated, so the
  X-User-ID header equals the resource's foreign key.
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    # Opaque roles: X-User-ID is not tied to any persisted entity.
    "anonymous_headers": build_user_headers("anon-1", "Anonymous"),
    "contest_lead_headers": build_user_headers("lead-1", "ContestLead"),
    "safety_officer_headers": build_user_headers("safety-1", "SafetyOfficer"),
    "stage_manager_headers": build_user_headers("stage-1", "StageManager"),
    # Treasurer is opaque, but segregation-of-duties compares X-User-ID values,
    # so two stable treasurer identities are provided.
    "treasurer_headers": build_user_headers("tr_1", "Treasurer"),
    "treasurer_2_headers": build_user_headers("tr_2", "Treasurer"),
    # Entity-backed fallbacks for non-ownership-gated calls only.
    "contestant_headers": build_user_headers("test-contestant-1", "Contestant"),
    "judge_headers": build_user_headers("test-judge-1", "Judge"),
}


def make_contestant_headers(contestant_id: str) -> dict:
    """Contestant is entity-backed: X-User-ID must be the Contestant id
    whenever the call is ownership-gated (entries, consents, bookings)."""
    return build_user_headers(contestant_id, "Contestant")


def make_judge_headers(judge_id: str) -> dict:
    """Judge is entity-backed: X-User-ID must be the Judge id whenever the
    call acts on the judge's own scoresheets."""
    return build_user_headers(judge_id, "Judge")


def make_treasurer_headers(user_id: str) -> dict:
    """Treasurer is opaque; pass a distinct user id to exercise segregation
    of duties (creator vs approver)."""
    return build_user_headers(user_id, "Treasurer")
