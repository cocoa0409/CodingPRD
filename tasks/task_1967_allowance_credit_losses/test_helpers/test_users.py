"""Pre-built role headers for every role in the PRD (§2.1).

All four roles have opaque identity: X-User-ID is never compared against any
persisted entity id. Shared constants are the canonical form. The per-instance
builders exist so segregation-of-duties tests can control which operator id is
presented (e.g., approver equals vs differs from executed_by_user_id).
"""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — canonical form for opaque roles (PRD §2.1).
TEST_USERS = {
    "credit_analyst_headers": build_user_headers("analyst-1", "CreditAnalyst"),
    "model_validator_headers": build_user_headers("validator-1", "ModelValidator"),
    "chief_credit_officer_headers": build_user_headers("cco-1", "ChiefCreditOfficer"),
    "external_auditor_headers": build_user_headers("auditor-1", "ExternalAuditor"),
}


def make_credit_analyst_headers(user_id: str) -> dict:
    """CreditAnalyst headers with a specific X-User-ID (for segregation-of-duties control)."""
    return build_user_headers(user_id, "CreditAnalyst")


def make_model_validator_headers(user_id: str) -> dict:
    """ModelValidator headers with a specific X-User-ID."""
    return build_user_headers(user_id, "ModelValidator")


def make_chief_credit_officer_headers(user_id: str) -> dict:
    """ChiefCreditOfficer headers with a specific X-User-ID (for segregation-of-duties control)."""
    return build_user_headers(user_id, "ChiefCreditOfficer")


def make_external_auditor_headers(user_id: str) -> dict:
    """ExternalAuditor headers with a specific X-User-ID."""
    return build_user_headers(user_id, "ExternalAuditor")
