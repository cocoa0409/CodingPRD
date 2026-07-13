"""Authentication, role permission, and ownership (queue B — rbac)."""
from test_helpers import (
    validate_error, ApiErrorId, NON_EXISTENT_UUID, TEST_USERS,
    make_creator_headers, new_publication, new_member,
)

CREATOR = TEST_USERS["creator_headers"]
MEMBER = TEST_USERS["member_headers"]
ANON = TEST_USERS["anonymous_headers"]


def test_member_cannot_create_tier_forbidden(api):
    """PRD §2.1: "When a recognized, authenticated caller attempts an operation
    their role is not permitted to perform, the request is rejected with
    `ERR_FORBIDDEN`."

    Design: Corner/rbac/member_cannot_create_tier_forbidden
    """
    pub = new_publication(api)
    resp = api.create_tier(
        pub["id"],
        {"name": "X", "tier_rank": 1, "monthly_price_cents": 1000, "trial_days": 0},
        MEMBER,
    )
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN.value)


def test_member_cannot_settle_payout_forbidden(api):
    """PRD §2.1: "When a recognized, authenticated caller attempts an operation
    their role is not permitted to perform, the request is rejected with
    `ERR_FORBIDDEN`."

    Design: Corner/rbac/member_cannot_settle_payout_forbidden
    """
    resp = api.settle_payout(NON_EXISTENT_UUID, {"outcome": "PAID"}, MEMBER)
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN.value)


def test_creator_cannot_post_to_unowned_publication_forbidden(api):
    """PRD §2.1: "When a caller is permitted the operation in general but targets
    a resource they do not own, the request is rejected with
    `ERR_NOT_RESOURCE_OWNER`."
    PRD §2.1: "ownership checks on a publication and all of its child resources
    compare that publication's `creator_user_id` to `X-User-ID`."

    Design: Corner/rbac/creator_cannot_post_to_unowned_publication_forbidden
    """
    pub = new_publication(api, creator_id="creator_1")
    resp = api.create_post(
        pub["id"],
        {"title": "T", "body": "B", "content_type": "POST", "min_tier_rank": 0},
        make_creator_headers("creator_2"),
    )
    validate_error(resp, ApiErrorId.ERR_NOT_RESOURCE_OWNER.value)


def test_missing_user_id_header_returns_401(api):
    """PRD §2.1: "A request whose `X-User-Role` is missing or not one of these
    five, or whose `X-User-ID` is absent for any role other than `Anonymous`, is
    rejected with `ERR_UNAUTHENTICATED`."

    Design: Corner/rbac/missing_user_id_header_returns_401
    """
    pub = new_publication(api)
    member = new_member(api, pub["id"])
    headers = {"X-User-Role": "Member", "Content-Type": "application/json"}
    resp = api.get_member(member["id"], headers)
    validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED.value)
