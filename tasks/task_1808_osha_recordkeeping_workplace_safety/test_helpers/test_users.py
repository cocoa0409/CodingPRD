"""Pre-built role headers for every role in the PRD.

All four roles are opaque identities (PRD §2.1): `X-User-ID` is not tied to any
persisted entity. The shared constants below are the canonical form. The
per-instance builders exist for tests that must pin a specific operator id —
segregation-of-duties and lead-identity checks compare stored fields
(`prepared_by`, `completed_by`, `lead_supervisor_id`, ...) against the incoming
`X-User-ID`, so those tests must control the id exactly.
"""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — canonical for opaque roles.
TEST_USERS = {
    "platform_admin_headers": build_user_headers("test-admin-1",
                                                 "PlatformAdmin"),
    "safety_officer_headers": build_user_headers("test-officer-1",
                                                 "SafetyOfficer"),
    "recordkeeping_coordinator_headers": build_user_headers(
        "test-coordinator-1", "RecordkeepingCoordinator"),
    "investigating_supervisor_headers": build_user_headers(
        "test-supervisor-1", "InvestigatingSupervisor"),
}


def make_platform_admin_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "PlatformAdmin")


def make_safety_officer_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "SafetyOfficer")


def make_recordkeeping_coordinator_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "RecordkeepingCoordinator")


def make_investigating_supervisor_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "InvestigatingSupervisor")
