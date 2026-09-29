"""Identity headers for the six roles of PRD Section 2.1.

Every request carries `X-User-ID` and `X-User-Role`. Five roles are opaque
identities, so their user ids are arbitrary but stable strings. `CarrierLiaison`
is backed by a carrier record: its `X-User-ID` must be the carrier's own `id`,
so liaison headers can only be built once a carrier exists.
"""

from prd_bench_local_runner.testing import build_user_headers

from .constants import (
    ROLE_CAPACITY_PLANNER,
    ROLE_CARRIER_LIAISON,
    ROLE_NOC_ANALYST,
    ROLE_NOC_SHIFT_LEAD,
    ROLE_PLATFORM_ADMIN,
    ROLE_VENDOR_MANAGER,
)

# --- Stable opaque user ids -------------------------------------------------
# These particular strings matter: several rules compare stamped audit ids for
# equality (the confirming user may not submit the claim, the order's author may
# not approve it), so the suite needs identities it can reuse and contrast.
ANALYST_USER_ID = "analyst-1"
SHIFT_LEAD_USER_ID = "lead-1"
VENDOR_MANAGER_USER_ID = "vm-1"
CAPACITY_PLANNER_USER_ID = "cp-1"
PLATFORM_ADMIN_USER_ID = "admin-1"

# A single human who holds two hats: used to prove that separation of duties is
# decided on the user id rather than on the acting role.
DUAL_HAT_USER_ID = "dual-1"

# A second identity in each role, for the positive half of separation-of-duties
# pairs where the first identity has been disqualified.
SECOND_SHIFT_LEAD_USER_ID = "lead-2"
SECOND_VENDOR_MANAGER_USER_ID = "vm-2"
SECOND_CAPACITY_PLANNER_USER_ID = "cp-2"

# A role string that is not one of the six declared roles.
UNDECLARED_ROLE = "Auditor"


TEST_USERS = {
    "analyst_headers": build_user_headers(ANALYST_USER_ID, ROLE_NOC_ANALYST),
    "shift_lead_headers": build_user_headers(SHIFT_LEAD_USER_ID, ROLE_NOC_SHIFT_LEAD),
    "vendor_manager_headers": build_user_headers(
        VENDOR_MANAGER_USER_ID, ROLE_VENDOR_MANAGER
    ),
    "capacity_planner_headers": build_user_headers(
        CAPACITY_PLANNER_USER_ID, ROLE_CAPACITY_PLANNER
    ),
    "admin_headers": build_user_headers(PLATFORM_ADMIN_USER_ID, ROLE_PLATFORM_ADMIN),
}

ANALYST_HEADERS = TEST_USERS["analyst_headers"]
SHIFT_LEAD_HEADERS = TEST_USERS["shift_lead_headers"]
VENDOR_MANAGER_HEADERS = TEST_USERS["vendor_manager_headers"]
CAPACITY_PLANNER_HEADERS = TEST_USERS["capacity_planner_headers"]
ADMIN_HEADERS = TEST_USERS["admin_headers"]


# --- Per-identity header builders ------------------------------------------
def make_analyst_headers(user_id: str) -> dict:
    return build_user_headers(user_id, ROLE_NOC_ANALYST)


def make_shift_lead_headers(user_id: str) -> dict:
    return build_user_headers(user_id, ROLE_NOC_SHIFT_LEAD)


def make_vendor_manager_headers(user_id: str) -> dict:
    return build_user_headers(user_id, ROLE_VENDOR_MANAGER)


def make_capacity_planner_headers(user_id: str) -> dict:
    return build_user_headers(user_id, ROLE_CAPACITY_PLANNER)


def make_platform_admin_headers(user_id: str) -> dict:
    return build_user_headers(user_id, ROLE_PLATFORM_ADMIN)


def make_carrier_liaison_headers(carrier_id: str) -> dict:
    """Liaison headers for one carrier: `X-User-ID` is that carrier's own id."""
    return build_user_headers(carrier_id, ROLE_CARRIER_LIAISON)


def make_headers_without_user_id(role: str) -> dict:
    """Headers that carry a role but omit `X-User-ID` entirely."""
    return {"X-User-Role": role, "Content-Type": "application/json"}


def make_headers_without_role(user_id: str) -> dict:
    """Headers that carry a user id but omit `X-User-Role` entirely."""
    return {"X-User-ID": user_id, "Content-Type": "application/json"}


def make_headers_with_undeclared_role(user_id: str = ANALYST_USER_ID) -> dict:
    """Headers naming a role that is not one of the six declared roles."""
    return build_user_headers(user_id, UNDECLARED_ROLE)
