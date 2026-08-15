"""Pre-built role headers for every role in the PRD.

Opaque roles (GeneralManager, ShiftManager, FuelDeskLead, Cashier) use shared
constants. Entity-backed roles (MaintenanceTech -> Technician.id,
FleetManager -> FleetAccount.id, LoyaltyMember -> LoyaltyMember.id) MUST be
built per-instance with make_*_headers(entity_id) whenever the call is
ownership-gated.
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    "gm_headers": build_user_headers("gm-1", "GeneralManager"),
    "sm_1_headers": build_user_headers("sm-1", "ShiftManager"),
    "sm_2_headers": build_user_headers("sm-2", "ShiftManager"),
    "fdl_headers": build_user_headers("fdl-1", "FuelDeskLead"),
    "cash_1_headers": build_user_headers("cash-1", "Cashier"),
    "cash_2_headers": build_user_headers("cash-2", "Cashier"),
}


def make_maintenance_tech_headers(technician_id: str) -> dict:
    """MaintenanceTech identity equals a Technician entity id. Pass the real
    Technician.id whenever the call is ownership-gated (start-work, parts)."""
    return build_user_headers(technician_id, "MaintenanceTech")


def make_fleet_manager_headers(fleet_account_id: str) -> dict:
    """FleetManager identity equals a FleetAccount entity id. Pass the real
    FleetAccount.id whenever the call is scoped to the fleet subtree."""
    return build_user_headers(fleet_account_id, "FleetManager")


def make_loyalty_member_headers(member_id: str) -> dict:
    """LoyaltyMember identity equals a LoyaltyMember entity id. Pass the real
    LoyaltyMember.id whenever the call is scoped to the member's own records."""
    return build_user_headers(member_id, "LoyaltyMember")
