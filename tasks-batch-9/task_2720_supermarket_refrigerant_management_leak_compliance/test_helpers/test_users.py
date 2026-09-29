"""
Role identities for the five roles of §2.1.

Three roles are opaque: `PlatformAdmin`, `ComplianceManager` and `Regulator`
carry any non-empty `X-User-ID`, so fixed operator strings are enough and two
distinct `Regulator` identities are kept because inspection closure compares the
closing principal against the principal who opened the inspection.

Two roles are entity-backed. A `Technician` acts under the `id` of their own
`Technician` row and a `StoreManager` under the `id` of the `Store` they manage,
so those headers can only be built after the row exists — hence the builders.
"""

from typing import Dict

from prd_bench_local_runner.testing import build_user_headers

from .types import (
    ROLE_COMPLIANCE_MANAGER,
    ROLE_PLATFORM_ADMIN,
    ROLE_REGULATOR,
    ROLE_STORE_MANAGER,
    ROLE_TECHNICIAN,
)

# ─── Opaque identities ────────────────────────────────────────────────

PLATFORM_ADMIN_USER_ID = "platform-admin-1"
COMPLIANCE_MANAGER_USER_ID = "compliance-manager-1"
COMPLIANCE_MANAGER_2_USER_ID = "compliance-manager-2"
REGULATOR_USER_ID = "regulator-1"
REGULATOR_2_USER_ID = "regulator-2"

PLATFORM_ADMIN_HEADERS = build_user_headers(PLATFORM_ADMIN_USER_ID, ROLE_PLATFORM_ADMIN)
COMPLIANCE_MANAGER_HEADERS = build_user_headers(
    COMPLIANCE_MANAGER_USER_ID, ROLE_COMPLIANCE_MANAGER
)
COMPLIANCE_MANAGER_2_HEADERS = build_user_headers(
    COMPLIANCE_MANAGER_2_USER_ID, ROLE_COMPLIANCE_MANAGER
)
REGULATOR_HEADERS = build_user_headers(REGULATOR_USER_ID, ROLE_REGULATOR)
REGULATOR_2_HEADERS = build_user_headers(REGULATOR_2_USER_ID, ROLE_REGULATOR)


# ─── Entity-backed identities ─────────────────────────────────────────


def make_technician_headers(technician_id: str) -> Dict[str, str]:
    """
    Headers for a `Technician`: `X-User-ID` is the id of the acting technician,
    which is what ownership checks compare the body's `technician_id` against.
    """
    return build_user_headers(technician_id, ROLE_TECHNICIAN)


def make_store_manager_headers(store_id: str) -> Dict[str, str]:
    """
    Headers for a `StoreManager`: `X-User-ID` is the id of the managed store,
    which is what the store-scope checks compare a resource's `store_id` against.
    """
    return build_user_headers(store_id, ROLE_STORE_MANAGER)


# ─── Malformed identities, for the authentication checks ──────────────

NO_HEADERS: Dict[str, str] = {}

MISSING_ROLE_HEADERS = {"X-User-ID": COMPLIANCE_MANAGER_USER_ID}

MISSING_USER_ID_HEADERS = {"X-User-Role": ROLE_COMPLIANCE_MANAGER}

EMPTY_USER_ID_HEADERS = {
    "X-User-ID": "",
    "X-User-Role": ROLE_COMPLIANCE_MANAGER,
}

EMPTY_ROLE_HEADERS = {
    "X-User-ID": COMPLIANCE_MANAGER_USER_ID,
    "X-User-Role": "",
}

UNDECLARED_ROLE_HEADERS = build_user_headers("someone-1", "RefrigerantAuditor")

#: Every role that may read any resource (§4: read endpoints are open to all).
ALL_READER_HEADERS = (
    PLATFORM_ADMIN_HEADERS,
    COMPLIANCE_MANAGER_HEADERS,
    REGULATOR_HEADERS,
)
