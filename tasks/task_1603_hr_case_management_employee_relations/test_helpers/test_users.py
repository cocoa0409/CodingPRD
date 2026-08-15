"""Pre-built role headers for every role in the PRD."""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe for opaque roles, and for tests that don't exercise ownership.
TEST_USERS = {
    # opaque role: shared constant is the canonical form.
    "er_manager_headers": build_user_headers("test-er-manager-1", "ERManager"),
    # opaque role: shared constant is the canonical form.
    "legal_counsel_headers": build_user_headers("test-legal-counsel-1", "LegalCounsel"),
    # opaque role: shared constant is the canonical form.
    "hr_analyst_headers": build_user_headers("test-hr-analyst-1", "HRAnalyst"),
    # entity_backed role: shared constant is a fallback for non-ownership tests only.
    "investigator_headers": build_user_headers("test-investigator-orphan", "Investigator"),
}


# Per-instance builders — required for entity_backed:Investigator.
def make_investigator_headers(investigator_id: str) -> dict:
    """For Investigator (entity_backed:Investigator). Pass the actual Investigator.id
    whenever the call is ownership-gated."""
    return build_user_headers(investigator_id, "Investigator")


def make_er_manager_headers(user_id: str = "test-er-manager-1") -> dict:
    return build_user_headers(user_id, "ERManager")


def make_legal_counsel_headers(user_id: str = "test-legal-counsel-1") -> dict:
    return build_user_headers(user_id, "LegalCounsel")


def make_hr_analyst_headers(user_id: str = "test-hr-analyst-1") -> dict:
    return build_user_headers(user_id, "HRAnalyst")
