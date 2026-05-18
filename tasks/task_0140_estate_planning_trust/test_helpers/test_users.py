"""Pre-built role headers for every role in the PRD.

PRD §2.1 identity rules:

- CourtClerk is OPAQUE. PRD §2.1: "When X-User-Role is CourtClerk,
  X-User-ID is an opaque operator identifier not tied to any persisted
  entity; the server may record it for audit but does not compare it
  to any entity's id." Shared constants are canonical.

- Executor is ENTITY-BACKED on Fiduciary. PRD §2.1: "When X-User-Role
  is Executor, X-User-ID is the id of the acting Fiduciary row (one
  whose scope_type is EXECUTOR); ownership checks compare any
  resource's executor reference back to this id."

  Every Executor-driven call whose success depends on owning the
  estate (or being the confirmed executor on it) MUST mint headers
  via make_executor_headers(executor_fiduciary["id"]) — never via the
  shared EXECUTOR_FALLBACK_ID constant. Falling back to the shared
  constant for the entity-backed Executor role reproduces the
  canonical bug: the literal "fallback-executor-1" never equals any
  real Fiduciary.id, so every ownership check rejects every request
  regardless of implementation correctness.

- Fiduciary (non-executor: TRUSTEE / GUARDIAN) is ENTITY-BACKED.
  PRD §2.1: "When X-User-Role is Fiduciary (covering the non-executor
  scopes — trustees and guardians), X-User-ID is again the id of the
  acting Fiduciary row, and self-only operations — for example,
  resigning — compare it against the Fiduciary.contact_user_id of the
  target row."

  Use make_fiduciary_headers(fiduciary["contact_user_id"]) for any
  ownership-gated call (e.g., self-resign).

- Beneficiary is ENTITY-BACKED. PRD §2.1: "When X-User-Role is
  Beneficiary, X-User-ID is the id of the acting Beneficiary, and
  any self-only operation (such as disclaiming one's own interest)
  requires that X-User-ID match Beneficiary.id."

  Use make_beneficiary_headers(beneficiary["id"]) for any
  ownership-gated call.

The shared *_FALLBACK_ID constants are ONLY safe for tests that DO
NOT exercise ownership (header-missing, role-mismatch on a
non-existent resource, or 404 paths).
"""
from __future__ import annotations

from typing import Dict

from prd_bench_local_runner.testing import build_user_headers


# ---------------------------------------------------------------------------
# Canonical opaque-actor identifiers — PRD §2.1.
# ---------------------------------------------------------------------------
COURT_CLERK_ID: str = "court-clerk-001"
COURT_CLERK_ID_ALT: str = "court-clerk-002"

# Entity-backed fallback ids — DO NOT use for ownership-gated calls.
EXECUTOR_FALLBACK_ID: str = "fallback-executor-1"
FIDUCIARY_FALLBACK_ID: str = "fallback-fiduciary-1"
BENEFICIARY_FALLBACK_ID: str = "fallback-beneficiary-1"


TEST_USERS: Dict[str, Dict[str, str]] = {
    # Opaque CourtClerk — shared constant is canonical.
    "court_clerk_headers": build_user_headers(COURT_CLERK_ID, "CourtClerk"),
    "court_clerk_headers_alt": build_user_headers(
        COURT_CLERK_ID_ALT, "CourtClerk",
    ),
    # Entity-backed Executor fallback — DO NOT use for ownership-gated
    # calls (i.e., calls on an existing Estate). Safe for: POST /estates
    # (no ownership check yet — first call to mint Fiduciary later),
    # header-missing, role-mismatch, 404 paths.
    "executor_fallback_headers": build_user_headers(
        EXECUTOR_FALLBACK_ID, "Executor",
    ),
    # Entity-backed Fiduciary fallback — DO NOT use for self-only calls
    # (resign). Safe only for read-only paths or tests that do not
    # exercise ownership.
    "fiduciary_fallback_headers": build_user_headers(
        FIDUCIARY_FALLBACK_ID, "Fiduciary",
    ),
    # Entity-backed Beneficiary fallback — same caveat as above.
    "beneficiary_fallback_headers": build_user_headers(
        BENEFICIARY_FALLBACK_ID, "Beneficiary",
    ),
}


# ---------------------------------------------------------------------------
# Per-instance builders — REQUIRED for entity-backed roles.
# The runtime Fiduciary.id / Beneficiary.id minted by their POST
# endpoints is the value the implementation will compare against in
# ownership checks.
# ---------------------------------------------------------------------------
def make_executor_headers(fiduciary_id: str) -> Dict[str, str]:
    """For Executor (entity_backed:Fiduciary, scope_type=EXECUTOR).

    PRD §2.1: "When X-User-Role is Executor, X-User-ID is the id of
    the acting Fiduciary row (one whose scope_type is EXECUTOR);
    ownership checks compare any resource's executor reference back
    to this id."

    Pass the actual Fiduciary.id (NOT contact_user_id) of the acting
    executor. Every Executor-driven mutation whose success depends on
    being the estate's executor MUST use this builder.
    """
    return build_user_headers(fiduciary_id, "Executor")


def make_fiduciary_headers(contact_user_id: str) -> Dict[str, str]:
    """For non-executor Fiduciary (TRUSTEE / GUARDIAN).

    PRD §2.1: "When X-User-Role is Fiduciary (covering the
    non-executor scopes — trustees and guardians), X-User-ID is again
    the id of the acting Fiduciary row, and self-only operations —
    for example, resigning — compare it against the
    Fiduciary.contact_user_id of the target row."

    Note: PRD says X-User-ID is "the id of the acting Fiduciary row"
    AND that self-only operations compare it to contact_user_id. The
    intended use is: pass the fiduciary's contact_user_id, which is
    what the row was created with as its signing user-id anchor.
    """
    return build_user_headers(contact_user_id, "Fiduciary")


def make_beneficiary_headers(beneficiary_id: str) -> Dict[str, str]:
    """For Beneficiary (entity_backed:Beneficiary).

    PRD §2.1: "When X-User-Role is Beneficiary, X-User-ID is the id
    of the acting Beneficiary, and any self-only operation (such as
    disclaiming one's own interest) requires that X-User-ID match
    Beneficiary.id."
    """
    return build_user_headers(beneficiary_id, "Beneficiary")


def make_court_clerk_headers(clerk_id: str) -> Dict[str, str]:
    """For CourtClerk (opaque). Any non-empty operator id is fine."""
    return build_user_headers(clerk_id, "CourtClerk")


__all__ = [
    "COURT_CLERK_ID",
    "COURT_CLERK_ID_ALT",
    "EXECUTOR_FALLBACK_ID",
    "FIDUCIARY_FALLBACK_ID",
    "BENEFICIARY_FALLBACK_ID",
    "TEST_USERS",
    "make_executor_headers",
    "make_fiduciary_headers",
    "make_beneficiary_headers",
    "make_court_clerk_headers",
]
