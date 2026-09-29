"""Header builders for the five roles of PRD 2.1.

Identity semantics differ by role and they decide how ownership is checked:

* `BrokerAdmin`, `BrokerAccountManager` and `BrokerAuditManager` carry an opaque
  operator identifier that "is not tied to any persisted entity", so a shared
  constant is correct for them.
* `RetailerBuyer` carries the `id` of the acting `Retailer`.
* `PrincipalPortalUser` carries the `id` of the acting `Principal`.

For the two entity-backed roles the caller MUST thread the real entity id through
`make_retailer_buyer_headers()` / `make_principal_portal_headers()`; using a
placeholder would trip the ownership-scope band rather than the rule under test.
"""

from typing import Dict

from prd_bench_local_runner.testing import build_user_headers

from .types import Role

# Opaque operator identifiers for the three broker-side roles, plus placeholder
# identifiers for the two entity-backed roles (only usable where no ownership
# check applies, e.g. authentication and role-permission assertions).
TEST_USERS: Dict[str, Dict[str, str]] = {
    "broker_admin": {"user_id": "u_admin_1", "role": Role.BROKER_ADMIN},
    "account_manager": {"user_id": "u_am_1", "role": Role.BROKER_ACCOUNT_MANAGER},
    "account_manager_2": {"user_id": "u_am_2", "role": Role.BROKER_ACCOUNT_MANAGER},
    "audit_manager": {"user_id": "u_audit_1", "role": Role.BROKER_AUDIT_MANAGER},
    "audit_manager_2": {"user_id": "u_audit_2", "role": Role.BROKER_AUDIT_MANAGER},
    "retailer_buyer": {"user_id": "u_buyer_unbound", "role": Role.RETAILER_BUYER},
    "principal_portal": {"user_id": "u_portal_unbound", "role": Role.PRINCIPAL_PORTAL_USER},
}

# Ready-made header dicts for the opaque broker roles.
BROKER_ADMIN_HEADERS = build_user_headers("u_admin_1", Role.BROKER_ADMIN)
ACCOUNT_MANAGER_HEADERS = build_user_headers("u_am_1", Role.BROKER_ACCOUNT_MANAGER)
ACCOUNT_MANAGER_2_HEADERS = build_user_headers("u_am_2", Role.BROKER_ACCOUNT_MANAGER)
AUDIT_MANAGER_HEADERS = build_user_headers("u_audit_1", Role.BROKER_AUDIT_MANAGER)
AUDIT_MANAGER_2_HEADERS = build_user_headers("u_audit_2", Role.BROKER_AUDIT_MANAGER)

FILER_USER_ID = "u_am_1"
APPROVER_USER_ID = "u_audit_1"


def make_broker_admin_headers(user_id: str = "u_admin_1") -> Dict[str, str]:
    return build_user_headers(user_id, Role.BROKER_ADMIN)


def make_account_manager_headers(user_id: str = "u_am_1") -> Dict[str, str]:
    return build_user_headers(user_id, Role.BROKER_ACCOUNT_MANAGER)


def make_audit_manager_headers(user_id: str = "u_audit_1") -> Dict[str, str]:
    return build_user_headers(user_id, Role.BROKER_AUDIT_MANAGER)


def make_retailer_buyer_headers(retailer_id: str) -> Dict[str, str]:
    """`X-User-ID` is the `id` of the acting `Retailer` (PRD 2.1)."""
    return build_user_headers(retailer_id, Role.RETAILER_BUYER)


def make_principal_portal_headers(principal_id: str) -> Dict[str, str]:
    """`X-User-ID` is the `id` of the acting `Principal` (PRD 2.1)."""
    return build_user_headers(principal_id, Role.PRINCIPAL_PORTAL_USER)


def headers_for_role(role: str, entity_id: str = "u_generic_1") -> Dict[str, str]:
    """Build headers for any role; `entity_id` is required for the two scoped roles."""
    return build_user_headers(entity_id, role)
