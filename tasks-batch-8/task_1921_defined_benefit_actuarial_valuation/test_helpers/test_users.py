"""Pre-built role headers for every role in the PRD."""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe for opaque roles, and for tests that don't exercise ownership.
TEST_USERS = {
    "firm_admin_headers": build_user_headers("test-firm-admin-1", "FirmAdmin"),
    "plan_admin_headers": build_user_headers("test-plan-admin-1", "PlanAdmin"),
    "auditor_headers": build_user_headers("test-auditor-1", "Auditor"),
    # entity_backed roles: shared constants are fallbacks for non-ownership tests only.
    "actuary_headers": build_user_headers("test-actuary-1", "Actuary"),
    "senior_actuary_headers": build_user_headers("test-senior-actuary-1", "SeniorActuary"),
}


# Per-instance builders — required for every entity_backed role.
def make_actuary_headers(user_id: str) -> dict:
    """For Actuary (entity_backed:Actuary). Pass the actual Actuary.id as user_id
    whenever the call is ownership-gated."""
    return build_user_headers(user_id, "Actuary")


def make_senior_actuary_headers(user_id: str) -> dict:
    """For SeniorActuary (entity_backed:Actuary). Pass the actual Actuary.id as user_id
    whenever the call is ownership-gated."""
    return build_user_headers(user_id, "SeniorActuary")
