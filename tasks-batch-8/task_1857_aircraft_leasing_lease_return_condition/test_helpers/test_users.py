"""Pre-built role headers for every role in the PRD."""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe for opaque roles, and for tests that don't exercise
# ownership. For entity-backed roles (LesseeRep, TechInspector) these are
# fallbacks for non-ownership-gated calls only; use the per-instance builders
# below whenever a call is ownership-gated.
TEST_USERS = {
    "lessor_admin_headers": build_user_headers("admin_1", "LessorAdmin"),
    "lessee_rep_headers": build_user_headers("test-lessee-rep-1", "LesseeRep"),
    "tech_inspector_headers": build_user_headers("test-inspector-1", "TechInspector"),
    "credit_officer_headers": build_user_headers("cred_1", "CreditOfficer"),
    "credit_officer_2_headers": build_user_headers("cred_2", "CreditOfficer"),
    "legal_approver_headers": build_user_headers("legal_1", "LegalApprover"),
    "legal_approver_2_headers": build_user_headers("legal_9", "LegalApprover"),
    "finance_manager_headers": build_user_headers("fin_1", "FinanceManager"),
}


def make_lessee_rep_headers(user_id: str) -> dict:
    """For LesseeRep (entity_backed: Lessee). Pass the actual Lessee.id as
    user_id whenever the call is ownership-gated."""
    return build_user_headers(user_id, "LesseeRep")


def make_tech_inspector_headers(user_id: str) -> dict:
    """For TechInspector (entity_backed: Inspector). Pass the actual
    Inspector.id as user_id whenever the call is gated by the booking gate."""
    return build_user_headers(user_id, "TechInspector")


def make_lessor_admin_headers(user_id: str = "admin_1") -> dict:
    return build_user_headers(user_id, "LessorAdmin")


def make_credit_officer_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "CreditOfficer")


def make_legal_approver_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "LegalApprover")


def make_finance_manager_headers(user_id: str = "fin_1") -> dict:
    return build_user_headers(user_id, "FinanceManager")
