"""Acting identities.

Five of the seven roles are opaque operator ids: any non-empty string is a
legitimate actor, so the suite pins a small stable cast of them. The remaining
two roles are entity-backed — a `Consignor` header must carry the id of a real
consignor row and a `Buyer` header the id of a real buyer row — so those must be
built per test from the row the test just created.
"""

from typing import Dict

from prd_bench_local_runner.testing import build_user_headers

from .types import UserRole

# --- Opaque operator identities --------------------------------------------

GALLERY_MANAGER_ID = "mgr-1"
GALLERY_MANAGER_2_ID = "mgr-2"
INTAKE_APPRAISER_ID = "appraiser-1"
INTAKE_APPRAISER_2_ID = "appraiser-2"
FLOOR_OPERATOR_ID = "floor-1"
FLOOR_OPERATOR_2_ID = "floor-2"
LOGISTICS_COORDINATOR_ID = "logi-1"
LOGISTICS_COORDINATOR_2_ID = "logi-2"
SYSTEM_OPERATOR_ID = "sysop-1"

GALLERY_MANAGER = build_user_headers(GALLERY_MANAGER_ID, UserRole.GALLERY_MANAGER.value)
GALLERY_MANAGER_2 = build_user_headers(GALLERY_MANAGER_2_ID, UserRole.GALLERY_MANAGER.value)
INTAKE_APPRAISER = build_user_headers(INTAKE_APPRAISER_ID, UserRole.INTAKE_APPRAISER.value)
INTAKE_APPRAISER_2 = build_user_headers(
    INTAKE_APPRAISER_2_ID, UserRole.INTAKE_APPRAISER.value
)
FLOOR_OPERATOR = build_user_headers(FLOOR_OPERATOR_ID, UserRole.FLOOR_OPERATOR.value)
FLOOR_OPERATOR_2 = build_user_headers(FLOOR_OPERATOR_2_ID, UserRole.FLOOR_OPERATOR.value)
LOGISTICS_COORDINATOR = build_user_headers(
    LOGISTICS_COORDINATOR_ID, UserRole.LOGISTICS_COORDINATOR.value
)
LOGISTICS_COORDINATOR_2 = build_user_headers(
    LOGISTICS_COORDINATOR_2_ID, UserRole.LOGISTICS_COORDINATOR.value
)
SYSTEM_OPERATOR = build_user_headers(SYSTEM_OPERATOR_ID, UserRole.SYSTEM_OPERATOR.value)

TEST_USERS: Dict[str, Dict[str, str]] = {
    "gallery_manager": GALLERY_MANAGER,
    "gallery_manager_2": GALLERY_MANAGER_2,
    "intake_appraiser": INTAKE_APPRAISER,
    "intake_appraiser_2": INTAKE_APPRAISER_2,
    "floor_operator": FLOOR_OPERATOR,
    "floor_operator_2": FLOOR_OPERATOR_2,
    "logistics_coordinator": LOGISTICS_COORDINATOR,
    "logistics_coordinator_2": LOGISTICS_COORDINATOR_2,
    "system_operator": SYSTEM_OPERATOR,
}


# --- Entity-backed identities ----------------------------------------------

def make_consignor_headers(consignor_id: str) -> Dict[str, str]:
    """Headers for the consignor whose own row is `consignor_id`."""
    return build_user_headers(consignor_id, UserRole.CONSIGNOR.value)


def make_buyer_headers(buyer_id: str) -> Dict[str, str]:
    """Headers for the buyer whose own row is `buyer_id`."""
    return build_user_headers(buyer_id, UserRole.BUYER.value)


def make_headers(user_id: str, role: str) -> Dict[str, str]:
    """Arbitrary id/role pairing, for authorization and authentication probes."""
    return build_user_headers(user_id, role)


ALL_ROLES = (
    UserRole.CONSIGNOR.value,
    UserRole.BUYER.value,
    UserRole.INTAKE_APPRAISER.value,
    UserRole.FLOOR_OPERATOR.value,
    UserRole.LOGISTICS_COORDINATOR.value,
    UserRole.GALLERY_MANAGER.value,
    UserRole.SYSTEM_OPERATOR.value,
)
