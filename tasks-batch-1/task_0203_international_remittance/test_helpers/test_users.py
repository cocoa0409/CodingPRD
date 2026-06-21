"""Pre-built role headers for every role in the PRD.

All four roles are opaque operator identities — X-User-ID is never compared
against any stored entity's id (PRD 2.1). Ownership is established through
foreign-key fields in request bodies, not by matching the caller. Shared
constants are therefore the canonical form for every role; no per-instance
entity-backed builders are required.
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    "platform_admin_headers": build_user_headers("test-admin-1", "PlatformAdmin"),
    "remittance_agent_headers": build_user_headers("test-agent-1", "RemittanceAgent"),
    "compliance_officer_headers": build_user_headers("test-officer-1", "ComplianceOfficer"),
    "payout_operator_headers": build_user_headers("test-operator-1", "PayoutOperator"),
}
