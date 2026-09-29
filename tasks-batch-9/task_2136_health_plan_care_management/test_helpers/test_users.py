"""Pre-built role headers for every role in the PRD (§2.1)."""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants.
#
# ProgramAdmin and UtilizationAnalyst carry opaque identifiers that the server
# never compares to any entity id, so these constants are always correct.
# CareManager, ClinicalReviewer and CommunityPartner are identity-backed: their
# X-User-ID must be a real entity id whenever the call is ownership-gated, so
# use the per-instance builders below for those.
TEST_USERS = {
    "program_admin_headers": build_user_headers("ops-admin-1", "ProgramAdmin"),
    "utilization_analyst_headers": build_user_headers("analyst-1", "UtilizationAnalyst"),
    "care_manager_headers": build_user_headers("cm-placeholder-1", "CareManager"),
    "clinical_reviewer_headers": build_user_headers(
        "reviewer-placeholder-1", "ClinicalReviewer"
    ),
    "community_partner_headers": build_user_headers(
        "partner-placeholder-1", "CommunityPartner"
    ),
}

PROGRAM_ADMIN = TEST_USERS["program_admin_headers"]
UTILIZATION_ANALYST = TEST_USERS["utilization_analyst_headers"]


def make_care_manager_headers(care_manager_id: str) -> dict:
    """Headers for a CareManager whose X-User-ID is the acting CareManager's id."""
    return build_user_headers(care_manager_id, "CareManager")


def make_clinical_reviewer_headers(care_manager_id: str) -> dict:
    """Headers for a ClinicalReviewer, whose X-User-ID is a CareManager id."""
    return build_user_headers(care_manager_id, "ClinicalReviewer")


def make_community_partner_headers(community_resource_id: str) -> dict:
    """Headers for a CommunityPartner, whose X-User-ID is a CommunityResource id."""
    return build_user_headers(community_resource_id, "CommunityPartner")


def make_program_admin_headers(user_id: str = "ops-admin-1") -> dict:
    return build_user_headers(user_id, "ProgramAdmin")


def make_utilization_analyst_headers(user_id: str = "analyst-1") -> dict:
    return build_user_headers(user_id, "UtilizationAnalyst")


# Headers carrying no identity at all, for the authentication check.
NO_AUTH_HEADERS = {"Content-Type": "application/json"}
