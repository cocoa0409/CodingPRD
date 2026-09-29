"""Pre-built role headers for every role in the PRD.

``ElectionAdministrator``, ``IndependentAuditor`` and ``CuratorialStaff`` are
opaque identities: any stable string works as ``X-User-ID``.

``Elector`` and ``ScreeningCommitteeMember`` are elector-backed: their
``X-User-ID`` must resolve to an existing Elector row, so callers MUST use
``make_elector_headers(elector["id"])`` / ``make_screening_member_headers(...)``
with the real row id. The shared constants below are only for tests that
deliberately probe an unknown elector identity.
"""

from prd_bench_local_runner.testing import build_user_headers

ADMIN_USER_ID = "admin-1"
AUDITOR_USER_ID = "auditor-1"
SECOND_AUDITOR_USER_ID = "auditor-2"
CURATOR_USER_ID = "curator-1"
UNKNOWN_ELECTOR_USER_ID = "not-an-elector-1"

TEST_USERS = {
    # Opaque roles — the shared constant is the canonical form.
    "admin_headers": build_user_headers(ADMIN_USER_ID, "ElectionAdministrator"),
    "auditor_headers": build_user_headers(AUDITOR_USER_ID, "IndependentAuditor"),
    "second_auditor_headers": build_user_headers(
        SECOND_AUDITOR_USER_ID, "IndependentAuditor"
    ),
    "curator_headers": build_user_headers(CURATOR_USER_ID, "CuratorialStaff"),
    # Elector-backed roles — these constants name no Elector row on purpose.
    "unknown_elector_headers": build_user_headers(UNKNOWN_ELECTOR_USER_ID, "Elector"),
    "unknown_screening_member_headers": build_user_headers(
        UNKNOWN_ELECTOR_USER_ID, "ScreeningCommitteeMember"
    ),
}


def make_admin_headers(user_id: str = ADMIN_USER_ID) -> dict:
    """Headers for ElectionAdministrator (opaque identity)."""
    return build_user_headers(user_id, "ElectionAdministrator")


def make_auditor_headers(user_id: str = AUDITOR_USER_ID) -> dict:
    """Headers for IndependentAuditor (opaque identity)."""
    return build_user_headers(user_id, "IndependentAuditor")


def make_curator_headers(user_id: str = CURATOR_USER_ID) -> dict:
    """Headers for CuratorialStaff (opaque identity)."""
    return build_user_headers(user_id, "CuratorialStaff")


def make_elector_headers(elector_id: str) -> dict:
    """Headers for Elector. Pass the real Elector row id as ``elector_id``."""
    return build_user_headers(elector_id, "Elector")


def make_screening_member_headers(elector_id: str) -> dict:
    """Headers for ScreeningCommitteeMember. Pass the real Elector row id."""
    return build_user_headers(elector_id, "ScreeningCommitteeMember")


ADMIN_HEADERS = TEST_USERS["admin_headers"]
AUDITOR_HEADERS = TEST_USERS["auditor_headers"]
CURATOR_HEADERS = TEST_USERS["curator_headers"]
