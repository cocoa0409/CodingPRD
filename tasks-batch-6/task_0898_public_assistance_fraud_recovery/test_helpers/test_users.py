"""Pre-built role headers for every role in the PRD.

All five roles have opaque identity: X-User-ID is an operator identifier that is
never compared against any entity id. Stored operator identifiers
(assigned_investigator_id, decided_by_user_id) are compared to one another for
segregation of duties, so tests that exercise that rule control X-User-ID
explicitly via make_headers().
"""
from prd_bench_local_runner.testing import build_user_headers

# Default per-role user ids. The default investigator id "inv-1" and adjudicator
# id "adj-1" differ, so happy-path hearing decisions pass segregation of duties.
DEFAULT_INVESTIGATOR_ID = "inv-1"
DEFAULT_ADJUDICATOR_ID = "adj-1"

TEST_USERS = {
    "intake_headers": build_user_headers("intake-1", "Intake"),
    "investigator_headers": build_user_headers(DEFAULT_INVESTIGATOR_ID, "Investigator"),
    "adjudicator_headers": build_user_headers(DEFAULT_ADJUDICATOR_ID, "Adjudicator"),
    "recovery_officer_headers": build_user_headers("rec-1", "RecoveryOfficer"),
    "supervisor_headers": build_user_headers("sup-1", "Supervisor"),
}


def make_headers(role: str, user_id: str) -> dict:
    """Build headers for an arbitrary role/user-id pair (for segregation-of-duties
    scenarios where the acting operator id must be controlled explicitly)."""
    return build_user_headers(user_id, role)


def make_investigator_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "Investigator")


def make_adjudicator_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "Adjudicator")
