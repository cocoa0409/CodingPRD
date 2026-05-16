"""Pre-built role headers for every role in PRD §2.1.

PRD §2.1 identity rules:

ENTITY-BACKED role — X-User-ID is the id of a persisted Candidate row:

  - Candidate: PRD §2.1 — "When `X-User-Role` is `Candidate`, `X-User-ID`
    is the `id` of the acting `Candidate` row; ownership checks on every
    resource that references a `Candidate` (registrations, accommodation
    requests, score reports, refund transactions, CLEP credit awards)
    compare the resource's `candidate_id` to `X-User-ID`."

    Every Candidate-role call whose success depends on owning the
    target resource MUST mint headers via make_candidate_headers(
    candidate_id) using the real Candidate.id returned by POST
    /candidates. The shared CANDIDATE_FALLBACK_ID constant is ONLY
    safe for tests that DO NOT exercise ownership (header-missing,
    role-mismatch, NotFound paths, or calls where the Candidate role
    is provably not permitted for the endpoint).

OPAQUE roles — X-User-ID is an opaque operator identifier not tied to
any persisted entity row. PRD §2.1 makes them canonical for shared
constants:

  - Proctor (no identity capture)
  - AccommodationsOfficer (id captured in reviewer_user_id on
    AccommodationRequest; segregation-of-duties in PRD §2.9 / §3.6
    compares the acting officer's X-User-ID against reviewer_user_id
    on subsequent reviews, so SoD tests need TWO DISTINCT officer ids)
  - Registrar (no identity capture)
  - CreditsOfficer (id captured in posted_by_user_id on CLEPCreditAward)
"""
from __future__ import annotations

from typing import Dict

from prd_bench_local_runner.testing import build_user_headers


# ---------------------------------------------------------------------------
# Opaque-role canonical ids.
# ---------------------------------------------------------------------------
REGISTRAR_ID = "registrar-001"
REGISTRAR_ID_ALT = "registrar-002"

PROCTOR_ID = "proctor-001"
PROCTOR_ID_ALT = "proctor-002"

ACCOMMODATIONS_OFFICER_ID = "officer-001"
ACCOMMODATIONS_OFFICER_ID_ALT = "officer-002"

CREDITS_OFFICER_ID = "credits-001"
CREDITS_OFFICER_ID_ALT = "credits-002"


# ---------------------------------------------------------------------------
# Entity-backed fallback id. DO NOT USE for ownership-gated Candidate
# calls — use make_candidate_headers(candidate["id"]) with the real
# Candidate.id returned from POST /candidates.
# ---------------------------------------------------------------------------
CANDIDATE_FALLBACK_ID = "candidate-fallback-1"


TEST_USERS: Dict[str, Dict[str, str]] = {
    # Opaque roles — shared constants are canonical (PRD §2.1).
    "registrar_headers": build_user_headers(REGISTRAR_ID, "Registrar"),
    "registrar_headers_alt": build_user_headers(REGISTRAR_ID_ALT, "Registrar"),
    "proctor_headers": build_user_headers(PROCTOR_ID, "Proctor"),
    "proctor_headers_alt": build_user_headers(PROCTOR_ID_ALT, "Proctor"),
    "accommodations_officer_headers": build_user_headers(
        ACCOMMODATIONS_OFFICER_ID, "AccommodationsOfficer",
    ),
    "accommodations_officer_headers_alt": build_user_headers(
        ACCOMMODATIONS_OFFICER_ID_ALT, "AccommodationsOfficer",
    ),
    "credits_officer_headers": build_user_headers(
        CREDITS_OFFICER_ID, "CreditsOfficer",
    ),
    "credits_officer_headers_alt": build_user_headers(
        CREDITS_OFFICER_ID_ALT, "CreditsOfficer",
    ),

    # Entity-backed fallback — ONLY for non-ownership tests.
    "candidate_headers_fallback": build_user_headers(
        CANDIDATE_FALLBACK_ID, "Candidate",
    ),
}


# ---------------------------------------------------------------------------
# Per-instance builders.
# ---------------------------------------------------------------------------
def make_candidate_headers(candidate_id: str) -> Dict[str, str]:
    """Mint Candidate headers bound to a real Candidate.id.

    PRD §2.1: "When `X-User-Role` is `Candidate`, `X-User-ID` is the
    `id` of the acting `Candidate` row; ownership checks on every
    resource that references a `Candidate` ... compare the resource's
    `candidate_id` to `X-User-ID`." Every Candidate-side mutation
    (create registration, self-cancel, submit ID, submit accommodation
    request, resubmit) MUST use this builder threading the actual
    Candidate.id from POST /candidates.
    """
    return build_user_headers(candidate_id, "Candidate")


def make_registrar_headers(registrar_id: str) -> Dict[str, str]:
    return build_user_headers(registrar_id, "Registrar")


def make_proctor_headers(proctor_id: str) -> Dict[str, str]:
    return build_user_headers(proctor_id, "Proctor")


def make_accommodations_officer_headers(officer_id: str) -> Dict[str, str]:
    """For AccommodationsOfficer (opaque). PRD §2.9 / §3.6 pin the
    caller's X-User-ID into reviewer_user_id at start-review, then
    reject any subsequent action by a different officer with
    ERR_NOT_PINNED_REVIEWER. Tests that exercise this SoD rule MUST
    use two distinct ids built via this helper."""
    return build_user_headers(officer_id, "AccommodationsOfficer")


def make_credits_officer_headers(officer_id: str) -> Dict[str, str]:
    """For CreditsOfficer (opaque). PRD §3.10: "the award row also
    records ... `posted_by_user_id` set from the officer's
    `X-User-ID`." Used to assert the field on AWARDED and DENIED
    outcomes."""
    return build_user_headers(officer_id, "CreditsOfficer")


__all__ = [
    "REGISTRAR_ID",
    "REGISTRAR_ID_ALT",
    "PROCTOR_ID",
    "PROCTOR_ID_ALT",
    "ACCOMMODATIONS_OFFICER_ID",
    "ACCOMMODATIONS_OFFICER_ID_ALT",
    "CREDITS_OFFICER_ID",
    "CREDITS_OFFICER_ID_ALT",
    "CANDIDATE_FALLBACK_ID",
    "TEST_USERS",
    "make_candidate_headers",
    "make_registrar_headers",
    "make_proctor_headers",
    "make_accommodations_officer_headers",
    "make_credits_officer_headers",
]
