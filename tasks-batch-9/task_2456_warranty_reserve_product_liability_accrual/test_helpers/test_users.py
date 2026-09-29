"""Header builders for the six roles (PRD §2.1).

Every mutating request carries `X-User-ID` and `X-User-Role`. For a
`SupplierRep` the `X-User-ID` is not an opaque identifier: it is the acting
`Supplier.id`, so its headers must always be threaded from a registered
supplier row.
"""

from typing import Dict, Optional
from uuid import uuid4

from prd_bench_local_runner.testing import build_user_headers

from .types import UserRole

# Stable opaque identifiers for the roles whose X-User-ID the PRD treats as
# opaque. Distinct values per role keep segregation-of-duties checks honest.
WARRANTY_ANALYST_USER_ID = "11111111-1111-4111-8111-111111111111"
WARRANTY_ANALYST_ALT_USER_ID = "11111111-1111-4111-8111-1111111111a2"
RESERVE_CONTROLLER_USER_ID = "22222222-2222-4222-8222-222222222222"
RESERVE_CONTROLLER_ALT_USER_ID = "22222222-2222-4222-8222-2222222222a2"
QUALITY_ENGINEER_USER_ID = "33333333-3333-4333-8333-333333333333"
QUALITY_ENGINEER_ALT_USER_ID = "33333333-3333-4333-8333-3333333333a2"
ACTUARY_USER_ID = "44444444-4444-4444-8444-444444444444"
ACTUARY_ALT_USER_ID = "44444444-4444-4444-8444-4444444444a2"
PLATFORM_ADMIN_USER_ID = "55555555-5555-4555-8555-555555555555"


def _headers(user_id: str, role: str) -> Dict[str, str]:
    return build_user_headers(user_id, role)


def make_warranty_analyst_headers(user_id: Optional[str] = None) -> Dict[str, str]:
    return _headers(user_id or WARRANTY_ANALYST_USER_ID, UserRole.WARRANTY_ANALYST.value)


def make_reserve_controller_headers(user_id: Optional[str] = None) -> Dict[str, str]:
    return _headers(user_id or RESERVE_CONTROLLER_USER_ID, UserRole.RESERVE_CONTROLLER.value)


def make_quality_engineer_headers(user_id: Optional[str] = None) -> Dict[str, str]:
    return _headers(user_id or QUALITY_ENGINEER_USER_ID, UserRole.QUALITY_ENGINEER.value)


def make_actuary_headers(user_id: Optional[str] = None) -> Dict[str, str]:
    return _headers(user_id or ACTUARY_USER_ID, UserRole.ACTUARY.value)


def make_platform_admin_headers(user_id: Optional[str] = None) -> Dict[str, str]:
    return _headers(user_id or PLATFORM_ADMIN_USER_ID, UserRole.PLATFORM_ADMIN.value)


def make_supplier_rep_headers(supplier_id: str) -> Dict[str, str]:
    """A supplier representative acts as the supplier named by `X-User-ID`."""
    return _headers(supplier_id, UserRole.SUPPLIER_REP.value)


# Ready-made header dicts for the opaque-identity roles.
ANALYST_HEADERS = make_warranty_analyst_headers()
ANALYST_ALT_HEADERS = make_warranty_analyst_headers(WARRANTY_ANALYST_ALT_USER_ID)
CONTROLLER_HEADERS = make_reserve_controller_headers()
CONTROLLER_ALT_HEADERS = make_reserve_controller_headers(RESERVE_CONTROLLER_ALT_USER_ID)
ENGINEER_HEADERS = make_quality_engineer_headers()
ENGINEER_ALT_HEADERS = make_quality_engineer_headers(QUALITY_ENGINEER_ALT_USER_ID)
ACTUARY_HEADERS = make_actuary_headers()
ACTUARY_ALT_HEADERS = make_actuary_headers(ACTUARY_ALT_USER_ID)
ADMIN_HEADERS = make_platform_admin_headers()

ALL_ROLE_HEADERS = {
    UserRole.WARRANTY_ANALYST.value: ANALYST_HEADERS,
    UserRole.RESERVE_CONTROLLER.value: CONTROLLER_HEADERS,
    UserRole.QUALITY_ENGINEER.value: ENGINEER_HEADERS,
    UserRole.ACTUARY.value: ACTUARY_HEADERS,
    UserRole.PLATFORM_ADMIN.value: ADMIN_HEADERS,
}


def headers_without_role(user_id: Optional[str] = None) -> Dict[str, str]:
    """Authentication headers missing `X-User-Role` entirely."""
    return {"X-User-ID": user_id or WARRANTY_ANALYST_USER_ID, "Content-Type": "application/json"}


def headers_without_user_id(role: str = UserRole.WARRANTY_ANALYST.value) -> Dict[str, str]:
    """Authentication headers missing `X-User-ID` entirely."""
    return {"X-User-Role": role, "Content-Type": "application/json"}


def headers_with_unknown_role(user_id: Optional[str] = None) -> Dict[str, str]:
    """A role string outside the six declared roles."""
    return _headers(user_id or WARRANTY_ANALYST_USER_ID, "WarrantyOverlord")


def fresh_user_id() -> str:
    """A brand-new opaque actor identifier."""
    return str(uuid4())
