"""Pre-built role headers for every role in the Warehouse Management PRD.

All six roles use an opaque identity model (PRD 2.1): X-User-ID is never compared
to any entity id for ownership. The shared constants below are therefore the
canonical caller form for every role. A few flows (cycle-count segregation of
duties, PRD 2.9 / 3.10) need to distinguish individual actors by X-User-ID, so a
per-role header builder is provided to mint headers with a chosen user id.
"""
from prd_bench_local_runner.testing import build_user_headers


TEST_USERS = {
    "platform_admin_headers": build_user_headers("test-admin-1", "PlatformAdmin"),
    "receiving_clerk_headers": build_user_headers("test-clerk-1", "ReceivingClerk"),
    "putaway_operator_headers": build_user_headers("test-putaway-1", "PutawayOperator"),
    "picker_headers": build_user_headers("test-picker-1", "Picker"),
    "wave_planner_headers": build_user_headers("test-planner-1", "WavePlanner"),
    "inventory_controller_headers": build_user_headers("test-ic-1", "InventoryController"),
}


def make_platform_admin_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "PlatformAdmin")


def make_receiving_clerk_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "ReceivingClerk")


def make_putaway_operator_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "PutawayOperator")


def make_picker_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "Picker")


def make_wave_planner_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "WavePlanner")


def make_inventory_controller_headers(user_id: str) -> dict:
    """For InventoryController. Pass a distinct user_id to exercise the
    cycle-count segregation-of-duties separation between counter and approver."""
    return build_user_headers(user_id, "InventoryController")
