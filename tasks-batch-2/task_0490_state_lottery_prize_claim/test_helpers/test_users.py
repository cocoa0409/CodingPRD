"""Pre-built role headers for every role in the PRD (Section 2.1).

Identity in this system is operator-based, not entity-backed: every role's
X-User-ID is an opaque operator identifier never compared against any entity id
(PRD 2.1). The shared constants below are therefore the canonical form for each
role. Where a workflow records and compares operator identifiers (segregation of
duties on prize-claim disburse and settlement finalize, PRD 2.6), tests need two
*distinct* LotteryOfficer identities — use officer_headers(user_id) to mint them.
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    "licensing_admin_headers": build_user_headers("u-licadmin", "LicensingAdmin"),
    "terminal_operator_headers": build_user_headers("u-termop", "TerminalOperator"),
    "claims_clerk_headers": build_user_headers("u-clerk", "ClaimsClerk"),
    # Default LotteryOfficer identity (used where no segregation distinction matters).
    "lottery_officer_headers": build_user_headers("u-officer", "LotteryOfficer"),
}


def officer_headers(user_id: str) -> dict:
    """Mint a LotteryOfficer header with an explicit X-User-ID.

    Use distinct user_ids across the two duties of a segregation-of-duties pair:
    the adjudicating/preparing officer vs. the disbursing/approving officer.
    """
    return build_user_headers(user_id, "LotteryOfficer")


def admin_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "LicensingAdmin")


def operator_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "TerminalOperator")


def clerk_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "ClaimsClerk")
