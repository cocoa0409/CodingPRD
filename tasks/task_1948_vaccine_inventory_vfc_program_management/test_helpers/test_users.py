"""Pre-built role headers for every role in the PRD (§2.1).

All three roles are opaque operator identities: `X-User-ID` is recorded for
attribution only and is never compared against any resource id, so the shared
constants below are the canonical form for every call.
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    "vaccine_manager_headers": build_user_headers("test-vm-1", "VaccineManager"),
    "state_program_officer_headers": build_user_headers("test-spo-1", "StateProgramOfficer"),
    "compliance_auditor_headers": build_user_headers("test-ca-1", "ComplianceAuditor"),
}

# Requests without the user-context headers are rejected (PRD §2.1); tests
# exercising that rule pass this empty mapping instead of role headers.
NO_AUTH_HEADERS: dict = {}
