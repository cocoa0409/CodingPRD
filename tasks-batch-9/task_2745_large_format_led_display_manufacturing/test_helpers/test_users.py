"""Authenticated identities for the LED Display Manufacturing API tests.

Six of the seven roles are opaque identities: the identifier in ``X-User-ID`` is
an operator identifier that is never compared to a persisted record, though the
server does record it where a workflow demands accountability. ``FieldEngineer``
is the one entity-backed identity: its ``X-User-ID`` is the id of the acting
commissioning crew, so its headers can only be built once a crew exists.
"""

from typing import Dict

from prd_bench_local_runner.testing import build_user_headers

from .constants import (
    ROLE_DESIGN_ENGINEER,
    ROLE_FIELD_ENGINEER,
    ROLE_PLANT_ADMIN,
    ROLE_PRODUCTION_OPERATOR,
    ROLE_QA_ENGINEER,
    ROLE_SERVICE_MANAGER,
    ROLE_STRUCTURAL_REVIEWER,
)

# Opaque operator identifiers. Distinct values are deliberate: the
# segregation-of-duties rules compare recorded operator identifiers to each
# other, so a submitter, a reviewer, a calibrating operator and a QA approver
# must be separable.
USER_PLANT_ADMIN = "adm-1"
USER_DESIGN_ENGINEER = "eng-1"
USER_DESIGN_ENGINEER_ALT = "eng-2"
USER_STRUCTURAL_REVIEWER = "rev-1"
USER_STRUCTURAL_REVIEWER_ALT = "rev-2"
USER_PRODUCTION_OPERATOR = "op-1"
USER_PRODUCTION_OPERATOR_ALT = "op-2"
USER_QA_ENGINEER = "qa-1"
USER_QA_ENGINEER_ALT = "qa-2"
USER_SERVICE_MANAGER = "svc-1"
USER_SERVICE_MANAGER_ALT = "svc-2"


def make_plant_admin_headers(user_id: str = USER_PLANT_ADMIN) -> Dict[str, str]:
    return build_user_headers(user_id, ROLE_PLANT_ADMIN)


def make_design_engineer_headers(user_id: str = USER_DESIGN_ENGINEER) -> Dict[str, str]:
    return build_user_headers(user_id, ROLE_DESIGN_ENGINEER)


def make_structural_reviewer_headers(
    user_id: str = USER_STRUCTURAL_REVIEWER,
) -> Dict[str, str]:
    return build_user_headers(user_id, ROLE_STRUCTURAL_REVIEWER)


def make_production_operator_headers(
    user_id: str = USER_PRODUCTION_OPERATOR,
) -> Dict[str, str]:
    return build_user_headers(user_id, ROLE_PRODUCTION_OPERATOR)


def make_qa_engineer_headers(user_id: str = USER_QA_ENGINEER) -> Dict[str, str]:
    return build_user_headers(user_id, ROLE_QA_ENGINEER)


def make_service_manager_headers(user_id: str = USER_SERVICE_MANAGER) -> Dict[str, str]:
    return build_user_headers(user_id, ROLE_SERVICE_MANAGER)


def make_field_engineer_headers(commissioning_crew_id: str) -> Dict[str, str]:
    """Headers for a field engineer acting as a specific commissioning crew.

    The crew id is mandatory: ownership checks on a commissioning visit compare
    the visit's ``commissioning_crew_id`` to ``X-User-ID``.
    """
    return build_user_headers(commissioning_crew_id, ROLE_FIELD_ENGINEER)


def make_headers(user_id: str, role: str) -> Dict[str, str]:
    """Headers for an arbitrary user/role pair, used by role-matrix tests."""
    return build_user_headers(user_id, role)


# Convenience identifier per role, for tests that iterate the role list.
DEFAULT_USER_ID_BY_ROLE = {
    ROLE_PLANT_ADMIN: USER_PLANT_ADMIN,
    ROLE_DESIGN_ENGINEER: USER_DESIGN_ENGINEER,
    ROLE_STRUCTURAL_REVIEWER: USER_STRUCTURAL_REVIEWER,
    ROLE_PRODUCTION_OPERATOR: USER_PRODUCTION_OPERATOR,
    ROLE_QA_ENGINEER: USER_QA_ENGINEER,
    ROLE_SERVICE_MANAGER: USER_SERVICE_MANAGER,
}
