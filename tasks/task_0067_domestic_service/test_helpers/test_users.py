"""Pre-built role headers for the Domestic Service Dispatch API (PRD §2.1).

PRD §2.1 distinguishes four roles by identity flavor:

- `Customer` is *entity-backed*: when X-User-Role is Customer, X-User-ID MUST
  equal the id of the acting Customer. Ownership checks (e.g., for customer-
  accept, rate, cancel) compare Order.customer_id to X-User-ID. A Customer
  acting on someone else's order is rejected.

- `ServicePersonnel` is *entity-backed*: X-User-ID MUST equal the id of the
  acting ServicePersonnel. The accept/reject/checkin/complete order-action
  endpoints additionally check Order.assigned_personnel_id == X-User-ID and
  reject mismatches with ERR_NOT_ASSIGNED.

- `PlatformOperator` is *opaque*: X-User-ID is an opaque operator identifier
  that is not tied to any persisted entity. The server may record it (e.g.,
  on AuditLogEntry.actor_id) but never compares it to an entity's id.

- `system` is *opaque*: an internal identifier used by test-driving endpoints
  and inbound webhooks. Not compared to any persisted entity.

For each entity-backed role this module exposes a per-instance builder
(`make_customer_headers(customer_id)`, `make_personnel_headers(personnel_id)`).
Fixtures MUST call those builders with the actual entity id whenever the
downstream call is ownership-gated; the shared constants in TEST_USERS are
appropriate only for tests that never reach an ownership check
(RBAC probes, missing-header probes, NOT_FOUND probes, malformed-payload
probes).
"""

from typing import Dict

from prd_bench_local_runner.testing import build_user_headers


# ─────────────────────────────────────────────────────────────
# Shared constants — canonical form for opaque roles, fallback-only for
# entity-backed roles.
# ─────────────────────────────────────────────────────────────

TEST_USERS: Dict[str, Dict[str, str]] = {
    # Opaque roles: X-User-ID never compared to any entity id.
    "operator_headers": build_user_headers("test-operator-1", "PlatformOperator"),
    "operator_headers_alt": build_user_headers(
        "test-operator-2", "PlatformOperator"
    ),
    "system_headers": build_user_headers("test-system-1", "system"),
    # Entity-backed fallbacks — valid only for tests that do NOT exercise ownership.
    "customer_headers_fallback": build_user_headers(
        "test-customer-fallback", "Customer"
    ),
    "personnel_headers_fallback": build_user_headers(
        "test-personnel-fallback", "ServicePersonnel"
    ),
}


# ─────────────────────────────────────────────────────────────
# Per-instance builders — REQUIRED whenever the call is ownership-gated.
# ─────────────────────────────────────────────────────────────


def make_customer_headers(customer_id: str) -> Dict[str, str]:
    """Build Customer headers where X-User-ID equals the acting Customer.id.

    Per PRD §2.1, ownership checks on Order (customer-accept, rate, cancel),
    Customer profile reads, and recurring-order operations compare the
    resource's customer_id to X-User-ID. Fixtures must thread the real
    Customer.id so the ownership gate is genuinely exercised — a shared
    constant would always fail every ownership check, hiding implementation
    behavior.
    """
    return build_user_headers(customer_id, "Customer")


def make_personnel_headers(personnel_id: str) -> Dict[str, str]:
    """Build ServicePersonnel headers where X-User-ID equals the acting personnel.id.

    Per PRD §2.1, the personnel-acting endpoints (accept, reject, checkin,
    execution patch, complete) require X-User-ID == Order.assigned_personnel_id
    and return ERR_NOT_ASSIGNED on mismatch. Fixtures must thread the actual
    personnel.id used for dispatch.
    """
    return build_user_headers(personnel_id, "ServicePersonnel")


def make_operator_headers(
    user_id: str = "test-operator-1",
) -> Dict[str, str]:
    """PlatformOperator is opaque (PRD §2.1) — X-User-ID is not compared to any entity."""
    return build_user_headers(user_id, "PlatformOperator")


def make_system_headers(user_id: str = "test-system-1") -> Dict[str, str]:
    """system role is opaque (PRD §2.1)."""
    return build_user_headers(user_id, "system")
