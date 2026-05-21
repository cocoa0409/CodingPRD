"""Pre-built role headers for every role in the PRD.

PRD §2.1 identity rules:

    "When `X-User-Role` is `Candidate`, `X-User-ID` is the `id` of the
    acting `Candidate`; ownership checks on any resource that references
    a `Candidate` (consent disclosures, orders, verification items,
    disputes) compare the resource's foreign-key `candidate_id` to
    `X-User-ID`."

    "When `X-User-Role` is `Recruiter`, `Adjudicator`, `Verifier`, or
    `PlatformAdmin`, `X-User-ID` is an opaque operator identifier not
    tied to any persisted entity."

Only ONE role is entity_backed in this PRD: Candidate. Every fixture
that creates a ConsentDisclosure (when the actor is the Candidate),
opens a Dispute, or calls revoke-consent, MUST use the candidate's
actual id as the `X-User-ID` — otherwise ownership checks
(ERR_DISPUTE_NOT_OWNED on disputes, ERR_FORBIDDEN on consent revocation)
will reject the request. The helper `make_candidate_headers(candidate_id)`
is mandatory for that.

Recruiter and Adjudicator are opaque, but the segregation-of-duties
rule (PRD §2.11) requires that the `X-User-ID` opening an order and
the `X-User-ID` issuing Pre-Adverse / Final-Adverse / resolving a
dispute against that order be DIFFERENT. Fixtures default to distinct
shared ids for the two roles and expose per-instance builders so tests
that probe SoD failure can deliberately collide the ids.
"""
from __future__ import annotations

import uuid
from typing import Dict

from prd_bench_local_runner.testing import build_user_headers


# ---------------------------------------------------------------------------
# Shared deterministic ids for opaque roles. Recruiter and Adjudicator
# default ids are intentionally distinct so the segregation-of-duties
# check (PRD §2.11) is satisfied by the default lifecycle path.
# ---------------------------------------------------------------------------
RECRUITER_SHARED_ID: str = "recruiter-op-0001"
RECRUITER_SECONDARY_ID: str = "recruiter-op-0002"

ADJUDICATOR_SHARED_ID: str = "adjudicator-op-0001"
ADJUDICATOR_SECONDARY_ID: str = "adjudicator-op-0002"

VERIFIER_SHARED_ID: str = "verifier-op-0001"

PLATFORM_ADMIN_SHARED_ID: str = "platform-admin-op-0001"

# Entity-backed placeholder — does NOT resolve to any real candidate
# unless a Candidate is created with this id. Used only for auth /
# role / 404 probes that don't exercise ownership.
CANDIDATE_PLACEHOLDER_ID: str = "candidate-placeholder-0001"


TEST_USERS: Dict[str, Dict[str, str]] = {
    # opaque Recruiter — shared constant is the canonical form.
    "recruiter_headers": build_user_headers(
        RECRUITER_SHARED_ID, "Recruiter",
    ),
    "recruiter_secondary_headers": build_user_headers(
        RECRUITER_SECONDARY_ID, "Recruiter",
    ),
    # opaque Adjudicator — shared constant is the canonical form.
    "adjudicator_headers": build_user_headers(
        ADJUDICATOR_SHARED_ID, "Adjudicator",
    ),
    "adjudicator_secondary_headers": build_user_headers(
        ADJUDICATOR_SECONDARY_ID, "Adjudicator",
    ),
    # opaque Verifier — shared constant is the canonical form.
    "verifier_headers": build_user_headers(
        VERIFIER_SHARED_ID, "Verifier",
    ),
    # opaque PlatformAdmin — shared constant is the canonical form.
    "platform_admin_headers": build_user_headers(
        PLATFORM_ADMIN_SHARED_ID, "PlatformAdmin",
    ),
    # entity_backed Candidate — placeholder for non-ownership probes.
    "candidate_headers": build_user_headers(
        CANDIDATE_PLACEHOLDER_ID, "Candidate",
    ),
}


# ---------------------------------------------------------------------------
# Per-instance builders.
# ---------------------------------------------------------------------------
def make_candidate_headers(candidate_id: str) -> Dict[str, str]:
    """Headers for a Candidate acting on behalf of `candidate_id`.

    MANDATORY whenever the call resolves an ownership check against the
    candidate — POST /fcra/candidates/{id}/consent (when acting as the
    candidate themselves), POST /fcra/candidates/{id}/consent/revoke
    (must equal own candidate id), POST /fcra/disputes (must be on own
    verification item), and GET /fcra/candidates/{id} (Candidate may
    read their own row).

    PRD §2.1: "ownership checks on any resource that references a
    `Candidate` ... compare the resource's foreign-key `candidate_id`
    to `X-User-ID`."
    """
    return build_user_headers(candidate_id, "Candidate")


def make_recruiter_headers(operator_id: str) -> Dict[str, str]:
    """Headers for a Recruiter with a specific opaque operator id.

    Use a DIFFERENT id from any Adjudicator that will act on the same
    order — PRD §2.11 segregation-of-duties.
    """
    return build_user_headers(operator_id, "Recruiter")


def make_adjudicator_headers(operator_id: str) -> Dict[str, str]:
    """Headers for an Adjudicator with a specific opaque operator id.

    PRD §2.11: "The Adjudicator's `X-User-ID` must differ from the
    `BackgroundCheckOrder.opened_by_user_id` recorded when the order
    was opened".
    """
    return build_user_headers(operator_id, "Adjudicator")


def make_verifier_headers(operator_id: str) -> Dict[str, str]:
    """Headers for a Verifier with a specific opaque operator id."""
    return build_user_headers(operator_id, "Verifier")


def make_platform_admin_headers(operator_id: str) -> Dict[str, str]:
    """Headers for a PlatformAdmin with a specific opaque operator id."""
    return build_user_headers(operator_id, "PlatformAdmin")


def new_candidate_id(prefix: str = "cand") -> str:
    """Generate a unique deterministic-shape candidate id for a fresh
    fixture. The id is supplied by the Recruiter when creating the
    candidate and is then used as `X-User-ID` when the candidate acts
    on their own consent / disputes.

    Note: when the Recruiter is the one creating a candidate, the
    server mints the candidate's id. We therefore use this helper only
    for tests that need a synthetic placeholder id (e.g. ownership-
    failure probes); fixtures that drive the happy path read the
    server-minted id off the create-candidate response.
    """
    return f"{prefix}-{uuid.uuid4().hex[:12]}"


def new_operator_id(prefix: str = "op") -> str:
    """Generate a unique opaque operator id."""
    return f"{prefix}-{uuid.uuid4().hex[:12]}"


__all__ = [
    "RECRUITER_SHARED_ID",
    "RECRUITER_SECONDARY_ID",
    "ADJUDICATOR_SHARED_ID",
    "ADJUDICATOR_SECONDARY_ID",
    "VERIFIER_SHARED_ID",
    "PLATFORM_ADMIN_SHARED_ID",
    "CANDIDATE_PLACEHOLDER_ID",
    "TEST_USERS",
    "make_candidate_headers",
    "make_recruiter_headers",
    "make_adjudicator_headers",
    "make_verifier_headers",
    "make_platform_admin_headers",
    "new_candidate_id",
    "new_operator_id",
]
