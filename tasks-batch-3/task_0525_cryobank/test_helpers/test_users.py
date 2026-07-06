"""Pre-built role headers for every role in the PRD (§2.1).

Five roles (ScreeningOfficer, LabTech, ComplianceOfficer, CatalogManager,
BillingClerk) use an opaque X-User-ID not tied to any entity. The Recipient
role's X-User-ID must be the acting Recipient entity's id — so ownership-gated
Recipient calls MUST use make_recipient_headers(recipient["id"]).
"""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe for opaque roles, and for tests that don't exercise
# recipient ownership.
TEST_USERS = {
    "screening_officer_headers": build_user_headers("test-screening-officer-1", "ScreeningOfficer"),
    "lab_tech_headers": build_user_headers("test-lab-tech-1", "LabTech"),
    "compliance_officer_headers": build_user_headers("test-compliance-officer-1", "ComplianceOfficer"),
    "catalog_manager_headers": build_user_headers("test-catalog-manager-1", "CatalogManager"),
    "billing_clerk_headers": build_user_headers("test-billing-clerk-1", "BillingClerk"),
    # Recipient (entity_backed): shared constant is a fallback for non-ownership
    # tests only (e.g. 401/403/404 checks). Ownership-gated calls MUST use the
    # per-instance builder below.
    "recipient_headers": build_user_headers("test-recipient-1", "Recipient"),
}


def make_recipient_headers(user_id: str) -> dict:
    """For Recipient (entity_backed:Recipient). Pass the actual Recipient.id as
    user_id whenever the call is ownership-gated (consent sign/revoke,
    recipient-owned reservation create/cancel, recipient birth report)."""
    return build_user_headers(user_id, "Recipient")
