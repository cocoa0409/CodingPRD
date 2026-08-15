"""Pre-built role headers for every role in the PRD.

Every role in this API uses an opaque X-User-ID (not tied to any persisted
entity), so the shared constants are the canonical form. The per-instance
builders exist for tests that must thread a specific X-User-ID through a
submit/decide pair (e.g., the self-approval guard on reviews).
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    "coordinator_headers": build_user_headers("test-coordinator-1", "DistrictSafetyCoordinator"),
    "officer_headers": build_user_headers("test-officer-1", "SchoolSafetyOfficer"),
    "principal_headers": build_user_headers("test-principal-1", "Principal"),
    "responder_headers": build_user_headers("test-responder-1", "FirstResponder"),
    "auditor_headers": build_user_headers("test-auditor-1", "StateAuditor"),
}


def make_coordinator_headers(user_id: str) -> dict:
    """DistrictSafetyCoordinator headers with a specific X-User-ID."""
    return build_user_headers(user_id, "DistrictSafetyCoordinator")


def make_officer_headers(user_id: str) -> dict:
    """SchoolSafetyOfficer headers with a specific X-User-ID."""
    return build_user_headers(user_id, "SchoolSafetyOfficer")


def make_principal_headers(user_id: str) -> dict:
    """Principal headers with a specific X-User-ID."""
    return build_user_headers(user_id, "Principal")


def make_responder_headers(user_id: str) -> dict:
    """FirstResponder headers with a specific X-User-ID."""
    return build_user_headers(user_id, "FirstResponder")


def make_auditor_headers(user_id: str) -> dict:
    """StateAuditor headers with a specific X-User-ID."""
    return build_user_headers(user_id, "StateAuditor")


__all__ = [
    "TEST_USERS",
    "make_coordinator_headers", "make_officer_headers", "make_principal_headers",
    "make_responder_headers", "make_auditor_headers",
]
