"""Pre-built role headers for every role in the PRD.

All six roles use opaque X-User-ID identifiers (the PRD never compares
X-User-ID to any entity id), so shared constants are the canonical form.
Per-call builders exist only to let segregation-of-duties tests control the
X-User-ID value explicitly.
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    "orchard_manager_headers": build_user_headers("test-orchard-mgr-1", "OrchardManager"),
    "cellar_lead_headers": build_user_headers("test-cellar-lead-1", "CellarLead"),
    "compliance_officer_headers": build_user_headers("test-compliance-1", "ComplianceOfficer"),
    "packaging_operator_headers": build_user_headers("test-packaging-1", "PackagingOperator"),
    "sales_rep_headers": build_user_headers("test-sales-rep-1", "SalesRep"),
    "platform_admin_headers": build_user_headers("test-platform-admin-1", "PlatformAdmin"),
}


def make_orchard_manager_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "OrchardManager")


def make_cellar_lead_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "CellarLead")


def make_compliance_officer_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "ComplianceOfficer")


def make_packaging_operator_headers(user_id: str) -> dict:
    """PackagingOperator with an explicit X-User-ID — needed to exercise the
    segregation-of-duties rule comparing the run's scheduler to its completer."""
    return build_user_headers(user_id, "PackagingOperator")


def make_sales_rep_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "SalesRep")


def make_platform_admin_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "PlatformAdmin")
