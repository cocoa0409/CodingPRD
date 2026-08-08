"""Pre-built role headers for every role in the PRD (§2.1).

Every role carries an OPAQUE identity: X-User-ID is an operator identifier that is
never compared against an entity primary key for ownership. The server only *records*
the acting X-User-ID for accountability (case/claim denied_by_user_id, appeal
decided_by_user_id) — the basis for the segregation-of-duties rule (§2.10). Therefore
tests that exercise segregation of duties must pass explicit user ids via
make_headers(role, user_id); other tests may use the shared constants below.
"""
from prd_bench_local_runner.testing import build_user_headers

# Default operator id per role.
DEFAULT_USER_IDS = {
    "ProgramAdmin": "admin-1",
    "IntakeCounselor": "intake-1",
    "Adjudicator": "adj-1",
    "FinanceOfficer": "finance-1",
    "RecoveryOfficer": "recovery-1",
    "AppealsOfficer": "appeals-1",
}

# Shared constants — canonical for opaque roles and non-segregation tests.
TEST_USERS = {
    "program_admin_headers": build_user_headers(DEFAULT_USER_IDS["ProgramAdmin"], "ProgramAdmin"),
    "intake_counselor_headers": build_user_headers(DEFAULT_USER_IDS["IntakeCounselor"], "IntakeCounselor"),
    "adjudicator_headers": build_user_headers(DEFAULT_USER_IDS["Adjudicator"], "Adjudicator"),
    "finance_officer_headers": build_user_headers(DEFAULT_USER_IDS["FinanceOfficer"], "FinanceOfficer"),
    "recovery_officer_headers": build_user_headers(DEFAULT_USER_IDS["RecoveryOfficer"], "RecoveryOfficer"),
    "appeals_officer_headers": build_user_headers(DEFAULT_USER_IDS["AppealsOfficer"], "AppealsOfficer"),
}


def make_headers(role: str, user_id: str = None) -> dict:
    """Build headers for a role with an explicit X-User-ID (defaults per role).

    Use an explicit user_id when a test needs a specific acting identity — e.g.
    segregation-of-duties, where the deciding AppealsOfficer's id must (not) equal
    the denying Adjudicator's id.
    """
    if user_id is None:
        user_id = DEFAULT_USER_IDS[role]
    return build_user_headers(user_id, role)
