"""Pre-built role headers for every role in the PRD (§2.1).

FundAdmin, MemberServicesAnalyst, BenefitApprover and MedicalReviewer carry
opaque operator identifiers; EmployerClerk, Member and SurvivorClaimant are
entity-backed and MUST be built per-instance with the real entity id whenever
the call is ownership-gated.
"""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe for opaque roles, and for entity-backed roles only
# in tests that never exercise an ownership check (e.g. 400/401/404 probes).
TEST_USERS = {
    "fund_admin_headers": build_user_headers("fund-admin-1", "FundAdmin"),
    "analyst_headers": build_user_headers("analyst-1", "MemberServicesAnalyst"),
    "approver_headers": build_user_headers("approver-1", "BenefitApprover"),
    "medical_reviewer_headers": build_user_headers("reviewer-1", "MedicalReviewer"),
    # entity_backed fallbacks — non-ownership tests only
    "employer_clerk_headers": build_user_headers("test-clerk-1", "EmployerClerk"),
    "member_headers": build_user_headers("test-member-1", "Member"),
    "survivor_claimant_headers": build_user_headers("test-claimant-1",
                                                    "SurvivorClaimant"),
}


# Opaque-role builders — segregation-of-duties tests need distinct operator ids.
def make_fund_admin_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "FundAdmin")


def make_analyst_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "MemberServicesAnalyst")


def make_approver_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "BenefitApprover")


def make_medical_reviewer_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "MedicalReviewer")


# Entity-backed builders — pass the actual entity id for ownership-gated calls.
def make_employer_clerk_headers(employer_id: str) -> dict:
    """EmployerClerk (entity-backed:Employer). user_id must be the Employer.id
    whose reports/lines are being touched."""
    return build_user_headers(employer_id, "EmployerClerk")


def make_member_headers(member_id: str) -> dict:
    """Member (entity-backed:Member). user_id must be the Member.id owning the
    targeted records."""
    return build_user_headers(member_id, "Member")


def make_survivor_claimant_headers(beneficiary_id: str) -> dict:
    """SurvivorClaimant (entity-backed:Beneficiary). user_id must be the
    Beneficiary designation's own id."""
    return build_user_headers(beneficiary_id, "SurvivorClaimant")
