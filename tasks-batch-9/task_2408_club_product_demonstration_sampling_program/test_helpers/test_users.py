"""Acting principals for every role (PRD 2.1).

Two roles are operator identities whose ``X-User-ID`` is opaque and never
compared to an entity id: ``ProgramAdmin`` and ``StaffingCoordinator``. Three
roles are entity-backed, so their headers must be minted from a row id created
during the test — hence the ``make_*_headers`` helpers rather than constants.

Three distinct ``ProgramAdmin`` operators are declared because the
segregation-of-duties rule compares the issuing operator's ``X-User-ID`` with
the deciding operator's, so a single admin identity cannot exercise both sides.
"""

from typing import Dict

from prd_bench_local_runner.testing import build_user_headers

from .types import Role

# --- opaque operator identities ---------------------------------------------
ADMIN_HQ_USER_ID = "admin_hq"
ADMIN_BILLING_USER_ID = "admin_billing"
ADMIN_CONTROLLER_USER_ID = "admin_controller"
STAFF_OPS_USER_ID = "staff_ops"

TEST_USERS = {
    "admin_hq": {"user_id": ADMIN_HQ_USER_ID, "role": Role.PROGRAM_ADMIN},
    "admin_billing": {"user_id": ADMIN_BILLING_USER_ID, "role": Role.PROGRAM_ADMIN},
    "admin_controller": {
        "user_id": ADMIN_CONTROLLER_USER_ID,
        "role": Role.PROGRAM_ADMIN,
    },
    "staff_ops": {"user_id": STAFF_OPS_USER_ID, "role": Role.STAFFING_COORDINATOR},
}

ADMIN_HQ_HEADERS = build_user_headers(ADMIN_HQ_USER_ID, Role.PROGRAM_ADMIN)
ADMIN_BILLING_HEADERS = build_user_headers(ADMIN_BILLING_USER_ID, Role.PROGRAM_ADMIN)
ADMIN_CONTROLLER_HEADERS = build_user_headers(
    ADMIN_CONTROLLER_USER_ID, Role.PROGRAM_ADMIN
)
STAFF_OPS_HEADERS = build_user_headers(STAFF_OPS_USER_ID, Role.STAFFING_COORDINATOR)


# --- entity-backed identities ------------------------------------------------
def make_manufacturer_headers(manufacturer_id: str) -> Dict[str, str]:
    """``X-User-ID`` is the id of the acting ``Manufacturer`` row."""
    return build_user_headers(manufacturer_id, Role.MANUFACTURER)


def make_club_headers(club_id: str) -> Dict[str, str]:
    """``X-User-ID`` is the id of the acting ``Club`` row."""
    return build_user_headers(club_id, Role.CLUB_OPERATIONS)


def make_demonstrator_headers(demonstrator_id: str) -> Dict[str, str]:
    """``X-User-ID`` is the id of the acting ``Demonstrator`` row."""
    return build_user_headers(demonstrator_id, Role.DEMONSTRATOR)
