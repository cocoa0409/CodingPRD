"""Fixed actors for the seven roles declared in PRD section 2.1.

PRD 2.1: "Every request -- without exception, including reads -- must carry two
headers: `X-User-ID`, an opaque non-empty string identifying the caller, and
`X-User-Role`". Only the Distributor role is entity-backed, so distributor
callers must use the id of a Distributor row created through the API; use
`distributor_headers()` for those.

Two distinct actors are provided for each role that participates in a
segregation-of-duties rule (PRD 2.8) so that "same user" and "different user"
paths can both be exercised.
"""

from prd_bench_local_runner.testing import build_user_headers

from .types import UserRole

USER_IDS = {
    "plant_admin": "pa-001",
    "formulator": "form-001",
    "formulator_b": "form-002",
    "technical_director": "td-001",
    "technical_director_b": "td-002",
    "qa_technician": "qa-001",
    "qa_technician_b": "qa-002",
    "production_planner": "pp-001",
    "warranty_adjuster": "adj-001",
    "warranty_adjuster_b": "adj-002",
}

PLANT_ADMIN = build_user_headers(USER_IDS["plant_admin"], UserRole.PLANT_ADMIN.value)
FORMULATOR = build_user_headers(USER_IDS["formulator"], UserRole.FORMULATOR.value)
FORMULATOR_B = build_user_headers(USER_IDS["formulator_b"], UserRole.FORMULATOR.value)
TECHNICAL_DIRECTOR = build_user_headers(
    USER_IDS["technical_director"], UserRole.TECHNICAL_DIRECTOR.value
)
TECHNICAL_DIRECTOR_B = build_user_headers(
    USER_IDS["technical_director_b"], UserRole.TECHNICAL_DIRECTOR.value
)
QA_TECHNICIAN = build_user_headers(
    USER_IDS["qa_technician"], UserRole.QA_TECHNICIAN.value
)
QA_TECHNICIAN_B = build_user_headers(
    USER_IDS["qa_technician_b"], UserRole.QA_TECHNICIAN.value
)
PRODUCTION_PLANNER = build_user_headers(
    USER_IDS["production_planner"], UserRole.PRODUCTION_PLANNER.value
)
WARRANTY_ADJUSTER = build_user_headers(
    USER_IDS["warranty_adjuster"], UserRole.WARRANTY_ADJUSTER.value
)
WARRANTY_ADJUSTER_B = build_user_headers(
    USER_IDS["warranty_adjuster_b"], UserRole.WARRANTY_ADJUSTER.value
)


def distributor_headers(distributor_id: str) -> dict:
    """Headers for a Distributor caller.

    PRD 2.1: "For the `Distributor` role the `X-User-ID` value is the `id` of a
    `Distributor` row."
    """
    return build_user_headers(distributor_id, UserRole.DISTRIBUTOR.value)


TEST_USERS = {
    "plant_admin_headers": PLANT_ADMIN,
    "formulator_headers": FORMULATOR,
    "formulator_b_headers": FORMULATOR_B,
    "technical_director_headers": TECHNICAL_DIRECTOR,
    "technical_director_b_headers": TECHNICAL_DIRECTOR_B,
    "qa_technician_headers": QA_TECHNICIAN,
    "qa_technician_b_headers": QA_TECHNICIAN_B,
    "production_planner_headers": PRODUCTION_PLANNER,
    "warranty_adjuster_headers": WARRANTY_ADJUSTER,
    "warranty_adjuster_b_headers": WARRANTY_ADJUSTER_B,
}

# Every role name that PRD section 2.1 accepts, keyed by the header value.
ALL_ROLE_HEADERS = {
    UserRole.PLANT_ADMIN.value: PLANT_ADMIN,
    UserRole.FORMULATOR.value: FORMULATOR,
    UserRole.TECHNICAL_DIRECTOR.value: TECHNICAL_DIRECTOR,
    UserRole.QA_TECHNICIAN.value: QA_TECHNICIAN,
    UserRole.PRODUCTION_PLANNER.value: PRODUCTION_PLANNER,
    UserRole.WARRANTY_ADJUSTER.value: WARRANTY_ADJUSTER,
}
