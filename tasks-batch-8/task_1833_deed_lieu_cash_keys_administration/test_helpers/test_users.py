"""Pre-built role headers for every role in the PRD (§2.1).

The Borrower role is entity-backed (X-User-ID must equal a Borrower record's id
for ownership-gated calls), so ownership-aware code paths MUST use
make_borrower_headers(borrower["id"]) rather than the shared fallback constant.
"""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe for opaque roles, and for tests that do not exercise
# entity-backed ownership.
TEST_USERS = {
    "servicing_admin_headers": build_user_headers("admin_1", "ServicingAdmin"),
    "specialist_headers": build_user_headers("spec_1", "PropertySolutionsSpecialist"),
    "specialist_2_headers": build_user_headers("spec_2", "PropertySolutionsSpecialist"),
    "workout_manager_headers": build_user_headers("mgr_1", "WorkoutManager"),
    "title_officer_headers": build_user_headers("to_1", "TitleOfficer"),
    "inspector_headers": build_user_headers("insp_1", "Inspector"),
    "inspector_2_headers": build_user_headers("insp_2", "Inspector"),
    "disbursement_officer_1_headers": build_user_headers("do_1", "DisbursementOfficer"),
    "disbursement_officer_2_headers": build_user_headers("do_2", "DisbursementOfficer"),
    "legal_counsel_headers": build_user_headers("lc_1", "LegalCounsel"),
    # Entity-backed role: fallback only for non-ownership tests (e.g. role-level 403).
    "borrower_headers": build_user_headers("borrower-unowned-1", "Borrower"),
}


# Per-instance builders — one per role. make_borrower_headers is mandatory for
# ownership-gated calls (counter/accept/withdraw-own-case/own reads).
def make_servicing_admin_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "ServicingAdmin")


def make_specialist_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "PropertySolutionsSpecialist")


def make_workout_manager_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "WorkoutManager")


def make_title_officer_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "TitleOfficer")


def make_borrower_headers(user_id: str) -> dict:
    """For Borrower (entity-backed:Borrower). Pass the actual Borrower.id as
    user_id whenever the call is ownership-gated."""
    return build_user_headers(user_id, "Borrower")


def make_inspector_headers(user_id: str) -> dict:
    """For Inspector: X-User-ID must equal the appointment's inspector_id."""
    return build_user_headers(user_id, "Inspector")


def make_disbursement_officer_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "DisbursementOfficer")


def make_legal_counsel_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "LegalCounsel")
