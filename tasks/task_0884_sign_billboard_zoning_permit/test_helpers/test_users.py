"""Pre-built role headers for every role in the PRD.

Two roles are entity-backed: `Applicant` (its X-User-ID must equal the acting
Applicant's id, and ownership checks compare a resource's applicant_id/operator_id
to it) and `Inspector` (its X-User-ID must equal the assigned inspector_id). The
`Planner` and `ZoningBoard` roles are opaque operator identities: the server records
them (e.g. recommended_by_user_id / decided_by_user_id) but never resolves them to a
persisted entity id.
"""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe for opaque roles, and for tests that do NOT exercise
# entity-backed ownership (e.g. 422-on-bad-payload, 404-on-missing-resource).
TEST_USERS = {
    "planner_headers": build_user_headers("planner-1", "Planner"),
    "zoningboard_headers": build_user_headers("board-1", "ZoningBoard"),
    # entity_backed Applicant: shared constant is a fallback for non-ownership tests only.
    "applicant_headers": build_user_headers("applicant-shared-1", "Applicant"),
    # entity_backed Inspector: shared constant is a fallback for non-ownership tests only.
    "inspector_headers": build_user_headers("inspector-shared-1", "Inspector"),
    # No valid auth headers — used for the ERR_UNAUTHENTICATED case.
    "anonymous_headers": {},
}


def make_applicant_headers(user_id: str) -> dict:
    """For the Applicant role (entity_backed:Applicant). Pass the actual Applicant.id
    as user_id whenever the call is ownership-gated (application/billboard/lease actions)."""
    return build_user_headers(user_id, "Applicant")


def make_inspector_headers(user_id: str) -> dict:
    """For the Inspector role (entity_backed:Inspector). Pass the actual Inspector.id
    whenever recording an inspection outcome (ownership-gated)."""
    return build_user_headers(user_id, "Inspector")


def make_planner_headers(user_id: str = "planner-1") -> dict:
    """Planner (opaque). user_id is recorded as recommended_by_user_id on a variance."""
    return build_user_headers(user_id, "Planner")


def make_zoningboard_headers(user_id: str = "board-1") -> dict:
    """ZoningBoard (opaque). user_id is recorded as decided_by_user_id and drives SoD."""
    return build_user_headers(user_id, "ZoningBoard")


def make_anonymous_headers() -> dict:
    """No auth headers at all — triggers ERR_UNAUTHENTICATED."""
    return {}
