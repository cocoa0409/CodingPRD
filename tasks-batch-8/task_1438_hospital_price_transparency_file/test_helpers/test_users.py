"""Pre-built role headers for every role in the PRD.

All five roles are opaque: X-User-ID is an operator identifier never compared
to any entity id (PRD section 2.1). Shared constants are therefore the
canonical form; the make_*_headers builders exist so the segregation-of-duties
correction tests can pin a specific X-User-ID per call.
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    "platform_admin_headers": build_user_headers("admin-1", "PlatformAdmin"),
    "contract_manager_headers": build_user_headers("cm-1", "ContractManager"),
    "transparency_officer_headers": build_user_headers(
        "to-1", "TransparencyOfficer"),
    "compliance_auditor_headers": build_user_headers(
        "ca-1", "ComplianceAuditor"),
    "consumer_headers": build_user_headers("consumer-1", "Consumer"),
}


def make_admin_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "PlatformAdmin")


def make_manager_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "ContractManager")


def make_officer_headers(user_id: str) -> dict:
    """TransparencyOfficer headers pinned to a specific X-User-ID — required
    for segregation-of-duties steps in the correction workflow."""
    return build_user_headers(user_id, "TransparencyOfficer")


def make_auditor_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "ComplianceAuditor")


def make_consumer_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "Consumer")
