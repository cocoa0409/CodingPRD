"""Pre-built role headers for every role in the PRD (§2.1).

PropertyManager is entity-backed: for ownership-gated writes (actuals,
scorecards, lease strategies) the X-User-ID MUST equal the target asset's
property_manager_id — use make_property_manager_headers(manager["id"]).
"""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants for the opaque roles (PortfolioDirector, AssetManager,
# InvestmentCommittee, Lender, Analyst). The two named users per working role
# let segregation-of-duties tests pick distinct operator ids.
TEST_USERS = {
    "director": build_user_headers("pd-1", "PortfolioDirector"),
    "director2": build_user_headers("pd-2", "PortfolioDirector"),
    "asset_manager": build_user_headers("am-1", "AssetManager"),
    "asset_manager2": build_user_headers("am-2", "AssetManager"),
    "committee": build_user_headers("ic-1", "InvestmentCommittee"),
    "committee2": build_user_headers("ic-2", "InvestmentCommittee"),
    "lender": build_user_headers("ln-1", "Lender"),
    "analyst": build_user_headers("an-1", "Analyst"),
    # Fallback for non-ownership contexts only (e.g., a GET as PropertyManager).
    "property_manager_guest": build_user_headers("pm-guest-1", "PropertyManager"),
}


def make_property_manager_headers(property_manager_id: str) -> dict:
    """For PropertyManager (entity-backed): pass the actual PropertyManager.id
    whenever the call is ownership-gated (actuals, scorecards, lease drafts)."""
    return build_user_headers(property_manager_id, "PropertyManager")


def make_asset_manager_headers(user_id: str) -> dict:
    """AssetManager with an explicit opaque operator id (SoD-sensitive flows)."""
    return build_user_headers(user_id, "AssetManager")


def make_committee_headers(user_id: str) -> dict:
    """InvestmentCommittee with an explicit opaque operator id (SoD flows)."""
    return build_user_headers(user_id, "InvestmentCommittee")


def make_director_headers(user_id: str) -> dict:
    """PortfolioDirector with an explicit opaque operator id."""
    return build_user_headers(user_id, "PortfolioDirector")
