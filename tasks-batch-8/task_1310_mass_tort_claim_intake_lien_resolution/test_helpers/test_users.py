"""Pre-built role headers for every role in the PRD (§2.1)."""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe for opaque roles, and for tests that don't exercise ownership.
TEST_USERS = {
    "program_admin_headers": build_user_headers("test-admin-1", "ProgramAdministrator"),
    "intake_specialist_headers": build_user_headers("test-intake-1", "IntakeSpecialist"),
    "records_analyst_headers": build_user_headers("test-records-1", "RecordsAnalyst"),
    "lien_analyst_headers": build_user_headers("test-lien-1", "LienAnalyst"),
    "disbursement_approver_headers": build_user_headers("test-approver-1", "DisbursementApprover"),
    # entity_backed role: shared constant is a fallback for non-ownership tests only.
    "claimant_headers": build_user_headers("test-claimant-1", "ClaimantRole"),
}


# Per-instance builders — required for entity_backed roles.
def make_claimant_headers(claimant_id: str) -> dict:
    """For ClaimantRole (entity_backed:Claimant). Pass the actual Claimant.id as
    claimant_id whenever the call is ownership-gated (PRD §2.1)."""
    return build_user_headers(claimant_id, "ClaimantRole")


def make_disbursement_approver_headers(user_id: str) -> dict:
    """Segregation-of-duties tests need distinct approver X-User-IDs (PRD §2.10)."""
    return build_user_headers(user_id, "DisbursementApprover")
