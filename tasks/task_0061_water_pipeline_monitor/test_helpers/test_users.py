"""Pre-built role headers for every role in the PRD.

PRD §2.1 explicitly states:

    "All six roles use opaque identifiers: when X-User-Role is any of
     TopologyEngineer, TopologyApprover, ControlOperator,
     MaintenanceSupervisor, Technician, or Auditor, the value of
     X-User-ID is an opaque operator identifier that is not tied to any
     persisted entity row. The server records X-User-ID onto resources
     where a scaffold transition writes it ... but it does not compare
     X-User-ID to any entity's id field for identity resolution.
     Ownership constraints in this system are expressed as field equality
     against these stored opaque IDs (e.g., a technician's X-User-ID must
     equal WorkOrder.assigned_technician_id when they request parts,
     start work, or complete it)."

In other words, all six roles are *opaque*; identity is the opaque string
the caller chose, and ownership is enforced as field equality against the
opaque IDs the server has already stored on entities. So shared-constant
TEST_USERS entries are safe for non-ownership tests, but ownership-gated
calls (technician on their own work order, supervisor verifying someone
else's work order, approver versus submitter) MUST thread the SAME
X-User-ID through every step of the workflow. The per-instance builders
below make that threading explicit.

The two segregation-of-duties rules (PRD §2.1) further require:

- TopologyApprover acting on a TopologyVersion MUST differ from
  TopologyVersion.submitted_by.
- MaintenanceSupervisor verifying a WorkOrder MUST differ from
  WorkOrder.assigned_technician_id.

The builders below let fixtures and tests mint distinct opaque IDs in the
same role so SoD can be exercised without conflating identity with role.
"""
from __future__ import annotations
from typing import Dict

from prd_bench_local_runner.testing import build_user_headers


# ---------------------------------------------------------------------------
# Canonical opaque-id constants. Per PRD §2.1 every role is opaque; these
# IDs are not compared against any entity.id and are safe for tests whose
# success does not depend on owner-equality threading.
# ---------------------------------------------------------------------------
TEST_USERS: Dict[str, Dict[str, str]] = {
    # TopologyEngineer
    "topology_engineer_headers": build_user_headers(
        "te-001", "TopologyEngineer",
    ),
    "topology_engineer_headers_alt": build_user_headers(
        "te-002", "TopologyEngineer",
    ),
    # TopologyApprover — two distinct opaque IDs so SoD can be exercised.
    "topology_approver_headers": build_user_headers(
        "ta-001", "TopologyApprover",
    ),
    "topology_approver_headers_alt": build_user_headers(
        "ta-002", "TopologyApprover",
    ),
    # ControlOperator
    "control_operator_headers": build_user_headers(
        "co-001", "ControlOperator",
    ),
    "control_operator_headers_alt": build_user_headers(
        "co-002", "ControlOperator",
    ),
    # MaintenanceSupervisor — two opaque IDs so verify-SoD test can run.
    "supervisor_headers": build_user_headers(
        "sup-001", "MaintenanceSupervisor",
    ),
    "supervisor_headers_alt": build_user_headers(
        "sup-002", "MaintenanceSupervisor",
    ),
    # Technician — three distinct IDs so a fixture can pick a technician,
    # assign them by ID, and verify with a non-technician supervisor.
    "technician_headers": build_user_headers(
        "tech-001", "Technician",
    ),
    "technician_headers_alt": build_user_headers(
        "tech-002", "Technician",
    ),
    "technician_headers_third": build_user_headers(
        "tech-003", "Technician",
    ),
    # Auditor — read-only role.
    "auditor_headers": build_user_headers(
        "auditor-001", "Auditor",
    ),
}


# Convenience opaque-id constants exported alongside the headers — useful
# when a test needs to know the X-User-ID it just sent (e.g., to compare
# to AuditLog.actor_id or WorkOrder.assigned_technician_id).
USER_IDS: Dict[str, str] = {
    "topology_engineer": "te-001",
    "topology_engineer_alt": "te-002",
    "topology_approver": "ta-001",
    "topology_approver_alt": "ta-002",
    "control_operator": "co-001",
    "control_operator_alt": "co-002",
    "supervisor": "sup-001",
    "supervisor_alt": "sup-002",
    "technician": "tech-001",
    "technician_alt": "tech-002",
    "technician_third": "tech-003",
    "auditor": "auditor-001",
}


# ---------------------------------------------------------------------------
# Per-instance builders. PRD §2.1 makes identity opaque, so these are pure
# convenience helpers — but the SoD rules in §2.1 require the caller to
# mint a *different* opaque ID than the one stored on the resource. Use
# these builders to produce headers carrying the exact opaque ID you need
# (the same one you wrote earlier — e.g., the technician X-User-ID stored
# on WorkOrder.assigned_technician_id during assign).
# ---------------------------------------------------------------------------
def make_topology_engineer_headers(user_id: str) -> Dict[str, str]:
    """Mint a TopologyEngineer header with the supplied opaque X-User-ID."""
    return build_user_headers(user_id, "TopologyEngineer")


def make_topology_approver_headers(user_id: str) -> Dict[str, str]:
    """Mint a TopologyApprover header with the supplied opaque X-User-ID.

    PRD §2.1 SoD: when approving/rejecting a TopologyVersion, the
    caller's X-User-ID MUST differ from TopologyVersion.submitted_by.
    """
    return build_user_headers(user_id, "TopologyApprover")


def make_control_operator_headers(user_id: str) -> Dict[str, str]:
    """Mint a ControlOperator header with the supplied opaque X-User-ID."""
    return build_user_headers(user_id, "ControlOperator")


def make_supervisor_headers(user_id: str) -> Dict[str, str]:
    """Mint a MaintenanceSupervisor header with the supplied opaque
    X-User-ID.

    PRD §2.1 SoD: when verifying a WorkOrder, the caller's X-User-ID
    MUST differ from WorkOrder.assigned_technician_id.
    """
    return build_user_headers(user_id, "MaintenanceSupervisor")


def make_technician_headers(user_id: str) -> Dict[str, str]:
    """Mint a Technician header with the supplied opaque X-User-ID.

    PRD §2.1: 'a technician's X-User-ID must equal
    WorkOrder.assigned_technician_id when they request parts, start
    work, or complete it'. Pass the same opaque ID the supervisor used
    when calling /assign.
    """
    return build_user_headers(user_id, "Technician")


def make_auditor_headers(user_id: str = "auditor-001") -> Dict[str, str]:
    """Mint an Auditor header with the supplied opaque X-User-ID."""
    return build_user_headers(user_id, "Auditor")


__all__ = [
    "TEST_USERS",
    "USER_IDS",
    "make_topology_engineer_headers",
    "make_topology_approver_headers",
    "make_control_operator_headers",
    "make_supervisor_headers",
    "make_technician_headers",
    "make_auditor_headers",
]
