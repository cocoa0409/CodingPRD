"""Petition moderation revision loop, invalid moderation, and victory-closure gates.

Queue-A depth: petition_moderation_revision_cycle, victory_requires_nonempty_delivery_boundary.
Queue-B breadth: moderate_draft_petition_invalid_state, victory_zero_verified_signatures.
"""
import pytest
from test_helpers import (
    validate_success, validate_error, get_success_data,
    ApiErrorId,
    register_member, create_draft_petition,
    publish_petition, submit_petition_under_review,
    register_sign_and_verify, setup_delivered_meeting,
    TEST_USERS, make_member_headers,
)

MODERATOR = TEST_USERS["moderator_headers"]
GUEST = TEST_USERS["guest_headers"]


# ── non_linear_state_machine / petition_moderation_revision_cycle ────────────
def test_request_changes_moves_petition_to_changes_requested(api):
    """PRD §3.1: "Requesting changes moves it from `UNDER_REVIEW` to `CHANGES_REQUESTED` with
    no further effect."

    Design: Difficulty/non_linear_state_machine/petition_moderation_revision_cycle
    """
    ctx = submit_petition_under_review(goal=100)
    updated = validate_success(api.moderate_petition(
        ctx["petition_id"], {"decision": "REQUEST_CHANGES"}, MODERATOR))
    assert updated["status"] == "CHANGES_REQUESTED"


def test_resubmit_from_changes_requested_reenters_under_review(api):
    """PRD §3.1: "The revision loop is cyclic: a petition that a moderator sent back to
    CHANGES_REQUESTED can be resubmitted by its author, again moving to UNDER_REVIEW."

    Design: Difficulty/non_linear_state_machine/petition_moderation_revision_cycle
    """
    ctx = submit_petition_under_review(goal=100)
    api.moderate_petition(ctx["petition_id"], {"decision": "REQUEST_CHANGES"}, MODERATOR)
    resubmitted = validate_success(api.submit_petition(
        ctx["petition_id"], make_member_headers(ctx["author_id"])))
    assert resubmitted["status"] == "UNDER_REVIEW"


# ── boundary_precision_check / victory_requires_nonempty_delivery_boundary ───
def test_victory_rejected_with_zero_delivered_meetings(api):
    """PRD §3.8: "the petition must have a verified_signature_count greater than 0 —
    checked first, and if it fails the closure is rejected with ERR_NO_VERIFIED_SIGNATURES
    — and a delivered_meeting_count of at least 1 — checked second, rejected with
    ERR_NO_DELIVERY."

    Design: Difficulty/boundary_precision_check/victory_requires_nonempty_delivery_boundary
    """
    ctx = publish_petition(goal=1)
    register_sign_and_verify(ctx["petition_id"])
    resp = api.close_petition(
        ctx["petition_id"], {"outcome": "VICTORY"}, make_member_headers(ctx["author_id"]))
    validate_error(resp, ApiErrorId.ERR_NO_DELIVERY.value, expected_status=422)


def test_victory_succeeds_with_one_delivered_meeting(api):
    """PRD §3.8: "Declaring victory moves the petition from PUBLISHED to CLOSED_VICTORY,
    but only when the campaign has produced real, delivered support: the petition must
    have a verified_signature_count greater than 0 ... and a delivered_meeting_count of
    at least 1 ... checked second, rejected with ERR_NO_DELIVERY."

    Design: Difficulty/boundary_precision_check/victory_requires_nonempty_delivery_boundary
    """
    ctx = publish_petition(goal=1)
    register_sign_and_verify(ctx["petition_id"])
    setup_delivered_meeting(ctx["petition_id"], ctx["target_id"], ctx["author_id"])
    closed = validate_success(api.close_petition(
        ctx["petition_id"], {"outcome": "VICTORY"}, make_member_headers(ctx["author_id"])))
    assert closed["status"] == "CLOSED_VICTORY"


# ── Corner instances ─────────────────────────────────────────────────────────
def test_moderate_draft_petition_is_invalid_state(api):
    """PRD §2.5: "the generic legal-state check for the requested transition
    (ERR_INVALID_STATE, 409)."
    PRD §3.1: "Approving it moves the petition from `UNDER_REVIEW` to `PUBLISHED`."

    Design: Corner/state_machines/moderate_draft_petition_invalid_state
    """
    author = register_member()
    pet = create_draft_petition(author["id"], goal=10)
    resp = api.moderate_petition(pet["id"], {"decision": "APPROVE"}, MODERATOR)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value, expected_status=409)


def test_victory_rejected_with_zero_verified_signatures(api):
    """PRD §3.8: "the petition must have a verified_signature_count greater than 0 —
    checked first, and if it fails the closure is rejected with ERR_NO_VERIFIED_SIGNATURES."

    Design: Corner/validations/victory_zero_verified_signatures
    """
    ctx = publish_petition(goal=10)
    resp = api.close_petition(
        ctx["petition_id"], {"outcome": "VICTORY"}, make_member_headers(ctx["author_id"]))
    validate_error(resp, ApiErrorId.ERR_NO_VERIFIED_SIGNATURES.value, expected_status=422)
