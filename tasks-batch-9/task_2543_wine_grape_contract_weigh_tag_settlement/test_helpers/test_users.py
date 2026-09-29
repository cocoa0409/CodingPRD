"""Pre-built role headers for the six roles named in the PRD.

`Grower` is the counterparty role whose `X-User-ID` is the `id` of the acting
producer row, so ownership-gated calls MUST use `make_grower_headers(grower_id)`.
The five winery roles carry opaque operator identifiers that are never compared
to any entity's `id`; the scale house and the lab use distinct operator ids so
that a grading is never recorded by the operator who captured the weight.
"""
from prd_bench_local_runner.testing import build_user_headers

# Opaque operator identifiers for the five winery roles.
MANAGER_USER_ID = "grm-1"
COORDINATOR_USER_ID = "coord-1"
SCALE_OPERATOR_USER_ID = "scale-op-1"
SECOND_SCALE_OPERATOR_USER_ID = "scale-op-2"
LAB_TECH_USER_ID = "lab-1"
SECOND_LAB_TECH_USER_ID = "lab-2"
CLERK_USER_ID = "ap-1"

TEST_USERS = {
    "manager_headers": build_user_headers(MANAGER_USER_ID, "GrowerRelationsManager"),
    "coordinator_headers": build_user_headers(COORDINATOR_USER_ID, "HarvestCoordinator"),
    "scale_operator_headers": build_user_headers(SCALE_OPERATOR_USER_ID, "ScaleOperator"),
    "lab_tech_headers": build_user_headers(LAB_TECH_USER_ID, "QualityLabTech"),
    "clerk_headers": build_user_headers(CLERK_USER_ID, "AccountsPayableClerk"),
    # Fallback constant for a producer: only for calls that do not exercise
    # ownership (e.g. a 404 on a non-existent row).
    "grower_headers": build_user_headers("unbound-grower", "Grower"),
}


def make_grower_headers(grower_id: str) -> dict:
    """Headers for the `Grower` role. `X-User-ID` is the acting producer's `id`."""
    return build_user_headers(grower_id, "Grower")


def make_manager_headers(user_id: str = MANAGER_USER_ID) -> dict:
    return build_user_headers(user_id, "GrowerRelationsManager")


def make_coordinator_headers(user_id: str = COORDINATOR_USER_ID) -> dict:
    return build_user_headers(user_id, "HarvestCoordinator")


def make_scale_operator_headers(user_id: str = SCALE_OPERATOR_USER_ID) -> dict:
    return build_user_headers(user_id, "ScaleOperator")


def make_lab_tech_headers(user_id: str = LAB_TECH_USER_ID) -> dict:
    return build_user_headers(user_id, "QualityLabTech")


def make_clerk_headers(user_id: str = CLERK_USER_ID) -> dict:
    return build_user_headers(user_id, "AccountsPayableClerk")


ALL_ROLE_NAMES = (
    "GrowerRelationsManager",
    "Grower",
    "HarvestCoordinator",
    "ScaleOperator",
    "QualityLabTech",
    "AccountsPayableClerk",
)
