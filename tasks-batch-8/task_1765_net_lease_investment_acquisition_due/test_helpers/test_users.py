"""Pre-built role headers for every role in the PRD.

All seven roles use opaque operator identifiers (PRD §2.1): X-User-ID is never
compared against a stored entity id, so shared constants are safe everywhere.
The make_* builders exist for segregation-of-duties tests, which must control
the exact X-User-ID carried on the proposing vs approving requests.
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    "analyst_headers": build_user_headers("analyst-1", "AcquisitionsAnalyst"),
    "committee_headers": build_user_headers("committee-1", "UnderwritingCommittee"),
    "dd_officer_headers": build_user_headers("dd-officer-1", "DueDiligenceOfficer"),
    "capital_markets_headers": build_user_headers("cmo-1", "CapitalMarketsOfficer"),
    "escrow_headers": build_user_headers("escrow-1", "EscrowOfficer"),
    "asset_manager_headers": build_user_headers("asset-manager-1", "AssetManager"),
    "platform_admin_headers": build_user_headers("platform-admin-1", "PlatformAdmin"),
}


def make_analyst_headers(user_id: str) -> dict:
    """AcquisitionsAnalyst headers with a specific X-User-ID (SoD control)."""
    return build_user_headers(user_id, "AcquisitionsAnalyst")


def make_committee_headers(user_id: str) -> dict:
    """UnderwritingCommittee headers with a specific X-User-ID (SoD control)."""
    return build_user_headers(user_id, "UnderwritingCommittee")


def make_dd_officer_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "DueDiligenceOfficer")


def make_capital_markets_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "CapitalMarketsOfficer")


def make_escrow_headers(user_id: str) -> dict:
    """EscrowOfficer headers with a specific X-User-ID (SoD control)."""
    return build_user_headers(user_id, "EscrowOfficer")


def make_asset_manager_headers(user_id: str) -> dict:
    """AssetManager headers with a specific X-User-ID (SoD control)."""
    return build_user_headers(user_id, "AssetManager")


def make_platform_admin_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "PlatformAdmin")
