"""Pre-built role headers for every role in the PRD (§2.1)."""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe for opaque roles, and for tests that do not exercise
# ownership (400-on-bad-payload, 404-on-missing-resource, or admin-acted calls).
TEST_USERS = {
    "admin_headers": build_user_headers("test-admin-1", "ResearchOpsAdmin"),
    "researcher_headers": build_user_headers("test-researcher-1", "Researcher"),
    "officer_headers": build_user_headers("officer-1", "IncentiveOfficer"),
    "legal_headers": build_user_headers("legal-1", "LegalCounsel"),
    # entity_backed roles: shared constants are fallbacks for non-ownership
    # tests only — ownership-gated calls MUST use the make_* builders below.
    "moderator_headers": build_user_headers("test-moderator-1", "Moderator"),
    "participant_headers": build_user_headers("test-participant-1", "Participant"),
}


# Per-instance builders — required for entity_backed roles (PRD §2.1: for
# Participant/Moderator actors on owned resources, X-User-ID must equal the
# resource's ownership field).
def make_participant_headers(user_id: str) -> dict:
    """For Participant (entity_backed:Participant). Pass the actual
    Participant.id whenever the call is ownership-gated."""
    return build_user_headers(user_id, "Participant")


def make_moderator_headers(user_id: str) -> dict:
    """For Moderator (entity_backed:Moderator). Pass the actual
    Moderator.id whenever the call is ownership-gated."""
    return build_user_headers(user_id, "Moderator")


# Opaque-role builders — X-User-ID is a plain operator identifier, never
# compared to an entity id, but recorded for attribution (PRD §2.1).
def make_admin_headers(user_id: str = "test-admin-1") -> dict:
    return build_user_headers(user_id, "ResearchOpsAdmin")


def make_researcher_headers(user_id: str = "test-researcher-1") -> dict:
    return build_user_headers(user_id, "Researcher")


def make_officer_headers(user_id: str) -> dict:
    """Segregation-of-duties workflows need distinct officer identities
    (officer-1 / officer-2 / officer-3)."""
    return build_user_headers(user_id, "IncentiveOfficer")


def make_legal_headers(user_id: str = "legal-1") -> dict:
    return build_user_headers(user_id, "LegalCounsel")
