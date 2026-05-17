"""Pre-built role headers for every role defined in PRD §2.1.

PRD §2.1 identity rules:

- PlanAdministrator, PayrollProcessor, and ComplianceOfficer are
  OPAQUE: "X-User-ID is an opaque operator identifier not tied to any
  persisted entity. The server may record it for audit purposes but
  does not compare it to any entity's id." Shared constants are
  canonical for these operator-only roles.

- Participant is ENTITY-BACKED: "X-User-ID is the id of the acting
  Participant resource. Ownership checks on any participant-scoped
  operation compare the resource's participant_id (or the participantId
  in the URL path) to X-User-ID; the participant may act only on
  themselves."

  Every Participant-acting call whose success depends on owning the
  targeted resource MUST mint headers via
  make_participant_headers(participant["id"]) — never via the shared
  PARTICIPANT_FALLBACK_ID constant. Falling back to the shared constant
  for entity-backed roles reproduces the canonical bug: the literal
  "fallback-participant-1" never equals any real Participant.id, so
  every ownership check rejects every request as
  ERR_INSUFFICIENT_PERMISSIONS.

The shared PARTICIPANT_FALLBACK_ID constant is ONLY safe for tests
that DO NOT exercise ownership (header-missing, role-mismatch on the
wrong-role-rejection path, 404 on non-existent path).

SEGREGATION OF DUTIES — PRD §2.1: "the same X-User-ID may not perform
two adjacent steps in the same workflow on the same plan". Concretely:
- A participant cannot request a loan and then later approve it from
  the PlanAdministrator role (the requester's X-User-ID is the
  Participant.id; the approver's X-User-ID must therefore be a
  different operator id).
- A PayrollProcessor who posts a ContributionRecord may not later
  approve a loan as PlanAdministrator within the same plan year using
  the SAME X-User-ID.

Two distinct admin / payroll / compliance operator constants below let
tests model two different operators when an SOD scenario demands it.
"""
from __future__ import annotations

from typing import Dict

from prd_bench_local_runner.testing import build_user_headers


# ---------------------------------------------------------------------------
# Canonical opaque-actor identifiers — PRD §2.1.
# ---------------------------------------------------------------------------
PLAN_ADMIN_ID = "admin-001"
PLAN_ADMIN_ID_ALT = "admin-002"

PAYROLL_ID = "payroll-001"
PAYROLL_ID_ALT = "payroll-002"

COMPLIANCE_ID = "compliance-001"
COMPLIANCE_ID_ALT = "compliance-002"

# Entity-backed fallback id — DO NOT use for ownership-gated calls.
PARTICIPANT_FALLBACK_ID = "fallback-participant-1"


TEST_USERS: Dict[str, Dict[str, str]] = {
    # Opaque PlanAdministrator — shared constant is canonical.
    "admin_headers": build_user_headers(PLAN_ADMIN_ID, "PlanAdministrator"),
    "admin_headers_alt": build_user_headers(
        PLAN_ADMIN_ID_ALT, "PlanAdministrator",
    ),
    # Opaque PayrollProcessor — shared constant is canonical.
    "payroll_headers": build_user_headers(PAYROLL_ID, "PayrollProcessor"),
    "payroll_headers_alt": build_user_headers(
        PAYROLL_ID_ALT, "PayrollProcessor",
    ),
    # Opaque ComplianceOfficer — shared constant is canonical.
    "compliance_headers": build_user_headers(
        COMPLIANCE_ID, "ComplianceOfficer",
    ),
    "compliance_headers_alt": build_user_headers(
        COMPLIANCE_ID_ALT, "ComplianceOfficer",
    ),
    # Entity-backed Participant fallback — DO NOT use for
    # ownership-gated calls. Safe only for header-missing / role-
    # mismatch / NotFound paths.
    "participant_fallback_headers": build_user_headers(
        PARTICIPANT_FALLBACK_ID, "Participant",
    ),
}


# ---------------------------------------------------------------------------
# Per-instance builders — REQUIRED for entity-backed Participant.
# The runtime Participant.id minted by POST /plans/{planId}/participants
# is the value the implementation will compare against in ownership
# checks (PRD §2.1).
# ---------------------------------------------------------------------------
def make_participant_headers(participant_id: str) -> Dict[str, str]:
    """For Participant (entity_backed:Participant). Pass the actual
    Participant.id of the acting participant.

    PRD §2.1: "When X-User-Role is Participant, X-User-ID is the id of
    the acting Participant resource. Ownership checks on any
    participant-scoped operation compare the resource's participant_id
    (or the participantId in the URL path) to X-User-ID; the
    participant may act only on themselves."

    Every Participant-driven call whose success depends on owning the
    targeted entity — POST loans, POST hardship-withdrawals,
    POST loans/{id}/repayments, POST vesting-snapshots, PATCH deferral,
    GET own collections — MUST use this builder, not the shared
    PARTICIPANT_FALLBACK_ID constant.
    """
    return build_user_headers(participant_id, "Participant")


def make_admin_headers(admin_id: str) -> Dict[str, str]:
    """For PlanAdministrator (opaque). Any non-empty operator id is
    fine; this builder exists so tests that want a distinct admin id
    (for segregation-of-duties scenarios) can supply one without
    relying on a single shared constant.
    """
    return build_user_headers(admin_id, "PlanAdministrator")


def make_payroll_headers(payroll_id: str) -> Dict[str, str]:
    """For PayrollProcessor (opaque)."""
    return build_user_headers(payroll_id, "PayrollProcessor")


def make_compliance_headers(compliance_id: str) -> Dict[str, str]:
    """For ComplianceOfficer (opaque)."""
    return build_user_headers(compliance_id, "ComplianceOfficer")


__all__ = [
    "PLAN_ADMIN_ID",
    "PLAN_ADMIN_ID_ALT",
    "PAYROLL_ID",
    "PAYROLL_ID_ALT",
    "COMPLIANCE_ID",
    "COMPLIANCE_ID_ALT",
    "PARTICIPANT_FALLBACK_ID",
    "TEST_USERS",
    "make_participant_headers",
    "make_admin_headers",
    "make_payroll_headers",
    "make_compliance_headers",
]
