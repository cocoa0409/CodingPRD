"""Pre-built role headers for every role in the PRD.

PRD §2.1 identity rule:

    "When `X-User-Role` is `Rider`, `X-User-ID` is the `id` of the
    acting `Rider`; any ownership check on a card, trip, dispute, or
    mobile token compares the resource's `rider_id` (directly or via
    the card's `rider_id`) to `X-User-ID`. When `X-User-Role` is
    `EmployerAdmin`, `X-User-ID` is the `id` of the acting `Employer`;
    ownership checks on a `CommuterBenefitAccount` or `FSAContribution`
    compare the account's `employer_id` to `X-User-ID`. When
    `X-User-Role` is `AgencyOfficer`, `X-User-ID` is an opaque operator
    identifier not tied to any persisted entity ... When `X-User-Role`
    is `Auditor`, `X-User-ID` is likewise an opaque operator
    identifier."

Two roles are entity_backed (Rider, EmployerAdmin). Every fixture or
test that issues an ownership-gated call (tap-in, tap-out, dispute
file, FSA contribution, account open, mobile token, card close, top-up
on own card) MUST mint headers via `make_rider_headers(rider_id)` or
`make_employer_admin_headers(employer_id)` with the actual entity id.
Falling back to the shared placeholder would force the implementation
to drop the ownership check in order to pass and is a test bug.

Two roles are opaque (AgencyOfficer, Auditor). Shared deterministic
ids are the canonical form for these.
"""
from __future__ import annotations

from typing import Dict

from prd_bench_local_runner.testing import build_user_headers


# ---------------------------------------------------------------------------
# Shared deterministic ids for opaque roles.
# ---------------------------------------------------------------------------
AGENCY_OFFICER_SHARED_ID: str = "agency-officer-op-0001"
AGENCY_OFFICER_SECONDARY_ID: str = "agency-officer-op-0002"

AUDITOR_SHARED_ID: str = "auditor-op-0001"

# Entity-backed placeholders — never resolve to a real entity. Used
# only for auth probes / wrong-role / 404 probes.
RIDER_PLACEHOLDER_ID: str = "rider-placeholder-0001"
EMPLOYER_ADMIN_PLACEHOLDER_ID: str = "employer-admin-placeholder-0001"


TEST_USERS: Dict[str, Dict[str, str]] = {
    # entity_backed Rider — shared constant is a placeholder for
    # auth/role/404 probes only.
    "rider_headers": build_user_headers(
        RIDER_PLACEHOLDER_ID, "Rider",
    ),
    # entity_backed EmployerAdmin — shared constant is a placeholder
    # for auth/role/404 probes only.
    "employer_admin_headers": build_user_headers(
        EMPLOYER_ADMIN_PLACEHOLDER_ID, "EmployerAdmin",
    ),
    # opaque AgencyOfficer — shared constants are the canonical form.
    "agency_officer_headers": build_user_headers(
        AGENCY_OFFICER_SHARED_ID, "AgencyOfficer",
    ),
    "agency_officer_secondary_headers": build_user_headers(
        AGENCY_OFFICER_SECONDARY_ID, "AgencyOfficer",
    ),
    # opaque Auditor — shared constant is the canonical form.
    "auditor_headers": build_user_headers(
        AUDITOR_SHARED_ID, "Auditor",
    ),
}


# ---------------------------------------------------------------------------
# Per-instance builders — MANDATORY for the entity_backed roles.
# PRD §2.1: "X-User-ID is the `id` of the acting `Rider`" /
# "X-User-ID is the `id` of the acting `Employer`".
# ---------------------------------------------------------------------------
def make_rider_headers(rider_id: str) -> Dict[str, str]:
    """Headers for a Rider acting on behalf of `rider_id`.

    Required whenever the call resolves an ownership check against the
    rider — POST /transit/trips (the card's rider_id must equal
    X-User-ID), POST /transit/trips/{id}/tap-out, POST /transit/disputes,
    POST /transit/cards/{id}/close, POST /transit/cards/{id}/top-up
    (own card), POST /transit/mobile-tokens, POST /transit/cards (own
    rider STANDARD or LOW_INCOME cards), POST
    /transit/low-income-verifications (on own rider_id), and GETs
    restricted to own resources.
    """
    return build_user_headers(rider_id, "Rider")


def make_employer_admin_headers(employer_id: str) -> Dict[str, str]:
    """Headers for an EmployerAdmin acting on behalf of `employer_id`.

    Required whenever the call resolves an ownership check against the
    employer — POST /transit/fsa-accounts (employer_id in payload must
    equal X-User-ID), POST /transit/fsa-contributions (account's
    employer_id must equal X-User-ID), POST
    /transit/fsa-contributions/{id}/reverse (same).
    """
    return build_user_headers(employer_id, "EmployerAdmin")


# ---------------------------------------------------------------------------
# Per-operator builders for opaque roles. Useful for tests that need
# two distinct operators (e.g., concurrent dispute resolution).
# ---------------------------------------------------------------------------
def make_agency_officer_headers(operator_id: str) -> Dict[str, str]:
    """Headers for an AgencyOfficer with a specific opaque operator id."""
    return build_user_headers(operator_id, "AgencyOfficer")


def make_auditor_headers(operator_id: str) -> Dict[str, str]:
    """Headers for an Auditor with a specific opaque operator id."""
    return build_user_headers(operator_id, "Auditor")


__all__ = [
    "AGENCY_OFFICER_SHARED_ID",
    "AGENCY_OFFICER_SECONDARY_ID",
    "AUDITOR_SHARED_ID",
    "RIDER_PLACEHOLDER_ID",
    "EMPLOYER_ADMIN_PLACEHOLDER_ID",
    "TEST_USERS",
    "make_rider_headers",
    "make_employer_admin_headers",
    "make_agency_officer_headers",
    "make_auditor_headers",
]
