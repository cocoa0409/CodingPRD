"""Pre-built role headers for every role in the PRD.

PRD §2.1 identity rules:

  "All three roles are entity-backed by the `Clinician` table: when
  `X-User-Role` is `OrderingProvider`, `LabTech`, or `LabDirector`,
  `X-User-ID` is the `id` of the acting `Clinician`, and ownership
  checks on any resource that references a `Clinician` compare the
  resource's foreign-key field to `X-User-ID`."

Concretely:

- An OrderingProvider cancelling an order has its X-User-ID checked
  against that order's `ordering_provider_id` (PRD §3.2).
- An acknowledger has its X-User-ID checked against the notification's
  `recipient_clinician_id` (PRD §3.5).
- A LabTech recording collection / opening transport legs / arriving /
  reporting break must be a Clinician with role_kind == LAB_TECH and
  active == true (PRD §3.3).
- A LabDirector releasing / amending / retracting must be a Clinician
  with role_kind == LAB_DIRECTOR (PRD §3.4) and the released_by_id
  Clinician's role_kind is also LAB_DIRECTOR.

Because all three roles are entity-backed, every header used in an
ownership-gated call MUST be minted via make_<role>_headers(<clinician
id>). The shared TEST_USERS constants below are FALLBACKS that are safe
only for tests that do NOT exercise ownership — auth-header / role
mismatch tests, malformed-payload tests, NotFound tests on path
segments that resolve, and pagination tests.

Falling back to a shared constant for ownership-gated calls reproduces
the canonical bug: a literal "fallback" string never equals any real
Clinician.id, so every ownership check (X-User-ID ==
ordering_provider_id, X-User-ID == recipient_clinician_id, role_kind
on the Clinician row matches X-User-Role) rejects every request,
cascading "Setup failed" into dozens of tests downstream.
"""
from __future__ import annotations

from typing import Dict

from prd_bench_local_runner.testing import build_user_headers


# ---------------------------------------------------------------------------
# Entity-backed fallback ids — DO NOT use for ownership-gated calls.
# ---------------------------------------------------------------------------
ORDERING_PROVIDER_FALLBACK_ID = "fallback-ordering-provider-1"
LAB_TECH_FALLBACK_ID = "fallback-lab-tech-1"
LAB_DIRECTOR_FALLBACK_ID = "fallback-lab-director-1"


TEST_USERS: Dict[str, Dict[str, str]] = {
    # All three roles are ENTITY-BACKED — these shared constants are
    # safe ONLY for auth/role-mismatch tests and tests that DO NOT
    # exercise ownership. Ownership-gated calls MUST use the
    # per-instance builders below.
    "ordering_provider_fallback_headers": build_user_headers(
        ORDERING_PROVIDER_FALLBACK_ID, "OrderingProvider",
    ),
    "lab_tech_fallback_headers": build_user_headers(
        LAB_TECH_FALLBACK_ID, "LabTech",
    ),
    "lab_director_fallback_headers": build_user_headers(
        LAB_DIRECTOR_FALLBACK_ID, "LabDirector",
    ),
}


# ---------------------------------------------------------------------------
# Per-instance builders — REQUIRED for entity-backed roles.
# ---------------------------------------------------------------------------
def make_ordering_provider_headers(clinician_id: str) -> Dict[str, str]:
    """For OrderingProvider (entity_backed:Clinician). Pass the actual
    Clinician.id of the acting ordering provider.

    PRD §2.1: "ownership checks on any resource that references a
    `Clinician` compare the resource's foreign-key field to
    `X-User-ID`."

    Every OrderingProvider call whose success depends on owning the
    targeted resource (cancelling an order whose ordering_provider_id
    matches, acknowledging a notification whose recipient_clinician_id
    matches, cancelling a retest whose original order's
    ordering_provider_id matches) MUST use this builder.
    """
    return build_user_headers(clinician_id, "OrderingProvider")


def make_lab_tech_headers(clinician_id: str) -> Dict[str, str]:
    """For LabTech (entity_backed:Clinician). Pass the actual
    Clinician.id of the acting lab tech.

    PRD §2.1: "The role declared in `X-User-Role` must also be
    consistent with the `role_kind` recorded on the underlying
    `Clinician` row for any operation that has a `role_kind`-specific
    precondition (for example, a `LabTech` actor's `Clinician` row must
    have `role_kind` equal to `LAB_TECH`)."

    Every LabTech call (collection, opening a transport leg, marking
    arrival, reporting a chain break, and WAIVED/MODERATE resulting)
    MUST use this builder.
    """
    return build_user_headers(clinician_id, "LabTech")


def make_lab_director_headers(clinician_id: str) -> Dict[str, str]:
    """For LabDirector (entity_backed:Clinician). Pass the actual
    Clinician.id of the acting lab director.

    PRD §2.6 / §3.4: "the clinician named in `released_by_id` must be
    active, must have `role_kind` of `LAB_DIRECTOR`, and must not be
    the same clinician as `resulted_by_id`."

    Every LabDirector call (clinician registration, panel definition,
    release, amend, retract, HIGH-complexity resulting, audit-log
    reads, clock advance, sweep) MUST use this builder when the call is
    ownership- / identity-gated. The released_by_id is part of the
    payload body — the helper here mints the X-User-ID header.
    """
    return build_user_headers(clinician_id, "LabDirector")


__all__ = [
    "ORDERING_PROVIDER_FALLBACK_ID",
    "LAB_TECH_FALLBACK_ID",
    "LAB_DIRECTOR_FALLBACK_ID",
    "TEST_USERS",
    "make_ordering_provider_headers",
    "make_lab_tech_headers",
    "make_lab_director_headers",
]
