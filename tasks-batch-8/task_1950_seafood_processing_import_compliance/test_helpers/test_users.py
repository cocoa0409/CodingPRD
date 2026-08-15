"""Pre-built role headers for every role in the PRD.

Every role in this PRD is `opaque` (X-User-ID is an operator identifier, never
compared against an entity id), so the shared constants are canonical.
Per-instance builders are still provided so tests can pin a specific operator
identity (used by segregation-of-duties and opened_by/closed_by assertions).
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    "import_coordinator_headers": build_user_headers(
        "test-import-coordinator-1", "ImportCoordinator"),
    "receiving_inspector_headers": build_user_headers(
        "test-receiving-inspector-1", "ReceivingInspector"),
    "qa_tech_headers": build_user_headers(
        "test-qa-tech-1", "QualityAssuranceTech"),
    "processing_supervisor_headers": build_user_headers(
        "test-processing-supervisor-1", "ProcessingSupervisor"),
    "compliance_manager_headers": build_user_headers(
        "test-compliance-manager-1", "ComplianceManager"),
    "platform_admin_headers": build_user_headers(
        "test-platform-admin-1", "PlatformAdmin"),
}


def make_import_coordinator_headers(user_id: str) -> dict:
    """ImportCoordinator headers pinned to a specific operator id."""
    return build_user_headers(user_id, "ImportCoordinator")


def make_receiving_inspector_headers(user_id: str) -> dict:
    """ReceivingInspector headers pinned to a specific operator id."""
    return build_user_headers(user_id, "ReceivingInspector")


def make_qa_tech_headers(user_id: str) -> dict:
    """QualityAssuranceTech headers pinned to a specific operator id."""
    return build_user_headers(user_id, "QualityAssuranceTech")


def make_processing_supervisor_headers(user_id: str) -> dict:
    """ProcessingSupervisor headers pinned to a specific operator id."""
    return build_user_headers(user_id, "ProcessingSupervisor")


def make_compliance_manager_headers(user_id: str) -> dict:
    """ComplianceManager headers pinned to a specific operator id.

    Use when a test asserts CorrectiveAction.opened_by / closed_by or the
    segregation-of-duties rule (resolver must differ from opened_by).
    """
    return build_user_headers(user_id, "ComplianceManager")


def make_platform_admin_headers(user_id: str) -> dict:
    """PlatformAdmin headers pinned to a specific operator id."""
    return build_user_headers(user_id, "PlatformAdmin")
