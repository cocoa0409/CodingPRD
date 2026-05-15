"""Pre-built role headers for every role in the PRD.

PRD §2.1 identity rules:

- Customer is ENTITY-BACKED.
  'When X-User-Role is Customer, X-User-ID is the id of the acting
  Customer; ownership checks on any resource that ultimately references
  a Customer ... compare the resource's customer_id (or transitively the
  owning Customer's id) to X-User-ID.'
  Every ownership-gated Customer call MUST use
  make_customer_headers(customer['id']) — passing a shared fallback
  constant guarantees the ownership check rejects every request and
  cascades 'Setup failed' into every downstream test.

- AdminOps, PaymentAdapter, LogisticsAdapter, VetAdapter all carry
  OPAQUE X-User-IDs ('not tied to any persisted entity ... but never
  compared to an entity id'). Shared constants are canonical for these
  four roles.
"""
from __future__ import annotations
from typing import Dict

from prd_bench_local_runner.testing import build_user_headers


# ---------------------------------------------------------------------------
# Shared opaque-role constants (canonical for AdminOps + adapters) and a
# non-binding Customer fallback for ownership-irrelevant tests only.
# ---------------------------------------------------------------------------
TEST_USERS: Dict[str, Dict[str, str]] = {
    # AdminOps (opaque) — used for catalog seeding, warehouse seeding,
    # audit-log reads, and the test-driver endpoints.
    "admin_ops_headers": build_user_headers(
        "admin-ops-001", "AdminOps",
    ),
    "admin_ops_headers_alt": build_user_headers(
        "admin-ops-002", "AdminOps",
    ),

    # PaymentAdapter (opaque) — drives /orders/{id}/events/payment
    "payment_adapter_headers": build_user_headers(
        "payment-adapter-001", "PaymentAdapter",
    ),

    # LogisticsAdapter (opaque) — drives /orders/{id}/events/logistics
    "logistics_adapter_headers": build_user_headers(
        "logistics-adapter-001", "LogisticsAdapter",
    ),

    # VetAdapter (opaque) — drives /pets/{petId}/recipe-adjustments/{adjId}/events/vet
    "vet_adapter_headers": build_user_headers(
        "vet-adapter-001", "VetAdapter",
    ),

    # Customer fallback — X-User-ID 'customer-fallback' matches no real
    # Customer.id. Use ONLY for tests that do NOT exercise ownership:
    # missing-auth, wrong-role, missing-resource.
    "customer_headers": build_user_headers(
        "customer-fallback", "Customer",
    ),
}


# ---------------------------------------------------------------------------
# Per-instance builder — REQUIRED for the entity_backed Customer role.
# ---------------------------------------------------------------------------
def make_customer_headers(customer_id: str) -> Dict[str, str]:
    """PRD §2.1: 'When X-User-Role is Customer, X-User-ID is the id of
    the acting Customer.' Pass the actual Customer.id returned by
    POST /customers whenever the call is ownership-gated."""
    return build_user_headers(customer_id, "Customer")


def make_admin_ops_headers(user_id: str) -> Dict[str, str]:
    """PRD §2.1: AdminOps X-User-ID is opaque. Use when a test wants a
    distinct operator id (e.g., to distinguish AuditLog.actor_id rows)."""
    return build_user_headers(user_id, "AdminOps")


def make_payment_adapter_headers(user_id: str) -> Dict[str, str]:
    """PRD §2.1: PaymentAdapter X-User-ID is opaque."""
    return build_user_headers(user_id, "PaymentAdapter")


def make_logistics_adapter_headers(user_id: str) -> Dict[str, str]:
    """PRD §2.1: LogisticsAdapter X-User-ID is opaque."""
    return build_user_headers(user_id, "LogisticsAdapter")


def make_vet_adapter_headers(user_id: str) -> Dict[str, str]:
    """PRD §2.1: VetAdapter X-User-ID is opaque."""
    return build_user_headers(user_id, "VetAdapter")


__all__ = [
    "TEST_USERS",
    "make_customer_headers",
    "make_admin_ops_headers",
    "make_payment_adapter_headers",
    "make_logistics_adapter_headers",
    "make_vet_adapter_headers",
]
