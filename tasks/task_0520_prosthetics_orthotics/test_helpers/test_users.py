"""Pre-built role headers for every role in the PRD.

Identity model (PRD §2.1):
  - Physician     -> X-User-ID is the id of the acting Physician entity (entity_backed).
  - Practitioner  -> X-User-ID is likewise the id of a Physician entity (the fitting
                     practitioner); ownership/segregation checks compare a resource's
                     fitting_practitioner_id to X-User-ID (entity_backed).
  - BillingSpecialist -> X-User-ID is an opaque operator id, not tied to any entity.
  - ComplianceOfficer -> X-User-ID is an opaque operator id, not tied to any entity.

The two entity_backed roles MUST use the per-instance builders below with the real
Physician entity id whenever a call is ownership- or segregation-gated.
"""
from prd_bench_local_runner.testing import build_user_headers


# Shared constants — safe for opaque roles, and for entity_backed roles only in tests
# whose success does NOT depend on the caller owning the subject resource.
TEST_USERS = {
    "physician_headers": build_user_headers("test-physician-1", "Physician"),
    "practitioner_headers": build_user_headers("test-practitioner-1", "Practitioner"),
    "billing_headers": build_user_headers("test-billing-1", "BillingSpecialist"),
    "compliance_headers": build_user_headers("test-compliance-1", "ComplianceOfficer"),
}


# Per-instance builders — required for the entity_backed roles.
def make_physician_headers(user_id: str) -> dict:
    """For Physician (entity_backed:Physician). Pass the prescribing Physician.id as
    user_id whenever the call is ownership-gated (sign/void a prescription)."""
    return build_user_headers(user_id, "Physician")


def make_practitioner_headers(user_id: str) -> dict:
    """For Practitioner (entity_backed:Physician). Pass the fitting Physician.id as
    user_id; segregation checks compare fitting_practitioner_id to this value."""
    return build_user_headers(user_id, "Practitioner")
