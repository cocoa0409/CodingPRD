"""Pre-built role headers for every role in the PRD.

PRD §2.1 distinguishes roles by identity binding:

- Operator, GateSystem, EnforcementOfficer, ParkingPartner, Auditor:
  opaque — `X-User-ID` is an opaque operator identifier not tied to any
  persisted entity row. The shared TEST_USERS constant is canonical.

- Driver: entity-backed on Vehicle. PRD §2.1: 'When X-User-Role is
  Driver, X-User-ID is the id of the acting Vehicle; ownership checks
  on any resource that references a Vehicle (sessions, reservations,
  violations, cards bound to that vehicle) compare the resource's
  vehicle_id to X-User-ID.'

For Driver, ownership-gated calls MUST use make_driver_headers(vehicle_id)
with the actual Vehicle.id. The shared TEST_USERS["driver_headers"]
fallback is suitable only for tests whose success does NOT depend on
ownership comparison (e.g., ERR_FORBIDDEN where the role is rejected
before identity is consulted).
"""
from __future__ import annotations
from typing import Dict

from prd_bench_local_runner.testing import build_user_headers


# Shared constants. For opaque roles these are canonical. For Driver
# (entity-backed on Vehicle) the constant is a fallback for non-ownership
# tests; ownership-gated tests must call make_driver_headers(vehicle_id).
TEST_USERS: Dict[str, Dict[str, str]] = {
    # Opaque roles — shared constants are canonical.
    "operator_headers": build_user_headers("operator-001", "Operator"),
    "operator_headers_alt": build_user_headers("operator-002", "Operator"),
    "gate_headers": build_user_headers("gate-001", "GateSystem"),
    "gate_headers_alt": build_user_headers("gate-002", "GateSystem"),
    "officer_headers": build_user_headers("officer-001", "EnforcementOfficer"),
    "partner_headers": build_user_headers("partner-001", "ParkingPartner"),
    "auditor_headers": build_user_headers("auditor-001", "Auditor"),

    # Entity-backed Driver — fallback only. Ownership-gated calls must use
    # make_driver_headers(vehicle["id"]).
    "driver_headers": build_user_headers("driver-fallback-001", "Driver"),
}


# ---------------------------------------------------------------------------
# Per-instance builders
# ---------------------------------------------------------------------------
def make_operator_headers(operator_id: str = "operator-001") -> Dict[str, str]:
    """Operator headers; identity is opaque per PRD §2.1.

    The optional operator_id allows distinguishing two operators in
    concurrency tests or AuditLog.actor_id assertions.
    """
    return build_user_headers(operator_id, "Operator")


def make_gate_headers(gate_id: str = "gate-001") -> Dict[str, str]:
    """GateSystem headers; identity is opaque per PRD §2.1."""
    return build_user_headers(gate_id, "GateSystem")


def make_officer_headers(officer_id: str = "officer-001") -> Dict[str, str]:
    """EnforcementOfficer headers; identity is opaque per PRD §2.1."""
    return build_user_headers(officer_id, "EnforcementOfficer")


def make_partner_headers(partner_id: str = "partner-001") -> Dict[str, str]:
    """ParkingPartner headers; identity is opaque per PRD §2.1."""
    return build_user_headers(partner_id, "ParkingPartner")


def make_auditor_headers(auditor_id: str = "auditor-001") -> Dict[str, str]:
    """Auditor headers; identity is opaque per PRD §2.1."""
    return build_user_headers(auditor_id, "Auditor")


def make_driver_headers(vehicle_id: str) -> Dict[str, str]:
    """Driver headers. PRD §2.1: 'When X-User-Role is Driver, X-User-ID
    is the id of the acting Vehicle; ownership checks on any resource
    that references a Vehicle (sessions, reservations, violations, cards
    bound to that vehicle) compare the resource's vehicle_id to X-User-ID.'

    Pass the actual Vehicle.id whenever the call is ownership-gated.
    """
    return build_user_headers(vehicle_id, "Driver")


__all__ = [
    "TEST_USERS",
    "make_operator_headers",
    "make_gate_headers",
    "make_officer_headers",
    "make_partner_headers",
    "make_auditor_headers",
    "make_driver_headers",
]
