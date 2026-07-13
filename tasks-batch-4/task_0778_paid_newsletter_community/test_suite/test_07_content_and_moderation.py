"""Content gating and community moderation.

Difficulty (queue A): comment moderation fork PENDING->HELD->APPROVED; comment
creation requires an active subscription. Corner (queue B): terminal comment
lockdown; reject-from-pending; read gated content with too-low tier.
"""
from test_helpers import (
    validate_success, validate_error, validate_paginated, ApiErrorId, TEST_USERS,
    make_member_headers,
    new_publication, new_verified_member, new_post,
    setup_pending_comment, setup_free_member_with_published_post,
)

CREATOR = TEST_USERS["creator_headers"]
MODERATOR = TEST_USERS["moderator_headers"]


# ---------------------------------------------------------------------------
# Difficulty A6 — moderation fork PENDING -> HELD -> APPROVED
# ---------------------------------------------------------------------------

def test_comment_held_then_approved_reaches_approved(api):
    """PRD §3.7: "a `HOLD` decision moves it to `HELD` and sets a
    `moderation_reason`. From `HELD`, an `APPROVE` decision moves it to
    `APPROVED` and a `REJECT` decision moves it to `REJECTED` with a reason."

    Design: Difficulty/non_linear_state_machine/comment_moderation_fork_pending_to_held_to_approved
    """
    base = setup_pending_comment(api)
    cmt = base["comment"]
    validate_success(api.moderate_comment(cmt["id"], {"decision": "HOLD"}, CREATOR),
                     expected_status=200)
    resp = api.moderate_comment(cmt["id"], {"decision": "APPROVE"}, CREATOR)
    data = validate_success(resp, expected_status=200)
    assert data["status"] == "APPROVED"


def test_comment_approval_increments_post_count(api):
    """PRD §3.7: "Each transition into `APPROVED` increments the owning post's
    `approved_comment_count`, and hiding an approved comment decrements it, so
    the post's `approved_comment_count` always reflects the number of comments
    currently in `APPROVED`."

    Design: Difficulty/non_linear_state_machine/comment_moderation_fork_pending_to_held_to_approved
    """
    base = setup_pending_comment(api)
    cmt, post = base["comment"], base["post"]
    api.moderate_comment(cmt["id"], {"decision": "HOLD"}, CREATOR)
    api.moderate_comment(cmt["id"], {"decision": "APPROVE"}, CREATOR)
    post_data = validate_success(api.get_post_content(post["id"], CREATOR), expected_status=200)
    assert post_data["approved_comment_count"] == 1


# ---------------------------------------------------------------------------
# Difficulty A14 — commenting requires an active subscription
# ---------------------------------------------------------------------------

def _verified_member_no_sub_with_post(api):
    pub = new_publication(api)
    member = new_verified_member(api, pub["id"])
    post = new_post(api, pub["id"], publish=True, min_tier_rank=0)
    return member, post


def test_comment_without_subscription_rejected(api):
    """PRD §3.7: "To read gated content or to comment, the member must hold an
    `ACTIVE` subscription whose `current_tier_rank` is at least the post's
    `min_tier_rank`. A member with no qualifying subscription is refused with
    `ERR_SUBSCRIPTION_REQUIRED` ..."

    Design: Difficulty/cross_entity_state_dependency/comment_creation_requires_active_subscription
    """
    member, post = _verified_member_no_sub_with_post(api)
    resp = api.create_comment(post["id"], {"body": "hey"}, make_member_headers(member["id"]))
    validate_error(resp, ApiErrorId.ERR_SUBSCRIPTION_REQUIRED.value)


def test_comment_without_subscription_creates_nothing(api):
    """PRD §3.7: "A member posts a **comment** by supplying its `body`; the
    comment records its `post_id`, the authoring `member_id`, starts in
    `PENDING` ..." — but only a member with a qualifying `ACTIVE` subscription may
    comment; without one the request is refused with `ERR_SUBSCRIPTION_REQUIRED`.

    Design: Difficulty/cross_entity_state_dependency/comment_creation_requires_active_subscription
    """
    member, post = _verified_member_no_sub_with_post(api)
    api.create_comment(post["id"], {"body": "hey"}, make_member_headers(member["id"]))
    comments, _meta = validate_paginated(api.list_comments(CREATOR, params={"post_id": post["id"]}))
    assert comments == [], "a rejected comment must not be persisted"


# ---------------------------------------------------------------------------
# Corner — terminal REJECTED comment cannot be moderated again
# ---------------------------------------------------------------------------

def test_moderate_terminal_rejected_comment_rejected(api):
    """PRD §3.7: "a `REJECT` decision moves it to the terminal `REJECTED` and
    sets a `moderation_reason` ... Any moderation attempt from a state that does
    not permit the requested decision is rejected with `ERR_INVALID_STATE`."

    Design: Corner/state_machines/moderate_terminal_rejected_comment_invalid_state_rejected
    """
    base = setup_pending_comment(api)
    cmt = base["comment"]
    api.moderate_comment(cmt["id"], {"decision": "REJECT"}, CREATOR)
    resp = api.moderate_comment(cmt["id"], {"decision": "APPROVE"}, CREATOR)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)


# ---------------------------------------------------------------------------
# Corner — reject a PENDING comment
# ---------------------------------------------------------------------------

def test_comment_reject_from_pending(api):
    """PRD §3.7: "From `PENDING`, an `APPROVE` decision moves the comment to
    `APPROVED`, a `REJECT` decision moves it to the terminal `REJECTED` and sets
    a `moderation_reason` ..."

    Design: Corner/state_machines/comment_reject_from_pending_sets_reason
    """
    base = setup_pending_comment(api)
    cmt = base["comment"]
    resp = api.moderate_comment(cmt["id"], {"decision": "REJECT"}, MODERATOR)
    data = validate_success(resp, expected_status=200)
    assert data["status"] == "REJECTED"


# ---------------------------------------------------------------------------
# Corner — read gated content with a too-low tier
# ---------------------------------------------------------------------------

def test_read_gated_content_tier_too_low(api):
    """PRD §3.7: "a member whose subscription rank falls below the post's minimum
    is refused with `ERR_TIER_TOO_LOW`."

    Design: Corner/validations/read_gated_content_tier_too_low_returns_403
    """
    base = setup_free_member_with_published_post(api, min_tier_rank=2)
    member, post = base["member"], base["post"]
    resp = api.get_post_content(post["id"], make_member_headers(member["id"]))
    validate_error(resp, ApiErrorId.ERR_TIER_TOO_LOW.value)
