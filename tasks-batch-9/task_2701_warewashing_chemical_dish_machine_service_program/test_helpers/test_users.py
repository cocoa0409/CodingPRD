"""
Caller identities and header builders — §2.1 of the PRD.

Three roles carry an opaque `X-User-ID` (`AccountManager`, `QualityAuditor`,
`PlatformAdmin`) and therefore get fixed constants here. Two roles are
entity-backed and their `X-User-ID` must be the identifier of a row created
during the test, so they get builder functions instead:

- `ServiceTechnician` — `X-User-ID` is the `id` of the acting `Technician` row.
- `CustomerContact` — `X-User-ID` is the `id` of the acting `Customer`.
"""

from prd_bench_local_runner.testing import build_user_headers

from .types import (
    ROLE_ACCOUNT_MANAGER,
    ROLE_CUSTOMER_CONTACT,
    ROLE_PLATFORM_ADMIN,
    ROLE_QUALITY_AUDITOR,
    ROLE_SERVICE_TECHNICIAN,
)

# ─── Opaque operator identifiers ──────────────────────────────────────

ACCOUNT_MANAGER_ID = "am-1"
ACCOUNT_MANAGER_2_ID = "am-2"
PLATFORM_ADMIN_ID = "admin-1"

# Segregation of duties (§2.11) needs three distinct auditor identities to
# carry a variance from draft through publication to adjudication.
AUDITOR_1_ID = "auditor-1"
AUDITOR_2_ID = "auditor-2"
AUDITOR_3_ID = "auditor-3"

ACCOUNT_MANAGER_HEADERS = build_user_headers(ACCOUNT_MANAGER_ID, ROLE_ACCOUNT_MANAGER)
ACCOUNT_MANAGER_2_HEADERS = build_user_headers(
    ACCOUNT_MANAGER_2_ID, ROLE_ACCOUNT_MANAGER
)
PLATFORM_ADMIN_HEADERS = build_user_headers(PLATFORM_ADMIN_ID, ROLE_PLATFORM_ADMIN)
AUDITOR_1_HEADERS = build_user_headers(AUDITOR_1_ID, ROLE_QUALITY_AUDITOR)
AUDITOR_2_HEADERS = build_user_headers(AUDITOR_2_ID, ROLE_QUALITY_AUDITOR)
AUDITOR_3_HEADERS = build_user_headers(AUDITOR_3_ID, ROLE_QUALITY_AUDITOR)


# ─── Entity-backed identity builders ──────────────────────────────────


def make_technician_headers(technician_id: str) -> dict:
    """Headers for a ServiceTechnician acting as the given Technician row."""
    return build_user_headers(technician_id, ROLE_SERVICE_TECHNICIAN)


def make_customer_contact_headers(customer_id: str) -> dict:
    """Headers for a CustomerContact acting for the given Customer row."""
    return build_user_headers(customer_id, ROLE_CUSTOMER_CONTACT)


def make_auditor_headers(auditor_id: str) -> dict:
    """Headers for a QualityAuditor with an arbitrary opaque identifier."""
    return build_user_headers(auditor_id, ROLE_QUALITY_AUDITOR)


def make_account_manager_headers(user_id: str) -> dict:
    """Headers for an AccountManager with an arbitrary opaque identifier."""
    return build_user_headers(user_id, ROLE_ACCOUNT_MANAGER)


def make_platform_admin_headers(user_id: str) -> dict:
    """Headers for a PlatformAdmin with an arbitrary opaque identifier."""
    return build_user_headers(user_id, ROLE_PLATFORM_ADMIN)


# ─── Malformed identity headers for §2.1 authentication tests ─────────


def headers_missing_user_id(role: str) -> dict:
    """Headers with X-User-Role only — X-User-ID absent."""
    return {"X-User-Role": role, "Content-Type": "application/json"}


def headers_missing_role(user_id: str) -> dict:
    """Headers with X-User-ID only — X-User-Role absent."""
    return {"X-User-ID": user_id, "Content-Type": "application/json"}


def headers_empty_user_id(role: str) -> dict:
    """Headers whose X-User-ID is present but empty."""
    return {"X-User-ID": "", "X-User-Role": role, "Content-Type": "application/json"}


def headers_empty_role(user_id: str) -> dict:
    """Headers whose X-User-Role is present but empty."""
    return {
        "X-User-ID": user_id,
        "X-User-Role": "",
        "Content-Type": "application/json",
    }


NO_HEADERS: dict = {}
