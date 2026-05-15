"""Pre-built role headers for every role in the PRD.

PRD §2.1 identity rules:

- Renter — X-User-ID is an opaque renter identifier; it is NOT the id of
  any persisted entity. The server stores it on Rental.renter_id (and by
  snapshot on InsuranceClaim.renter_id). Ownership checks compare
  X-User-ID against Rental.renter_id (or InsuranceClaim.renter_id)
  directly. Because Rental.renter_id is taken from X-User-ID at
  creation time, any fixed string a fixture chooses will become the
  bound renter_id — so an ownership-gated call MUST be made with the
  SAME X-User-ID the rental was created with. `make_renter_headers(id)`
  is the canonical builder.

- Operator — opaque operator identifier; the server records it on
  AuditEvent.actor_id but does not gate ownership against any entity.
  Shared constants are canonical.

- RepairTechnician — opaque technician identifier; the server compares
  it to RepairTicket.assigned_technician_id when authorising
  POST /repair-tickets/{ticket_id}/repair. `make_technician_headers(tid)`
  is the canonical builder when the call is ownership-gated.

- InsuranceAgent — opaque insurer identifier; agent writes are gated
  by role only, not by ownership. Shared constants are canonical.
"""
from __future__ import annotations

from typing import Dict

from prd_bench_local_runner.testing import build_user_headers


# ---------------------------------------------------------------------------
# Canonical opaque-actor identifiers.
# ---------------------------------------------------------------------------
OPERATOR_ID = "operator-001"
OPERATOR_ID_ALT = "operator-002"

INSURANCE_AGENT_ID = "agent-001"
INSURANCE_AGENT_ID_ALT = "agent-002"

# Stable defaults a fixture may use when it does not need a fresh id
# per test. NOTE: a Renter rental is owned by the X-User-ID present at
# creation time — fixtures that need ownership-gated follow-ups must
# either pass renter_id explicitly or use these stable defaults and
# build follow-up headers with the same id.
RENTER_ID_DEFAULT = "renter-default-001"
RENTER_ID_ALT = "renter-default-002"

TECHNICIAN_ID_DEFAULT = "tech-default-001"
TECHNICIAN_ID_ALT = "tech-default-002"


TEST_USERS: Dict[str, Dict[str, str]] = {
    # Operator (opaque) — canonical shared constants.
    "operator_headers": build_user_headers(OPERATOR_ID, "Operator"),
    "operator_headers_alt": build_user_headers(OPERATOR_ID_ALT, "Operator"),

    # InsuranceAgent (opaque, no ownership) — canonical shared constants.
    "insurance_agent_headers": build_user_headers(
        INSURANCE_AGENT_ID, "InsuranceAgent",
    ),
    "insurance_agent_headers_alt": build_user_headers(
        INSURANCE_AGENT_ID_ALT, "InsuranceAgent",
    ),

    # Renter fallback — for tests that do NOT exercise ownership
    # (missing-auth, wrong-role, missing-resource). Ownership-gated
    # tests MUST use make_renter_headers(rental['renter_id']).
    "renter_headers": build_user_headers(RENTER_ID_DEFAULT, "Renter"),
    "renter_headers_alt": build_user_headers(RENTER_ID_ALT, "Renter"),

    # RepairTechnician fallback — for tests that do NOT exercise the
    # assigned-technician ownership check. The /repair endpoint MUST
    # use make_technician_headers(ticket['assigned_technician_id']).
    "technician_headers": build_user_headers(TECHNICIAN_ID_DEFAULT, "RepairTechnician"),
}


# ---------------------------------------------------------------------------
# Per-instance builders — REQUIRED for ownership-gated calls.
# ---------------------------------------------------------------------------
def make_renter_headers(renter_id: str) -> Dict[str, str]:
    """PRD §2.1: "Ownership checks on rentals, renewals, returns,
    holding-claims, claim filings, and evidence submissions compare
    X-User-ID against Rental.renter_id (or the snapshotted
    InsuranceClaim.renter_id) directly."

    Pass the renter_id that the rental (or claim) is bound to whenever
    the call is ownership-gated."""
    return build_user_headers(renter_id, "Renter")


def make_operator_headers(operator_id: str) -> Dict[str, str]:
    """PRD §2.1: Operator X-User-ID is opaque. Useful when a test wants
    distinct actor_user_id values on AuditEvent rows."""
    return build_user_headers(operator_id, "Operator")


def make_technician_headers(technician_id: str) -> Dict[str, str]:
    """PRD §2.1 + §3.8: "the assigned RepairTechnician — and only that
    technician, identified by X-User-ID equality with
    assigned_technician_id — then marks the work as repaired."

    Pass the technician_id stored on RepairTicket.assigned_technician_id
    whenever calling /repair-tickets/{id}/repair."""
    return build_user_headers(technician_id, "RepairTechnician")


def make_insurance_agent_headers(agent_id: str) -> Dict[str, str]:
    """PRD §2.1: InsuranceAgent X-User-ID is opaque; agent writes are
    gated by role only."""
    return build_user_headers(agent_id, "InsuranceAgent")


__all__ = [
    "OPERATOR_ID",
    "OPERATOR_ID_ALT",
    "INSURANCE_AGENT_ID",
    "INSURANCE_AGENT_ID_ALT",
    "RENTER_ID_DEFAULT",
    "RENTER_ID_ALT",
    "TECHNICIAN_ID_DEFAULT",
    "TECHNICIAN_ID_ALT",
    "TEST_USERS",
    "make_renter_headers",
    "make_operator_headers",
    "make_technician_headers",
    "make_insurance_agent_headers",
]
