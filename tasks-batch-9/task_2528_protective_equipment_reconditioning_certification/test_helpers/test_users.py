"""Pre-built role headers for every role the PRD defines.

Every request carries ``X-User-Role`` and ``X-User-ID``. ``CustomerContact`` is
backed by a real ``CustomerAccount``: its ``X-User-ID`` must be that account's
``id``, so scoped reads must always be issued through
``make_customer_contact_headers(account["id"])``.
"""
from prd_bench_local_runner.testing import build_user_headers

# Distinct plant user ids. Two technicians and two compliance officers exist so
# that the PRD's two-person rules (repair verification, destruction witness vs
# verification) can be exercised with genuinely different actors.
PLANT_MANAGER_USER_ID = "pm-1"
INTAKE_CLERK_USER_ID = "clerk-1"
TECHNICIAN_1_USER_ID = "tech-1"
TECHNICIAN_2_USER_ID = "tech-2"
CERTIFYING_INSPECTOR_1_USER_ID = "insp-1"
CERTIFYING_INSPECTOR_2_USER_ID = "insp-2"
COMPLIANCE_OFFICER_1_USER_ID = "comp-1"
COMPLIANCE_OFFICER_2_USER_ID = "comp-2"
CUSTOMER_CONTACT_FALLBACK_USER_ID = "test-customer-contact-1"


def make_plant_manager_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "PlantManager")


def make_intake_clerk_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "IntakeClerk")


def make_technician_headers(user_id: str) -> dict:
    """Pass a distinct id per technician; repair verification compares
    ``X-User-ID`` against the order's ``installed_by_user_id``."""
    return build_user_headers(user_id, "Technician")


def make_certifying_inspector_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "CertifyingInspector")


def make_compliance_officer_headers(user_id: str) -> dict:
    """Pass a distinct id per officer; destruction verification compares
    ``X-User-ID`` against the record's ``witnessed_by_user_id``."""
    return build_user_headers(user_id, "ComplianceOfficer")


def make_customer_contact_headers(customer_account_id: str) -> dict:
    """For CustomerContact. ``customer_account_id`` MUST be a real
    ``CustomerAccount.id`` — every read is scoped to that account."""
    return build_user_headers(customer_account_id, "CustomerContact")


# Shared constants. Safe for the opaque plant roles; the CustomerContact entry
# is a fallback for tests that do not exercise account scoping at all.
TEST_USERS = {
    "plant_manager_headers": make_plant_manager_headers(PLANT_MANAGER_USER_ID),
    "intake_clerk_headers": make_intake_clerk_headers(INTAKE_CLERK_USER_ID),
    "technician_headers": make_technician_headers(TECHNICIAN_1_USER_ID),
    "technician_2_headers": make_technician_headers(TECHNICIAN_2_USER_ID),
    "certifying_inspector_headers": make_certifying_inspector_headers(
        CERTIFYING_INSPECTOR_1_USER_ID
    ),
    "certifying_inspector_2_headers": make_certifying_inspector_headers(
        CERTIFYING_INSPECTOR_2_USER_ID
    ),
    "compliance_officer_headers": make_compliance_officer_headers(
        COMPLIANCE_OFFICER_1_USER_ID
    ),
    "compliance_officer_2_headers": make_compliance_officer_headers(
        COMPLIANCE_OFFICER_2_USER_ID
    ),
    "customer_contact_headers": make_customer_contact_headers(
        CUSTOMER_CONTACT_FALLBACK_USER_ID
    ),
}

# Convenience aliases used throughout the fixtures.
PLANT_MANAGER = TEST_USERS["plant_manager_headers"]
INTAKE_CLERK = TEST_USERS["intake_clerk_headers"]
TECHNICIAN_1 = TEST_USERS["technician_headers"]
TECHNICIAN_2 = TEST_USERS["technician_2_headers"]
INSPECTOR_1 = TEST_USERS["certifying_inspector_headers"]
INSPECTOR_2 = TEST_USERS["certifying_inspector_2_headers"]
COMPLIANCE_1 = TEST_USERS["compliance_officer_headers"]
COMPLIANCE_2 = TEST_USERS["compliance_officer_2_headers"]

ALL_PLANT_ROLE_HEADERS = {
    "PlantManager": PLANT_MANAGER,
    "IntakeClerk": INTAKE_CLERK,
    "Technician": TECHNICIAN_1,
    "CertifyingInspector": INSPECTOR_1,
    "ComplianceOfficer": COMPLIANCE_1,
}
