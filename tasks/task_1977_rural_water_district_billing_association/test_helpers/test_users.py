"""Pre-built role headers for every role in the PRD.

All five roles are opaque (X-User-ID is never compared to an entity id), so the
shared constants are canonical. Distinct-id builders exist for flows that key on
the operator identifier: one vote per board member per resolution, and the
segregation-of-duties rule between billing and collecting.
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    "system_admin_headers": build_user_headers("op-admin-1", "SystemAdmin"),
    "billing_clerk_headers": build_user_headers("op-clerk-1", "BillingClerk"),
    "treasurer_headers": build_user_headers("op-treasurer-1", "Treasurer"),
    "board_director_headers": build_user_headers("op-director-proposer", "BoardDirector"),
    "field_operator_headers": build_user_headers("op-field-1", "FieldOperator"),
}

# Distinct board voter ids — a director may vote only once per resolution,
# and the proposer may not cast the deciding vote, so adoption votes come
# from three directors who are not the proposer.
BOARD_VOTER_IDS = ("op-director-v1", "op-director-v2", "op-director-v3", "op-director-v4")


def make_system_admin_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "SystemAdmin")


def make_billing_clerk_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "BillingClerk")


def make_treasurer_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "Treasurer")


def make_board_director_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "BoardDirector")


def make_field_operator_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "FieldOperator")


def board_voter_headers() -> list:
    """Fresh triplet of distinct BoardDirector headers for one resolution's votes."""
    return [make_board_director_headers(uid) for uid in BOARD_VOTER_IDS]
