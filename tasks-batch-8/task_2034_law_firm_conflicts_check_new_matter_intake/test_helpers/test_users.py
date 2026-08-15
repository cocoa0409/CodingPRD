"""Pre-built role headers for every role in the PRD (section 2.1).

Three roles are opaque (FirmAdmin, IntakeSpecialist, BillingClerk): the shared
constants below are canonical for them. Three roles are entity-backed
(ResponsibleAttorney and ConflictsPartner -> Attorney.id; Client -> Party.id):
for ownership-gated calls, use the per-instance builders with the real entity id.
"""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe for opaque roles and for tests that do not exercise
# ownership gating (400-on-bad-payload, 404-on-missing-resource, and any call
# by FirmAdmin / IntakeSpecialist / BillingClerk).
TEST_USERS = {
    "firm_admin_headers": build_user_headers("test-firm-admin-1", "FirmAdmin"),
    "intake_specialist_headers": build_user_headers(
        "test-intake-specialist-1", "IntakeSpecialist"
    ),
    "billing_clerk_headers": build_user_headers("test-billing-clerk-1", "BillingClerk"),
    # Fallbacks for entity-backed roles — only for tests that never hit an
    # ownership-gated path (e.g. asserting ERR_FORBIDDEN for a wrong role).
    "responsible_attorney_headers": build_user_headers(
        "test-attorney-1", "ResponsibleAttorney"
    ),
    "conflicts_partner_headers": build_user_headers(
        "test-partner-1", "ConflictsPartner"
    ),
    "client_headers": build_user_headers("test-client-1", "Client"),
}


def make_responsible_attorney_headers(user_id: str) -> dict:
    """ResponsibleAttorney is entity-backed by Attorney: pass the Attorney.id
    whenever the call is ownership-gated (hit review, waiver create/SEND/REDRAFT,
    letter ISSUE, matter CLOSE, wall-gated matter read)."""
    return build_user_headers(user_id, "ResponsibleAttorney")


def make_conflicts_partner_headers(user_id: str) -> dict:
    """ConflictsPartner is entity-backed by Attorney: pass the Attorney.id
    whenever the call compares the acting attorney (SoD on APPROVE, wall
    administration, DECLINE/VOID, wall-gated matter read)."""
    return build_user_headers(user_id, "ConflictsPartner")


def make_client_headers(user_id: str) -> dict:
    """Client is entity-backed by Party: pass the client Party.id whenever the
    call is ownership-gated (RECORD_CONSENT, DECLINE, REVOKE, COUNTERSIGN,
    reads of own matter/letters/deposit)."""
    return build_user_headers(user_id, "Client")
