"""Pre-built role headers for the Public Rental Housing API (PRD §2.1).

PRD §2.1 distinguishes two identity flavors:

- `Applicant` is *entity-backed*: when X-User-Role is Applicant, X-User-ID is the id of
  the acting Application's owner. The server records X-User-ID into
  Application.applicant_user_id at creation, and downstream ownership-gated calls
  (allocation confirm/reject, contract pay-deposit/sign, rent-reduction resubmit)
  compare the chain root's applicant_user_id to X-User-ID.

- `HousingDirector`, `HousingOfficer`, `Citizen`, and `IntegrationGateway` are *opaque*:
  the server may record X-User-ID into audit/segregation fields but never compares it to
  any entity id.

For every entity-backed role this module exposes a per-instance builder
(`make_applicant_headers(user_id)`); fixtures MUST call that builder with the
applicant's actual chosen X-User-ID so that ownership checks resolve correctly. The
shared-constant fallback in TEST_USERS is appropriate only for tests that never reach an
ownership check (RBAC probes, missing-header probes, NOT_FOUND probes).

PRD §3.6 requires the rent-reduction primary reviewer and final approver to be different
X-User-IDs (segregation of duties). We expose `make_housing_officer_headers(user_id)` and
`make_housing_director_headers(user_id)` so fixtures and tests can mint as many distinct
opaque operators as needed.
"""

from typing import Dict

from prd_bench_local_runner.testing import build_user_headers


# ──────────────────────────────────────────────────────────
# Shared constants — canonical form for opaque roles, fallback-only for Applicant.
# ──────────────────────────────────────────────────────────

TEST_USERS: Dict[str, Dict[str, str]] = {
    # Opaque roles: X-User-ID never compared to any entity id.
    "housing_director_headers": build_user_headers("test-director-1", "HousingDirector"),
    "housing_director_headers_alt": build_user_headers("test-director-2", "HousingDirector"),
    "housing_officer_headers": build_user_headers("test-officer-1", "HousingOfficer"),
    "housing_officer_headers_alt": build_user_headers("test-officer-2", "HousingOfficer"),
    "citizen_headers": build_user_headers("test-citizen-1", "Citizen"),
    "integration_gateway_headers": build_user_headers(
        "test-integration-1", "IntegrationGateway"
    ),
    # Applicant fallback — valid only for tests that do not exercise ownership.
    "applicant_headers_fallback": build_user_headers(
        "test-applicant-fallback", "Applicant"
    ),
}


# ──────────────────────────────────────────────────────────
# Per-instance builders — REQUIRED whenever the call is ownership-gated.
# ──────────────────────────────────────────────────────────


def make_applicant_headers(user_id: str) -> Dict[str, str]:
    """Build Applicant headers where X-User-ID equals the acting Application's
    applicant_user_id. Ownership checks on allocation confirm/reject, pay-deposit, sign,
    and resubmit compare the chain-root Application.applicant_user_id to X-User-ID, so
    fixtures must pass the same id they used to create the Application.
    """
    return build_user_headers(user_id, "Applicant")


def make_housing_director_headers(user_id: str) -> Dict[str, str]:
    """Build HousingDirector headers with an arbitrary opaque user_id. Used by tests
    exercising rent-reduction final-approve segregation of duties, which requires the
    director's X-User-ID to differ from the recorded primary reviewer's X-User-ID.
    """
    return build_user_headers(user_id, "HousingDirector")


def make_housing_officer_headers(user_id: str) -> Dict[str, str]:
    """Build HousingOfficer headers with an arbitrary opaque user_id. Used so tests can
    distinguish the officer who advances PRIMARY_REVIEW -> SECONDARY_REVIEW from the
    one who does anything else.
    """
    return build_user_headers(user_id, "HousingOfficer")


def make_citizen_headers(user_id: str = "test-citizen-1") -> Dict[str, str]:
    return build_user_headers(user_id, "Citizen")


def make_integration_gateway_headers(
    user_id: str = "test-integration-1",
) -> Dict[str, str]:
    return build_user_headers(user_id, "IntegrationGateway")
