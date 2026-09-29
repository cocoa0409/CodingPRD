"""Pre-built role headers for every role named in the PRD (§2.1).

Five of the six roles carry an opaque identity, so a shared constant is the
canonical form for them. `MemberOwner` is the exception: `X-User-ID` is the `id`
of the acting `Member` row, so ownership-gated calls MUST use
`make_member_owner_headers(member["id"])`.
"""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe for the five opaque roles and for tests that do not
# exercise per-row ownership.
TEST_USERS = {
    "secretary_headers": build_user_headers("sec-1", "AssociationSecretary"),
    "clerk_headers": build_user_headers("clerk-1", "AssessmentClerk"),
    "treasurer_headers": build_user_headers("bt-1", "BoardTreasurer"),
    "treasurer_two_headers": build_user_headers("bt-2", "BoardTreasurer"),
    "treasurer_three_headers": build_user_headers("bt-3", "BoardTreasurer"),
    "commissioner_headers": build_user_headers("rc-1", "RoadCommissioner"),
    "commissioner_two_headers": build_user_headers("rc-2", "RoadCommissioner"),
    "contractor_headers": build_user_headers("c-1", "Contractor"),
    "contractor_two_headers": build_user_headers("c-2", "Contractor"),
    "contractor_three_headers": build_user_headers("c-3", "Contractor"),
    # MemberOwner: shared constant is a fallback for non-ownership tests only.
    "member_owner_headers": build_user_headers("member-owner-fallback", "MemberOwner"),
}


# --- Per-user-id builders (the five opaque roles) ---

def make_secretary_headers(user_id: str = "sec-1") -> dict:
    """Headers for an AssociationSecretary acting under `user_id`."""
    return build_user_headers(user_id, "AssociationSecretary")


def make_clerk_headers(user_id: str = "clerk-1") -> dict:
    """Headers for an AssessmentClerk acting under `user_id`."""
    return build_user_headers(user_id, "AssessmentClerk")


def make_treasurer_headers(user_id: str = "bt-1") -> dict:
    """Headers for a BoardTreasurer acting under `user_id`.

    Remedy effectuation compares `X-User-ID` against `initiated_by_user_id`, so
    the initiating and effectuating treasurers must use different ids.
    """
    return build_user_headers(user_id, "BoardTreasurer")


def make_commissioner_headers(user_id: str = "rc-1") -> dict:
    """Headers for a RoadCommissioner acting under `user_id`.

    Project award compares `X-User-ID` against `created_by_user_id`, so the
    creating and awarding commissioners must use different ids.
    """
    return build_user_headers(user_id, "RoadCommissioner")


def make_contractor_headers(user_id: str = "c-1") -> dict:
    """Headers for a Contractor acting under `user_id`.

    Bid withdrawal compares `X-User-ID` against the bid's `contractor_user_id`.
    """
    return build_user_headers(user_id, "Contractor")


# --- Per-instance builder for the one identity-bearing role ---

def make_member_owner_headers(member_id: str) -> dict:
    """Headers for a MemberOwner. Pass the acting `Member`'s `id` as `member_id`.

    Ownership checks compare a resource's `member_id` to `X-User-ID`, so every
    ownership-gated call must use this builder rather than a shared constant.
    """
    return build_user_headers(member_id, "MemberOwner")


def make_headers(role: str, user_id: str) -> dict:
    """Generic builder for an arbitrary role/user-id pair."""
    return build_user_headers(user_id, role)


def make_blank_user_headers(role: str = "MemberOwner") -> dict:
    """Headers whose `X-User-ID` is blank — PRD §2.1 rejects these as
    ERR_UNAUTHENTICATED."""
    return build_user_headers("", role)
