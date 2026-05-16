"""Pre-built role headers for every role in the PRD.

PRD §2.1 identity rules:

- ComplianceOfficer is OPAQUE. PRD §2.1: "When X-User-Role is
  ComplianceOfficer, X-User-ID is an opaque operator identifier not tied
  to any persisted entity. The server records it ... but never compares it
  to any entity's id. Segregation of duties is enforced by comparing
  recorded X-User-ID values across successive transitions on the same
  case." Shared constants are canonical, but every transition that
  requires a *different* officer than a previous one MUST use a
  distinct shared constant (we provide multiple).

- Coach is OPAQUE. PRD §2.1: "When X-User-Role is Coach, X-User-ID is
  likewise opaque; the server does not match it to any entity row."

- Booster is OPAQUE. PRD §2.1: "When X-User-Role is Booster, X-User-ID
  is opaque (it identifies a booster account, not an entity in this
  API); the server records it for audit but does not compare it to any
  entity's id."

- Auditor is OPAQUE. PRD §2.1: "When X-User-Role is Auditor, X-User-ID
  is opaque and not tied to any persisted entity."

- Athlete is ENTITY-BACKED. PRD §2.1: "When X-User-Role is Athlete,
  X-User-ID is the id of the acting Athlete. Ownership checks on any
  resource that references an Athlete compare the resource's athlete_id
  field to X-User-ID; an Athlete who supplies someone else's athlete_id
  when submitting an NIL deal or entering the portal is rejected with
  ERR_FORBIDDEN."

  Every Athlete-role call whose success depends on owning the targeted
  Athlete resource MUST mint headers via
  make_athlete_headers(athlete["id"]). The ATHLETE_FALLBACK_ID shared
  constant is ONLY safe for tests that DO NOT exercise ownership
  (header-missing tests, role-mismatch tests, NotFound paths).
"""
from __future__ import annotations

from typing import Dict

from prd_bench_local_runner.testing import build_user_headers


# ---------------------------------------------------------------------------
# Canonical opaque-actor identifiers.
# Two distinct ComplianceOfficer identifiers are needed because the PRD
# §3.6 / §3.7 segregation-of-duties checks compare X-User-IDs across
# successive transitions on the same case (NIL submitter vs reviewer,
# violation reviewer vs appellate reviewer).
# ---------------------------------------------------------------------------
COMPLIANCE_OFFICER_PRIMARY = "officer-primary-1"
COMPLIANCE_OFFICER_SECONDARY = "officer-secondary-2"
COMPLIANCE_OFFICER_TERTIARY = "officer-tertiary-3"
COACH_PRIMARY = "coach-primary-1"
COACH_SECONDARY = "coach-secondary-2"
BOOSTER_PRIMARY = "booster-primary-1"
AUDITOR_PRIMARY = "auditor-primary-1"

# Athlete fallback — ONLY safe for tests that do NOT exercise ownership.
# Ownership-gated Athlete calls MUST instead mint headers via
# make_athlete_headers(athlete["id"]).
ATHLETE_FALLBACK_ID = "fallback-athlete-id"


TEST_USERS: Dict[str, Dict[str, str]] = {
    # Opaque ComplianceOfficer — shared constants are canonical. The
    # PRIMARY is the default; SECONDARY/TERTIARY exist to satisfy the
    # segregation-of-duties checks (PRD §3.6 NIL deal review and PRD
    # §3.7 violation appeal both require a different X-User-ID than the
    # one used in the prior step on the same case).
    "officer_headers": build_user_headers(
        COMPLIANCE_OFFICER_PRIMARY, "ComplianceOfficer",
    ),
    "officer_headers_secondary": build_user_headers(
        COMPLIANCE_OFFICER_SECONDARY, "ComplianceOfficer",
    ),
    "officer_headers_tertiary": build_user_headers(
        COMPLIANCE_OFFICER_TERTIARY, "ComplianceOfficer",
    ),
    # Opaque Coach — shared constant is canonical.
    "coach_headers": build_user_headers(COACH_PRIMARY, "Coach"),
    "coach_headers_secondary": build_user_headers(
        COACH_SECONDARY, "Coach",
    ),
    # Opaque Booster — shared constant is canonical.
    "booster_headers": build_user_headers(BOOSTER_PRIMARY, "Booster"),
    # Opaque Auditor — shared constant is canonical.
    "auditor_headers": build_user_headers(AUDITOR_PRIMARY, "Auditor"),
    # Entity-backed Athlete fallback — DO NOT use for ownership-gated
    # calls. Tests that exercise ownership must mint via
    # make_athlete_headers(athlete["id"]).
    "athlete_headers": build_user_headers(
        ATHLETE_FALLBACK_ID, "Athlete",
    ),
}


# ---------------------------------------------------------------------------
# Per-instance builder — REQUIRED for the entity-backed Athlete role.
# ---------------------------------------------------------------------------
def make_athlete_headers(athlete_id: str) -> Dict[str, str]:
    """For Athlete (entity_backed). Pass the actual Athlete.id of the
    acting athlete.

    PRD §2.1: "X-User-ID is the id of the acting Athlete. Ownership
    checks on any resource that references an Athlete compare the
    resource's athlete_id field to X-User-ID; an Athlete who supplies
    someone else's athlete_id when submitting an NIL deal or entering
    the portal is rejected with ERR_FORBIDDEN."

    Every Athlete-role call whose success depends on owning the
    targeted resource — POST /nil-deals (with own athlete_id), PATCH
    /nil-deals/{id} (must own the deal), POST /transfer-portal-entries
    (with own athlete_id), POST /transfer-portal-entries/{id}/state
    (must own the entry) — MUST use this builder, not the
    ATHLETE_FALLBACK_ID shared constant.
    """
    return build_user_headers(athlete_id, "Athlete")


def make_officer_headers(officer_id: str) -> Dict[str, str]:
    """For ComplianceOfficer (opaque). Any non-empty operator id works;
    this builder is provided for tests that want a *distinct* operator id
    to drive the segregation-of-duties check on NIL deal review or
    violation appeal."""
    return build_user_headers(officer_id, "ComplianceOfficer")


def make_coach_headers(coach_id: str) -> Dict[str, str]:
    """For Coach (opaque). Any non-empty operator id works."""
    return build_user_headers(coach_id, "Coach")


def make_booster_headers(booster_id: str) -> Dict[str, str]:
    """For Booster (opaque). Any non-empty operator id works."""
    return build_user_headers(booster_id, "Booster")


def make_auditor_headers(auditor_id: str) -> Dict[str, str]:
    """For Auditor (opaque). Any non-empty operator id works."""
    return build_user_headers(auditor_id, "Auditor")


__all__ = [
    "COMPLIANCE_OFFICER_PRIMARY",
    "COMPLIANCE_OFFICER_SECONDARY",
    "COMPLIANCE_OFFICER_TERTIARY",
    "COACH_PRIMARY",
    "COACH_SECONDARY",
    "BOOSTER_PRIMARY",
    "AUDITOR_PRIMARY",
    "ATHLETE_FALLBACK_ID",
    "TEST_USERS",
    "make_athlete_headers",
    "make_officer_headers",
    "make_coach_headers",
    "make_booster_headers",
    "make_auditor_headers",
]
