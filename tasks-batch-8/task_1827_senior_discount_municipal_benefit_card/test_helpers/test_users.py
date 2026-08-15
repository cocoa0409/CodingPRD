"""Pre-built role headers for every role in the PRD (§2.1).

Cardholder and MerchantOperator are entity-backed roles: X-User-ID must be the
id of an existing Cardholder / Merchant. Ownership-gated calls MUST use the
per-instance builders (make_cardholder_headers / make_merchant_operator_headers)
with the real entity id — the shared constants for those two roles are
fallbacks for tests that do not exercise ownership.
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    "applicant_headers": build_user_headers("applicant-1", "Applicant"),
    # entity_backed:Cardholder — fallback for non-ownership tests only.
    "cardholder_headers": build_user_headers("test-cardholder-1", "Cardholder"),
    "eligibility_specialist_headers": build_user_headers("spec-1", "EligibilitySpecialist"),
    "program_administrator_headers": build_user_headers("admin-1", "ProgramAdministrator"),
    # entity_backed:Merchant — fallback for non-ownership tests only.
    "merchant_operator_headers": build_user_headers("test-merchant-1", "MerchantOperator"),
    "fraud_analyst_headers": build_user_headers("fraud-1", "FraudAnalyst"),
}


def make_applicant_headers(user_id: str = "applicant-1") -> dict:
    return build_user_headers(user_id, "Applicant")


def make_cardholder_headers(cardholder_id: str) -> dict:
    """For Cardholder (entity_backed:Cardholder). Pass the actual Cardholder.id
    whenever the call is ownership-gated."""
    return build_user_headers(cardholder_id, "Cardholder")


def make_eligibility_specialist_headers(user_id: str = "spec-1") -> dict:
    return build_user_headers(user_id, "EligibilitySpecialist")


def make_program_administrator_headers(user_id: str = "admin-1") -> dict:
    return build_user_headers(user_id, "ProgramAdministrator")


def make_merchant_operator_headers(merchant_id: str) -> dict:
    """For MerchantOperator (entity_backed:Merchant). Pass the acting
    Merchant.id whenever the call is ownership-gated."""
    return build_user_headers(merchant_id, "MerchantOperator")


def make_fraud_analyst_headers(user_id: str = "fraud-1") -> dict:
    return build_user_headers(user_id, "FraudAnalyst")
