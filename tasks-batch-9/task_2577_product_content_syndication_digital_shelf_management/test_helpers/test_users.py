"""Pre-built role headers for the seven roles named in PRD §2.1.

`RetailerIntegration` is the retailer's own integration principal: its
`X-User-ID` is the `id` of the acting `Retailer`, so every ownership-gated call
made in that capacity MUST use `make_retailer_integration_headers(retailer_id)`
with the real retailer id.  The other six roles carry opaque operator
identifiers that the server never compares to an entity id.
"""
from prd_bench_local_runner.testing import build_user_headers

# Opaque operator identifiers used consistently across the suite.
ADMIN_USER_ID = "admin_1"
AUTHOR_USER_ID = "author_1"
LEGAL_USER_ID = "legal_1"
BRAND_USER_ID = "brand_1"
OPERATOR_USER_ID = "operator_1"
ACCOUNT_TEAM_USER_ID = "acct_team_1"

TEST_USERS = {
    # opaque roles — the shared constant is the canonical form
    "shelf_admin_headers": build_user_headers(ADMIN_USER_ID, "ShelfAdmin"),
    "content_author_headers": build_user_headers(AUTHOR_USER_ID, "ContentAuthor"),
    "legal_reviewer_headers": build_user_headers(LEGAL_USER_ID, "LegalReviewer"),
    "brand_approver_headers": build_user_headers(BRAND_USER_ID, "BrandGovernanceApprover"),
    "syndication_operator_headers": build_user_headers(OPERATOR_USER_ID, "SyndicationOperator"),
    "account_team_headers": build_user_headers(ACCOUNT_TEAM_USER_ID, "AccountTeamLead"),
    # entity-backed role — fallback for calls that are not ownership-gated only
    "retailer_integration_headers": build_user_headers(
        "00000000-0000-4000-8000-000000000000", "RetailerIntegration"
    ),
}


def make_shelf_admin_headers(user_id: str = ADMIN_USER_ID) -> dict:
    return build_user_headers(user_id, "ShelfAdmin")


def make_content_author_headers(user_id: str = AUTHOR_USER_ID) -> dict:
    return build_user_headers(user_id, "ContentAuthor")


def make_legal_reviewer_headers(user_id: str = LEGAL_USER_ID) -> dict:
    return build_user_headers(user_id, "LegalReviewer")


def make_brand_approver_headers(user_id: str = BRAND_USER_ID) -> dict:
    return build_user_headers(user_id, "BrandGovernanceApprover")


def make_syndication_operator_headers(user_id: str = OPERATOR_USER_ID) -> dict:
    return build_user_headers(user_id, "SyndicationOperator")


def make_account_team_headers(user_id: str = ACCOUNT_TEAM_USER_ID) -> dict:
    return build_user_headers(user_id, "AccountTeamLead")


def make_retailer_integration_headers(retailer_id: str) -> dict:
    """For `RetailerIntegration`: pass the acting Retailer's own `id`, because
    ownership checks compare the resource's retailer foreign key to
    `X-User-ID`."""
    return build_user_headers(retailer_id, "RetailerIntegration")
