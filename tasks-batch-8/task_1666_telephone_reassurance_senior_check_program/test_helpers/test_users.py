"""Pre-built role headers for every role in the PRD (§2.1).

IntakeWorker / ProgramCoordinator / QualityReviewer / ExternalResponder carry an
opaque X-User-ID (never matched against an entity id). VolunteerCaller is
entity-backed: X-User-ID must equal the acting VolunteerCaller record's id
whenever the call is ownership-gated (call logs, availability windows,
confidentiality agreements) — use make_volunteer_headers(volunteer["id"]).
"""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe for opaque roles, and for calls that are not
# ownership-gated. Never use the volunteer fallback for ownership-gated calls.
TEST_USERS = {
    "intake_headers": build_user_headers("intake-1", "IntakeWorker"),
    "coordinator_headers": build_user_headers("coord-1", "ProgramCoordinator"),
    "reviewer_headers": build_user_headers("qr-1", "QualityReviewer"),
    "responder_headers": build_user_headers("resp-1", "ExternalResponder"),
    # Fallback for VolunteerCaller on calls that do not exercise ownership.
    "volunteer_headers": build_user_headers("vol-generic", "VolunteerCaller"),
}


def make_intake_headers(user_id: str) -> dict:
    """IntakeWorker with a specific opaque operator id."""
    return build_user_headers(user_id, "IntakeWorker")


def make_coordinator_headers(user_id: str) -> dict:
    """ProgramCoordinator with a specific opaque operator id (e.g. for
    segregation-of-duties scenarios where opened_by_user_id matters)."""
    return build_user_headers(user_id, "ProgramCoordinator")


def make_reviewer_headers(user_id: str) -> dict:
    """QualityReviewer with a specific opaque operator id."""
    return build_user_headers(user_id, "QualityReviewer")


def make_responder_headers(user_id: str) -> dict:
    """ExternalResponder with a specific opaque operator id."""
    return build_user_headers(user_id, "ExternalResponder")


def make_volunteer_headers(user_id: str) -> dict:
    """VolunteerCaller (entity-backed). Pass the actual VolunteerCaller.id as
    user_id whenever the call is ownership-gated (logging a call on the
    volunteer's own assignment, managing own availability windows, signing the
    volunteer's own confidentiality agreement)."""
    return build_user_headers(user_id, "VolunteerCaller")
