"""Canonical actors and their identity headers (PRD §2.1).

Every request carries ``X-User-ID`` and ``X-User-Role``.  Five of the six
roles are opaque labels: the server never resolves them against a stored row,
so any stable string works as the user id.

``Operator`` is different.  The PRD ties an operator's requests to a stored
``Operator`` row through its ``operator_id``, so an Operator's ``X-User-ID``
must be the real row id.  Use :func:`make_operator_headers` for that, never
the module-level opaque constants.
"""

from typing import Dict

from prd_bench_local_runner.testing.headers import build_user_headers

from .types import UserRole


# --------------------------------------------------------------------------
# Opaque user ids
# --------------------------------------------------------------------------

USER_PROCESS_ENGINEER = "u_pe_1"
USER_PROCESS_ENGINEER_2 = "u_pe_2"
USER_QUALITY_MANAGER = "u_qm_1"
USER_QUALITY_MANAGER_2 = "u_qm_2"
USER_EQUIPMENT_ENGINEER = "u_ee_1"
USER_FAB_PLANNER = "u_fp_1"
USER_YIELD_ENGINEER = "u_ye_1"

#: One human who holds two roles; used to provoke separation-of-duties.
USER_DUAL_ROLE = "u_dual_1"

#: Placeholder operator id for calls that are rejected before the body is
#: ever resolved (role screens, missing-row probes).
USER_OPERATOR_PLACEHOLDER = "u_op_x"


# --------------------------------------------------------------------------
# Header builders, one per opaque role
# --------------------------------------------------------------------------


def process_engineer_headers(user_id: str = USER_PROCESS_ENGINEER) -> Dict[str, str]:
    return build_user_headers(user_id, UserRole.PROCESS_ENGINEER.value)


def quality_manager_headers(user_id: str = USER_QUALITY_MANAGER) -> Dict[str, str]:
    return build_user_headers(user_id, UserRole.QUALITY_MANAGER.value)


def equipment_engineer_headers(user_id: str = USER_EQUIPMENT_ENGINEER) -> Dict[str, str]:
    return build_user_headers(user_id, UserRole.EQUIPMENT_ENGINEER.value)


def fab_planner_headers(user_id: str = USER_FAB_PLANNER) -> Dict[str, str]:
    return build_user_headers(user_id, UserRole.FAB_PLANNER.value)


def yield_engineer_headers(user_id: str = USER_YIELD_ENGINEER) -> Dict[str, str]:
    return build_user_headers(user_id, UserRole.YIELD_ENGINEER.value)


def make_operator_headers(operator_id: str) -> Dict[str, str]:
    """Headers for an Operator whose identity is a stored ``Operator`` row.

    ``operator_id`` must be the ``id`` of a real row, because the server
    compares it against the ``operator_id`` in step-run bodies and against
    the target of an operator PATCH.
    """
    return build_user_headers(operator_id, UserRole.OPERATOR.value)


def operator_headers_opaque(
    user_id: str = USER_OPERATOR_PLACEHOLDER,
) -> Dict[str, str]:
    """Operator headers for requests rejected before identity resolution."""
    return build_user_headers(user_id, UserRole.OPERATOR.value)


def headers_for_role(role: str, user_id: str) -> Dict[str, str]:
    """Generic builder, for parametrised role sweeps."""
    return build_user_headers(user_id, role)


#: Default opaque user id per role, for parametrised role sweeps.
DEFAULT_USER_FOR_ROLE = {
    UserRole.PROCESS_ENGINEER.value: USER_PROCESS_ENGINEER,
    UserRole.QUALITY_MANAGER.value: USER_QUALITY_MANAGER,
    UserRole.EQUIPMENT_ENGINEER.value: USER_EQUIPMENT_ENGINEER,
    UserRole.FAB_PLANNER.value: USER_FAB_PLANNER,
    UserRole.YIELD_ENGINEER.value: USER_YIELD_ENGINEER,
    UserRole.OPERATOR.value: USER_OPERATOR_PLACEHOLDER,
}


#: A role value that is well formed but is not one of the six.
UNKNOWN_ROLE = "FabDirector"
