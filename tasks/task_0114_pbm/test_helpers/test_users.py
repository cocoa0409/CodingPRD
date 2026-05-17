"""Pre-built role headers for every role in the PRD.

PRD §2.1 identity rule (verbatim):

    "For every one of these four roles, X-User-ID is an opaque
    operator identifier that is not tied to any persisted entity in
    the system. The server may record the identifier on side-effect-
    bearing operations (for example, as part of audit on a transition)
    but never compares X-User-ID to any entity's id. Ownership is
    therefore not derived from the caller's identity; the caller's
    role alone determines the set of operations they may invoke, and
    the resources they may touch are constrained only by the path-
    parameter ids the request supplies."

Consequence: every PBM role (PBMAdmin, Prescriber, ClinicalReviewer,
ClaimsAdjudicator) is OPAQUE. Shared role-header constants in
``TEST_USERS`` are canonical for every call. There is no entity-backed
role, so no per-instance-id ownership-threaded headers are needed.

Per-role ``make_<role>_headers(user_id)`` helpers are still provided so
that tests can mint headers with a distinct operator id (e.g., to
exercise audit fields, or to use a second principal in a concurrency
test) without re-typing the role string.
"""
from __future__ import annotations

from typing import Dict

from prd_bench_local_runner.testing import build_user_headers


# ---------------------------------------------------------------------------
# Canonical opaque-operator identifiers — PRD §2.1.
# ---------------------------------------------------------------------------
PBM_ADMIN_ID = "pbm-admin-001"
PBM_ADMIN_ID_ALT = "pbm-admin-002"

PRESCRIBER_ID = "prescriber-001"
PRESCRIBER_ID_ALT = "prescriber-002"

CLINICAL_REVIEWER_ID = "clinical-reviewer-001"
CLINICAL_REVIEWER_ID_ALT = "clinical-reviewer-002"

CLAIMS_ADJUDICATOR_ID = "claims-adjudicator-001"
CLAIMS_ADJUDICATOR_ID_ALT = "claims-adjudicator-002"


TEST_USERS: Dict[str, Dict[str, str]] = {
    # PBMAdmin — opaque. Authorized for plan / drug / member / formulary
    # / copay-card / rebate-agreement / ledger / clock operations.
    "admin_headers": build_user_headers(PBM_ADMIN_ID, "PBMAdmin"),
    "admin_headers_alt": build_user_headers(
        PBM_ADMIN_ID_ALT, "PBMAdmin",
    ),

    # Prescriber — opaque. Authorized for PA create / submit / resubmit
    # and for POST /pbm/claims.
    "prescriber_headers": build_user_headers(PRESCRIBER_ID, "Prescriber"),
    "prescriber_headers_alt": build_user_headers(
        PRESCRIBER_ID_ALT, "Prescriber",
    ),

    # ClinicalReviewer — opaque. Authorized for PA approve / deny /
    # request-info / revoke.
    "clinical_reviewer_headers": build_user_headers(
        CLINICAL_REVIEWER_ID, "ClinicalReviewer",
    ),
    "clinical_reviewer_headers_alt": build_user_headers(
        CLINICAL_REVIEWER_ID_ALT, "ClinicalReviewer",
    ),

    # ClaimsAdjudicator — opaque. Authorized for claim adjudicate / pay
    # / reverse, and for POST /pbm/claims.
    "claims_adjudicator_headers": build_user_headers(
        CLAIMS_ADJUDICATOR_ID, "ClaimsAdjudicator",
    ),
    "claims_adjudicator_headers_alt": build_user_headers(
        CLAIMS_ADJUDICATOR_ID_ALT, "ClaimsAdjudicator",
    ),
}


# ---------------------------------------------------------------------------
# Per-role header builders. PRD §2.1: "the server may record the
# identifier on side-effect-bearing operations (for example, as part
# of audit on a transition) but never compares X-User-ID to any
# entity's id." Use these when a test wants a fresh operator id.
# ---------------------------------------------------------------------------
def make_admin_headers(user_id: str) -> Dict[str, str]:
    """For PBMAdmin (opaque). Any non-empty operator id is fine."""
    return build_user_headers(user_id, "PBMAdmin")


def make_prescriber_headers(user_id: str) -> Dict[str, str]:
    """For Prescriber (opaque). Any non-empty operator id is fine."""
    return build_user_headers(user_id, "Prescriber")


def make_clinical_reviewer_headers(user_id: str) -> Dict[str, str]:
    """For ClinicalReviewer (opaque). Any non-empty operator id is
    fine."""
    return build_user_headers(user_id, "ClinicalReviewer")


def make_claims_adjudicator_headers(user_id: str) -> Dict[str, str]:
    """For ClaimsAdjudicator (opaque). Any non-empty operator id is
    fine."""
    return build_user_headers(user_id, "ClaimsAdjudicator")


__all__ = [
    "PBM_ADMIN_ID",
    "PBM_ADMIN_ID_ALT",
    "PRESCRIBER_ID",
    "PRESCRIBER_ID_ALT",
    "CLINICAL_REVIEWER_ID",
    "CLINICAL_REVIEWER_ID_ALT",
    "CLAIMS_ADJUDICATOR_ID",
    "CLAIMS_ADJUDICATOR_ID_ALT",
    "TEST_USERS",
    "make_admin_headers",
    "make_prescriber_headers",
    "make_clinical_reviewer_headers",
    "make_claims_adjudicator_headers",
]
