"""Principals and request headers (PRD 2.1).

Every request carries ``X-User-ID`` identifying the acting principal and
``X-User-Role`` declaring the operational capacity it acts in.

For the five operator roles ``X-User-ID`` is an opaque identifier that is never
compared to an entity id, so a single well-known value per role is enough — with
a second veterinarian and a second processor available where a rule needs two
distinct principals (segregation of duties). For ``GrowerFarm`` the identifier is
matched against the ``operator_user_id`` recorded on the farm row, so grower
headers are always built from the id the farm was registered with.
"""

from typing import Dict

from prd_bench_local_runner.testing import build_user_headers

from .types import Role

# ---------------------------------------------------------------------------
# Well-known opaque operator identifiers
# ---------------------------------------------------------------------------

HATCHERY_MANAGER_USER_ID = "u_hatch_1"
FLOCK_MANAGER_USER_ID = "u_flock_1"
INCUBATION_OPERATOR_USER_ID = "u_incu_1"
CHICK_PROCESSOR_USER_ID = "u_proc_1"
CHICK_PROCESSOR_2_USER_ID = "u_proc_2"
VETERINARIAN_USER_ID = "u_vet_1"
VETERINARIAN_2_USER_ID = "u_vet_2"

# ---------------------------------------------------------------------------
# Well-known grower principals (matched against GrowerFarm.operator_user_id)
# ---------------------------------------------------------------------------

GROWER_1_USER_ID = "u_grower_1"
GROWER_2_USER_ID = "u_grower_2"


# ---------------------------------------------------------------------------
# Header builders
# ---------------------------------------------------------------------------


def make_hatchery_manager_headers(
    user_id: str = HATCHERY_MANAGER_USER_ID,
) -> Dict[str, str]:
    return build_user_headers(user_id, Role.HATCHERY_MANAGER.value)


def make_flock_manager_headers(
    user_id: str = FLOCK_MANAGER_USER_ID,
) -> Dict[str, str]:
    return build_user_headers(user_id, Role.FLOCK_MANAGER.value)


def make_incubation_operator_headers(
    user_id: str = INCUBATION_OPERATOR_USER_ID,
) -> Dict[str, str]:
    return build_user_headers(user_id, Role.INCUBATION_OPERATOR.value)


def make_chick_processor_headers(
    user_id: str = CHICK_PROCESSOR_USER_ID,
) -> Dict[str, str]:
    return build_user_headers(user_id, Role.CHICK_PROCESSOR.value)


def make_veterinarian_headers(
    user_id: str = VETERINARIAN_USER_ID,
) -> Dict[str, str]:
    return build_user_headers(user_id, Role.VETERINARIAN.value)


def make_grower_farm_headers(user_id: str) -> Dict[str, str]:
    """Headers for the grower principal that owns ``user_id``'s farm scope."""
    return build_user_headers(user_id, Role.GROWER_FARM.value)


def make_headers(role: str, user_id: str) -> Dict[str, str]:
    """Headers for an arbitrary role/principal pair."""
    return build_user_headers(user_id, str(role))


def make_unauthenticated_headers(role: str = Role.FLOCK_MANAGER.value) -> Dict[str, str]:
    """Headers that declare a role but carry no ``X-User-ID`` at all.

    "A request with a missing or empty X-User-ID is rejected with
    ERR_UNAUTHENTICATED (401) before its body is even parsed."
    """
    return {"X-User-Role": str(role), "Content-Type": "application/json"}


# ---------------------------------------------------------------------------
# Pre-built headers for the common principals
# ---------------------------------------------------------------------------

HATCHERY_MANAGER = make_hatchery_manager_headers()
FLOCK_MANAGER = make_flock_manager_headers()
INCUBATION_OPERATOR = make_incubation_operator_headers()
CHICK_PROCESSOR = make_chick_processor_headers()
CHICK_PROCESSOR_2 = make_chick_processor_headers(CHICK_PROCESSOR_2_USER_ID)
VETERINARIAN = make_veterinarian_headers()
VETERINARIAN_2 = make_veterinarian_headers(VETERINARIAN_2_USER_ID)
GROWER_1 = make_grower_farm_headers(GROWER_1_USER_ID)
GROWER_2 = make_grower_farm_headers(GROWER_2_USER_ID)

#: Every role authorised to read one egg lot (PRD 4).
EGG_LOT_READER_HEADERS = (
    FLOCK_MANAGER,
    INCUBATION_OPERATOR,
    VETERINARIAN,
    HATCHERY_MANAGER,
)

#: Every one of the six recognised roles, for sweeps over the clock endpoint.
ALL_ROLE_HEADERS = (
    HATCHERY_MANAGER,
    FLOCK_MANAGER,
    INCUBATION_OPERATOR,
    CHICK_PROCESSOR,
    VETERINARIAN,
    GROWER_1,
)
