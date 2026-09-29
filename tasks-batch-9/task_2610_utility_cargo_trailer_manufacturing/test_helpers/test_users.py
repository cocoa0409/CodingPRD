"""Fixed user identities per role, plus the Dealer header builder.

PRD 2.1 requires `X-User-ID` and `X-User-Role` on every request. Only the
`Dealer` role is entity-backed: for a Dealer the `X-User-ID` must be the
`id` of an enrolled dealer row. The other six roles are opaque strings.

PRD 2.11 makes segregation of duties an identity comparison, so two
distinct CertificationOfficer identities are provided: `co-1` certifies the
model and `co-2` issues the label.
"""

from prd_bench_local_runner.testing import build_user_headers

from .types import Role


PLANT_ENGINEER_ID = "pe-1"
CERT_OFFICER_1_ID = "co-1"
CERT_OFFICER_2_ID = "co-2"
WELD_SUPERVISOR_ID = "ws-1"
ASSEMBLY_TECH_ID = "at-1"
QUALITY_INSPECTOR_ID = "qi-1"
SALES_ADMIN_ID = "sa-1"
DEALER_USER_ID = "dlr-1"


TEST_USERS = {
    "plant_engineer": {"user_id": PLANT_ENGINEER_ID, "role": Role.PLANT_ENGINEER},
    "cert_officer": {"user_id": CERT_OFFICER_1_ID, "role": Role.CERTIFICATION_OFFICER},
    "cert_officer_2": {"user_id": CERT_OFFICER_2_ID, "role": Role.CERTIFICATION_OFFICER},
    "weld_supervisor": {"user_id": WELD_SUPERVISOR_ID, "role": Role.WELD_SUPERVISOR},
    "assembly_tech": {"user_id": ASSEMBLY_TECH_ID, "role": Role.ASSEMBLY_TECH},
    "quality_inspector": {"user_id": QUALITY_INSPECTOR_ID, "role": Role.QUALITY_INSPECTOR},
    "sales_admin": {"user_id": SALES_ADMIN_ID, "role": Role.SALES_ADMIN},
    "dealer": {"user_id": DEALER_USER_ID, "role": Role.DEALER},
}


PLANT_ENGINEER = build_user_headers(PLANT_ENGINEER_ID, Role.PLANT_ENGINEER)
CERT_OFFICER = build_user_headers(CERT_OFFICER_1_ID, Role.CERTIFICATION_OFFICER)
CERT_OFFICER_2 = build_user_headers(CERT_OFFICER_2_ID, Role.CERTIFICATION_OFFICER)
WELD_SUPERVISOR = build_user_headers(WELD_SUPERVISOR_ID, Role.WELD_SUPERVISOR)
ASSEMBLY_TECH = build_user_headers(ASSEMBLY_TECH_ID, Role.ASSEMBLY_TECH)
QUALITY_INSPECTOR = build_user_headers(QUALITY_INSPECTOR_ID, Role.QUALITY_INSPECTOR)
SALES_ADMIN = build_user_headers(SALES_ADMIN_ID, Role.SALES_ADMIN)
DEALER = build_user_headers(DEALER_USER_ID, Role.DEALER)


def make_dealer_headers(dealer_id):
    """Headers for the entity-backed `Dealer` role.

    PRD 2.1: for a Dealer the `X-User-ID` must be the `id` of an enrolled
    dealer, so every dealer-scoped call needs headers built from the row
    that was actually created by the test.
    """
    return build_user_headers(dealer_id, Role.DEALER)


def make_headers(user_id, role):
    """Headers for an arbitrary identity, used for segregation-of-duties tests."""
    return build_user_headers(user_id, role)


def headers_for(key):
    spec = TEST_USERS[key]
    return build_user_headers(spec["user_id"], spec["role"])


ALL_ROLE_HEADERS = (
    PLANT_ENGINEER,
    CERT_OFFICER,
    WELD_SUPERVISOR,
    ASSEMBLY_TECH,
    QUALITY_INSPECTOR,
    SALES_ADMIN,
    DEALER,
)
