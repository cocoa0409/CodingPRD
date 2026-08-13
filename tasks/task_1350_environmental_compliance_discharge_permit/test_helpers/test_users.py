"""Pre-built role headers for every role in the PRD (§2.1).

All eight roles are opaque: X-User-ID is an operator identifier recorded on
mutated resources and compared only by the segregation-of-duties checks — it is
never compared to an entity's id. Shared constants below use stable operator
ids; the make_*_headers builders exist for tests that must control the exact
operator id (segregation-of-duties scenarios).
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    "environmental_manager_headers": build_user_headers("em-1", "EnvironmentalManager"),
    "field_sampler_headers": build_user_headers("sampler-1", "FieldSampler"),
    "lab_analyst_headers": build_user_headers("analyst-1", "LabAnalyst"),
    "lab_validator_headers": build_user_headers("validator-1", "LabValidator"),
    "compliance_officer_headers": build_user_headers("co-1", "ComplianceOfficer"),
    "facility_inspector_headers": build_user_headers("fi-1", "FacilityInspector"),
    "regulator_headers": build_user_headers("reg-1", "Regulator"),
    "system_admin_headers": build_user_headers("admin-1", "SystemAdmin"),
    # A second compliance officer / validator for segregation-of-duties flows.
    "compliance_officer_2_headers": build_user_headers("co-2", "ComplianceOfficer"),
    "lab_validator_2_headers": build_user_headers("validator-2", "LabValidator"),
}


def make_environmental_manager_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "EnvironmentalManager")


def make_field_sampler_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "FieldSampler")


def make_lab_analyst_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "LabAnalyst")


def make_lab_validator_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "LabValidator")


def make_compliance_officer_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "ComplianceOfficer")


def make_facility_inspector_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "FacilityInspector")


def make_regulator_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "Regulator")


def make_system_admin_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "SystemAdmin")


def headers_missing_role(user_id: str = "no-role-1") -> dict:
    """X-User-ID present, X-User-Role absent (PRD §2.1 rejection shape)."""
    return {"X-User-ID": user_id, "Content-Type": "application/json"}


def headers_with_undeclared_role(user_id: str = "rogue-1", role: str = "SuperUser") -> dict:
    """A role outside the eight declared roles (PRD §2.1 rejection shape)."""
    return build_user_headers(user_id, role)
