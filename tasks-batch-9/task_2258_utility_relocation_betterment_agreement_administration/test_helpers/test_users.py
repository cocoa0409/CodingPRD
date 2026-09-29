"""Request identities for the seven roles the PRD recognises.

Six of the roles carry an opaque identity: any stable ``X-User-ID`` works and the
shared constants below are enough.  ``UtilityOwnerRep`` is different: the PRD
scopes it to the utility owner it represents, so its ``X-User-ID`` must be the
real ``UtilityOwner.id`` of the row being acted on.  For that role always call
:func:`make_utility_owner_rep_headers` with the owner id returned by the owner
registration endpoint - there is deliberately no shared constant for it.
"""
from prd_bench_local_runner.testing import build_user_headers

# ---------------------------------------------------------------------------
# Named user identifiers used where the PRD makes identity observable
# (segregation of duties and the "first issuer" stamp).
# ---------------------------------------------------------------------------
PROGRAM_ADMIN_USER_ID = "admin-1"
COORDINATOR_USER_ID = "coordinator-1"
ADJUDICATOR_USER_ID = "adjudicator-1"
SECOND_ADJUDICATOR_USER_ID = "adjudicator-2"
OFFICER_USER_ID = "officer-1"
SECOND_OFFICER_USER_ID = "officer-2"
AUDITOR_USER_ID = "auditor-1"
SECOND_AUDITOR_USER_ID = "auditor-2"
ENGINEER_USER_ID = "engineer-1"


def make_program_admin_headers(user_id: str = PROGRAM_ADMIN_USER_ID) -> dict:
    return build_user_headers(user_id, "ProgramAdmin")


def make_utility_coordinator_headers(user_id: str = COORDINATOR_USER_ID) -> dict:
    return build_user_headers(user_id, "UtilityCoordinator")


def make_right_of_way_adjudicator_headers(user_id: str = ADJUDICATOR_USER_ID) -> dict:
    return build_user_headers(user_id, "RightOfWayAdjudicator")


def make_agreement_officer_headers(user_id: str = OFFICER_USER_ID) -> dict:
    return build_user_headers(user_id, "AgreementOfficer")


def make_external_auditor_headers(user_id: str = AUDITOR_USER_ID) -> dict:
    return build_user_headers(user_id, "ExternalAuditor")


def make_construction_engineer_headers(user_id: str = ENGINEER_USER_ID) -> dict:
    return build_user_headers(user_id, "ConstructionEngineer")


def make_utility_owner_rep_headers(owner_id: str) -> dict:
    """Headers for the entity-backed role.

    ``owner_id`` must be the identifier of a registered utility owner; the PRD
    resolves the representative's scope from ``X-User-ID``.
    """
    return build_user_headers(owner_id, "UtilityOwnerRep")


TEST_USERS: dict[str, dict] = {
    "program_admin_headers": make_program_admin_headers(),
    "utility_coordinator_headers": make_utility_coordinator_headers(),
    "right_of_way_adjudicator_headers": make_right_of_way_adjudicator_headers(),
    "second_adjudicator_headers": make_right_of_way_adjudicator_headers(
        SECOND_ADJUDICATOR_USER_ID
    ),
    "agreement_officer_headers": make_agreement_officer_headers(),
    "external_auditor_headers": make_external_auditor_headers(),
    "construction_engineer_headers": make_construction_engineer_headers(),
}

# Headers that carry no identity at all, used to exercise the authentication rung.
NO_AUTH_HEADERS: dict = {}

# A syntactically fine but unrecognised role string.
UNKNOWN_ROLE_HEADERS: dict = build_user_headers("stranger-1", "DistrictClerk")

__all__ = [
    "PROGRAM_ADMIN_USER_ID",
    "COORDINATOR_USER_ID",
    "ADJUDICATOR_USER_ID",
    "SECOND_ADJUDICATOR_USER_ID",
    "OFFICER_USER_ID",
    "SECOND_OFFICER_USER_ID",
    "AUDITOR_USER_ID",
    "SECOND_AUDITOR_USER_ID",
    "ENGINEER_USER_ID",
    "make_program_admin_headers",
    "make_utility_coordinator_headers",
    "make_right_of_way_adjudicator_headers",
    "make_agreement_officer_headers",
    "make_external_auditor_headers",
    "make_construction_engineer_headers",
    "make_utility_owner_rep_headers",
    "TEST_USERS",
    "NO_AUTH_HEADERS",
    "UNKNOWN_ROLE_HEADERS",
]
