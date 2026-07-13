"""Pre-built role headers for every role in the PRD.

CareCoordinator and BillingClerk are opaque roles (X-User-ID is an operator id
not compared to any entity), so their shared constants are the canonical form.
Caregiver and FamilyContact are entity_backed: for ownership-gated calls the
X-User-ID MUST be the acting entity's own id, so per-instance builders are used.
"""
from prd_bench_local_runner.testing import build_user_headers


TEST_USERS = {
    # Opaque roles — shared constant is canonical.
    "coordinator_headers": build_user_headers("test-coordinator-1", "CareCoordinator"),
    "billing_headers": build_user_headers("test-billing-1", "BillingClerk"),
    # entity_backed roles — shared constants are a fallback for non-ownership
    # tests only (e.g. ERR_UNAUTHORIZED where the call is rejected before any
    # ownership comparison). Ownership-gated calls MUST use the builders below.
    "caregiver_headers": build_user_headers("test-caregiver-1", "Caregiver"),
    "family_headers": build_user_headers("test-family-1", "FamilyContact"),
}


def make_caregiver_headers(caregiver_id: str) -> dict:
    """For a Caregiver (entity_backed:Caregiver). Pass the actual Caregiver.id
    whenever the call is ownership-gated (clock-in, clock-out, escalate, log)."""
    return build_user_headers(caregiver_id, "Caregiver")


def make_family_contact_headers(contact_id: str) -> dict:
    """For a FamilyContact (entity_backed:FamilyContact). Pass the actual
    FamilyContact.id whenever the call is ownership-gated (acknowledge/resolve)."""
    return build_user_headers(contact_id, "FamilyContact")
