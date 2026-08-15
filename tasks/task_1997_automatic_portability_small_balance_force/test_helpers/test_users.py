"""Pre-built role headers for every role in the PRD."""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe for opaque roles and for tests that do not exercise
# ownership. For Participant-role calls that ARE ownership-gated, use
# make_participant_headers(<participant_id>) instead.
TEST_USERS = {
    # entity_backed role: fallback only for non-ownership tests.
    "participant_headers": build_user_headers("test-participant-1", "Participant"),
    # opaque roles: shared constants are canonical.
    "plan_sponsor_headers": build_user_headers("test-sponsor-1", "PlanSponsor"),
    "provider_ops_headers": build_user_headers("test-ops-1", "ProviderOps"),
    "fiduciary_reviewer_headers": build_user_headers("test-reviewer-1", "FiduciaryReviewer"),
}


def make_participant_headers(user_id: str) -> dict:
    """For Participant (entity_backed:Participant). Pass the actual Participant.id
    as user_id whenever the call is ownership-gated (elections, voids, IRA close,
    own-record PATCH)."""
    return build_user_headers(user_id, "Participant")


def make_plan_sponsor_headers(user_id: str) -> dict:
    """Opaque PlanSponsor identity with a caller-chosen id."""
    return build_user_headers(user_id, "PlanSponsor")


def make_provider_ops_headers(user_id: str) -> dict:
    """Opaque ProviderOps identity with a caller-chosen id (used as the
    executed_by_user_id anchor in segregation-of-duties scenarios)."""
    return build_user_headers(user_id, "ProviderOps")


def make_fiduciary_reviewer_headers(user_id: str) -> dict:
    """Opaque FiduciaryReviewer identity with a caller-chosen id."""
    return build_user_headers(user_id, "FiduciaryReviewer")
