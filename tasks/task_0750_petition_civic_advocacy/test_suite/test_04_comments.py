"""Comment moderation branch-return semantics, update moderatability, and delivery.

Queue-A depth: comment_flag_dismiss_branch_return.
Queue-B breadth: moderate_update_type_comment_not_moderatable, update_deliver_sets_delivered_flag.
"""
import pytest
from test_helpers import (
    validate_success, validate_error, get_success_data,
    ApiErrorId,
    register_member, publish_petition,
    post_comment, post_approved_comment, post_flagged_comment,
    TEST_USERS, make_member_headers,
)

MODERATOR = TEST_USERS["moderator_headers"]
GUEST = TEST_USERS["guest_headers"]


# ── non_linear_state_machine / comment_flag_dismiss_branch_return ────────────
def test_dismiss_flag_restores_comment_and_count(api):
    """PRD §3.4: "dismissing the flag restores the comment, moving it from FLAGGED back
    to APPROVED and increasing approved_comment_count by 1 again."

    Design: Difficulty/non_linear_state_machine/comment_flag_dismiss_branch_return
    """
    ctx = publish_petition(goal=100)
    commenter = register_member()
    flagged = post_flagged_comment(ctx["petition_id"], commenter["id"])
    dismissed = validate_success(api.moderate_comment(
        flagged["id"], {"decision": "DISMISS"}, MODERATOR))
    assert dismissed["status"] == "APPROVED"
    pet = get_success_data(api.get_petition(ctx["petition_id"], GUEST))
    assert pet["approved_comment_count"] == 1


def test_remove_flag_leaves_count_decremented(api):
    """PRD §3.4: "removing it moves it from FLAGGED to REMOVED and does not change the
    count, precisely because the count was already decremented when the comment was
    flagged."

    Design: Difficulty/non_linear_state_machine/comment_flag_dismiss_branch_return
    """
    ctx = publish_petition(goal=100)
    commenter = register_member()
    flagged = post_flagged_comment(ctx["petition_id"], commenter["id"])
    removed = validate_success(api.moderate_comment(
        flagged["id"], {"decision": "REMOVE"}, MODERATOR))
    assert removed["status"] == "REMOVED"
    pet = get_success_data(api.get_petition(ctx["petition_id"], GUEST))
    assert pet["approved_comment_count"] == 0


# ── Corner instances ─────────────────────────────────────────────────────────
def test_moderate_update_type_comment_rejected(api):
    """PRD §3.4: "A Moderator moderates a COMMENT — and only a record whose comment_type
    is COMMENT, in a state and type eligible for the requested decision, or the request
    is refused with ERR_CONTENT_NOT_MODERATABLE."

    Design: Corner/state_machines/moderate_update_type_comment_not_moderatable
    """
    ctx = publish_petition(goal=10)
    update = post_comment(ctx["petition_id"], ctx["author_id"],
                          body="progress", comment_type="UPDATE")
    resp = api.moderate_comment(update["id"], {"decision": "APPROVE"}, MODERATOR)
    validate_error(resp, ApiErrorId.ERR_CONTENT_NOT_MODERATABLE.value, expected_status=409)


def test_deliver_approved_update_sets_delivered_flag(api):
    """PRD §3.4: "The petition author may mark an approved UPDATE as delivered to signers,
    which sets the record's delivered flag to true."

    Design: Corner/endpoints/update_deliver_sets_delivered_flag
    """
    ctx = publish_petition(goal=10)
    update = post_comment(ctx["petition_id"], ctx["author_id"],
                          body="we won a hearing", comment_type="UPDATE")
    delivered = validate_success(api.deliver_comment(
        update["id"], make_member_headers(ctx["author_id"])))
    assert delivered["delivered"] is True
