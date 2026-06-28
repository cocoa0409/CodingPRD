"""Pre-built role headers for every role in the PRD."""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe for opaque roles (ManufacturingOps, BillingAdmin), and
# for tests that don't exercise ownership. For entity_backed roles (Patient,
# Clinician) the shared constant is a fallback for non-ownership tests only:
# ownership-gated calls MUST use the per-instance builder with the real entity id.
TEST_USERS = {
    # entity_backed roles — shared constant is a NON-ownership fallback only.
    "patient_headers": build_user_headers("test-patient-1", "Patient"),
    "clinician_headers": build_user_headers("test-clinician-1", "Clinician"),
    # opaque roles — shared constant is the canonical form.
    "manufacturing_headers": build_user_headers("test-mfg-1", "ManufacturingOps"),
    "billing_headers": build_user_headers("test-billing-1", "BillingAdmin"),
}


# Per-instance builders — required for every entity_backed role.
def make_patient_headers(user_id: str) -> dict:
    """For Patient (entity_backed:Patient). Pass the actual Patient.id as user_id
    whenever the call is ownership-gated."""
    return build_user_headers(user_id, "Patient")


def make_clinician_headers(user_id: str) -> dict:
    """For Clinician (entity_backed:Clinician). Pass the actual Clinician.id as
    user_id whenever the call is assignment/ownership-gated (e.g. plan review)."""
    return build_user_headers(user_id, "Clinician")


def make_manufacturing_headers(user_id: str = "test-mfg-1") -> dict:
    """ManufacturingOps is an opaque operator identity not tied to any entity."""
    return build_user_headers(user_id, "ManufacturingOps")


def make_billing_headers(user_id: str = "test-billing-1") -> dict:
    """BillingAdmin is an opaque operator identity not tied to any entity."""
    return build_user_headers(user_id, "BillingAdmin")
