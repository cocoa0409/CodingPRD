"""
Auth header builders for the six declared roles.

Five roles carry an opaque staff identity: X-User-ID is an arbitrary staff
identifier that is recorded for audit and compared for segregation of duties,
but it never has to match a stored row. The Applicant role is different - its
X-User-ID must be the Applicant.id of the registered applicant, so every
Applicant call has to be threaded through ``make_applicant_headers(applicant_id)``
with the id the API actually minted.
"""

from typing import Dict

from prd_bench_local_runner.testing import build_user_headers

from .types import (
    ROLE_APPLICANT,
    ROLE_BOARD_CLERK,
    ROLE_COUNTY_TREASURER,
    ROLE_DISPOSITION_OFFICER,
    ROLE_INTAKE_OFFICER,
    ROLE_INVENTORY_MANAGER,
)

# --- Opaque staff identities -------------------------------------------------
# Two distinct intake officers exist because the officer who initiates an
# acquisition packet may not be the officer who closes it, and two distinct
# disposition officers exist because the officer who performed the governing
# screening may not issue the recommendation.
INTAKE_OFFICER_1 = "intake-1"
INTAKE_OFFICER_2 = "intake-2"
BOARD_CLERK_1 = "clerk-1"
DISPOSITION_OFFICER_1 = "disp-1"
DISPOSITION_OFFICER_2 = "disp-2"
INVENTORY_MANAGER_1 = "inv-1"
COUNTY_TREASURER_1 = "treas-1"


def make_intake_officer_headers(user_id: str = INTAKE_OFFICER_1) -> Dict[str, str]:
    """Headers for an IntakeOfficer acting under the given staff identifier."""
    return build_user_headers(user_id, ROLE_INTAKE_OFFICER)


def make_board_clerk_headers(user_id: str = BOARD_CLERK_1) -> Dict[str, str]:
    """Headers for a BoardClerk acting under the given staff identifier."""
    return build_user_headers(user_id, ROLE_BOARD_CLERK)


def make_disposition_officer_headers(
    user_id: str = DISPOSITION_OFFICER_1,
) -> Dict[str, str]:
    """Headers for a DispositionOfficer acting under the given staff identifier."""
    return build_user_headers(user_id, ROLE_DISPOSITION_OFFICER)


def make_inventory_manager_headers(
    user_id: str = INVENTORY_MANAGER_1,
) -> Dict[str, str]:
    """Headers for an InventoryManager acting under the given staff identifier."""
    return build_user_headers(user_id, ROLE_INVENTORY_MANAGER)


def make_county_treasurer_headers(
    user_id: str = COUNTY_TREASURER_1,
) -> Dict[str, str]:
    """Headers for a CountyTreasurer acting under the given staff identifier."""
    return build_user_headers(user_id, ROLE_COUNTY_TREASURER)


def make_applicant_headers(applicant_id: str) -> Dict[str, str]:
    """
    Headers for an Applicant.

    ``applicant_id`` must be the id of a registered Applicant row: the API
    resolves ownership of applications and development agreements by comparing
    X-User-ID with the application's applicant_id.
    """
    return build_user_headers(applicant_id, ROLE_APPLICANT)


# Ready-made headers for the five opaque staff roles. The Applicant role is
# absent on purpose: it can only be built once an Applicant row exists.
INTAKE_1 = make_intake_officer_headers(INTAKE_OFFICER_1)
INTAKE_2 = make_intake_officer_headers(INTAKE_OFFICER_2)
CLERK_1 = make_board_clerk_headers(BOARD_CLERK_1)
DISP_1 = make_disposition_officer_headers(DISPOSITION_OFFICER_1)
DISP_2 = make_disposition_officer_headers(DISPOSITION_OFFICER_2)
INV_1 = make_inventory_manager_headers(INVENTORY_MANAGER_1)
TREAS_1 = make_county_treasurer_headers(COUNTY_TREASURER_1)

TEST_USERS: Dict[str, Dict[str, str]] = {
    ROLE_INTAKE_OFFICER: INTAKE_1,
    ROLE_BOARD_CLERK: CLERK_1,
    ROLE_DISPOSITION_OFFICER: DISP_1,
    ROLE_INVENTORY_MANAGER: INV_1,
    ROLE_COUNTY_TREASURER: TREAS_1,
}
