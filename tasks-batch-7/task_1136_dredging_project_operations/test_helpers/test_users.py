"""Pre-built role headers for every role in the PRD (§2.1).

All five role identities are opaque: the server never compares X-User-ID
against an entity id — only against the recorded *_by_user_id fields for
segregation of duties (§2.8). The shared constants below use the canonical
per-role operator ids used throughout the suite; the make_*_headers builders
exist for tests that must thread a specific id (e.g. an OwnerEngineer call
carrying the survey submitter's id to exercise segregation).
"""
from prd_bench_local_runner.testing import build_user_headers

# Canonical operator ids — referenced by name in test docstrings.
OWNER_ID = "eng-1"
CONTRACTOR_ID = "ops-1"
SURVEYOR_ID = "surv-1"
MONITOR_ID = "mon-1"
SITE_OPERATOR_ID = "site-1"

TEST_USERS = {
    "owner_headers": build_user_headers(OWNER_ID, "OwnerEngineer"),
    "contractor_headers": build_user_headers(CONTRACTOR_ID, "ContractorOps"),
    "surveyor_headers": build_user_headers(SURVEYOR_ID, "SurveyParty"),
    "monitor_headers": build_user_headers(MONITOR_ID, "EnvironmentalMonitor"),
    "site_operator_headers": build_user_headers(SITE_OPERATOR_ID, "SiteOperator"),
}


def make_owner_headers(user_id: str) -> dict:
    """OwnerEngineer headers carrying a specific operator id (SoD tests)."""
    return build_user_headers(user_id, "OwnerEngineer")


def make_contractor_headers(user_id: str) -> dict:
    """ContractorOps headers carrying a specific operator id (SoD tests)."""
    return build_user_headers(user_id, "ContractorOps")


def make_surveyor_headers(user_id: str) -> dict:
    """SurveyParty headers carrying a specific operator id (SoD tests)."""
    return build_user_headers(user_id, "SurveyParty")


def make_monitor_headers(user_id: str) -> dict:
    """EnvironmentalMonitor headers carrying a specific operator id."""
    return build_user_headers(user_id, "EnvironmentalMonitor")


def make_site_operator_headers(user_id: str) -> dict:
    """SiteOperator headers carrying a specific operator id (SoD tests)."""
    return build_user_headers(user_id, "SiteOperator")
