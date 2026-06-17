"""Pre-built role headers for every role in the PRD.

The PRD recognizes exactly four roles (§2.1): RegistrationAgency, Sponsor,
TrainingCoordinator, Apprentice.

Identity binding (§2.1):
  - Sponsor    -> entity-backed: X-User-ID is the acting Sponsor's id.
  - Apprentice -> entity-backed: X-User-ID is the acting Apprentice's id.
  - RegistrationAgency / TrainingCoordinator -> opaque operator identifiers,
    never compared to a persisted entity id.

For the two entity-backed roles a per-instance builder is provided; fixtures and
tests MUST thread the real entity id through these builders for ownership-gated
calls rather than relying on the shared constants.
"""
from prd_bench_local_runner.testing import build_user_headers


# Shared constants — safe for the two opaque operator roles, and for tests that
# do not exercise Sponsor/Apprentice ownership.
TEST_USERS = {
    "registration_agency_headers": build_user_headers("test-agency-1", "RegistrationAgency"),
    "training_coordinator_headers": build_user_headers("test-coordinator-1", "TrainingCoordinator"),
    # Fallbacks for the entity-backed roles — used only by non-ownership tests
    # (e.g. 400-on-bad-payload, 404-on-missing-resource, pagination bounds).
    "sponsor_headers": build_user_headers("test-sponsor-1", "Sponsor"),
    "apprentice_headers": build_user_headers("test-apprentice-1", "Apprentice"),
}


def make_sponsor_headers(user_id: str) -> dict:
    """For the entity-backed Sponsor role. Pass the actual Sponsor.id as user_id
    whenever the call is ownership-gated (building programs, registering
    agreements, logging hours under that sponsor)."""
    return build_user_headers(user_id, "Sponsor")


def make_apprentice_headers(user_id: str) -> dict:
    """For the entity-backed Apprentice role. Pass the actual Apprentice.id as
    user_id whenever the apprentice acts on its own training data."""
    return build_user_headers(user_id, "Apprentice")
