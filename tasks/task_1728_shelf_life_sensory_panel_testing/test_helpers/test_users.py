"""Pre-built role headers for every role in the PRD (§2.1).

LabDirector, SensoryScientist, PanelCoordinator, LabAnalyst, and QAOfficer are
opaque identities: X-User-ID is not tied to any persisted entity (the server
may record it, e.g. as a report's author_user_id or a claim's verified_by).
Panelist is entity-backed by Panelist and Client is entity-backed by
ClientAccount: ownership-gated calls MUST use the per-instance builders with
the real entity id — never the shared constants.
"""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe for opaque roles, and for tests that do not exercise
# ownership (400-on-bad-payload, 404-on-missing-resource, wrong-role checks).
TEST_USERS = {
    "lab_director_headers": build_user_headers("test-director-1", "LabDirector"),
    "scientist_headers": build_user_headers("test-scientist-1", "SensoryScientist"),
    "coordinator_headers": build_user_headers("test-coordinator-1", "PanelCoordinator"),
    "analyst_headers": build_user_headers("test-analyst-1", "LabAnalyst"),
    "qa_headers": build_user_headers("test-qa-1", "QAOfficer"),
    # entity_backed roles: shared constants are fallbacks for non-ownership tests only.
    "panelist_headers": build_user_headers("test-panelist-1", "Panelist"),
    "client_headers": build_user_headers("test-client-1", "Client"),
}


def make_lab_director_headers(user_id: str = "test-director-1") -> dict:
    return build_user_headers(user_id, "LabDirector")


def make_scientist_headers(user_id: str = "test-scientist-1") -> dict:
    """Opaque id; pass a stable distinct value (e.g. 'sci-author') when the
    report-author identity matters (author-only operations, SoD checks)."""
    return build_user_headers(user_id, "SensoryScientist")


def make_coordinator_headers(user_id: str = "test-coordinator-1") -> dict:
    return build_user_headers(user_id, "PanelCoordinator")


def make_analyst_headers(user_id: str = "test-analyst-1") -> dict:
    return build_user_headers(user_id, "LabAnalyst")


def make_qa_headers(user_id: str = "test-qa-1") -> dict:
    """Opaque id; pass a value distinct from the report author for QA actions
    (segregation of duties)."""
    return build_user_headers(user_id, "QAOfficer")


def make_panelist_headers(panelist_id: str) -> dict:
    """For Panelist (entity_backed:Panelist). Pass the acting Panelist.id
    whenever the call is ownership-gated (attribute-score submission)."""
    return build_user_headers(panelist_id, "Panelist")


def make_client_headers(client_id: str) -> dict:
    """For Client (entity_backed:ClientAccount). Pass the owning
    ClientAccount.id whenever the call is ownership-gated (request-changes)."""
    return build_user_headers(client_id, "Client")
