"""Pre-built role headers for every role in the PRD.

LabAdmin, Histotech, and PathologyAssistant use opaque operator identifiers:
X-User-ID is never compared to a persisted entity id, so the shared constants
are canonical. Pathologist is entity-backed: X-User-ID must equal the acting
Pathologist entity's id whenever the call is ownership-gated, so tests and
fixtures must use make_pathologist_headers(pathologist["id"]) for those calls.
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    "lab_admin_headers": build_user_headers("test-admin-1", "LabAdmin"),
    "histotech_headers": build_user_headers("test-histotech-1", "Histotech"),
    "pathology_assistant_headers": build_user_headers("test-pa-1", "PathologyAssistant"),
    # Fallback only: safe for calls that are not ownership-gated. Ownership-gated
    # calls must use make_pathologist_headers with the real Pathologist.id.
    "pathologist_headers": build_user_headers("test-pathologist-1", "Pathologist"),
}


def make_lab_admin_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "LabAdmin")


def make_histotech_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "Histotech")


def make_pathology_assistant_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "PathologyAssistant")


def make_pathologist_headers(user_id: str) -> dict:
    """For Pathologist (entity-backed). Pass the actual Pathologist.id as
    user_id whenever the call is ownership-gated (submit, sign-out, amend,
    consult accept/decline/answer/incorporate/reroute, acknowledge)."""
    return build_user_headers(user_id, "Pathologist")
