"""Pre-built role headers for every role in the PRD.

The PRD declares exactly four roles. Client and Therapist are entity-backed:
their X-User-ID must equal the acting entity's id for ownership-gated calls, so
per-instance builders make_client_headers(client_id) / make_therapist_headers(
therapist_id) are mandatory. ClinicalAdmin and BillingAdmin are opaque operator
identities whose X-User-ID is recorded but never matched to an entity id, so a
shared constant is the canonical form for them.
"""
from prd_bench_local_runner.testing import build_user_headers


# Shared constants — safe for opaque roles, and for entity-backed tests that do
# NOT exercise ownership (e.g. 401/missing-role, or never-owned resources).
TEST_USERS = {
    # entity_backed roles: shared constant is a fallback for non-ownership tests only.
    "client_headers": build_user_headers("test-client-1", "Client"),
    "therapist_headers": build_user_headers("test-therapist-1", "Therapist"),
    # opaque roles: shared constant is the canonical form.
    "clinical_admin_headers": build_user_headers("test-clinical-admin-1", "ClinicalAdmin"),
    "billing_admin_headers": build_user_headers("test-billing-admin-1", "BillingAdmin"),
}


# Per-instance builders — required for the entity_backed roles.
def make_client_headers(client_id: str) -> dict:
    """For Client (entity_backed:Client). Pass the actual Client.id as user_id
    whenever the call is ownership-gated."""
    return build_user_headers(client_id, "Client")


def make_therapist_headers(therapist_id: str) -> dict:
    """For Therapist (entity_backed:Therapist). Pass the actual Therapist.id as
    user_id whenever the call is ownership-gated."""
    return build_user_headers(therapist_id, "Therapist")


def make_clinical_admin_headers(user_id: str = "test-clinical-admin-1") -> dict:
    return build_user_headers(user_id, "ClinicalAdmin")


def make_billing_admin_headers(user_id: str = "test-billing-admin-1") -> dict:
    return build_user_headers(user_id, "BillingAdmin")
