"""Pre-built role headers for every role in the PRD (§2.1).

All four roles use opaque identity — X-User-ID is an opaque operator identifier
that the server never compares to any entity's id (PRD §2.1). Therefore only
shared-constant header entries are needed; there are no entity_backed
per-instance builders.

The one place X-User-ID matters is segregation of duties (PRD §2.10): the
analyst who submits a credit application stamps their X-User-ID onto
submitted_by_user_id, and approval/decline require the acting analyst's
X-User-ID to differ. The two analyst identifiers below are deliberately
distinct so a submit-by-ANALYST_1 followed by an approve-by-ANALYST_2 passes
the rule, while an approve-by-ANALYST_1 trips it.
"""
from prd_bench_local_runner.testing import build_user_headers


# Canonical operator identifiers for the segregation-of-duties rule.
ANALYST_1_USER_ID = "analyst-1"
ANALYST_2_USER_ID = "analyst-2"

TEST_USERS = {
    "credit_analyst_headers": build_user_headers(ANALYST_1_USER_ID, "CreditAnalyst"),
    "credit_analyst_2_headers": build_user_headers(ANALYST_2_USER_ID, "CreditAnalyst"),
    "funding_officer_headers": build_user_headers("officer-1", "FundingOfficer"),
    "servicer_headers": build_user_headers("servicer-1", "Servicer"),
    "asset_manager_headers": build_user_headers("asset-1", "AssetManager"),
}
