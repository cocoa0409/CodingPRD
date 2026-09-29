"""Acting identities and header builders (PRD §2.1).

``StateAdmin`` and ``ComplianceReviewer`` present opaque operator identifiers, so
fixed strings are fine and two of each are provided for the segregation-of-duties
comparisons. ``AgencyCoordinator`` presents the acting ``Agency.id`` and
``StateWarehouseOperator`` presents the acting ``Warehouse.id``, so those headers
must be built from a row created during the test.
"""

from typing import Dict

from prd_bench_local_runner.testing import build_user_headers

from .types import Role

# Opaque operator identifiers.
STATE_ADMIN_ID = "adm-1"
SECOND_STATE_ADMIN_ID = "adm-2"
COMPLIANCE_REVIEWER_ID = "rev-1"
SECOND_COMPLIANCE_REVIEWER_ID = "rev-2"


TEST_USERS: Dict[str, Dict[str, str]] = {
    "state_admin": {"user_id": STATE_ADMIN_ID, "role": Role.STATE_ADMIN},
    "second_state_admin": {"user_id": SECOND_STATE_ADMIN_ID, "role": Role.STATE_ADMIN},
    "compliance_reviewer": {
        "user_id": COMPLIANCE_REVIEWER_ID,
        "role": Role.COMPLIANCE_REVIEWER,
    },
    "second_compliance_reviewer": {
        "user_id": SECOND_COMPLIANCE_REVIEWER_ID,
        "role": Role.COMPLIANCE_REVIEWER,
    },
}


def make_state_admin_headers(user_id: str = STATE_ADMIN_ID) -> Dict[str, str]:
    return build_user_headers(user_id, Role.STATE_ADMIN)


def make_second_state_admin_headers() -> Dict[str, str]:
    return build_user_headers(SECOND_STATE_ADMIN_ID, Role.STATE_ADMIN)


def make_compliance_reviewer_headers(
    user_id: str = COMPLIANCE_REVIEWER_ID,
) -> Dict[str, str]:
    return build_user_headers(user_id, Role.COMPLIANCE_REVIEWER)


def make_second_compliance_reviewer_headers() -> Dict[str, str]:
    return build_user_headers(SECOND_COMPLIANCE_REVIEWER_ID, Role.COMPLIANCE_REVIEWER)


def make_agency_coordinator_headers(agency_id: str) -> Dict[str, str]:
    """The coordinator's ``X-User-ID`` is the id of the acting ``Agency``."""
    return build_user_headers(agency_id, Role.AGENCY_COORDINATOR)


def make_warehouse_operator_headers(warehouse_id: str) -> Dict[str, str]:
    """The operator's ``X-User-ID`` is the id of the acting ``Warehouse``."""
    return build_user_headers(warehouse_id, Role.STATE_WAREHOUSE_OPERATOR)


def make_headers(user_id: str, role: str) -> Dict[str, str]:
    """Escape hatch for role strings the API does not recognise."""
    return build_user_headers(user_id, role)


NO_HEADERS: Dict[str, str] = {}
