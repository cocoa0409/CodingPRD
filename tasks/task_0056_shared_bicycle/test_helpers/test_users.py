"""Pre-built role headers for every role in the PRD.

PRD §2.1 identity rules:

- Operator / FieldStaff / Admin carry OPAQUE X-User-IDs. 'When
  X-User-Role is Operator, X-User-ID is an opaque operator identifier
  not tied to any persisted entity. The server may record it (for
  example as assigned_operator_id on a WorkOrder after assignment, or
  as actor_id on AuditLog) but does not compare it to any entity's id.
  The same opaque-identifier semantics apply when X-User-Role is
  FieldStaff or Admin.' Shared constants are safe for these roles.

- Rider is ENTITY-BACKED. 'When X-User-Role is Rider, X-User-ID is the
  id of the acting Rider entity; ownership checks on any resource that
  references a Rider (for instance, Ride.rider_id) compare the
  resource's foreign-key field to X-User-ID. A rider may read and act
  only on their own Ride records and only on their own Rider record.'
  Every ownership-gated Rider-role call MUST use make_rider_headers(
  rider['id']) — passing a shared fallback constant guarantees the
  ownership check fails for any real rider id, cascading 'Setup
  failed' into every downstream test.
"""
from __future__ import annotations
from typing import Dict

from prd_bench_local_runner.testing import build_user_headers


# ---------------------------------------------------------------------------
# Shared opaque-role constants and a non-binding Rider fallback.
# ---------------------------------------------------------------------------
TEST_USERS: Dict[str, Dict[str, str]] = {
    # Opaque roles — canonical constants.
    "admin_headers": build_user_headers("admin-001", "Admin"),
    "admin_headers_alt": build_user_headers("admin-002", "Admin"),
    "operator_headers": build_user_headers("operator-001", "Operator"),
    "operator_headers_alt": build_user_headers("operator-002", "Operator"),
    "field_staff_headers": build_user_headers(
        "field-staff-001", "FieldStaff",
    ),
    # Rider fallback — use ONLY for tests that do NOT exercise
    # ownership. Per PRD §2.1 the real X-User-ID must equal Rider.id
    # for any ownership-gated call; the per-instance builder below is
    # the correct path in fixtures.
    "rider_headers": build_user_headers("rider-fallback", "Rider"),
}


# ---------------------------------------------------------------------------
# Per-instance builders.
# ---------------------------------------------------------------------------
def make_rider_headers(rider_id: str) -> Dict[str, str]:
    """PRD §2.1: 'When X-User-Role is Rider, X-User-ID is the id of the
    acting Rider entity; ownership checks on any resource that references
    a Rider (for instance, Ride.rider_id) compare the resource's
    foreign-key field to X-User-ID.' Pass the actual Rider.id returned
    by POST /riders whenever the downstream call is ownership-gated
    (POST /rides, POST /rides/{id}/end, POST /rides/{id}/fault-report,
    POST /rides/{id}/dispute, POST /riders/{rider_id}/monthly-pass)."""
    return build_user_headers(rider_id, "Rider")


def make_admin_headers(user_id: str = "admin-001") -> Dict[str, str]:
    """PRD §2.1: Admin X-User-ID is an opaque identifier."""
    return build_user_headers(user_id, "Admin")


def make_operator_headers(user_id: str = "operator-001") -> Dict[str, str]:
    """PRD §2.1: Operator X-User-ID is an opaque identifier."""
    return build_user_headers(user_id, "Operator")


def make_field_staff_headers(
    user_id: str = "field-staff-001",
) -> Dict[str, str]:
    """PRD §2.1: FieldStaff X-User-ID is an opaque identifier."""
    return build_user_headers(user_id, "FieldStaff")


__all__ = [
    "TEST_USERS",
    "make_rider_headers",
    "make_admin_headers",
    "make_operator_headers",
    "make_field_staff_headers",
]
