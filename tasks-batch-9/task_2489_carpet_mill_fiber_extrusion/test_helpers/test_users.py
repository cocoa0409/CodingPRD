"""Pre-built role headers for every role in the PRD.

The PRD authenticates a caller from X-User-ID plus X-User-Role. Six roles carry
opaque identity, so a shared constant is the canonical form for them. DealerBuyer
is backed by an Account, so its X-User-ID must be the id of the Account it acts
for; use make_dealer_buyer_headers(account_id) whenever the call is scoped to
that account.
"""

from prd_bench_local_runner.testing import build_user_headers

# Stable user ids. The QA technician and the certification officer are distinct
# people so that certificate issuance is not blocked by segregation of duties.
MILL_PLANNER_USER_ID = "planner-1"
EXTRUSION_OPERATOR_USER_ID = "extrusion-op-1"
DYE_HOUSE_OPERATOR_USER_ID = "dye-op-1"
QA_LAB_TECHNICIAN_USER_ID = "qa-tech-1"
QA_LAB_TECHNICIAN_2_USER_ID = "qa-tech-2"
CERTIFICATION_OFFICER_USER_ID = "cert-officer-1"
PLANT_ADMIN_USER_ID = "plant-admin-1"

# Shared constants — canonical for opaque roles, and for DealerBuyer tests that
# do not depend on the caller owning the subject account.
TEST_USERS = {
    "mill_planner_headers": build_user_headers(MILL_PLANNER_USER_ID, "MillPlanner"),
    "extrusion_operator_headers": build_user_headers(
        EXTRUSION_OPERATOR_USER_ID, "ExtrusionOperator"
    ),
    "dye_house_operator_headers": build_user_headers(
        DYE_HOUSE_OPERATOR_USER_ID, "DyeHouseOperator"
    ),
    "qa_lab_technician_headers": build_user_headers(
        QA_LAB_TECHNICIAN_USER_ID, "QALabTechnician"
    ),
    "qa_lab_technician_2_headers": build_user_headers(
        QA_LAB_TECHNICIAN_2_USER_ID, "QALabTechnician"
    ),
    "certification_officer_headers": build_user_headers(
        CERTIFICATION_OFFICER_USER_ID, "CertificationOfficer"
    ),
    # DealerBuyer is Account-backed: this fallback is for non-ownership tests only.
    "dealer_buyer_headers": build_user_headers("dealer-buyer-1", "DealerBuyer"),
    "plant_admin_headers": build_user_headers(PLANT_ADMIN_USER_ID, "PlantAdmin"),
}

ALL_ROLE_NAMES = [
    "MillPlanner",
    "ExtrusionOperator",
    "DyeHouseOperator",
    "QALabTechnician",
    "CertificationOfficer",
    "DealerBuyer",
    "PlantAdmin",
]


# ---------------------------------------------------------------------------
# Per-instance builders
# ---------------------------------------------------------------------------


def make_dealer_buyer_headers(account_id: str) -> dict:
    """For DealerBuyer, whose identity is an Account. Pass the real Account id
    whenever the call is scoped to that account."""
    return build_user_headers(account_id, "DealerBuyer")


def make_mill_planner_headers(user_id: str = MILL_PLANNER_USER_ID) -> dict:
    return build_user_headers(user_id, "MillPlanner")


def make_extrusion_operator_headers(user_id: str = EXTRUSION_OPERATOR_USER_ID) -> dict:
    return build_user_headers(user_id, "ExtrusionOperator")


def make_dye_house_operator_headers(user_id: str = DYE_HOUSE_OPERATOR_USER_ID) -> dict:
    return build_user_headers(user_id, "DyeHouseOperator")


def make_qa_lab_technician_headers(user_id: str = QA_LAB_TECHNICIAN_USER_ID) -> dict:
    return build_user_headers(user_id, "QALabTechnician")


def make_certification_officer_headers(
    user_id: str = CERTIFICATION_OFFICER_USER_ID,
) -> dict:
    return build_user_headers(user_id, "CertificationOfficer")


def make_plant_admin_headers(user_id: str = PLANT_ADMIN_USER_ID) -> dict:
    return build_user_headers(user_id, "PlantAdmin")


def make_headers_for_role(role: str, user_id: str) -> dict:
    """Generic builder, for parametrized role sweeps."""
    return build_user_headers(user_id, role)
