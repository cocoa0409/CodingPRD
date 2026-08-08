"""Pre-built role headers for every role in the PRD (§2.1).

Opaque roles (HealthOfficer, Inspector, PlanReviewer, RecordsClerk, PublicUser)
carry an identifier that is never compared to any entity id, so the shared
constants below are always safe for them.

EstablishmentOperator and Artist are entity-backed: their X-User-ID must be the
id of the establishment (respectively the artist) they act as. Every
ownership-gated call MUST build headers with the real entity id through the
per-instance builders at the bottom of this module.
"""

from prd_bench_local_runner.testing import build_user_headers

# Two distinct HealthOfficer identifiers: segregation of duties forbids the
# officer who issued an enforcement action from lifting it (PRD §2.1).
OFFICER_ONE_ID = "officer-ho-1"
OFFICER_TWO_ID = "officer-ho-2"
INSPECTOR_ONE_ID = "officer-insp-1"
INSPECTOR_TWO_ID = "officer-insp-2"
PLAN_REVIEWER_ID = "reviewer-1"
RECORDS_CLERK_ID = "clerk-1"
PUBLIC_USER_ID = "citizen-1"

TEST_USERS = {
    "health_officer_headers": build_user_headers(OFFICER_ONE_ID, "HealthOfficer"),
    "health_officer_2_headers": build_user_headers(OFFICER_TWO_ID, "HealthOfficer"),
    "inspector_headers": build_user_headers(INSPECTOR_ONE_ID, "Inspector"),
    "inspector_2_headers": build_user_headers(INSPECTOR_TWO_ID, "Inspector"),
    "plan_reviewer_headers": build_user_headers(PLAN_REVIEWER_ID, "PlanReviewer"),
    "records_clerk_headers": build_user_headers(RECORDS_CLERK_ID, "RecordsClerk"),
    "public_user_headers": build_user_headers(PUBLIC_USER_ID, "PublicUser"),
}

# A request that carries neither X-User-ID nor X-User-Role.
NO_AUTH_HEADERS = {"Content-Type": "application/json"}


def make_operator_headers(establishment_id: str) -> dict:
    """Headers for an EstablishmentOperator acting as the given establishment.

    X-User-ID is the establishment's own id.
    """
    return build_user_headers(establishment_id, "EstablishmentOperator")


def make_artist_headers(artist_id: str) -> dict:
    """Headers for an Artist acting as themselves. X-User-ID is the artist id."""
    return build_user_headers(artist_id, "Artist")


def make_health_officer_headers(user_id: str) -> dict:
    """Headers for a specific HealthOfficer identifier."""
    return build_user_headers(user_id, "HealthOfficer")


def make_inspector_headers(user_id: str) -> dict:
    """Headers for a specific Inspector identifier."""
    return build_user_headers(user_id, "Inspector")


def make_public_user_headers(user_id: str) -> dict:
    """Headers for a specific PublicUser identifier."""
    return build_user_headers(user_id, "PublicUser")
