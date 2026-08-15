"""Pre-built role headers for every role in the PRD (§2.1).

Entity-backed roles (FleetAccountManager -> FleetAccount.id, FleetDriver ->
FleetCard.id) MUST be built per-instance via the make_* builders whenever the
call is ownership-gated; the shared constants exist only for tests whose
outcome does not depend on owning the subject resource.
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    # Opaque roles: shared constants are the canonical form.
    "network_operator_headers": build_user_headers("netop-1", "NetworkOperator"),
    "station_manager_headers": build_user_headers("sm-1", "StationManager"),
    "compliance_officer_headers": build_user_headers("co-1", "ComplianceOfficer"),
    "anonymous_headers": build_user_headers("anon-pump-1", "Anonymous"),
    # Entity-backed roles: fallback for non-ownership tests only.
    "fleet_account_manager_headers": build_user_headers("fam-1", "FleetAccountManager"),
    "fleet_driver_headers": build_user_headers("driver-1", "FleetDriver"),
}


def make_fleet_account_manager_headers(account_id: str) -> dict:
    """FleetAccountManager headers whose X-User-ID is the managed account id."""
    return build_user_headers(account_id, "FleetAccountManager")


def make_fleet_driver_headers(card_id: str) -> dict:
    """FleetDriver headers whose X-User-ID is the held FleetCard id."""
    return build_user_headers(card_id, "FleetDriver")


def make_station_manager_headers(user_id: str) -> dict:
    """StationManager headers with a specific opaque id (e.g. performer ids)."""
    return build_user_headers(user_id, "StationManager")


def make_compliance_officer_headers(user_id: str) -> dict:
    """ComplianceOfficer headers with a specific opaque id (e.g. approver ids)."""
    return build_user_headers(user_id, "ComplianceOfficer")


def make_anonymous_headers(user_id: str) -> dict:
    """Anonymous headers with a specific opaque pump-side id."""
    return build_user_headers(user_id, "Anonymous")


def make_network_operator_headers(user_id: str) -> dict:
    """NetworkOperator headers with a specific opaque id."""
    return build_user_headers(user_id, "NetworkOperator")
