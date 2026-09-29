"""
Identity headers for the seven roles of the Valve Manufacturing API (PRD §2.1).

Every request must carry ``X-User-ID`` and ``X-User-Role``. Six of the seven roles
carry an opaque identity — ``X-User-ID`` is an operator identifier that is never
compared against any entity's ``id`` — so the default operator identifiers below are
arbitrary but stable. ``SupplierRep`` is the exception: its ``X-User-ID`` is the ``id``
of the acting foundry, so its headers must be built per foundry with
``make_supplier_rep_headers(foundry_id)``.
"""

from prd_bench_local_runner.testing import build_user_headers

from .constants import (
    ROLE_FIELD_SERVICE_COORDINATOR,
    ROLE_MONOGRAM_AUDITOR,
    ROLE_PROCUREMENT_SPECIALIST,
    ROLE_PRODUCT_ENGINEER,
    ROLE_QUALITY_MANAGER,
    ROLE_SUPPLIER_REP,
    ROLE_TEST_TECHNICIAN,
)
from .types import Headers

# Default opaque operator identifiers, one per role that carries an opaque identity.
DEFAULT_USER_IDS = {
    ROLE_PRODUCT_ENGINEER: "pe-1",
    ROLE_PROCUREMENT_SPECIALIST: "proc-1",
    ROLE_TEST_TECHNICIAN: "tech-1",
    ROLE_QUALITY_MANAGER: "qm-1",
    ROLE_MONOGRAM_AUDITOR: "aud-1",
    ROLE_FIELD_SERVICE_COORDINATOR: "fsc-1",
}

TEST_USERS = {
    role: build_user_headers(user_id, role) for role, user_id in DEFAULT_USER_IDS.items()
}


def make_headers(role: str, user_id: str) -> Headers:
    """Headers for an arbitrary role/identity pair."""
    return build_user_headers(user_id, role)


def make_product_engineer_headers(user_id: str = "pe-1") -> Headers:
    return build_user_headers(user_id, ROLE_PRODUCT_ENGINEER)


def make_procurement_specialist_headers(user_id: str = "proc-1") -> Headers:
    return build_user_headers(user_id, ROLE_PROCUREMENT_SPECIALIST)


def make_test_technician_headers(user_id: str = "tech-1") -> Headers:
    return build_user_headers(user_id, ROLE_TEST_TECHNICIAN)


def make_quality_manager_headers(user_id: str = "qm-1") -> Headers:
    return build_user_headers(user_id, ROLE_QUALITY_MANAGER)


def make_monogram_auditor_headers(user_id: str = "aud-1") -> Headers:
    return build_user_headers(user_id, ROLE_MONOGRAM_AUDITOR)


def make_field_service_coordinator_headers(user_id: str = "fsc-1") -> Headers:
    return build_user_headers(user_id, ROLE_FIELD_SERVICE_COORDINATOR)


def make_supplier_rep_headers(foundry_id: str) -> Headers:
    """When ``X-User-Role`` is ``SupplierRep``, ``X-User-ID`` is the ``id`` of the
    acting ``Foundry``; ownership checks compare a resource's ``foundry_id`` to it."""
    return build_user_headers(foundry_id, ROLE_SUPPLIER_REP)


def make_headers_without_identity(role: str) -> Headers:
    """Headers whose ``X-User-ID`` is empty — the §2.1 unauthenticated case."""
    return build_user_headers("", role)


PRODUCT_ENGINEER = TEST_USERS[ROLE_PRODUCT_ENGINEER]
PROCUREMENT_SPECIALIST = TEST_USERS[ROLE_PROCUREMENT_SPECIALIST]
TEST_TECHNICIAN = TEST_USERS[ROLE_TEST_TECHNICIAN]
QUALITY_MANAGER = TEST_USERS[ROLE_QUALITY_MANAGER]
MONOGRAM_AUDITOR = TEST_USERS[ROLE_MONOGRAM_AUDITOR]
FIELD_SERVICE_COORDINATOR = TEST_USERS[ROLE_FIELD_SERVICE_COORDINATOR]
