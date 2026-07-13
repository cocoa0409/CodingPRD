"""Pre-built role headers for every role in the PRD (§2.1)."""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants.
#
# PRD §2.1: for ProgramAdmin, Merchant, FraudAnalyst and TelematicsGateway,
# X-User-ID is an opaque operator identifier not tied to any persisted entity —
# the shared constant is the canonical form for those roles.
#
# For FleetManager, X-User-ID is the id of the acting FleetAccount. The shared
# constant below is a fallback usable ONLY by tests that never reach a fleet
# ownership check (e.g. authorization-only denials). Any ownership-gated call
# MUST use make_fleet_manager_headers(account_id) instead.
TEST_USERS = {
    "program_admin_headers": build_user_headers("test-admin-1", "ProgramAdmin"),
    "merchant_headers": build_user_headers("test-merchant-1", "Merchant"),
    "fraud_analyst_headers": build_user_headers("test-fraud-1", "FraudAnalyst"),
    "telematics_gateway_headers": build_user_headers("test-gateway-1", "TelematicsGateway"),
    "fleet_manager_headers": build_user_headers("test-fleet-manager-1", "FleetManager"),
}

# A request carrying no authentication headers at all (PRD §2.1 —
# ERR_UNAUTHENTICATED when either header is missing).
NO_AUTH_HEADERS: dict = {}


def make_fleet_manager_headers(fleet_account_id: str) -> dict:
    """Headers for a FleetManager acting on behalf of a specific fleet account.

    PRD §2.1: "When `X-User-Role` is `FleetManager`, `X-User-ID` is the `id` of
    the acting `FleetAccount`". Every ownership-gated call must pass the real
    FleetAccount.id here.
    """
    return build_user_headers(fleet_account_id, "FleetManager")
