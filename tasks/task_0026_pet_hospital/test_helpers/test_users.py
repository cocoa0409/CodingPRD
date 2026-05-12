"""Pre-built role headers for every role in the PRD.

PRD §2.1: 'X-User-ID is treated as an opaque operator identifier that
the server may persist on audit-log entries and on prescription/visit
records but does not compare against any entity's id for ownership
purposes — the role-to-endpoint mapping alone determines access.'

All seven roles in this PRD are opaque per §2.1, so the shared TEST_USERS
constants are canonical. The per-instance builders are still provided as
a convenience for tests that want distinct operator ids in audit-log
assertions or for the segregation-of-duties rule (which compares the
prescription's stored drafting_vet_id against the X-User-ID of the
caller invoking approve — see PRD §2.1 last paragraph and §3.7).
"""
from __future__ import annotations
from typing import Dict

from prd_bench_local_runner.testing import build_user_headers


# Shared canonical constants — opaque roles only (PRD §2.1).
TEST_USERS: Dict[str, Dict[str, str]] = {
    "triage_nurse_headers": build_user_headers("triage-001", "TriageNurse"),
    "triage_nurse_headers_alt": build_user_headers("triage-002", "TriageNurse"),
    "drafting_vet_headers": build_user_headers("drafting-vet-001", "DraftingVet"),
    "drafting_vet_headers_alt": build_user_headers("drafting-vet-002", "DraftingVet"),
    "reviewing_vet_headers": build_user_headers("reviewing-vet-001", "ReviewingVet"),
    "reviewing_vet_headers_alt": build_user_headers("reviewing-vet-002", "ReviewingVet"),
    "pharmacist_headers": build_user_headers("pharmacist-001", "Pharmacist"),
    "cashier_headers": build_user_headers("cashier-001", "Cashier"),
    "owner_service_headers": build_user_headers("owner-svc-001", "OwnerService"),
    "platform_admin_headers": build_user_headers("admin-001", "PlatformAdmin"),
}


# --- Per-instance builders ---
# All roles in this PRD are opaque, so these builders simply parameterize
# the operator id. Use them when a test needs distinct operator ids
# (e.g., the segregation-of-duties rule in PRD §3.7 compares the approve
# caller's X-User-ID against the prescription's drafting_vet_id, which
# was set from the drafter's X-User-ID at draft creation time).

def make_triage_nurse_headers(operator_id: str = "triage-001") -> Dict[str, str]:
    """TriageNurse headers (opaque per PRD §2.1)."""
    return build_user_headers(operator_id, "TriageNurse")


def make_drafting_vet_headers(operator_id: str = "drafting-vet-001") -> Dict[str, str]:
    """DraftingVet headers (opaque per PRD §2.1).

    Pass distinct operator_id values when the test needs to compare
    drafting_vet_id (recorded from X-User-ID at draft time) against a
    different X-User-ID at submit / dispense / amend time. Note PRD §3.4:
    Visit.assigned_vet_id is set by triage routing, and §3.5 / §3.6 / §3.7
    require the caller's X-User-ID to equal Visit.assigned_vet_id for
    several DraftingVet actions on the visit.
    """
    return build_user_headers(operator_id, "DraftingVet")


def make_reviewing_vet_headers(operator_id: str = "reviewing-vet-001") -> Dict[str, str]:
    """ReviewingVet headers (opaque per PRD §2.1).

    Pass an operator_id distinct from the drafting vet's X-User-ID when
    the prescription contains any controlled-drug item — PRD §3.7
    rejects approval with ERR_SEGREGATION_OF_DUTIES otherwise.
    """
    return build_user_headers(operator_id, "ReviewingVet")


def make_pharmacist_headers(operator_id: str = "pharmacist-001") -> Dict[str, str]:
    """Pharmacist headers (opaque per PRD §2.1)."""
    return build_user_headers(operator_id, "Pharmacist")


def make_cashier_headers(operator_id: str = "cashier-001") -> Dict[str, str]:
    """Cashier headers (opaque per PRD §2.1)."""
    return build_user_headers(operator_id, "Cashier")


def make_owner_service_headers(operator_id: str = "owner-svc-001") -> Dict[str, str]:
    """OwnerService headers (opaque per PRD §2.1)."""
    return build_user_headers(operator_id, "OwnerService")


def make_platform_admin_headers(operator_id: str = "admin-001") -> Dict[str, str]:
    """PlatformAdmin headers (opaque per PRD §2.1)."""
    return build_user_headers(operator_id, "PlatformAdmin")


__all__ = [
    "TEST_USERS",
    "make_triage_nurse_headers",
    "make_drafting_vet_headers",
    "make_reviewing_vet_headers",
    "make_pharmacist_headers",
    "make_cashier_headers",
    "make_owner_service_headers",
    "make_platform_admin_headers",
]
