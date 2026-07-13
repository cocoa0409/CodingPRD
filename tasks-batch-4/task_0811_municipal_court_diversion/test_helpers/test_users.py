"""Pre-built role headers for every role in the PRD."""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe for opaque roles, and for tests that don't exercise
# defendant resource-ownership. Five of the six roles are opaque; only Defendant
# is entity-backed (X-User-ID must equal the acting Defendant's id).
TEST_USERS = {
    "court_clerk_headers": build_user_headers("clerk-1", "CourtClerk"),
    "judge_headers": build_user_headers("judge-1", "Judge"),
    "probation_officer_headers": build_user_headers("po_1", "ProbationOfficer"),
    "cashier_headers": build_user_headers("cashier-1", "Cashier"),
    "court_admin_headers": build_user_headers("admin-1", "CourtAdmin"),
    # Fallback only — never use for a defendant ownership-gated call.
    "defendant_headers": build_user_headers("defendant-fallback", "Defendant"),
}


def make_defendant_headers(user_id: str) -> dict:
    """For the Defendant role (entity_backed:Defendant). Pass the actual
    Defendant.id as user_id for any ownership-gated call (plea, accept, own payment)."""
    return build_user_headers(user_id, "Defendant")


def make_probation_officer_headers(user_id: str) -> dict:
    """For the ProbationOfficer role (opaque). The opaque X-User-ID is stored on
    an assignment as assigned_by_officer_id and later compared for segregation of
    duties, so tests pass explicit ids (e.g. 'po_1' creator vs 'po_2' verifier)."""
    return build_user_headers(user_id, "ProbationOfficer")


def make_court_clerk_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "CourtClerk")


def make_judge_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "Judge")


def make_cashier_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "Cashier")


def make_court_admin_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "CourtAdmin")
