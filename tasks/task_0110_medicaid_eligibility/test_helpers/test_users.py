"""Pre-built role headers for every role in the PRD.

PRD §2.1 identity model:

    "All four roles have an opaque identity. When X-User-Role is
    IntakeWorker, EligibilityCaseworker, AppealsOfficer, or PolicyAdmin,
    the value of X-User-ID is an opaque operator identifier that is not
    tied to any persisted entity in the system."

Therefore every role is OPAQUE. Shared TEST_USERS constants are the
canonical form for every call. There is no entity-backed ownership
check that would require a builder to mint headers from a particular
entity id.

PRD §2.1 also defines a segregation-of-duties rule that compares
X-User-ID values ACROSS time and roles:

    "An EligibilityCaseworker who is asked to re-decide an application
    that has cycled back into review must not be the same X-User-ID who
    issued the prior INELIGIBLE determination on that same application.
    An AppealsOfficer who is asked to grant or uphold an appeal must
    not be the same X-User-ID who issued the determination being
    appealed (in either role capacity)."

To exercise that rule, tests need DISTINCT opaque operator ids inside
one role and ACROSS roles. We expose:

  - Per-role primary constants (TEST_USERS["{role}_headers"]).
  - Per-role alternate constants (TEST_USERS["{role}_headers_alt"]) for
    the same role but a different X-User-ID — needed for re-decide
    scenarios.
  - make_<role>_headers(operator_id) builders so a test can mint
    arbitrarily many distinct opaque ids per role on demand (e.g., for
    cross-role same-actor tests where one operator acts as both
    caseworker and appeals officer).
"""
from __future__ import annotations

from typing import Dict

from prd_bench_local_runner.testing import build_user_headers


# ---------------------------------------------------------------------------
# Canonical opaque operator identifiers — PRD §2.1 (all four roles opaque).
# ---------------------------------------------------------------------------
INTAKE_WORKER_ID = "iw-001"
INTAKE_WORKER_ID_ALT = "iw-002"

ELIGIBILITY_CASEWORKER_ID = "ec-001"
ELIGIBILITY_CASEWORKER_ID_ALT = "ec-002"

APPEALS_OFFICER_ID = "ao-001"
APPEALS_OFFICER_ID_ALT = "ao-002"

POLICY_ADMIN_ID = "pa-001"
POLICY_ADMIN_ID_ALT = "pa-002"


TEST_USERS: Dict[str, Dict[str, str]] = {
    # IntakeWorker — opaque.
    "intake_worker_headers": build_user_headers(
        INTAKE_WORKER_ID, "IntakeWorker",
    ),
    "intake_worker_headers_alt": build_user_headers(
        INTAKE_WORKER_ID_ALT, "IntakeWorker",
    ),

    # EligibilityCaseworker — opaque. The primary and alt constants both
    # represent valid caseworkers; the segregation-of-duties rule (PRD
    # §2.1) requires that re-decisions use a DIFFERENT X-User-ID from
    # the original deny — tests pick the alt for re-decide steps.
    "eligibility_caseworker_headers": build_user_headers(
        ELIGIBILITY_CASEWORKER_ID, "EligibilityCaseworker",
    ),
    "eligibility_caseworker_headers_alt": build_user_headers(
        ELIGIBILITY_CASEWORKER_ID_ALT, "EligibilityCaseworker",
    ),

    # AppealsOfficer — opaque. The primary and alt constants both
    # represent valid officers; segregation-of-duties (PRD §2.1)
    # requires the appeals officer to differ from the X-User-ID who
    # issued the appealed determination.
    "appeals_officer_headers": build_user_headers(
        APPEALS_OFFICER_ID, "AppealsOfficer",
    ),
    "appeals_officer_headers_alt": build_user_headers(
        APPEALS_OFFICER_ID_ALT, "AppealsOfficer",
    ),

    # PolicyAdmin — opaque.
    "policy_admin_headers": build_user_headers(
        POLICY_ADMIN_ID, "PolicyAdmin",
    ),
    "policy_admin_headers_alt": build_user_headers(
        POLICY_ADMIN_ID_ALT, "PolicyAdmin",
    ),
}


# ---------------------------------------------------------------------------
# Per-instance builders — all roles are opaque per PRD §2.1, so these
# are convenience helpers for tests that need a distinct operator id
# (e.g., same-actor segregation-of-duties tests).
# ---------------------------------------------------------------------------
def make_intake_worker_headers(operator_id: str) -> Dict[str, str]:
    """Mint IntakeWorker headers with a specific opaque operator id."""
    return build_user_headers(operator_id, "IntakeWorker")


def make_eligibility_caseworker_headers(operator_id: str) -> Dict[str, str]:
    """Mint EligibilityCaseworker headers with a specific opaque
    operator id. PRD §2.1: segregation-of-duties compares the acting
    X-User-ID against the X-User-ID who issued any prior INELIGIBLE
    determination on the same application — tests use this builder to
    pin a deciding operator id."""
    return build_user_headers(operator_id, "EligibilityCaseworker")


def make_appeals_officer_headers(operator_id: str) -> Dict[str, str]:
    """Mint AppealsOfficer headers with a specific opaque operator id.
    PRD §2.1: segregation-of-duties compares the acting appeals
    officer's X-User-ID against the X-User-ID who issued the appealed
    determination, regardless of the role they acted under previously."""
    return build_user_headers(operator_id, "AppealsOfficer")


def make_policy_admin_headers(operator_id: str) -> Dict[str, str]:
    """Mint PolicyAdmin headers with a specific opaque operator id."""
    return build_user_headers(operator_id, "PolicyAdmin")


__all__ = [
    "INTAKE_WORKER_ID",
    "INTAKE_WORKER_ID_ALT",
    "ELIGIBILITY_CASEWORKER_ID",
    "ELIGIBILITY_CASEWORKER_ID_ALT",
    "APPEALS_OFFICER_ID",
    "APPEALS_OFFICER_ID_ALT",
    "POLICY_ADMIN_ID",
    "POLICY_ADMIN_ID_ALT",
    "TEST_USERS",
    "make_intake_worker_headers",
    "make_eligibility_caseworker_headers",
    "make_appeals_officer_headers",
    "make_policy_admin_headers",
]
