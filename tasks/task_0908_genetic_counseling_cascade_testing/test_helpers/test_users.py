"""Pre-built role headers for every role in the PRD.

Two roles are entity-backed: GeneticCounselor's X-User-ID is a Counselor.id, and
LabTechnician's X-User-ID is a Lab.id. Ownership-gated calls (booking a session,
releasing a result) MUST use the per-instance builders with the real entity id.
BillingSpecialist and ProgramAdmin are opaque operator identifiers.
"""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe for opaque roles and for tests that do not exercise
# entity-backed ownership (e.g. 404-on-missing-resource, 403-forbidden-role).
TEST_USERS = {
    # entity_backed roles: shared constant is a fallback for non-ownership tests only.
    "counselor_headers": build_user_headers("test-counselor-1", "GeneticCounselor"),
    "lab_headers": build_user_headers("test-lab-1", "LabTechnician"),
    # opaque roles: shared constant is the canonical form.
    "billing_headers": build_user_headers("test-billing-1", "BillingSpecialist"),
    "admin_headers": build_user_headers("test-admin-1", "ProgramAdmin"),
}


def make_counselor_headers(counselor_id: str) -> dict:
    """For GeneticCounselor (entity_backed:Counselor). Pass the actual Counselor.id
    whenever the call is ownership-gated (e.g. booking a session whose counselor_id
    must equal X-User-ID)."""
    return build_user_headers(counselor_id, "GeneticCounselor")


def make_lab_headers(lab_id: str) -> dict:
    """For LabTechnician (entity_backed:Lab). Pass the actual Lab.id whenever the call
    is ownership-gated (e.g. releasing a result on an order owned by that lab)."""
    return build_user_headers(lab_id, "LabTechnician")


def make_billing_headers(user_id: str = "test-billing-1") -> dict:
    return build_user_headers(user_id, "BillingSpecialist")


def make_admin_headers(user_id: str = "test-admin-1") -> dict:
    return build_user_headers(user_id, "ProgramAdmin")
