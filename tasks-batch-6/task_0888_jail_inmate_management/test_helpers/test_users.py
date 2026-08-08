"""Pre-built role headers for every role in the PRD.

The five staff roles carry an opaque X-User-ID that is never compared to an
entity id, so shared constants are the canonical form for them. The Visitor
role is entity_backed: its X-User-ID must equal the acting Visitor entity's id,
so ownership-gated calls use make_visitor_headers(visitor_id).
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    "intake_headers": build_user_headers("intake-officer-1", "IntakeOfficer"),
    "classification_headers": build_user_headers("classification-officer-1", "ClassificationOfficer"),
    "scheduler_headers": build_user_headers("scheduler-1", "Scheduler"),
    "health_headers": build_user_headers("health-officer-1", "HealthGrievanceOfficer"),
    "supervisor_headers": build_user_headers("supervisor-1", "Supervisor"),
    # Visitor shared constant is a fallback for non-ownership tests only.
    "visitor_headers": build_user_headers("visitor-shared-1", "Visitor"),
}


def make_visitor_headers(user_id: str) -> dict:
    """For the Visitor role (entity_backed:Visitor). Pass the actual Visitor.id
    as user_id whenever the call is ownership-gated (own-visit request/cancel/read)."""
    return build_user_headers(user_id, "Visitor")


def make_intake_headers(user_id: str) -> dict:
    """IntakeOfficer with an explicit X-User-ID (used for segregation-of-duties setups)."""
    return build_user_headers(user_id, "IntakeOfficer")


def make_supervisor_headers(user_id: str) -> dict:
    """Supervisor with an explicit X-User-ID (used for segregation-of-duties setups)."""
    return build_user_headers(user_id, "Supervisor")
