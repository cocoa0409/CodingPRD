"""Pre-built role headers for every role in the PRD (§2.1).

All nine roles use opaque X-User-ID identifiers that are never compared to any
resource id, so shared constants are the canonical form. Distinct principal
builders are still provided because the approval quorum's segregation-of-duties
rule compares X-User-ID values across recorded approvals (PRD §3.5).
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    "platform_admin_headers": build_user_headers("admin-001", "PlatformAdmin"),
    "engagement_manager_headers": build_user_headers("mgr-001", "EngagementManager"),
    "classification_analyst_headers": build_user_headers("analyst-001", "ClassificationAnalyst"),
    "hr_approver_headers": build_user_headers("hr-001", "HRApprover"),
    "legal_approver_headers": build_user_headers("legal-001", "LegalApprover"),
    "compliance_board_member_headers": build_user_headers("board-001", "ComplianceBoardMember"),
    "compliance_officer_headers": build_user_headers("officer-001", "ComplianceOfficer"),
    "tax_reporting_specialist_headers": build_user_headers("tax-001", "TaxReportingSpecialist"),
    "agency_liaison_headers": build_user_headers("liaison-001", "AgencyLiaison"),
}

# Distinct principals for the fixed quorum steps (PRD §3.5).
APPROVER_USER_IDS = {
    "HRApprover": "hr-001",
    "LegalApprover": "legal-001",
    "ComplianceBoardMember": "board-001",
}


def make_platform_admin_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "PlatformAdmin")


def make_engagement_manager_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "EngagementManager")


def make_classification_analyst_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "ClassificationAnalyst")


def make_hr_approver_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "HRApprover")


def make_legal_approver_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "LegalApprover")


def make_compliance_board_member_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "ComplianceBoardMember")


def make_compliance_officer_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "ComplianceOfficer")


def make_tax_reporting_specialist_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "TaxReportingSpecialist")


def make_agency_liaison_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "AgencyLiaison")
