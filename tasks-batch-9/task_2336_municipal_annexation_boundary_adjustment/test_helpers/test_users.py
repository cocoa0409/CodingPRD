"""Actor headers.

Identity semantics differ by role (PRD §2.1):

* ``MunicipalPlanner`` and ``CityClerk`` carry the acting **Municipality** id in
  ``X-User-ID``.
* ``PropertyOwner`` carries the acting **PropertyOwner** id in ``X-User-ID``.
* ``StateLawAdmin``, ``FiscalAnalyst``, ``BoundaryCommissioner`` and
  ``CountyAssessor`` carry an opaque operator identifier.

Because the first two families are entity-backed, their headers can only be
built once the entity exists — hence the ``make_*_headers(entity_id)``
builders. There is deliberately no shared constant for them.
"""
from typing import Dict

from prd_bench_local_runner.testing import build_user_headers

from .types import UserRole

# --------------------------------------------------------------------------
# Opaque operator identifiers. These are not compared against any entity id,
# so a fixed value per role is correct.
# --------------------------------------------------------------------------
STATE_LAW_ADMIN_USER_ID = "11111111-1111-4111-8111-111111111111"
FISCAL_ANALYST_USER_ID = "22222222-2222-4222-8222-222222222222"
FISCAL_ANALYST_ALT_USER_ID = "22222222-2222-4222-8222-2222222222ab"
BOUNDARY_COMMISSIONER_USER_ID = "33333333-3333-4333-8333-333333333333"
BOUNDARY_COMMISSIONER_ALT_USER_ID = "33333333-3333-4333-8333-3333333333ab"
COUNTY_ASSESSOR_USER_ID = "44444444-4444-4444-8444-444444444444"


TEST_USERS: Dict[str, Dict[str, str]] = {
    "state_law_admin": {
        "user_id": STATE_LAW_ADMIN_USER_ID,
        "role": UserRole.STATE_LAW_ADMIN.value,
    },
    "fiscal_analyst": {
        "user_id": FISCAL_ANALYST_USER_ID,
        "role": UserRole.FISCAL_ANALYST.value,
    },
    "other_fiscal_analyst": {
        "user_id": FISCAL_ANALYST_ALT_USER_ID,
        "role": UserRole.FISCAL_ANALYST.value,
    },
    "boundary_commissioner": {
        "user_id": BOUNDARY_COMMISSIONER_USER_ID,
        "role": UserRole.BOUNDARY_COMMISSIONER.value,
    },
    "other_boundary_commissioner": {
        "user_id": BOUNDARY_COMMISSIONER_ALT_USER_ID,
        "role": UserRole.BOUNDARY_COMMISSIONER.value,
    },
    "county_assessor": {
        "user_id": COUNTY_ASSESSOR_USER_ID,
        "role": UserRole.COUNTY_ASSESSOR.value,
    },
}


# --------------------------------------------------------------------------
# Opaque-role header shortcuts
# --------------------------------------------------------------------------
def state_law_admin_headers() -> Dict[str, str]:
    return build_user_headers(STATE_LAW_ADMIN_USER_ID, UserRole.STATE_LAW_ADMIN.value)


def fiscal_analyst_headers(user_id: str = FISCAL_ANALYST_USER_ID) -> Dict[str, str]:
    return build_user_headers(user_id, UserRole.FISCAL_ANALYST.value)


def boundary_commissioner_headers(
    user_id: str = BOUNDARY_COMMISSIONER_USER_ID,
) -> Dict[str, str]:
    return build_user_headers(user_id, UserRole.BOUNDARY_COMMISSIONER.value)


def county_assessor_headers(user_id: str = COUNTY_ASSESSOR_USER_ID) -> Dict[str, str]:
    return build_user_headers(user_id, UserRole.COUNTY_ASSESSOR.value)


# --------------------------------------------------------------------------
# Entity-backed role header builders. `municipality_id` / `property_owner_id`
# must be the id of a municipality / owner that actually exists.
# --------------------------------------------------------------------------
def make_municipal_planner_headers(municipality_id: str) -> Dict[str, str]:
    """Headers for a MunicipalPlanner acting for `municipality_id`."""
    return build_user_headers(municipality_id, UserRole.MUNICIPAL_PLANNER.value)


def make_city_clerk_headers(municipality_id: str) -> Dict[str, str]:
    """Headers for a CityClerk acting for `municipality_id`."""
    return build_user_headers(municipality_id, UserRole.CITY_CLERK.value)


def make_property_owner_headers(property_owner_id: str) -> Dict[str, str]:
    """Headers for a PropertyOwner acting as `property_owner_id`."""
    return build_user_headers(property_owner_id, UserRole.PROPERTY_OWNER.value)


def make_headers(user_id: str, role: str) -> Dict[str, str]:
    """Escape hatch for tests that need an arbitrary id/role pair."""
    return build_user_headers(user_id, role)
