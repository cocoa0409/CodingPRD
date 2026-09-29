"""Pre-built role headers for every role in the PRD.

Three roles resolve `X-User-ID` to a stored row — `Patient` resolves to a Patient,
`HearingProfessional` and `LicensedAudiologist` both resolve to a Provider. For those
roles ALWAYS use the `make_*_headers()` builders with the real entity id; the shared
`TEST_USERS` constants are only safe for calls whose outcome does not depend on the
caller resolving to (or owning) a stored row.
"""
from prd_bench_local_runner.testing import build_user_headers

# Operator user ids used consistently across the suite.
CARE_OPS_USER_ID = "ops_1"
CARE_OPS_USER_ID_2 = "ops_2"
REIMBURSEMENT_USER_ID = "rs_1"
REIMBURSEMENT_USER_ID_2 = "rs_2"
REPAIR_TECH_USER_ID = "tech_1"
FIRMWARE_ENGINEER_USER_ID = "fw_1"
COMPLIANCE_USER_ID = "comp_1"
COMPLIANCE_USER_ID_2 = "comp_2"
PLATFORM_ADMIN_USER_ID = "admin_1"

TEST_USERS = {
    # entity-backed roles: fallback only for non-ownership tests.
    "patient_headers": build_user_headers("test-patient-1", "Patient"),
    "hearing_professional_headers": build_user_headers("test-provider-1", "HearingProfessional"),
    "licensed_audiologist_headers": build_user_headers("test-provider-2", "LicensedAudiologist"),
    # opaque operator roles: the canonical form.
    "care_ops_headers": build_user_headers(CARE_OPS_USER_ID, "CareOpsAgent"),
    "care_ops_headers_2": build_user_headers(CARE_OPS_USER_ID_2, "CareOpsAgent"),
    "reimbursement_headers": build_user_headers(REIMBURSEMENT_USER_ID, "ReimbursementSpecialist"),
    "reimbursement_headers_2": build_user_headers(REIMBURSEMENT_USER_ID_2, "ReimbursementSpecialist"),
    "repair_tech_headers": build_user_headers(REPAIR_TECH_USER_ID, "RepairTechnician"),
    "firmware_engineer_headers": build_user_headers(FIRMWARE_ENGINEER_USER_ID, "FirmwareEngineer"),
    "compliance_headers": build_user_headers(COMPLIANCE_USER_ID, "ComplianceOfficer"),
    "compliance_headers_2": build_user_headers(COMPLIANCE_USER_ID_2, "ComplianceOfficer"),
    "platform_admin_headers": build_user_headers(PLATFORM_ADMIN_USER_ID, "PlatformAdmin"),
}

# Convenience aliases for the operator roles.
ADMIN = TEST_USERS["platform_admin_headers"]
CARE_OPS = TEST_USERS["care_ops_headers"]
CARE_OPS_2 = TEST_USERS["care_ops_headers_2"]
REIMBURSEMENT = TEST_USERS["reimbursement_headers"]
REIMBURSEMENT_2 = TEST_USERS["reimbursement_headers_2"]
REPAIR_TECH = TEST_USERS["repair_tech_headers"]
FIRMWARE_ENGINEER = TEST_USERS["firmware_engineer_headers"]
COMPLIANCE = TEST_USERS["compliance_headers"]
COMPLIANCE_2 = TEST_USERS["compliance_headers_2"]


def make_patient_headers(patient_id: str) -> dict:
    """Headers for the Patient role. Pass the real Patient.id."""
    return build_user_headers(patient_id, "Patient")


def make_hearing_professional_headers(provider_id: str) -> dict:
    """Headers for the HearingProfessional role. Pass the real Provider.id."""
    return build_user_headers(provider_id, "HearingProfessional")


def make_licensed_audiologist_headers(provider_id: str) -> dict:
    """Headers for the LicensedAudiologist role. Pass the real Provider.id."""
    return build_user_headers(provider_id, "LicensedAudiologist")


def make_care_ops_headers(user_id: str = CARE_OPS_USER_ID) -> dict:
    return build_user_headers(user_id, "CareOpsAgent")


def make_reimbursement_headers(user_id: str = REIMBURSEMENT_USER_ID) -> dict:
    return build_user_headers(user_id, "ReimbursementSpecialist")


def make_repair_tech_headers(user_id: str = REPAIR_TECH_USER_ID) -> dict:
    return build_user_headers(user_id, "RepairTechnician")


def make_firmware_engineer_headers(user_id: str = FIRMWARE_ENGINEER_USER_ID) -> dict:
    return build_user_headers(user_id, "FirmwareEngineer")


def make_compliance_headers(user_id: str = COMPLIANCE_USER_ID) -> dict:
    return build_user_headers(user_id, "ComplianceOfficer")


def make_admin_headers(user_id: str = PLATFORM_ADMIN_USER_ID) -> dict:
    return build_user_headers(user_id, "PlatformAdmin")
