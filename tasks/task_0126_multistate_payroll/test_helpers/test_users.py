"""Pre-built role headers for every role in the PRD.

PRD §2.1 identity rules — ALL FOUR ROLES ARE OPAQUE:

  "For every one of the four roles, X-User-ID is an opaque operator
   identifier that is not tied to any persisted entity. The server may
   record the supplied identifier on a resource (for example, capturing
   it as the calculator, approver, finalizer, or amender so that
   segregation-of-duties comparisons can be made on later transitions),
   but it never compares X-User-ID to any entity's id."

So a shared constant per role is canonical for any single-actor call.
There is NO entity-backed role; no ownership comparison against any
entity id is ever performed.

SEGREGATION OF DUTIES (PRD §2.6) however requires distinct
X-User-IDs across consecutive control steps on the same artifact:

  - approver != most-recent-calculator on the same Paycheck
  - treasurer != approver AND != calculator on the same Paycheck
  - remit-treasurer != finalizer (and != amender on post-amend remit)

To honor these without leaking SOD violations into ordinary fixture
flow, every role exposes at least TWO canonical operator ids — a
primary and an alternate — and per-instance builders let tests mint
arbitrary operator ids when a third (or matching-equal) actor is
needed.

The shared constant in TEST_USERS is safe for any test whose success
does not depend on cross-step actor inequality (404 paths, malformed
payloads, single-actor reads, role-permission negatives). Tests that
exercise SOD MUST mint distinct ids via the per-instance builders.
"""
from __future__ import annotations

from typing import Dict

from prd_bench_local_runner.testing import build_user_headers


# ---------------------------------------------------------------------------
# Canonical opaque-actor identifiers — PRD §2.1.
# ---------------------------------------------------------------------------
SPECIALIST_ID = "specialist-001"
SPECIALIST_ID_ALT = "specialist-002"

MANAGER_ID = "manager-001"
MANAGER_ID_ALT = "manager-002"

TREASURER_ID = "treasurer-001"
TREASURER_ID_ALT = "treasurer-002"


TEST_USERS: Dict[str, Dict[str, str]] = {
    # Opaque PayrollSpecialist — shared constant is canonical.
    "specialist_headers": build_user_headers(
        SPECIALIST_ID, "PayrollSpecialist",
    ),
    "specialist_headers_alt": build_user_headers(
        SPECIALIST_ID_ALT, "PayrollSpecialist",
    ),
    # Opaque PayrollManager — shared constant is canonical.
    "manager_headers": build_user_headers(MANAGER_ID, "PayrollManager"),
    "manager_headers_alt": build_user_headers(
        MANAGER_ID_ALT, "PayrollManager",
    ),
    # Opaque Treasurer — shared constant is canonical.
    "treasurer_headers": build_user_headers(TREASURER_ID, "Treasurer"),
    "treasurer_headers_alt": build_user_headers(
        TREASURER_ID_ALT, "Treasurer",
    ),
}


# ---------------------------------------------------------------------------
# Per-instance builders — every role is opaque, but SOD tests need
# distinct operator ids that the shared constants alone cannot supply.
# ---------------------------------------------------------------------------
def make_specialist_headers(user_id: str) -> Dict[str, str]:
    """For PayrollSpecialist (opaque). Use a custom operator id when
    testing SOD scenarios that require the calculator and approver to
    share an X-User-ID (positive control of ERR_SEGREGATION_OF_DUTIES)
    or when a fixture needs N distinct specialists in sequence.
    """
    return build_user_headers(user_id, "PayrollSpecialist")


def make_manager_headers(user_id: str) -> Dict[str, str]:
    """For PayrollManager (opaque). Distinct operator ids let tests
    finalize a remittance under one manager and amend it under a
    second, or trigger SOD by passing the calculator's id to approve.
    """
    return build_user_headers(user_id, "PayrollManager")


def make_treasurer_headers(user_id: str) -> Dict[str, str]:
    """For Treasurer (opaque). Used for the third (or post-amend
    fourth) distinct operator id required by PRD §2.6 on
    mark-paid and remit transitions.
    """
    return build_user_headers(user_id, "Treasurer")


__all__ = [
    "SPECIALIST_ID",
    "SPECIALIST_ID_ALT",
    "MANAGER_ID",
    "MANAGER_ID_ALT",
    "TREASURER_ID",
    "TREASURER_ID_ALT",
    "TEST_USERS",
    "make_specialist_headers",
    "make_manager_headers",
    "make_treasurer_headers",
]
