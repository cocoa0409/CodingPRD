"""Auth headers for every role (PRD §2.1).

Five of the six roles carry an opaque operator identifier that is never
compared to any persisted row, so a fixed header dict per role is enough. The
``Customer`` role is different: ``X-User-ID`` must be the ``id`` of the acting
``ServiceAccount``, so customer headers can only be built once that account
exists — use :func:`make_customer_headers`.
"""

from typing import Dict

from prd_bench_local_runner.testing import build_user_headers

from .types import UserRole

# Opaque operator identifiers. Distinct values matter because segregation of
# duties and the hearing-officer conflict compare identifiers directly.
CSR_USER_ID = "csr-1"
CSR_ALT_USER_ID = "csr-2"
SUPERVISOR_USER_ID = "sup-1"
SUPERVISOR_ALT_USER_ID = "sup-2"
TECHNICIAN_USER_ID = "tech-1"
CLERK_USER_ID = "clerk-1"
CLERK_ALT_USER_ID = "clerk-2"
ADMIN_USER_ID = "admin-1"


def make_headers(role: str, user_id: str) -> Dict[str, str]:
    """Build headers for an arbitrary role/identifier pair."""
    return build_user_headers(user_id, role)


def make_customer_headers(account_id: str) -> Dict[str, str]:
    """Build ``Customer`` headers whose ``X-User-ID`` is a ServiceAccount id."""
    return build_user_headers(account_id, UserRole.CUSTOMER.value)


def make_csr_headers(user_id: str = CSR_USER_ID) -> Dict[str, str]:
    """Build ``CustomerServiceRep`` headers for a named operator."""
    return build_user_headers(user_id, UserRole.CUSTOMER_SERVICE_REP.value)


def make_supervisor_headers(user_id: str = SUPERVISOR_USER_ID) -> Dict[str, str]:
    """Build ``BillingSupervisor`` headers for a named operator."""
    return build_user_headers(user_id, UserRole.BILLING_SUPERVISOR.value)


def make_technician_headers(user_id: str = TECHNICIAN_USER_ID) -> Dict[str, str]:
    """Build ``MeterTechnician`` headers for a named operator."""
    return build_user_headers(user_id, UserRole.METER_TECHNICIAN.value)


def make_clerk_headers(user_id: str = CLERK_USER_ID) -> Dict[str, str]:
    """Build ``UtilityBoardClerk`` headers for a named operator."""
    return build_user_headers(user_id, UserRole.UTILITY_BOARD_CLERK.value)


def make_admin_headers(user_id: str = ADMIN_USER_ID) -> Dict[str, str]:
    """Build ``SystemAdmin`` headers for a named operator."""
    return build_user_headers(user_id, UserRole.SYSTEM_ADMIN.value)


# Ready-made headers for the five opaque-identity roles.
TEST_USERS: Dict[str, Dict[str, str]] = {
    "csr": make_csr_headers(),
    "csr_alt": make_csr_headers(CSR_ALT_USER_ID),
    "supervisor": make_supervisor_headers(),
    "supervisor_alt": make_supervisor_headers(SUPERVISOR_ALT_USER_ID),
    "technician": make_technician_headers(),
    "clerk": make_clerk_headers(),
    "clerk_alt": make_clerk_headers(CLERK_ALT_USER_ID),
    "system_admin": make_admin_headers(),
}

CSR_HEADERS = TEST_USERS["csr"]
CSR_ALT_HEADERS = TEST_USERS["csr_alt"]
SUPERVISOR_HEADERS = TEST_USERS["supervisor"]
SUPERVISOR_ALT_HEADERS = TEST_USERS["supervisor_alt"]
TECHNICIAN_HEADERS = TEST_USERS["technician"]
CLERK_HEADERS = TEST_USERS["clerk"]
CLERK_ALT_HEADERS = TEST_USERS["clerk_alt"]
ADMIN_HEADERS = TEST_USERS["system_admin"]

# Every role name, including the entity-backed Customer role.
ALL_ROLE_NAMES = [role.value for role in UserRole]


def headers_without_role(user_id: str = CSR_USER_ID) -> Dict[str, str]:
    """Headers carrying ``X-User-ID`` but no ``X-User-Role``."""
    return {"X-User-ID": user_id, "Content-Type": "application/json"}


def headers_without_user_id(role: str = UserRole.CUSTOMER_SERVICE_REP.value) -> Dict[str, str]:
    """Headers carrying ``X-User-Role`` but no ``X-User-ID``."""
    return {"X-User-Role": role, "Content-Type": "application/json"}


def headers_with_empty_role(user_id: str = CSR_USER_ID) -> Dict[str, str]:
    """Headers whose ``X-User-Role`` is present but empty."""
    return {
        "X-User-ID": user_id,
        "X-User-Role": "",
        "Content-Type": "application/json",
    }


def headers_with_empty_user_id(
    role: str = UserRole.CUSTOMER_SERVICE_REP.value,
) -> Dict[str, str]:
    """Headers whose ``X-User-ID`` is present but empty."""
    return {
        "X-User-ID": "",
        "X-User-Role": role,
        "Content-Type": "application/json",
    }


def headers_with_unknown_role(user_id: str = CSR_USER_ID) -> Dict[str, str]:
    """Headers naming a role that is not one of the six declared names."""
    return build_user_headers(user_id, "WaterCommissioner")


def no_headers() -> Dict[str, str]:
    """Only the content type — neither identity header is present."""
    return {"Content-Type": "application/json"}
