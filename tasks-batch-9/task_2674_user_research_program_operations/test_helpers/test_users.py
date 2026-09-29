"""Operator identities used by the suite.

Operator identity is opaque for all five roles: ``X-User-ID`` is never resolved
against a stored entity identifier, so these are plain shared constants.  The
three ownership comparisons and the publication segregation-of-duties check are
string comparisons against a previously recorded operator-id field, which is why
distinct ids per role matter here.
"""

from prd_bench_local_runner.testing import build_user_headers

from .types import Role

# Opaque operator identifiers.
STAKEHOLDER_USER_ID = "u_stake_1"
OTHER_STAKEHOLDER_USER_ID = "u_stake_2"
RESEARCHER_USER_ID = "u_res_1"
OTHER_RESEARCHER_USER_ID = "u_res_2"
RESEARCH_LEAD_USER_ID = "u_lead_1"
OTHER_RESEARCH_LEAD_USER_ID = "u_lead_2"
PRIVACY_OFFICER_USER_ID = "u_priv_1"
RESEARCH_OPS_ADMIN_USER_ID = "u_ops_1"

TEST_USERS = {
    "stakeholder": build_user_headers(STAKEHOLDER_USER_ID, Role.STAKEHOLDER.value),
    "other_stakeholder": build_user_headers(
        OTHER_STAKEHOLDER_USER_ID, Role.STAKEHOLDER.value
    ),
    "researcher": build_user_headers(RESEARCHER_USER_ID, Role.RESEARCHER.value),
    "other_researcher": build_user_headers(
        OTHER_RESEARCHER_USER_ID, Role.RESEARCHER.value
    ),
    "research_lead": build_user_headers(
        RESEARCH_LEAD_USER_ID, Role.RESEARCH_LEAD.value
    ),
    "other_research_lead": build_user_headers(
        OTHER_RESEARCH_LEAD_USER_ID, Role.RESEARCH_LEAD.value
    ),
    "privacy_officer": build_user_headers(
        PRIVACY_OFFICER_USER_ID, Role.PRIVACY_OFFICER.value
    ),
    "research_ops_admin": build_user_headers(
        RESEARCH_OPS_ADMIN_USER_ID, Role.RESEARCH_OPS_ADMIN.value
    ),
}

# Convenience aliases for the headers most fixtures reach for.
STAKEHOLDER_HEADERS = TEST_USERS["stakeholder"]
OTHER_STAKEHOLDER_HEADERS = TEST_USERS["other_stakeholder"]
RESEARCHER_HEADERS = TEST_USERS["researcher"]
OTHER_RESEARCHER_HEADERS = TEST_USERS["other_researcher"]
RESEARCH_LEAD_HEADERS = TEST_USERS["research_lead"]
OTHER_RESEARCH_LEAD_HEADERS = TEST_USERS["other_research_lead"]
PRIVACY_OFFICER_HEADERS = TEST_USERS["privacy_officer"]
RESEARCH_OPS_ADMIN_HEADERS = TEST_USERS["research_ops_admin"]

# Headers that name a role outside the five declared roles.
UNKNOWN_ROLE_HEADERS = build_user_headers("u_unknown_1", "Auditor")


def headers_for(role: str, user_id: str) -> dict:
    """Build headers for an arbitrary opaque operator id acting in ``role``."""
    return build_user_headers(user_id, role)
