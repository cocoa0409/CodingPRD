"""Pre-built role headers for every role in the PRD (§2.1).

All staff roles (ComplianceOfficer, EscrowAnalyst, DisbursementProcessor,
PayeeVerifier, InsuranceSpecialist) are opaque identities: X-User-ID is never
compared to an entity id, only to recorded audit anchors where a
segregation-of-duties rule says so. Borrower is entity-backed by Loan:
X-User-ID must equal the owning Loan's id, so ownership-gated calls MUST use
make_borrower_headers(loan_id) with the real loan id — never the shared
borrower constant.
"""
from prd_bench_local_runner.testing import build_user_headers

# Shared staff identities. Two identities per SoD-gated desk so a creator /
# scheduler / investigator is always distinguishable from a verifier /
# releaser / resolver.
TEST_USERS = {
    "compliance_officer_headers": build_user_headers("co_1", "ComplianceOfficer"),
    "compliance_officer_2_headers": build_user_headers("co_2", "ComplianceOfficer"),
    "escrow_analyst_headers": build_user_headers("ea_1", "EscrowAnalyst"),
    "escrow_analyst_2_headers": build_user_headers("ea_9", "EscrowAnalyst"),
    "disbursement_processor_headers": build_user_headers("dp_1", "DisbursementProcessor"),
    "disbursement_processor_2_headers": build_user_headers("dp_2", "DisbursementProcessor"),
    "payee_verifier_headers": build_user_headers("pv_1", "PayeeVerifier"),
    "payee_verifier_2_headers": build_user_headers("pv_2", "PayeeVerifier"),
    "insurance_specialist_headers": build_user_headers("is_1", "InsuranceSpecialist"),
    # entity_backed role: shared constant is a fallback for non-ownership
    # tests only; ownership-gated calls must use make_borrower_headers(loan_id).
    "borrower_headers": build_user_headers("test-borrower-1", "Borrower"),
}


def make_compliance_officer_headers(user_id: str = "co_1") -> dict:
    return build_user_headers(user_id, "ComplianceOfficer")


def make_escrow_analyst_headers(user_id: str = "ea_1") -> dict:
    return build_user_headers(user_id, "EscrowAnalyst")


def make_disbursement_processor_headers(user_id: str = "dp_1") -> dict:
    return build_user_headers(user_id, "DisbursementProcessor")


def make_payee_verifier_headers(user_id: str = "pv_1") -> dict:
    return build_user_headers(user_id, "PayeeVerifier")


def make_insurance_specialist_headers(user_id: str = "is_1") -> dict:
    return build_user_headers(user_id, "InsuranceSpecialist")


def make_borrower_headers(loan_id: str) -> dict:
    """For Borrower (entity_backed:Loan). Pass the owning Loan.id whenever the
    call is ownership-gated (error cases, notice acknowledge, borrower
    deposits, policy create/reinstate)."""
    return build_user_headers(loan_id, "Borrower")
