"""Pre-built identity headers for every role the PRD declares.

The five operator roles carry an opaque X-User-ID. A TenantPortalUser's
X-User-ID is the acting Tenant's own id, so ownership-gated calls MUST use
make_tenant_portal_headers(tenant["id"]).
"""
from typing import Dict

from prd_bench_local_runner.testing import build_user_headers

from .constants import (
    CERTIFYING_OFFICER_USER_ID,
    SECOND_OFFICER_USER_ID,
    SUBMITTING_AGENT_USER_ID,
)

# Shared constants for the five opaque operator roles. The leasing-agent and
# compliance-officer constants deliberately carry the two distinct user ids the
# submit-then-certify separation is measured on.
TEST_USERS: Dict[str, Dict[str, str]] = {
    "portfolio_admin_headers": build_user_headers("admin-001", "PortfolioAdmin"),
    "leasing_agent_headers": build_user_headers(SUBMITTING_AGENT_USER_ID, "LeasingAgent"),
    "compliance_officer_headers": build_user_headers(CERTIFYING_OFFICER_USER_ID, "ComplianceOfficer"),
    "second_compliance_officer_headers": build_user_headers(SECOND_OFFICER_USER_ID, "ComplianceOfficer"),
    "property_manager_headers": build_user_headers("manager-001", "PropertyManager"),
    "facilities_engineer_headers": build_user_headers("engineer-001", "FacilitiesEngineer"),
    # Fallback only — never use for an ownership-gated tenant-portal call.
    "tenant_portal_user_headers": build_user_headers("tenant-unknown", "TenantPortalUser"),
}

PORTFOLIO_ADMIN = TEST_USERS["portfolio_admin_headers"]
LEASING_AGENT = TEST_USERS["leasing_agent_headers"]
COMPLIANCE_OFFICER = TEST_USERS["compliance_officer_headers"]
SECOND_COMPLIANCE_OFFICER = TEST_USERS["second_compliance_officer_headers"]
PROPERTY_MANAGER = TEST_USERS["property_manager_headers"]
FACILITIES_ENGINEER = TEST_USERS["facilities_engineer_headers"]


def make_portfolio_admin_headers(user_id: str = "admin-001") -> Dict[str, str]:
    return build_user_headers(user_id, "PortfolioAdmin")


def make_leasing_agent_headers(user_id: str = SUBMITTING_AGENT_USER_ID) -> Dict[str, str]:
    return build_user_headers(user_id, "LeasingAgent")


def make_compliance_officer_headers(user_id: str = CERTIFYING_OFFICER_USER_ID) -> Dict[str, str]:
    return build_user_headers(user_id, "ComplianceOfficer")


def make_property_manager_headers(user_id: str = "manager-001") -> Dict[str, str]:
    return build_user_headers(user_id, "PropertyManager")


def make_facilities_engineer_headers(user_id: str = "engineer-001") -> Dict[str, str]:
    return build_user_headers(user_id, "FacilitiesEngineer")


def make_tenant_portal_headers(tenant_id: str) -> Dict[str, str]:
    """A TenantPortalUser's X-User-ID is the acting Tenant's id."""
    return build_user_headers(tenant_id, "TenantPortalUser")


ALL_ROLE_NAMES = [
    "PortfolioAdmin",
    "LeasingAgent",
    "ComplianceOfficer",
    "PropertyManager",
    "FacilitiesEngineer",
    "TenantPortalUser",
]
