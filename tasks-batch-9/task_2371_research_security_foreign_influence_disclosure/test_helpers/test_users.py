"""Pre-built role headers for every role named in the PRD."""

from prd_bench_local_runner.testing import build_user_headers

# Canonical user ids for the four roles whose X-User-ID is an opaque identifier.
SYSTEM_ADMIN_USER_ID = "admin-1"
RSO_USER_ID = "rso-1"
RSO_SECOND_USER_ID = "rso-2"
CRO_USER_ID = "cro-1"
CRO_SECOND_USER_ID = "cro-2"
LIAISON_USER_ID = "liaison-1"
LIAISON_SECOND_USER_ID = "liaison-2"

# Shared constants. Safe for the four opaque roles, whose X-User-ID is never
# compared against an entity id. The investigator entry is a fallback for tests
# that do not exercise ownership; ownership-gated calls MUST use
# make_investigator_headers(<Investigator.id>).
TEST_USERS = {
    "system_admin_headers": build_user_headers(SYSTEM_ADMIN_USER_ID, "SystemAdmin"),
    "rso_headers": build_user_headers(RSO_USER_ID, "ResearchSecurityOfficer"),
    "rso_second_headers": build_user_headers(
        RSO_SECOND_USER_ID, "ResearchSecurityOfficer"
    ),
    "cro_headers": build_user_headers(CRO_USER_ID, "ConflictReviewOfficial"),
    "cro_second_headers": build_user_headers(
        CRO_SECOND_USER_ID, "ConflictReviewOfficial"
    ),
    "liaison_headers": build_user_headers(LIAISON_USER_ID, "AgencyLiaison"),
    "liaison_second_headers": build_user_headers(
        LIAISON_SECOND_USER_ID, "AgencyLiaison"
    ),
    "investigator_headers": build_user_headers("investigator-1", "Investigator"),
}


def make_investigator_headers(investigator_id: str) -> dict:
    """Headers for the Investigator role.

    X-User-ID is the Investigator's own id, so every ownership check compares it
    directly against the resource's investigator_id. Always pass the real
    Investigator id for ownership-gated calls.
    """
    return build_user_headers(investigator_id, "Investigator")


def make_system_admin_headers(user_id: str = SYSTEM_ADMIN_USER_ID) -> dict:
    return build_user_headers(user_id, "SystemAdmin")


def make_research_security_officer_headers(user_id: str = RSO_USER_ID) -> dict:
    return build_user_headers(user_id, "ResearchSecurityOfficer")


def make_conflict_review_official_headers(user_id: str = CRO_USER_ID) -> dict:
    return build_user_headers(user_id, "ConflictReviewOfficial")


def make_agency_liaison_headers(user_id: str = LIAISON_USER_ID) -> dict:
    return build_user_headers(user_id, "AgencyLiaison")


ALL_ROLE_NAMES = [
    "SystemAdmin",
    "ResearchSecurityOfficer",
    "ConflictReviewOfficial",
    "AgencyLiaison",
    "Investigator",
]
