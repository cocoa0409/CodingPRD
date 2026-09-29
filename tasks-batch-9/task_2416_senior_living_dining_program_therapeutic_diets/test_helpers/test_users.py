"""Pre-built role headers for every role the PRD defines.

For the six operator roles the `X-User-ID` is an opaque operator identifier
that is never compared against any entity's `id`, so a shared constant is the
canonical form.  `ResidentRepresentative` is different: its `X-User-ID` is the
`id` of the acting `Resident` and must resolve to an existing resident, so it
has no meaningful shared constant and must always be built per resident with
`make_resident_representative_headers()`.
"""
from prd_bench_local_runner.testing import build_user_headers

# Opaque operator identifiers, stable so that recorded-identifier assertions
# (ordered_by_user_id, signed_off_by_user_id, finalized_by_user_id, ...) and
# segregation-of-duties comparisons are deterministic.
PROGRAM_ADMIN_USER_ID = "pa-1"
CLINICAL_STAFF_USER_ID = "cs-1"
CLINICAL_STAFF_ALT_USER_ID = "cs-2"
DIETITIAN_USER_ID = "rd-1"
DIETITIAN_ALT_USER_ID = "rd-2"
DINING_MANAGER_USER_ID = "dsm-1"
KITCHEN_LEAD_USER_ID = "skl-1"
BILLING_SPECIALIST_USER_ID = "bs-1"


TEST_USERS = {
    "program_admin_headers": build_user_headers(
        PROGRAM_ADMIN_USER_ID, "ProgramAdministrator"
    ),
    "clinical_staff_headers": build_user_headers(
        CLINICAL_STAFF_USER_ID, "ClinicalStaff"
    ),
    "clinical_staff_alt_headers": build_user_headers(
        CLINICAL_STAFF_ALT_USER_ID, "ClinicalStaff"
    ),
    "dietitian_headers": build_user_headers(DIETITIAN_USER_ID, "RegisteredDietitian"),
    "dietitian_alt_headers": build_user_headers(
        DIETITIAN_ALT_USER_ID, "RegisteredDietitian"
    ),
    "dining_manager_headers": build_user_headers(
        DINING_MANAGER_USER_ID, "DiningServicesManager"
    ),
    "kitchen_lead_headers": build_user_headers(
        KITCHEN_LEAD_USER_ID, "SatelliteKitchenLead"
    ),
    "billing_specialist_headers": build_user_headers(
        BILLING_SPECIALIST_USER_ID, "BillingSpecialist"
    ),
}


def make_program_admin_headers(user_id: str = PROGRAM_ADMIN_USER_ID) -> dict:
    return build_user_headers(user_id, "ProgramAdministrator")


def make_clinical_staff_headers(user_id: str = CLINICAL_STAFF_USER_ID) -> dict:
    return build_user_headers(user_id, "ClinicalStaff")


def make_dietitian_headers(user_id: str = DIETITIAN_USER_ID) -> dict:
    return build_user_headers(user_id, "RegisteredDietitian")


def make_dining_manager_headers(user_id: str = DINING_MANAGER_USER_ID) -> dict:
    return build_user_headers(user_id, "DiningServicesManager")


def make_kitchen_lead_headers(user_id: str = KITCHEN_LEAD_USER_ID) -> dict:
    return build_user_headers(user_id, "SatelliteKitchenLead")


def make_billing_specialist_headers(user_id: str = BILLING_SPECIALIST_USER_ID) -> dict:
    return build_user_headers(user_id, "BillingSpecialist")


def make_resident_representative_headers(resident_id: str) -> dict:
    """Headers for a `ResidentRepresentative`.

    `resident_id` MUST be the `id` of the acting resident: the PRD requires
    that a `ResidentRepresentative`'s `X-User-ID` resolve to an existing
    resident, and ownership checks compare the addressed resource's resident
    reference against it.
    """
    return build_user_headers(resident_id, "ResidentRepresentative")
