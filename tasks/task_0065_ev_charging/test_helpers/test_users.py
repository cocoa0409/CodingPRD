"""Pre-built role headers for every role in the PRD.

PRD §2.1 identity rules:

- PlatformOperator, FieldTechnician, CustomerService carry OPAQUE
  X-User-IDs. PRD §2.1 says of these three: 'X-User-ID is an opaque
  operator identifier not tied to any persisted entity. The server may
  record it (for example, as actor_id on AuditLog rows ...) but does not
  compare it to any entity's id.' Shared constants are safe for these
  roles.

- StationOwner is ENTITY-BACKED by Operator. PRD §2.1: 'when X-User-Role
  is StationOwner, X-User-ID is the id of the acting Operator. Ownership
  checks on any resource that references an Operator (for example,
  Station.station_owner_id) compare the resource's foreign-key field to
  X-User-ID.' Every ownership-gated StationOwner call MUST use
  make_station_owner_headers(operator['id']).

- EVDriver is ENTITY-BACKED by Member. PRD §2.1: 'when X-User-Role is
  EVDriver, X-User-ID is the id of the acting Member. Ownership checks
  on any resource that references a Member (reservations, queue entries,
  sessions) compare the resource's foreign-key field to X-User-ID.'
  Every ownership-gated EVDriver call MUST use
  make_ev_driver_headers(member['id']).

- FieldTechnician: although opaque, PRD §2.1 adds: 'a technician may
  only begin or complete a ticket whose assigned_technician_id equals
  their own X-User-ID.' Tests that exercise that gate must use a header
  whose X-User-ID matches the value passed to assigned_technician_id at
  dispatch time.
"""
from __future__ import annotations
from typing import Dict

from prd_bench_local_runner.testing import build_user_headers


# ---------------------------------------------------------------------------
# Shared opaque-role constants and entity_backed fallback constants.
# Use entity_backed fallbacks ONLY for tests that do not exercise
# ownership — for example, 401/404 negative tests.
# ---------------------------------------------------------------------------
TEST_USERS: Dict[str, Dict[str, str]] = {
    # Opaque roles — canonical constants.
    "platform_operator_headers": build_user_headers(
        "platform-operator-001", "PlatformOperator",
    ),
    "platform_operator_headers_alt": build_user_headers(
        "platform-operator-002", "PlatformOperator",
    ),
    "field_technician_headers": build_user_headers(
        "field-technician-001", "FieldTechnician",
    ),
    "field_technician_headers_alt": build_user_headers(
        "field-technician-002", "FieldTechnician",
    ),
    "customer_service_headers": build_user_headers(
        "customer-service-001", "CustomerService",
    ),
    "customer_service_headers_alt": build_user_headers(
        "customer-service-002", "CustomerService",
    ),

    # entity_backed fallbacks — wrong-identity, do not pass any
    # ownership check. Use only for tests that do NOT exercise
    # ownership (missing-auth, missing-resource, wrong-role tests).
    "station_owner_headers": build_user_headers(
        "station-owner-fallback", "StationOwner",
    ),
    "ev_driver_headers": build_user_headers(
        "ev-driver-fallback", "EVDriver",
    ),
}


# ---------------------------------------------------------------------------
# Per-instance builders. Required for every entity_backed role.
# ---------------------------------------------------------------------------
def make_station_owner_headers(operator_id: str) -> Dict[str, str]:
    """PRD §2.1: 'When X-User-Role is StationOwner, X-User-ID is the id of
    the acting Operator.' Pass the actual Operator.id (the row created with
    role_kind STATION_OWNER) whenever the downstream call is
    ownership-gated (shelve/off-shelve/decommission a pile at an owned
    station, accept/reject a repair ticket at an owned station)."""
    return build_user_headers(operator_id, "StationOwner")


def make_ev_driver_headers(member_id: str) -> Dict[str, str]:
    """PRD §2.1: 'When X-User-Role is EVDriver, X-User-ID is the id of the
    acting Member.' Pass the actual Member.id whenever the downstream call
    is ownership-gated (create a reservation, cancel it, join the queue,
    abandon it, create or start or stop a session)."""
    return build_user_headers(member_id, "EVDriver")


def make_platform_operator_headers(
    user_id: str = "platform-operator-001",
) -> Dict[str, str]:
    """PRD §2.1: 'PlatformOperator ... X-User-ID is an opaque operator
    identifier not tied to any persisted entity.'"""
    return build_user_headers(user_id, "PlatformOperator")


def make_field_technician_headers(
    user_id: str = "field-technician-001",
) -> Dict[str, str]:
    """PRD §2.1: 'FieldTechnician ... a technician may only begin or
    complete a ticket whose assigned_technician_id equals their own
    X-User-ID.' Pass the value used as assigned_technician_id at dispatch
    when invoking begin/complete on that ticket."""
    return build_user_headers(user_id, "FieldTechnician")


def make_customer_service_headers(
    user_id: str = "customer-service-001",
) -> Dict[str, str]:
    """PRD §2.1: 'CustomerService ... X-User-ID is an opaque operator
    identifier not tied to any persisted entity.'"""
    return build_user_headers(user_id, "CustomerService")


__all__ = [
    "TEST_USERS",
    "make_station_owner_headers",
    "make_ev_driver_headers",
    "make_platform_operator_headers",
    "make_field_technician_headers",
    "make_customer_service_headers",
]
