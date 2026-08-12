"""Pre-built auth headers for every role in the PRD (§2.1).

`ClubAdmin`, `WarehouseOperator` and `FinanceOfficer` carry an opaque
`X-User-ID` that is never compared to an entity id, so the shared constants
below are the canonical form for them.  `Member` and `DropCoordinator` carry
the id of the acting `Member` row, so ownership-gated calls MUST use the
per-instance builders with the real member id.
"""

from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe for the opaque roles and for calls that never reach
# an ownership check.
TEST_USERS = {
    "club_admin_headers": build_user_headers("admin-1", "ClubAdmin"),
    "warehouse_headers": build_user_headers("warehouse-1", "WarehouseOperator"),
    "finance_headers": build_user_headers("finance-1", "FinanceOfficer"),
    # entity_backed roles: placeholders only, never for ownership-gated calls.
    "member_headers": build_user_headers("member-placeholder", "Member"),
    "coordinator_headers": build_user_headers(
        "coordinator-placeholder", "DropCoordinator"
    ),
}

# Two distinct finance identities, because segregation of duties on a drop
# reconciliation is enforced on X-User-ID rather than on role (PRD §2.1).
FINANCE_PREPARER_USER_ID = "fin-prep-1"
FINANCE_POSTER_USER_ID = "fin-post-2"
FINANCE_SECOND_PREPARER_USER_ID = "fin-prep-9"

FINANCE_PREPARER_HEADERS = build_user_headers(
    FINANCE_PREPARER_USER_ID, "FinanceOfficer"
)
FINANCE_POSTER_HEADERS = build_user_headers(FINANCE_POSTER_USER_ID, "FinanceOfficer")
FINANCE_SECOND_PREPARER_HEADERS = build_user_headers(
    FINANCE_SECOND_PREPARER_USER_ID, "FinanceOfficer"
)


def make_member_headers(member_id: str) -> dict:
    """Headers for the `Member` role. `X-User-ID` is the acting Member's id."""
    return build_user_headers(member_id, "Member")


def make_coordinator_headers(member_id: str) -> dict:
    """Headers for `DropCoordinator`. `X-User-ID` is the acting Member's id."""
    return build_user_headers(member_id, "DropCoordinator")


def make_club_admin_headers(user_id: str = "admin-1") -> dict:
    return build_user_headers(user_id, "ClubAdmin")


def make_warehouse_headers(user_id: str = "warehouse-1") -> dict:
    return build_user_headers(user_id, "WarehouseOperator")


def make_finance_headers(user_id: str = "finance-1") -> dict:
    return build_user_headers(user_id, "FinanceOfficer")


def make_headers(role: str, user_id: str) -> dict:
    return build_user_headers(user_id, role)
