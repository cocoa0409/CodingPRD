"""Pre-built role headers for every role in the PRD.

`SiteController` is the plant controller of exactly one asset: its `X-User-ID`
is the `id` of the acting storage asset, so ownership-gated calls MUST use
`make_site_controller_headers(asset["id"])`. The other six roles carry an
opaque operator identifier that is never compared to an entity id.
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    "platform_admin_headers": build_user_headers("admin-user-1", "PlatformAdmin"),
    "asset_manager_headers": build_user_headers("asset-manager-1", "AssetManager"),
    "market_trader_headers": build_user_headers("market-trader-1", "MarketTrader"),
    "market_operator_headers": build_user_headers("market-operator-1", "MarketOperator"),
    "control_room_headers": build_user_headers("control-room-1", "ControlRoomOperator"),
    # Shared fallback only — never use for an ownership-gated call.
    "site_controller_headers": build_user_headers("site-controller-1", "SiteController"),
    "safety_officer_headers": build_user_headers("safety-officer-1", "SafetyOfficer"),
}

# Second identifiers for the two separation-of-duties surfaces: warranty
# adjudication and safety-event closure both require a different `X-User-ID`.
SECOND_PLATFORM_ADMIN = build_user_headers("admin-user-2", "PlatformAdmin")
SECOND_ASSET_MANAGER = build_user_headers("asset-manager-2", "AssetManager")
SECOND_SAFETY_OFFICER = build_user_headers("safety-officer-2", "SafetyOfficer")


def make_site_controller_headers(asset_id: str) -> dict:
    """Headers for the `SiteController` of one asset.

    Pass the actual storage asset's `id`: telemetry append, dispatch execution,
    completion and failure, and capacity-test start and completion all compare
    the target asset's `id` to `X-User-ID`.
    """
    return build_user_headers(asset_id, "SiteController")


def make_platform_admin_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "PlatformAdmin")


def make_asset_manager_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "AssetManager")


def make_market_trader_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "MarketTrader")


def make_market_operator_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "MarketOperator")


def make_control_room_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "ControlRoomOperator")


def make_safety_officer_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "SafetyOfficer")


def make_headers(user_id: str, role: str) -> dict:
    """Arbitrary identifier/role pair — used by the authentication probes."""
    return build_user_headers(user_id, role)
