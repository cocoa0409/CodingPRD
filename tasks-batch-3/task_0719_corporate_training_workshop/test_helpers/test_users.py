"""Pre-built role headers for every role in the PRD (§2.1)."""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe for opaque roles, and for tests that don't exercise ownership.
# Four of five roles (ProgramDesigner, SchedulingCoordinator, Learner, FinanceManager) carry
# an opaque X-User-ID not tied to any entity, so a shared constant is the canonical form for them.
# Facilitator is entity-backed: the shared constant below is a fallback for non-ownership
# negative tests only; ownership-gated calls MUST use make_facilitator_headers(facilitator_id).
TEST_USERS = {
    "program_designer_headers": build_user_headers("test-designer-1", "ProgramDesigner"),
    "scheduling_coordinator_headers": build_user_headers("test-coordinator-1", "SchedulingCoordinator"),
    "learner_headers": build_user_headers("test-learner-1", "Learner"),
    "finance_manager_headers": build_user_headers("test-finance-1", "FinanceManager"),
    # Facilitator fallback (non-ownership use only):
    "facilitator_headers": build_user_headers("test-facilitator-1", "Facilitator"),
}


# Per-instance builders.
def make_facilitator_headers(user_id: str) -> dict:
    """For Facilitator (entity_backed:Facilitator). Pass the actual Facilitator.id as user_id
    whenever the call is ownership-gated (mark-attendance, grade assessment)."""
    return build_user_headers(user_id, "Facilitator")


def make_learner_headers(user_id: str) -> dict:
    """Learner is opaque; any X-User-ID is accepted. Helper provided for readability when a
    test threads a learner-specific identifier."""
    return build_user_headers(user_id, "Learner")


def make_program_designer_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "ProgramDesigner")


def make_scheduling_coordinator_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "SchedulingCoordinator")


def make_finance_manager_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "FinanceManager")


# Unauthenticated request: no identity headers at all (PRD §2.1 -> ERR_UNAUTHENTICATED).
NO_AUTH_HEADERS: dict = {}
