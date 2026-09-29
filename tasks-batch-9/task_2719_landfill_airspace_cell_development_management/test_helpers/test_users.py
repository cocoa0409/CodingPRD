"""Pre-built role headers for every role in the PRD.

Six of the eight roles carry an opaque ``X-User-ID`` that the server never
compares to any entity's ``id``, so a shared constant is the canonical form for
them. ``SiteOperator`` and ``ScaleOperator`` are different: their ``X-User-ID``
is the ``id`` of the acting ``Landfill``, so every ownership-gated write must be
issued with headers built from the real landfill id via the builders below.
"""
from prd_bench_local_runner.testing import build_user_headers

PLATFORM_ADMIN_USER_ID = "platform-admin-1"
CQA_ENGINEER_USER_ID = "cqa-engineer-2"
SURVEYOR_USER_ID = "surveyor-1"
ENVIRONMENTAL_MANAGER_USER_ID = "env-manager-1"
REGULATORY_AGENCY_USER_ID = "agency-inspector-1"
FINANCE_FILER_USER_ID = "finance-filer-1"
FINANCE_CERTIFIER_USER_ID = "finance-certifier-2"

# A second CQA engineer, for tests that need two distinct reviewers.
CQA_ENGINEER_ALT_USER_ID = "cqa-engineer-3"
# A second agency inspector.
REGULATORY_AGENCY_ALT_USER_ID = "agency-inspector-2"

TEST_USERS = {
    "platform_admin_headers": build_user_headers(PLATFORM_ADMIN_USER_ID, "PlatformAdmin"),
    "cqa_engineer_headers": build_user_headers(CQA_ENGINEER_USER_ID, "CqaEngineer"),
    "cqa_engineer_alt_headers": build_user_headers(CQA_ENGINEER_ALT_USER_ID, "CqaEngineer"),
    "surveyor_headers": build_user_headers(SURVEYOR_USER_ID, "SurveyorOfRecord"),
    "environmental_manager_headers": build_user_headers(
        ENVIRONMENTAL_MANAGER_USER_ID, "EnvironmentalManager"
    ),
    "regulatory_agency_headers": build_user_headers(
        REGULATORY_AGENCY_USER_ID, "RegulatoryAgency"
    ),
    "finance_filer_headers": build_user_headers(FINANCE_FILER_USER_ID, "FinanceOfficer"),
    "finance_certifier_headers": build_user_headers(
        FINANCE_CERTIFIER_USER_ID, "FinanceOfficer"
    ),
    # Fallbacks for the two entity-backed roles. Safe ONLY for reads and for
    # requests refused before the site-scope check; never for a scoped write.
    "site_operator_headers": build_user_headers("site-operator-unowned", "SiteOperator"),
    "scale_operator_headers": build_user_headers("scale-operator-unowned", "ScaleOperator"),
}


def make_site_operator_headers(user_id: str) -> dict:
    """Headers for a SiteOperator. ``user_id`` must be the acting Landfill's id."""
    return build_user_headers(user_id, "SiteOperator")


def make_scale_operator_headers(user_id: str) -> dict:
    """Headers for a ScaleOperator. ``user_id`` must be the acting Landfill's id."""
    return build_user_headers(user_id, "ScaleOperator")


def make_cqa_engineer_headers(user_id: str) -> dict:
    """Headers for a CqaEngineer carrying an explicit operator identifier."""
    return build_user_headers(user_id, "CqaEngineer")


def make_finance_officer_headers(user_id: str) -> dict:
    """Headers for a FinanceOfficer carrying an explicit operator identifier."""
    return build_user_headers(user_id, "FinanceOfficer")


def make_regulatory_agency_headers(user_id: str) -> dict:
    """Headers for a RegulatoryAgency principal."""
    return build_user_headers(user_id, "RegulatoryAgency")


def make_environmental_manager_headers(user_id: str) -> dict:
    """Headers for an EnvironmentalManager."""
    return build_user_headers(user_id, "EnvironmentalManager")


def make_surveyor_headers(user_id: str) -> dict:
    """Headers for a SurveyorOfRecord."""
    return build_user_headers(user_id, "SurveyorOfRecord")


def make_platform_admin_headers(user_id: str) -> dict:
    """Headers for a PlatformAdmin."""
    return build_user_headers(user_id, "PlatformAdmin")


def headers_without_user_id(role: str) -> dict:
    """Well-formed headers with X-User-ID deliberately absent."""
    return {"X-User-Role": role, "Content-Type": "application/json"}


def headers_without_role(user_id: str) -> dict:
    """Well-formed headers with X-User-Role deliberately absent."""
    return {"X-User-ID": user_id, "Content-Type": "application/json"}


def headers_without_auth() -> dict:
    """Neither X-User-ID nor X-User-Role is present."""
    return {"Content-Type": "application/json"}
