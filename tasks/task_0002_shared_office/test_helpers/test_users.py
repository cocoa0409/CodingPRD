"""Pre-built role headers for every role recognized by the Shared Office API.

Per PRD §2.1 the six recognized roles split into two identity groups:
  - `TenantAdmin` and `TenantMember` are *entity-backed*: `X-User-ID` is the `id` of
    the acting `Member`, and the server compares the resource's foreign-key field
    (for example, `reservation.member_id` or `visitor.host_member_id`) to
    `X-User-ID`.
  - `PlatformAdmin`, `Receptionist`, `BillingOfficer`, and `PaymentClerk` are
    *opaque*: `X-User-ID` is a bare operator identifier not compared to any entity.

Two forms are therefore provided for each role:

- A shared-constant entry in `TEST_USERS` — safe only for tests whose success does
  not depend on the caller owning a specific resource. Opaque roles use the shared
  constant as their canonical form. Entity-backed fallbacks are included strictly
  for non-ownership checks (for example, forbidden-role probes).

- A per-instance builder `make_<role>_headers(user_id)` — **mandatory for every
  entity-backed role** whenever the downstream call is ownership-gated. Fixtures
  must pass the actual Member's `id` so the ownership check on the server resolves
  correctly; falling back to a shared constant would cause every ownership check
  to reject the request.

Per PRD §3.6, each `PlatformAdmin` needing to exercise segregation of duties on
lease finalize-termination must carry a distinct `X-User-ID`; the helpers
`make_platform_admin_headers(user_id)` below let tests mint as many distinct
PlatformAdmin identities as they need.
"""

from typing import Dict

from prd_bench_local_runner.testing import build_user_headers


# ──────────────────────────────────────────────────────────
# Shared constants — canonical form for opaque roles; fallback-only for
# entity-backed roles (see note above).
# ──────────────────────────────────────────────────────────

TEST_USERS: Dict[str, Dict[str, str]] = {
    # Opaque roles (PRD §2.1): X-User-ID never compared to any entity id.
    "admin_headers": build_user_headers("test-platform-admin-1", "PlatformAdmin"),
    "admin_headers_alt": build_user_headers("test-platform-admin-2", "PlatformAdmin"),
    "receptionist_headers": build_user_headers("test-receptionist-1", "Receptionist"),
    "billing_officer_headers": build_user_headers("test-billing-officer-1", "BillingOfficer"),
    "payment_clerk_headers": build_user_headers("test-payment-clerk-1", "PaymentClerk"),
    # Entity-backed fallbacks — valid only for tests that do not exercise ownership
    # (for example, forbidden-role probes that should fail on RBAC before reaching
    # any ownership check).
    "tenant_admin_headers_fallback": build_user_headers(
        "test-tenant-admin-fallback", "TenantAdmin"
    ),
    "tenant_member_headers_fallback": build_user_headers(
        "test-tenant-member-fallback", "TenantMember"
    ),
}


# ──────────────────────────────────────────────────────────
# Per-instance builders — REQUIRED whenever the call is ownership-gated.
# ──────────────────────────────────────────────────────────


def make_tenant_admin_headers(member_id: str) -> Dict[str, str]:
    """Build TenantAdmin headers where X-User-ID == Member.id of a tenant-admin
    member. PRD §2.1 specifies that when X-User-Role is TenantAdmin the value of
    X-User-ID is the id of the acting Member."""
    return build_user_headers(member_id, "TenantAdmin")


def make_tenant_member_headers(member_id: str) -> Dict[str, str]:
    """Build TenantMember headers where X-User-ID == Member.id. PRD §2.1: ownership
    checks on reservation.member_id and visitor.host_member_id compare the
    resource's foreign key to X-User-ID."""
    return build_user_headers(member_id, "TenantMember")


def make_platform_admin_headers(user_id: str) -> Dict[str, str]:
    """Build PlatformAdmin headers with an arbitrary opaque user_id. PRD §3.6 calls
    for two DIFFERENT PlatformAdmin X-User-IDs across begin-review and
    finalize-termination to satisfy segregation of duties."""
    return build_user_headers(user_id, "PlatformAdmin")


def make_receptionist_headers(user_id: str = "test-receptionist-1") -> Dict[str, str]:
    """Build Receptionist headers (opaque identity)."""
    return build_user_headers(user_id, "Receptionist")


def make_billing_officer_headers(user_id: str = "test-billing-officer-1") -> Dict[str, str]:
    """Build BillingOfficer headers (opaque identity)."""
    return build_user_headers(user_id, "BillingOfficer")


def make_payment_clerk_headers(user_id: str = "test-payment-clerk-1") -> Dict[str, str]:
    """Build PaymentClerk headers (opaque identity)."""
    return build_user_headers(user_id, "PaymentClerk")
