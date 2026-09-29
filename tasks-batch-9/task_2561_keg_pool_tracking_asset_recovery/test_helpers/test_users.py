"""Pre-built request headers for every role the PRD declares.

Three roles carry opaque operator identifiers (PoolOperator,
ServiceTechnician, AssetRecoveryAnalyst) and their shared constants are the
canonical form.  Two roles are entity-backed: a Brewer acts under its own
Brewer identifier and a Distributor under its own Distributor identifier, so
every ownership-gated call MUST use ``make_brewer_headers(brewer["id"])`` or
``make_distributor_headers(distributor["id"])`` rather than a shared constant.
"""

from typing import Dict

from prd_bench_local_runner.testing import build_user_headers

# --- Opaque operator identifiers -----------------------------------------
POOL_OPERATOR_USER_ID = "op-1"
SECOND_POOL_OPERATOR_USER_ID = "op-2"
TECHNICIAN_USER_ID = "tech-1"
SECOND_TECHNICIAN_USER_ID = "tech-2"
ANALYST_USER_ID = "analyst-1"
SECOND_ANALYST_USER_ID = "analyst-2"
THIRD_ANALYST_USER_ID = "analyst-3"

# Shared constants.  Safe for the three opaque roles, and for probes that do
# not exercise ownership (missing payload fields, unknown identifiers, ...).
TEST_USERS: Dict[str, Dict[str, str]] = {
    "pool_operator_headers": build_user_headers(
        POOL_OPERATOR_USER_ID, "PoolOperator"
    ),
    "second_pool_operator_headers": build_user_headers(
        SECOND_POOL_OPERATOR_USER_ID, "PoolOperator"
    ),
    "technician_headers": build_user_headers(
        TECHNICIAN_USER_ID, "ServiceTechnician"
    ),
    "second_technician_headers": build_user_headers(
        SECOND_TECHNICIAN_USER_ID, "ServiceTechnician"
    ),
    "analyst_headers": build_user_headers(ANALYST_USER_ID, "AssetRecoveryAnalyst"),
    "second_analyst_headers": build_user_headers(
        SECOND_ANALYST_USER_ID, "AssetRecoveryAnalyst"
    ),
    "third_analyst_headers": build_user_headers(
        THIRD_ANALYST_USER_ID, "AssetRecoveryAnalyst"
    ),
    # Entity-backed roles: these constants intentionally do NOT match any
    # stored row, so they are only for probes that must present an
    # unrecognised brewer or distributor identifier.
    "unknown_brewer_headers": build_user_headers("unknown-brewer", "Brewer"),
    "unknown_distributor_headers": build_user_headers(
        "unknown-distributor", "Distributor"
    ),
}


def make_pool_operator_headers(user_id: str) -> Dict[str, str]:
    """Headers for a named pool operator (opaque identifier)."""
    return build_user_headers(user_id, "PoolOperator")


def make_technician_headers(user_id: str) -> Dict[str, str]:
    """Headers for a named service technician (opaque identifier).

    The release segregation rule compares the releasing identifier against
    the identifier that recorded the pressure test, so tests must be able to
    name two different technicians.
    """
    return build_user_headers(user_id, "ServiceTechnician")


def make_analyst_headers(user_id: str) -> Dict[str, str]:
    """Headers for a named asset recovery analyst (opaque identifier).

    The resolution segregation rule compares the resolving identifier against
    the identifier that created the assessment.
    """
    return build_user_headers(user_id, "AssetRecoveryAnalyst")


def make_brewer_headers(user_id: str) -> Dict[str, str]:
    """Headers for a Brewer actor.

    ``user_id`` MUST be a stored brewer's own identifier: the brewer's
    identity is that identifier, and ownership is checked against it.
    """
    return build_user_headers(user_id, "Brewer")


def make_distributor_headers(user_id: str) -> Dict[str, str]:
    """Headers for a Distributor actor.

    ``user_id`` MUST be a stored distributor's own identifier: the
    distributor's identity is that identifier, and ownership is checked
    against it.
    """
    return build_user_headers(user_id, "Distributor")


def all_role_headers(brewer_id: str, distributor_id: str) -> Dict[str, Dict[str, str]]:
    """Headers for all five roles, with the two entity-backed roles bound to
    real stored rows."""
    return {
        "PoolOperator": TEST_USERS["pool_operator_headers"],
        "Brewer": make_brewer_headers(brewer_id),
        "Distributor": make_distributor_headers(distributor_id),
        "ServiceTechnician": TEST_USERS["technician_headers"],
        "AssetRecoveryAnalyst": TEST_USERS["analyst_headers"],
    }
