"""Pre-built role headers for every role in the PRD."""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants -- safe for the five opaque roles, and for tests on the two
# entity-backed roles that do not exercise an ownership check.
TEST_USERS = {
    "intake_agent_headers": build_user_headers("op-intake-1", "IntakeAgent"),
    "title_clerk_headers": build_user_headers("op-title-1", "TitleClerk"),
    "auction_manager_headers": build_user_headers("op-auction-1", "AuctionManager"),
    "finance_officer_headers": build_user_headers("fo-alice", "FinanceOfficer"),
    "finance_officer_bob_headers": build_user_headers("fo-bob", "FinanceOfficer"),
    "program_admin_headers": build_user_headers("op-admin-1", "ProgramAdmin"),
    # entity-backed fallbacks: only for calls with no ownership check.
    "donor_headers": build_user_headers("test-donor-1", "Donor"),
    "charity_admin_headers": build_user_headers("test-charity-1", "CharityAdmin"),
}


def make_donor_headers(donor_id: str) -> dict:
    """For the Donor role, whose X-User-ID is the acting donor record's id.

    Pass the real Donor.id whenever the call is ownership-gated (donation
    cancellation, donation listing filtered by donor_id).
    """
    return build_user_headers(donor_id, "Donor")


def make_charity_admin_headers(charity_id: str) -> dict:
    """For the CharityAdmin role, whose X-User-ID is the acting charity affiliate's id.

    Pass the real CharityAffiliate.id whenever the call is ownership-gated
    (batch dispute, charity-summary report, donation listing filtered by charity_id).
    """
    return build_user_headers(charity_id, "CharityAdmin")


def make_finance_officer_headers(user_id: str) -> dict:
    """For FinanceOfficer, whose opaque X-User-ID is stamped into
    closed_by_user_id / paid_by_user_id and drives the segregation-of-duties gate."""
    return build_user_headers(user_id, "FinanceOfficer")


def make_program_admin_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "ProgramAdmin")
