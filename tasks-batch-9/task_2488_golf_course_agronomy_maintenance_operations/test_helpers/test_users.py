"""Identity headers for the five roles of PRD §2.1.

"Every request must carry two headers: `X-User-ID`, identifying the acting
operator, and `X-User-Role`, declaring the capacity in which they are acting."

Four of the roles carry an opaque identifier: "When `X-User-Role` is
`Superintendent`, `Agronomist`, `TournamentOfficial`, or `EquipmentTechnician`,
`X-User-ID` is an opaque operator identifier not tied to any persisted entity."
The fifth is entity backed: "When `X-User-Role` is `Applicator`, `X-User-ID` is
the `id` of the acting `Applicator` record", so `make_applicator_headers` must be
handed a real applicator id captured from a registration response.
"""

from prd_bench_local_runner.testing import build_user_headers

from .types import UserRole

# Opaque operator identities.  Two distinct identifiers exist per reviewing role
# because the plan approval gate compares the approver's identifier against the
# `submitted_by_user_id` captured at submission.
SUPERINTENDENT_PRIMARY = "super-1"
SUPERINTENDENT_SECONDARY = "super-2"
AGRONOMIST_PRIMARY = "agro-1"
AGRONOMIST_SECONDARY = "agro-2"
TOURNAMENT_OFFICIAL_PRIMARY = "tourn-1"
EQUIPMENT_TECHNICIAN_PRIMARY = "tech-1"
# One operator who acts in two capacities, used to drive an approver's identifier
# into collision with the submitter's.
DUAL_ROLE_OPERATOR = "dual-1"


def make_superintendent_headers(user_id=SUPERINTENDENT_PRIMARY):
    return build_user_headers(user_id, UserRole.SUPERINTENDENT.value)


def make_agronomist_headers(user_id=AGRONOMIST_PRIMARY):
    return build_user_headers(user_id, UserRole.AGRONOMIST.value)


def make_tournament_official_headers(user_id=TOURNAMENT_OFFICIAL_PRIMARY):
    return build_user_headers(user_id, UserRole.TOURNAMENT_OFFICIAL.value)


def make_equipment_technician_headers(user_id=EQUIPMENT_TECHNICIAN_PRIMARY):
    return build_user_headers(user_id, UserRole.EQUIPMENT_TECHNICIAN.value)


def make_applicator_headers(applicator_id):
    """Headers for an `Applicator` acting as the applicator row of the given id."""
    return build_user_headers(applicator_id, UserRole.APPLICATOR.value)


SUPER_HEADERS = make_superintendent_headers()
SUPER_2_HEADERS = make_superintendent_headers(SUPERINTENDENT_SECONDARY)
AGRO_HEADERS = make_agronomist_headers()
AGRO_2_HEADERS = make_agronomist_headers(AGRONOMIST_SECONDARY)
TOURN_HEADERS = make_tournament_official_headers()
TECH_HEADERS = make_equipment_technician_headers()
DUAL_AGRO_HEADERS = make_agronomist_headers(DUAL_ROLE_OPERATOR)
DUAL_SUPER_HEADERS = make_superintendent_headers(DUAL_ROLE_OPERATOR)


TEST_USERS = {
    UserRole.SUPERINTENDENT.value: SUPER_HEADERS,
    UserRole.AGRONOMIST.value: AGRO_HEADERS,
    UserRole.TOURNAMENT_OFFICIAL.value: TOURN_HEADERS,
    UserRole.EQUIPMENT_TECHNICIAN.value: TECH_HEADERS,
}


def headers_for(role):
    """Headers for an opaque role named by its enum member or its wire string."""
    key = role.value if hasattr(role, "value") else role
    return TEST_USERS[key]


# Malformed identity headers for the authentication rule of PRD §2.8 priority 1.
NO_ROLE_HEADERS = {
    "X-User-ID": SUPERINTENDENT_PRIMARY,
    "Content-Type": "application/json",
}
UNDECLARED_ROLE_HEADERS = {
    "X-User-ID": SUPERINTENDENT_PRIMARY,
    "X-User-Role": "Greenkeeper",
    "Content-Type": "application/json",
}
APPLICATOR_WITHOUT_USER_ID_HEADERS = {
    "X-User-Role": UserRole.APPLICATOR.value,
    "Content-Type": "application/json",
}
