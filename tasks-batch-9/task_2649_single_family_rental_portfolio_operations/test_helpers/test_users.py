"""Canonical acting principals for the Single-Family Rental Portfolio API.

PRD SS2.1: "Every request carries two headers. ``X-User-ID`` identifies the acting
principal and ``X-User-Role`` names the capacity in which the principal is acting."

Ten of the twelve roles carry an *opaque* ``X-User-ID`` that is never compared with a
stored row, so a fixed identifier per role is safe and keeps segregation-of-duties
comparisons stable across a test.  The two entity-backed roles (``Vendor`` and
``Prospect``) must be addressed with the identifier of the row they act as, so they are
built on demand by :func:`make_vendor_headers` and :func:`make_prospect_headers`.
"""

from prd_bench_local_runner.testing import build_user_headers

# --- opaque-identity roles (PRD SS2.1) ------------------------------------------------
SYSTEM_USER_ID = "system-1"
PORTFOLIO_ADMIN_USER_ID = "admin-1"
ACQUISITION_ANALYST_USER_ID = "analyst-1"
ACQUISITION_ANALYST_2_USER_ID = "analyst-2"
INVESTMENT_COMMITTEE_USER_ID = "ic-1"
INVESTMENT_COMMITTEE_2_USER_ID = "ic-2"
OPERATIONS_MANAGER_USER_ID = "ops-1"
VENDOR_MANAGER_USER_ID = "vm-1"
LEASING_AGENT_USER_ID = "agent-1"
COMPLIANCE_OFFICER_USER_ID = "co-1"
COMPLIANCE_OFFICER_2_USER_ID = "co-2"
REGIONAL_DIRECTOR_USER_ID = "rd-1"
ANONYMOUS_USER_ID = "anon-device-1"

ROLE_SYSTEM = "System"
ROLE_PORTFOLIO_ADMIN = "PortfolioAdmin"
ROLE_ACQUISITION_ANALYST = "AcquisitionAnalyst"
ROLE_INVESTMENT_COMMITTEE = "InvestmentCommittee"
ROLE_OPERATIONS_MANAGER = "OperationsManager"
ROLE_VENDOR_MANAGER = "VendorManager"
ROLE_LEASING_AGENT = "LeasingAgent"
ROLE_COMPLIANCE_OFFICER = "ComplianceOfficer"
ROLE_REGIONAL_DIRECTOR = "RegionalDirector"
ROLE_ANONYMOUS = "Anonymous"
ROLE_VENDOR = "Vendor"
ROLE_PROSPECT = "Prospect"

TEST_USERS = {
    "system": build_user_headers(SYSTEM_USER_ID, ROLE_SYSTEM),
    "portfolio_admin": build_user_headers(PORTFOLIO_ADMIN_USER_ID, ROLE_PORTFOLIO_ADMIN),
    "acquisition_analyst": build_user_headers(
        ACQUISITION_ANALYST_USER_ID, ROLE_ACQUISITION_ANALYST
    ),
    "acquisition_analyst_2": build_user_headers(
        ACQUISITION_ANALYST_2_USER_ID, ROLE_ACQUISITION_ANALYST
    ),
    "investment_committee": build_user_headers(
        INVESTMENT_COMMITTEE_USER_ID, ROLE_INVESTMENT_COMMITTEE
    ),
    "investment_committee_2": build_user_headers(
        INVESTMENT_COMMITTEE_2_USER_ID, ROLE_INVESTMENT_COMMITTEE
    ),
    "operations_manager": build_user_headers(
        OPERATIONS_MANAGER_USER_ID, ROLE_OPERATIONS_MANAGER
    ),
    "vendor_manager": build_user_headers(VENDOR_MANAGER_USER_ID, ROLE_VENDOR_MANAGER),
    "leasing_agent": build_user_headers(LEASING_AGENT_USER_ID, ROLE_LEASING_AGENT),
    "compliance_officer": build_user_headers(
        COMPLIANCE_OFFICER_USER_ID, ROLE_COMPLIANCE_OFFICER
    ),
    "compliance_officer_2": build_user_headers(
        COMPLIANCE_OFFICER_2_USER_ID, ROLE_COMPLIANCE_OFFICER
    ),
    "regional_director": build_user_headers(
        REGIONAL_DIRECTOR_USER_ID, ROLE_REGIONAL_DIRECTOR
    ),
    "anonymous": build_user_headers(ANONYMOUS_USER_ID, ROLE_ANONYMOUS),
}


def make_vendor_headers(vendor_id):
    """Headers for the ``Vendor`` role acting as the vendor row ``vendor_id``.

    PRD SS2.1: "When ``X-User-Role`` is ``Vendor``, ``X-User-ID`` is the ``id`` of the
    acting vendor row."
    """
    return build_user_headers(vendor_id, ROLE_VENDOR)


def make_prospect_headers(prospect_id):
    """Headers for the ``Prospect`` role acting as the prospect row ``prospect_id``.

    PRD SS2.1: "When ``X-User-Role`` is ``Prospect``, ``X-User-ID`` is the ``id`` of the
    acting prospect row."
    """
    return build_user_headers(prospect_id, ROLE_PROSPECT)


def make_headers(user_id, role):
    """Headers for an arbitrary ``(user_id, role)`` pair."""
    return build_user_headers(user_id, role)


def headers_without_user_id(role):
    """Headers carrying only ``X-User-Role`` -- used to exercise ``ERR_UNAUTHENTICATED``
    and the clock setter's documented exemption from the ``X-User-ID`` requirement."""
    return {"X-User-Role": role, "Content-Type": "application/json"}
