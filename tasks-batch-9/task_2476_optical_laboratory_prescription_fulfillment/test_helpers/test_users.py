"""Acting identities used across the suite.

Every request carries ``X-User-ID`` and ``X-User-Role``. For five of the six
roles ``X-User-ID`` is an opaque operator identifier not tied to any persisted
entity; for the ``Prescriber`` role it is the ``id`` of the acting prescriber
row, so those headers are built from a captured id instead of a constant.
"""

from prd_bench_local_runner.testing import build_user_headers

from .types import UserRole

# Fixed opaque operator identifiers. Two opticians, two technicians and one
# each of inspector, manager and benefits administrator, so that
# segregation-of-duties scenarios always have a second identity to fall back on.
OPTICIAN_A = "0a000000-0000-4000-8000-000000000001"
OPTICIAN_B = "0a000000-0000-4000-8000-000000000002"
TECHNICIAN_A = "0b000000-0000-4000-8000-000000000001"
TECHNICIAN_B = "0b000000-0000-4000-8000-000000000002"
INSPECTOR_A = "0c000000-0000-4000-8000-000000000001"
INSPECTOR_B = "0c000000-0000-4000-8000-000000000002"
MANAGER_A = "0d000000-0000-4000-8000-000000000001"
MANAGER_B = "0d000000-0000-4000-8000-000000000002"
BENEFITS_A = "0e000000-0000-4000-8000-000000000001"


TEST_USERS = {
    "optician_a": {"user_id": OPTICIAN_A, "role": UserRole.STORE_OPTICIAN.value},
    "optician_b": {"user_id": OPTICIAN_B, "role": UserRole.STORE_OPTICIAN.value},
    "technician_a": {"user_id": TECHNICIAN_A, "role": UserRole.LAB_TECHNICIAN.value},
    "technician_b": {"user_id": TECHNICIAN_B, "role": UserRole.LAB_TECHNICIAN.value},
    "inspector_a": {"user_id": INSPECTOR_A, "role": UserRole.QUALITY_INSPECTOR.value},
    "inspector_b": {"user_id": INSPECTOR_B, "role": UserRole.QUALITY_INSPECTOR.value},
    "manager_a": {"user_id": MANAGER_A, "role": UserRole.LAB_MANAGER.value},
    "manager_b": {"user_id": MANAGER_B, "role": UserRole.LAB_MANAGER.value},
    "benefits_a": {"user_id": BENEFITS_A, "role": UserRole.BENEFITS_ADMINISTRATOR.value},
}


def make_optician_headers(user_id: str = OPTICIAN_A) -> dict:
    return build_user_headers(user_id, UserRole.STORE_OPTICIAN.value)


def make_technician_headers(user_id: str = TECHNICIAN_A) -> dict:
    return build_user_headers(user_id, UserRole.LAB_TECHNICIAN.value)


def make_inspector_headers(user_id: str = INSPECTOR_A) -> dict:
    return build_user_headers(user_id, UserRole.QUALITY_INSPECTOR.value)


def make_manager_headers(user_id: str = MANAGER_A) -> dict:
    return build_user_headers(user_id, UserRole.LAB_MANAGER.value)


def make_benefits_headers(user_id: str = BENEFITS_A) -> dict:
    return build_user_headers(user_id, UserRole.BENEFITS_ADMINISTRATOR.value)


def make_prescriber_headers(prescriber_id: str) -> dict:
    """The ``Prescriber`` role is entity-backed: ``X-User-ID`` is the row id."""
    return build_user_headers(prescriber_id, UserRole.PRESCRIBER.value)


OPTICIAN_A_HEADERS = make_optician_headers(OPTICIAN_A)
OPTICIAN_B_HEADERS = make_optician_headers(OPTICIAN_B)
TECHNICIAN_A_HEADERS = make_technician_headers(TECHNICIAN_A)
TECHNICIAN_B_HEADERS = make_technician_headers(TECHNICIAN_B)
INSPECTOR_A_HEADERS = make_inspector_headers(INSPECTOR_A)
INSPECTOR_B_HEADERS = make_inspector_headers(INSPECTOR_B)
MANAGER_A_HEADERS = make_manager_headers(MANAGER_A)
MANAGER_B_HEADERS = make_manager_headers(MANAGER_B)
BENEFITS_A_HEADERS = make_benefits_headers(BENEFITS_A)
