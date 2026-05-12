"""Pre-built role headers for every role in the PRD.

PRD §2.1: 'when X-User-Role is TriageManager, Developer, QAEngineer, or
ReleaseManager, the value of X-User-ID is the id of the acting TeamMember,
and any ownership check ... compares the defect's assignee_id foreign-key
field to X-User-ID.'

All four persisted roles are entity-backed. Ownership-gated calls
(start-progress, submit-fix, pause-sla/resume-sla by the assignee; verify
by an independent QAEngineer; severity-override approve/reject by an
independent TriageManager) MUST use make_<role>_headers(team_member_id)
with the real TeamMember.id minted by POST
/projects/{p}/team-members.

PRD §2.1 also notes 'Any is a pseudo-role used only on read endpoints' —
opaque shape. The shared TEST_USERS entry for Any is canonical (and the
implementation accepts any of the four persisted roles in its place per the
prose).
"""
from __future__ import annotations

from typing import Dict

from prd_bench_local_runner.testing import build_user_headers


# Shared fallback constants. These are safe ONLY when:
#   - the role is opaque (Any), or
#   - the test does NOT exercise an ownership check (e.g., RBAC permission
#     denied, 404 on missing entity, 400 on bad payload).
# For ownership-gated calls (e.g., start-progress by the assigned developer),
# use the per-instance builder below with the actual TeamMember.id.
TEST_USERS: Dict[str, Dict[str, str]] = {
    # Opaque pseudo-role for read endpoints.
    "any_headers": build_user_headers("any-reader-001", "Any"),

    # Fallbacks for the four persisted (entity_backed) roles. Use only on
    # non-ownership tests.
    "triage_manager_headers": build_user_headers(
        "triage-fallback", "TriageManager",
    ),
    "developer_headers": build_user_headers(
        "developer-fallback", "Developer",
    ),
    "qa_engineer_headers": build_user_headers(
        "qa-fallback", "QAEngineer",
    ),
    "release_manager_headers": build_user_headers(
        "release-fallback", "ReleaseManager",
    ),
}


# ---------------------------------------------------------------------------
# Per-instance builders. Identity-thread the X-User-ID with the actual
# TeamMember.id minted under POST /projects/{p}/team-members.
# ---------------------------------------------------------------------------
def make_triage_manager_headers(team_member_id: str) -> Dict[str, str]:
    """PRD §2.1: TriageManager is entity-backed against TeamMember.
    X-User-ID is the TeamMember.id of the acting TriageManager."""
    return build_user_headers(team_member_id, "TriageManager")


def make_developer_headers(team_member_id: str) -> Dict[str, str]:
    """PRD §2.1: Developer is entity-backed. For ownership-gated calls
    (start-progress, submit-fix, pause-sla, resume-sla) the server compares
    defect.assignee_id to X-User-ID, so the X-User-ID must be the
    Developer's TeamMember.id."""
    return build_user_headers(team_member_id, "Developer")


def make_qa_engineer_headers(team_member_id: str) -> Dict[str, str]:
    """PRD §2.1: QAEngineer is entity-backed. PRD §3.7 enforces verifier
    independence by comparing X-User-ID to FixRecord.developer_id, so the
    header MUST carry the real QA TeamMember.id."""
    return build_user_headers(team_member_id, "QAEngineer")


def make_release_manager_headers(team_member_id: str) -> Dict[str, str]:
    """PRD §2.1: ReleaseManager is entity-backed. Regression-run actor."""
    return build_user_headers(team_member_id, "ReleaseManager")


def make_any_headers(reader_id: str = "any-reader-001") -> Dict[str, str]:
    """PRD §2.1: 'the implementation should treat a request whose
    X-User-Role matches one of the four persisted roles as automatically
    satisfying any Any-permitted read.' This helper exists for cases that
    want to specify the opaque reader id explicitly."""
    return build_user_headers(reader_id, "Any")


__all__ = [
    "TEST_USERS",
    "make_triage_manager_headers",
    "make_developer_headers",
    "make_qa_engineer_headers",
    "make_release_manager_headers",
    "make_any_headers",
]
