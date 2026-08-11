"""Pre-built role headers for every role in the PRD (§2.1).

All five operational roles use opaque `X-User-ID` values: per PRD §2.1 the
identifier "is an opaque operator identifier that is not tied to any persisted
entity", so shared constants are the canonical form for every role here.
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    "contractor_scheduler_headers": build_user_headers(
        "test-contractor-scheduler-1", "ContractorScheduler"
    ),
    "project_controls_engineer_headers": build_user_headers(
        "test-project-controls-engineer-1", "ProjectControlsEngineer"
    ),
    "owner_representative_headers": build_user_headers(
        "test-owner-representative-1", "OwnerRepresentative"
    ),
    "claims_consultant_headers": build_user_headers(
        "test-claims-consultant-1", "ClaimsConsultant"
    ),
    "system_admin_headers": build_user_headers("test-system-admin-1", "SystemAdmin"),
}

# A header set with no identity headers at all (anonymous caller).
ANONYMOUS_HEADERS = {"Content-Type": "application/json"}
