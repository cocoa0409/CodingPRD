"""Pre-built role headers for every role in the PRD.

`ProgramAdmin` and `FinanceAdmin` are opaque operator identities, so the shared
constants below are the canonical form for them. The four remaining roles are
entity-backed: `X-User-ID` must resolve to a persisted StaffMember row, so
ownership-gated calls MUST use the per-instance builders with the real staff id.
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    # Opaque roles — the shared constant is the canonical form.
    "program_admin_headers": build_user_headers("op-program-admin-1", "ProgramAdmin"),
    "finance_admin_headers": build_user_headers("op-finance-admin-1", "FinanceAdmin"),
    # Entity-backed roles — fallback only for tests that never reach an
    # identity-resolving check (for example a missing-header rejection).
    "transplant_coordinator_headers": build_user_headers(
        "staff-coordinator-1", "TransplantCoordinator"
    ),
    "donor_advocate_headers": build_user_headers("staff-advocate-1", "DonorAdvocate"),
    "evaluation_reviewer_headers": build_user_headers(
        "staff-reviewer-1", "EvaluationReviewer"
    ),
    "quality_officer_headers": build_user_headers("staff-quality-1", "QualityOfficer"),
}


def make_program_admin_headers(user_id: str = "op-program-admin-1") -> dict:
    """ProgramAdmin is an opaque operator identifier, never a foreign key."""
    return build_user_headers(user_id, "ProgramAdmin")


def make_finance_admin_headers(user_id: str = "op-finance-admin-1") -> dict:
    """FinanceAdmin is an opaque operator identifier recorded as adjudicated_by_user_id."""
    return build_user_headers(user_id, "FinanceAdmin")


def make_coordinator_headers(user_id: str) -> dict:
    """Pass the id of an active StaffMember whose staff_role is TRANSPLANT_COORDINATOR."""
    return build_user_headers(user_id, "TransplantCoordinator")


def make_advocate_headers(user_id: str) -> dict:
    """Pass the id of an active StaffMember whose staff_role is LIVING_DONOR_ADVOCATE.

    For any operation on a donor candidate this must be the donor's
    advocate_staff_id.
    """
    return build_user_headers(user_id, "DonorAdvocate")


def make_reviewer_headers(user_id: str) -> dict:
    """Pass the id of an active StaffMember whose staff_role is EVALUATION_REVIEWER.

    For any operation on an existing evaluation this must be the evaluation's
    reviewer_staff_id.
    """
    return build_user_headers(user_id, "EvaluationReviewer")


def make_quality_officer_headers(user_id: str) -> dict:
    """Pass the id of an active StaffMember whose staff_role is QUALITY_OFFICER."""
    return build_user_headers(user_id, "QualityOfficer")
