"""Role headers for the seven roles of PRD §2.1.

Six roles carry an opaque operator identifier. `DealerPrincipal` is the sole
entity-backed role: "For a `DealerPrincipal` the `X-User-ID` *is* the
`Dealer.id`", so its headers can only be built once the dealer row exists.
"""
from prd_bench_local_runner.testing import build_user_headers

PLANT_ADMIN_USER_ID = "pa-1"
PRODUCTION_SCHEDULER_USER_ID = "ps-1"
LINE_SUPERVISOR_USER_ID = "ls-1"
QUALITY_INSPECTOR_1_USER_ID = "qi-alice"
QUALITY_INSPECTOR_2_USER_ID = "qi-bob"
WARRANTY_ADMIN_1_USER_ID = "wa-1"
WARRANTY_ADMIN_2_USER_ID = "wa-2"
RECALL_COORDINATOR_USER_ID = "rc-1"

TEST_USERS = {
    "plant_admin_headers": build_user_headers(PLANT_ADMIN_USER_ID, "PlantAdmin"),
    "production_scheduler_headers": build_user_headers(
        PRODUCTION_SCHEDULER_USER_ID, "ProductionScheduler"
    ),
    "line_supervisor_headers": build_user_headers(LINE_SUPERVISOR_USER_ID, "LineSupervisor"),
    "quality_inspector_headers": build_user_headers(
        QUALITY_INSPECTOR_1_USER_ID, "QualityInspector"
    ),
    "quality_inspector_2_headers": build_user_headers(
        QUALITY_INSPECTOR_2_USER_ID, "QualityInspector"
    ),
    "warranty_admin_headers": build_user_headers(
        WARRANTY_ADMIN_1_USER_ID, "WarrantyAdministrator"
    ),
    "warranty_admin_2_headers": build_user_headers(
        WARRANTY_ADMIN_2_USER_ID, "WarrantyAdministrator"
    ),
    "recall_coordinator_headers": build_user_headers(
        RECALL_COORDINATOR_USER_ID, "RecallCoordinator"
    ),
}


def make_dealer_principal_headers(dealer_id: str) -> dict:
    """Headers for the DealerPrincipal whose X-User-ID is this Dealer.id."""
    return build_user_headers(dealer_id, "DealerPrincipal")


def make_quality_inspector_headers(user_id: str) -> dict:
    """Headers for a specific QualityInspector operator identity."""
    return build_user_headers(user_id, "QualityInspector")


def make_warranty_admin_headers(user_id: str) -> dict:
    """Headers for a specific WarrantyAdministrator operator identity."""
    return build_user_headers(user_id, "WarrantyAdministrator")


def make_line_supervisor_headers(user_id: str) -> dict:
    """Headers for a specific LineSupervisor operator identity."""
    return build_user_headers(user_id, "LineSupervisor")
