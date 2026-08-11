"""Pre-built role headers for every role in the PRD."""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe for opaque roles and for tests that don't exercise
# ownership. The ConservatorOfficer shared constant is a fallback for
# non-ownership tests only; ownership-gated calls MUST use
# make_conservator_headers(conservator["id"]).
TEST_USERS = {
    "admin_headers": build_user_headers("test-admin-1", "FiduciaryAdmin"),
    "case_manager_headers": build_user_headers("cm-1", "CaseManager"),
    "financial_officer_headers": build_user_headers("fo-1", "FinancialOfficer"),
    "conservator_headers": build_user_headers("test-conservator-1", "ConservatorOfficer"),
    "auditor_headers": build_user_headers("test-auditor-1", "ComplianceAuditor"),
}


def make_admin_headers(user_id: str = "test-admin-1") -> dict:
    return build_user_headers(user_id, "FiduciaryAdmin")


def make_case_manager_headers(user_id: str = "cm-1") -> dict:
    return build_user_headers(user_id, "CaseManager")


def make_financial_officer_headers(user_id: str = "fo-1") -> dict:
    return build_user_headers(user_id, "FinancialOfficer")


def make_conservator_headers(user_id: str) -> dict:
    """For ConservatorOfficer (entity_backed:Conservator). Pass the actual
    Conservator.id as user_id whenever the call is ownership-gated (co-approve)."""
    return build_user_headers(user_id, "ConservatorOfficer")


def make_auditor_headers(user_id: str = "test-auditor-1") -> dict:
    return build_user_headers(user_id, "ComplianceAuditor")
