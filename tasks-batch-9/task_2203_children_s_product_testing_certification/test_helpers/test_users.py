"""Request identity headers for each role described in PRD 2.1.

Four roles carry an opaque operator identifier; two roles are entity-backed and
their `X-User-ID` must be the id of the acting Laboratory or Supplier, so those
headers are built per-entity through the `make_*` helpers.
"""

from typing import Dict

from prd_bench_local_runner.testing import build_user_headers

from .types import Role


# Opaque operator identities (PRD 2.1).  Distinct values so that the two
# segregation-of-duties checks can be exercised in either direction.
ADMIN_USER_ID = "admin-operator-01"
COORDINATOR_USER_ID = "coordinator-operator-01"
COORDINATOR_ALT_USER_ID = "coordinator-operator-02"
OFFICER_USER_ID = "officer-operator-01"
OFFICER_ALT_USER_ID = "officer-operator-02"
MANAGER_USER_ID = "manager-operator-01"
MANAGER_ALT_USER_ID = "manager-operator-02"


TEST_USERS: Dict[str, Dict[str, str]] = {
    "admin": build_user_headers(ADMIN_USER_ID, Role.COMPLIANCE_ADMINISTRATOR.value),
    "coordinator": build_user_headers(
        COORDINATOR_USER_ID, Role.TEST_COORDINATOR.value
    ),
    "coordinator_alt": build_user_headers(
        COORDINATOR_ALT_USER_ID, Role.TEST_COORDINATOR.value
    ),
    "officer": build_user_headers(OFFICER_USER_ID, Role.CERTIFICATION_OFFICER.value),
    "officer_alt": build_user_headers(
        OFFICER_ALT_USER_ID, Role.CERTIFICATION_OFFICER.value
    ),
    "manager": build_user_headers(MANAGER_USER_ID, Role.DISTRIBUTION_MANAGER.value),
    "manager_alt": build_user_headers(
        MANAGER_ALT_USER_ID, Role.DISTRIBUTION_MANAGER.value
    ),
}

ADMIN_HEADERS = TEST_USERS["admin"]
COORDINATOR_HEADERS = TEST_USERS["coordinator"]
COORDINATOR_ALT_HEADERS = TEST_USERS["coordinator_alt"]
OFFICER_HEADERS = TEST_USERS["officer"]
OFFICER_ALT_HEADERS = TEST_USERS["officer_alt"]
MANAGER_HEADERS = TEST_USERS["manager"]
MANAGER_ALT_HEADERS = TEST_USERS["manager_alt"]


def make_laboratory_user_headers(laboratory_id: str) -> Dict[str, str]:
    """Headers for a LaboratoryUser acting as the laboratory with this id."""
    return build_user_headers(laboratory_id, Role.LABORATORY_USER.value)


def make_supplier_user_headers(supplier_id: str) -> Dict[str, str]:
    """Headers for a SupplierUser acting as the supplier with this id."""
    return build_user_headers(supplier_id, Role.SUPPLIER_USER.value)


def make_headers(user_id: str, role: str) -> Dict[str, str]:
    """Headers for an arbitrary identity/role pair."""
    return build_user_headers(user_id, role)
