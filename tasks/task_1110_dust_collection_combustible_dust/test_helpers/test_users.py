"""Pre-built role headers for every role in the PRD (§2.1).

All eight roles are opaque: X-User-ID is an operator identifier not tied to any
persisted entity. Workflows do compare X-User-ID against recorded attribution
fields (author_id, approver_id, auditor_id, issuer_id, performer_id,
investigation_lead_id, owner_id), so callers that must match a recorded
identifier use the per-instance make_*_headers(user_id) builders below.
"""
from prd_bench_local_runner.testing import build_user_headers

# Canonical operator identifiers used across the suite.
ADMIN_USER_ID = "admin-1"
MANAGER_USER_ID = "mgr-1"
ENGINEER_USER_ID = "eng-1"
SAFETY_USER_ID = "sm-1"
PERFORMER_USER_ID = "hp-1"
AUDITOR_USER_ID = "aud-1"
INSPECTOR_USER_ID = "insp-1"
INVESTIGATOR_USER_ID = "inv-1"

TEST_USERS = {
    "platform_admin_headers": build_user_headers(ADMIN_USER_ID, "PlatformAdmin"),
    "compliance_manager_headers": build_user_headers(MANAGER_USER_ID, "ComplianceManager"),
    "compliance_engineer_headers": build_user_headers(ENGINEER_USER_ID, "ComplianceEngineer"),
    "safety_manager_headers": build_user_headers(SAFETY_USER_ID, "SafetyManager"),
    "hot_work_performer_headers": build_user_headers(PERFORMER_USER_ID, "HotWorkPerformer"),
    "housekeeping_auditor_headers": build_user_headers(AUDITOR_USER_ID, "HousekeepingAuditor"),
    "inspector_user_headers": build_user_headers(INSPECTOR_USER_ID, "InspectorUser"),
    "incident_investigator_headers": build_user_headers(INVESTIGATOR_USER_ID, "IncidentInvestigator"),
}


def make_platform_admin_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "PlatformAdmin")


def make_compliance_manager_headers(user_id: str) -> dict:
    """ComplianceManager headers with a specific X-User-ID (e.g. DHA approver)."""
    return build_user_headers(user_id, "ComplianceManager")


def make_compliance_engineer_headers(user_id: str) -> dict:
    """ComplianceEngineer headers with a specific X-User-ID (e.g. DHA author)."""
    return build_user_headers(user_id, "ComplianceEngineer")


def make_safety_manager_headers(user_id: str) -> dict:
    """SafetyManager headers with a specific X-User-ID (e.g. permit issuer)."""
    return build_user_headers(user_id, "SafetyManager")


def make_hot_work_performer_headers(user_id: str) -> dict:
    """HotWorkPerformer headers with a specific X-User-ID (must equal performer_id
    when starting or closing a permit)."""
    return build_user_headers(user_id, "HotWorkPerformer")


def make_housekeeping_auditor_headers(user_id: str) -> dict:
    """HousekeepingAuditor headers with a specific X-User-ID (must equal
    auditor_id when recording or skipping an audit)."""
    return build_user_headers(user_id, "HousekeepingAuditor")


def make_inspector_user_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "InspectorUser")


def make_incident_investigator_headers(user_id: str) -> dict:
    """IncidentInvestigator headers with a specific X-User-ID (must equal
    investigation_lead_id / owner_id for investigation and CAPA actions)."""
    return build_user_headers(user_id, "IncidentInvestigator")
