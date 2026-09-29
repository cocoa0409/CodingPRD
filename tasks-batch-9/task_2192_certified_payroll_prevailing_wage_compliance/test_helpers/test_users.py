"""Pre-built role headers for every role in the PRD.

PayrollPreparer and CertifyingOfficial are entity-backed: X-User-ID must be the
id of the acting ContractorStaff row. Use the per-instance builders for those two
roles whenever the call is ownership- or capability-checked. PortalAdmin,
AgencyComplianceOfficer and LaborStandardsAuditor are opaque operator identifiers.
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    # Opaque roles: the shared constant is the canonical form.
    "portal_admin_headers": build_user_headers("op-portal-admin-1", "PortalAdmin"),
    "agency_officer_headers": build_user_headers("op-agency-officer-1", "AgencyComplianceOfficer"),
    "agency_officer_2_headers": build_user_headers("op-agency-officer-2", "AgencyComplianceOfficer"),
    "auditor_headers": build_user_headers("op-auditor-1", "LaborStandardsAuditor"),
    "auditor_2_headers": build_user_headers("op-auditor-2", "LaborStandardsAuditor"),
    # Entity-backed roles: these constants are NOT real ContractorStaff ids, so they
    # are only valid for tests that expect ERR_STAFF_NOT_FOUND or that exercise a
    # check reached before staff resolution.
    "preparer_headers": build_user_headers("not-a-real-staff-row-preparer", "PayrollPreparer"),
    "certifier_headers": build_user_headers("not-a-real-staff-row-certifier", "CertifyingOfficial"),
}


def make_portal_admin_headers(user_id: str = "op-portal-admin-1") -> dict:
    """PortalAdmin (opaque operator identifier)."""
    return build_user_headers(user_id, "PortalAdmin")


def make_agency_officer_headers(user_id: str) -> dict:
    """AgencyComplianceOfficer (opaque, but recorded as accepted_by_user_id)."""
    return build_user_headers(user_id, "AgencyComplianceOfficer")


def make_auditor_headers(user_id: str) -> dict:
    """LaborStandardsAuditor (opaque, recorded as raised_by_user_id)."""
    return build_user_headers(user_id, "LaborStandardsAuditor")


def make_preparer_headers(staff_id: str) -> dict:
    """PayrollPreparer: pass the acting ContractorStaff row's id as X-User-ID."""
    return build_user_headers(staff_id, "PayrollPreparer")


def make_certifier_headers(staff_id: str) -> dict:
    """CertifyingOfficial: pass the acting ContractorStaff row's id as X-User-ID."""
    return build_user_headers(staff_id, "CertifyingOfficial")


ALL_ROLE_NAMES = [
    "PortalAdmin",
    "PayrollPreparer",
    "CertifyingOfficial",
    "AgencyComplianceOfficer",
    "LaborStandardsAuditor",
]
