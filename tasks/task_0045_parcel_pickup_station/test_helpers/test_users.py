"""Pre-built role headers for every role in the PRD.

PRD §2.1 distinguishes two role identity shapes:

- PlatformAdmin, Recipient, CourierCompany, PaymentSystem carry an
  opaque operator id in X-User-ID. PRD §2.1: 'When X-User-Role is
  PlatformAdmin, Recipient, CourierCompany, or PaymentSystem, X-User-ID
  is an opaque operator identifier not tied to any persisted entity;
  the server may record it (for example, as actor_id on AuditEvent
  rows the relevant transition writes) but does not compare it to any
  entity's id.' The shared TEST_USERS constants are canonical for
  these roles.

- Manager and Clerk are entity-backed by Staff. PRD §2.1: 'When
  X-User-Role is Manager, X-User-ID is the id of the acting Staff
  record; when X-User-Role is Clerk, X-User-ID is likewise the id of
  the acting Staff record. For both roles, any ownership or
  station-scoping check on a resource that references a Staff (for
  example, the staff actor recorded on an AuditEvent) compares the
  resource's foreign key to X-User-ID.' Fixtures that create real
  Staff rows MUST use make_manager_headers(staff_id) /
  make_clerk_headers(staff_id) when the downstream call would
  exercise ownership.
"""
from __future__ import annotations

from typing import Dict

from prd_bench_local_runner.testing import build_user_headers


# ---------------------------------------------------------------------------
# Shared constants. Canonical for opaque roles; fallback for the
# entity-backed Manager/Clerk roles only on tests that do NOT exercise
# an ownership comparison (e.g., ERR_AUTH_MISSING, ERR_FORBIDDEN,
# ERR_RESOURCE_NOT_FOUND, ERR_VALIDATION on a missing/invalid payload).
# ---------------------------------------------------------------------------
TEST_USERS: Dict[str, Dict[str, str]] = {
    # Opaque roles -- canonical shared constants.
    "platform_admin_headers": build_user_headers("admin-001", "PlatformAdmin"),
    "platform_admin_headers_alt": build_user_headers("admin-002", "PlatformAdmin"),
    "recipient_headers": build_user_headers("recipient-001", "Recipient"),
    "recipient_headers_alt": build_user_headers("recipient-002", "Recipient"),
    "courier_company_headers": build_user_headers(
        "courier-co-001", "CourierCompany"
    ),
    "payment_system_headers": build_user_headers(
        "payment-system-001", "PaymentSystem"
    ),

    # Fallback constants for entity-backed Manager/Clerk roles. These
    # are NOT canonical: any ownership-gated test path MUST use the
    # make_* builders below with a real Staff.id.
    "manager_headers": build_user_headers("manager-fallback", "Manager"),
    "clerk_headers": build_user_headers("clerk-fallback", "Clerk"),
}


# ---------------------------------------------------------------------------
# Per-instance builders for the entity-backed Manager / Clerk roles.
# Pass the actual Staff.id minted by POST /stations/{id}/staff so that
# X-User-ID resolves to a real entity.
# ---------------------------------------------------------------------------
def make_manager_headers(staff_id: str) -> Dict[str, str]:
    """PRD §2.1: 'When X-User-Role is Manager, X-User-ID is the id of the
    acting Staff record.' Pass the Staff.id of a MANAGER role_kind staff
    member at the target station whenever the call is ownership-gated."""
    return build_user_headers(staff_id, "Manager")


def make_clerk_headers(staff_id: str) -> Dict[str, str]:
    """PRD §2.1: 'When X-User-Role is Clerk, X-User-ID is likewise the id
    of the acting Staff record.' Pass the Staff.id of a CLERK role_kind
    staff member at the target station whenever the call is
    ownership-gated (inbound, pickup, shelf reassignment)."""
    return build_user_headers(staff_id, "Clerk")


def make_platform_admin_headers(admin_id: str = "admin-001") -> Dict[str, str]:
    """PRD §2.1: PlatformAdmin X-User-ID is opaque."""
    return build_user_headers(admin_id, "PlatformAdmin")


def make_recipient_headers(recipient_id: str = "recipient-001") -> Dict[str, str]:
    """PRD §2.1: Recipient X-User-ID is opaque."""
    return build_user_headers(recipient_id, "Recipient")


def make_courier_company_headers(
    courier_id: str = "courier-co-001",
) -> Dict[str, str]:
    """PRD §2.1: CourierCompany X-User-ID is opaque."""
    return build_user_headers(courier_id, "CourierCompany")


def make_payment_system_headers(
    payment_id: str = "payment-system-001",
) -> Dict[str, str]:
    """PRD §2.1: PaymentSystem X-User-ID is opaque."""
    return build_user_headers(payment_id, "PaymentSystem")


__all__ = [
    "TEST_USERS",
    "make_manager_headers",
    "make_clerk_headers",
    "make_platform_admin_headers",
    "make_recipient_headers",
    "make_courier_company_headers",
    "make_payment_system_headers",
]
