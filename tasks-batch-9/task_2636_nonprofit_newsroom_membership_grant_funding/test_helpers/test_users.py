"""Pre-built role headers for every role in the PRD."""

from prd_bench_local_runner.testing import build_user_headers

# Operator identifiers. DevelopmentOfficer, EditorialDirector, FinanceController
# and BoardOversight are opaque operator identities that are never resolved to a
# row, so these strings only ever matter to the segregation-of-duties comparisons.
USER_IDS = {
    "development_officer": "user-do-1",
    "development_officer_2": "user-do-2",
    "editorial_director": "user-ed-1",
    "editorial_director_2": "user-ed-2",
    "finance_controller": "user-fc-1",
    "board_oversight": "user-bo-1",
}

TEST_USERS = {
    "development_officer_headers": build_user_headers(
        USER_IDS["development_officer"], "DevelopmentOfficer"
    ),
    "development_officer_2_headers": build_user_headers(
        USER_IDS["development_officer_2"], "DevelopmentOfficer"
    ),
    "editorial_director_headers": build_user_headers(
        USER_IDS["editorial_director"], "EditorialDirector"
    ),
    "editorial_director_2_headers": build_user_headers(
        USER_IDS["editorial_director_2"], "EditorialDirector"
    ),
    "finance_controller_headers": build_user_headers(
        USER_IDS["finance_controller"], "FinanceController"
    ),
    "board_oversight_headers": build_user_headers(
        USER_IDS["board_oversight"], "BoardOversight"
    ),
    # Member is the one role whose X-User-ID is a real Member row id. The shared
    # constant is a fallback for calls that never reach an ownership check.
    "member_headers": build_user_headers(
        "00000000-0000-4000-8000-0000000000ff", "Member"
    ),
}


def make_development_officer_headers(user_id: str) -> dict:
    """Headers for a specific DevelopmentOfficer operator identity."""
    return build_user_headers(user_id, "DevelopmentOfficer")


def make_editorial_director_headers(user_id: str) -> dict:
    """Headers for a specific EditorialDirector operator identity."""
    return build_user_headers(user_id, "EditorialDirector")


def make_finance_controller_headers(user_id: str) -> dict:
    """Headers for a specific FinanceController operator identity."""
    return build_user_headers(user_id, "FinanceController")


def make_board_oversight_headers(user_id: str) -> dict:
    """Headers for a specific BoardOversight operator identity."""
    return build_user_headers(user_id, "BoardOversight")


def make_member_headers(user_id: str) -> dict:
    """Headers for the Member role. When X-User-Role is Member, X-User-ID is the
    id of the acting member row, so pass the actual member's id whenever the call
    is ownership-gated."""
    return build_user_headers(user_id, "Member")
