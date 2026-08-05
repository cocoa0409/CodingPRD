"""Pre-built identity headers for every role in the PRD.

PRD 2.1 gives X-User-ID a different meaning per role:

* ProgramAdmin, ClinicManager and PayrollProcessor carry an opaque operator
  identifier that is never compared to any entity's id -> the shared constants
  below are the canonical form for those three.
* Clinician and CareNavigator carry the acting Provider's id, EmployerBenefitsAdmin
  carries the acting Employer's id and Participant carries the acting Participant's
  id -> those four MUST be built per instance with the real entity id, otherwise
  every ownership check rejects every request.
"""

from prd_bench_local_runner.testing import build_user_headers

# Shared constants. Safe for the three opaque roles, and for tests that never
# exercise an ownership check (bad payload, unknown id, forbidden role).
TEST_USERS = {
    "program_admin_headers": build_user_headers("op-program-admin-1", "ProgramAdmin"),
    "clinic_manager_headers": build_user_headers("op-clinic-manager-1", "ClinicManager"),
    "payroll_processor_headers": build_user_headers(
        "op-payroll-processor-1", "PayrollProcessor"
    ),
    # Fallbacks for the entity-backed roles: only for non-ownership assertions.
    "clinician_headers": build_user_headers("unbacked-clinician", "Clinician"),
    "care_navigator_headers": build_user_headers("unbacked-navigator", "CareNavigator"),
    "employer_admin_headers": build_user_headers(
        "unbacked-employer-admin", "EmployerBenefitsAdmin"
    ),
    "participant_headers": build_user_headers("unbacked-participant", "Participant"),
}


# --- Per-instance builders for the four entity-backed roles ----------------
def make_program_admin_headers(user_id="op-program-admin-1"):
    """ProgramAdmin identity is opaque; the id is only recorded, never matched."""
    return build_user_headers(user_id, "ProgramAdmin")


def make_clinic_manager_headers(user_id="op-clinic-manager-1"):
    """ClinicManager identity is opaque; the id is only recorded, never matched."""
    return build_user_headers(user_id, "ClinicManager")


def make_payroll_processor_headers(user_id="op-payroll-processor-1"):
    """PayrollProcessor identity is opaque; recorded as exported_by_user_id."""
    return build_user_headers(user_id, "PayrollProcessor")


def make_clinician_headers(provider_id):
    """Pass the id of a Provider whose provider_function is CLINICIAN."""
    return build_user_headers(provider_id, "Clinician")


def make_navigator_headers(provider_id):
    """Pass the id of a Provider whose provider_function is NAVIGATOR."""
    return build_user_headers(provider_id, "CareNavigator")


def make_employer_admin_headers(employer_id):
    """Pass the acting Employer's id."""
    return build_user_headers(employer_id, "EmployerBenefitsAdmin")


def make_participant_headers(participant_id):
    """Pass the acting Participant's id."""
    return build_user_headers(participant_id, "Participant")


def headers_without_identity():
    """A request carrying neither X-User-ID nor X-User-Role (PRD 2.1)."""
    return {"Content-Type": "application/json"}
