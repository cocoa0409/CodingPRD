"""Pre-built role headers for every role in the PRD.

Three roles have opaque identity, so a shared constant id is the canonical form
for them. RightsHolderUser is identified by the RightsHolder id it acts for, so
every ownership-gated call MUST build its headers with
``make_rights_holder_user_headers(holder["id"])``.
"""

from prd_bench_local_runner.testing import build_user_headers

# ─── Distinct operator identities ─────────────────────
# Some operations require two different human operators (the analyst who
# attached a sub-perfect provisional match may not approve the claim it enables;
# the admin who recorded a finding may not settle it).

ADMIN_USER_ID = "test-admin-1"
ADMIN_SETTLE_USER_ID = "admin-settle-9"
ANALYST_USER_ID = "test-analyst-1"
ANALYST_FUZZY_MATCHER_USER_ID = "analyst-fuzzy-1"
ANALYST_REVIEWER_USER_ID = "analyst-review-2"
REGULATOR_USER_ID = "test-regulator-1"
HOLDER_PLACEHOLDER_USER_ID = "test-holder-1"


TEST_USERS = {
    # opaque roles: the shared constant is the canonical form.
    "royalty_admin_headers": build_user_headers(ADMIN_USER_ID, "RoyaltyAdmin"),
    "rights_ops_analyst_headers": build_user_headers(ANALYST_USER_ID, "RightsOpsAnalyst"),
    "regulatory_officer_headers": build_user_headers(REGULATOR_USER_ID, "RegulatoryOfficer"),
    # entity-backed role: fallback for tests that never reach an ownership check
    # (bad payloads, unknown ids, role refusals).
    "rights_holder_user_headers": build_user_headers(
        HOLDER_PLACEHOLDER_USER_ID, "RightsHolderUser"
    ),
    # Named operator variants used by segregation-of-duties flows.
    "fuzzy_matcher_headers": build_user_headers(
        ANALYST_FUZZY_MATCHER_USER_ID, "RightsOpsAnalyst"
    ),
    "reviewer_headers": build_user_headers(ANALYST_REVIEWER_USER_ID, "RightsOpsAnalyst"),
    "settling_admin_headers": build_user_headers(ADMIN_SETTLE_USER_ID, "RoyaltyAdmin"),
}


def make_rights_holder_user_headers(user_id: str) -> dict:
    """For RightsHolderUser (identified by a RightsHolder id).

    Pass the actual RightsHolder.id whenever the call is ownership-gated:
    filing or disputing a claim, supplying evidence, opening an audit
    engagement or asserting a finding.
    """
    return build_user_headers(user_id, "RightsHolderUser")


def make_royalty_admin_headers(user_id: str) -> dict:
    """RoyaltyAdmin headers for a named operator (e.g. the settling admin)."""
    return build_user_headers(user_id, "RoyaltyAdmin")


def make_rights_ops_analyst_headers(user_id: str) -> dict:
    """RightsOpsAnalyst headers for a named operator (matcher vs reviewer)."""
    return build_user_headers(user_id, "RightsOpsAnalyst")


def make_regulatory_officer_headers(user_id: str) -> dict:
    """RegulatoryOfficer headers for a named operator."""
    return build_user_headers(user_id, "RegulatoryOfficer")
