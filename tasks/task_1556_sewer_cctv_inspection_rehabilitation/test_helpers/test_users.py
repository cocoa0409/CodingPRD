"""Pre-built role headers for every role in the PRD (§2.1).

Identity semantics: DistrictEngineer and CustomerServiceRep are opaque operator
identities; Coder / QaReviewer / CrewLead are entity-backed — X-User-ID must be
the acting Technician's id whenever the call is ownership-gated.
"""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe for opaque roles and for tests that never exercise
# technician ownership checks (400/404 paths, RBAC denials, reads).
TEST_USERS = {
    "engineer_headers": build_user_headers("test-engineer-1", "DistrictEngineer"),
    "csr_headers": build_user_headers("test-csr-1", "CustomerServiceRep"),
    # Fallbacks for entity-backed roles — ONLY for tests whose outcome does not
    # depend on the caller being a specific technician. Ownership-gated calls
    # MUST use the make_*_headers builders below with the real Technician.id.
    "coder_headers": build_user_headers("test-coder-1", "Coder"),
    "qa_reviewer_headers": build_user_headers("test-qa-1", "QaReviewer"),
    "crew_lead_headers": build_user_headers("test-crew-1", "CrewLead"),
}


def make_coder_headers(user_id: str) -> dict:
    """Coder is entity-backed: pass the acting Technician.id as user_id."""
    return build_user_headers(user_id, "Coder")


def make_qa_reviewer_headers(user_id: str) -> dict:
    """QaReviewer is entity-backed: pass the acting Technician.id as user_id."""
    return build_user_headers(user_id, "QaReviewer")


def make_crew_lead_headers(user_id: str) -> dict:
    """CrewLead is entity-backed: pass the acting Technician.id as user_id."""
    return build_user_headers(user_id, "CrewLead")
