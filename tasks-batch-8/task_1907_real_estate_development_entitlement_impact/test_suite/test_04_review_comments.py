"""Review comment cycles: referential guards, the blocking gate, and the
branching resolution fork with round increments."""
from test_helpers import (
    ApiErrorId,
    assert_review_comment,
    create_review_comment_payload,
    get_application,
    make_applicant_headers,
    post_comment,
    setup_submitted_application,
    setup_under_review_application,
    validate_error,
    validate_success,
)


def test_review_comment_revises_comment_id_self_reference(api):
    """PRD 3.4: "an optional `revises_comment_id` may mark the new comment as
    superseding an earlier one, but only when the target belongs to the same
    application and the same discipline — a cross-application or
    cross-discipline target is refused with `ERR_REVISION_MISMATCH`."

    Design: Corner/entities/review_comment_revises_comment_id_self_reference
    """
    ctx1 = setup_under_review_application(reviewer_disciplines=["TRANSPORTATION"])
    # Second application (own project) under review by the same reviewer.
    ctx2 = setup_submitted_application()
    ctx2["reviewer"] = ctx1["reviewer"]
    ctx2["reviewer_headers"] = ctx1["reviewer_headers"]
    validate_success(
        api.open_review(ctx2["application"]["id"], ctx2["reviewer_headers"])
    )

    comment1 = post_comment(
        ctx1,
        severity="INFO",
        discipline="TRANSPORTATION",
        comment_text="app1 comment",
    )
    assert_review_comment(comment1)

    payload = create_review_comment_payload(
        ctx1["reviewer"]["id"],
        discipline="TRANSPORTATION",
        comment_text="cross-app revise",
        severity="INFO",
        revises_comment_id=comment1["id"],
    )
    response = api.create_review_comment(
        ctx2["application"]["id"], payload, ctx2["reviewer_headers"]
    )
    validate_error(response, ApiErrorId.ERR_REVISION_MISMATCH)


def test_discipline_mismatch_reviewer_comment_rejected(api):
    """PRD 3.4: "the comment's `discipline` must appear in the authoring
    reviewer's registered `disciplines`, else `ERR_DISCIPLINE_MISMATCH`."

    Design: Corner/validations/discipline_mismatch_reviewer_comment_rejected
    """
    ctx = setup_under_review_application(reviewer_disciplines=["TRANSPORTATION"])
    payload = create_review_comment_payload(
        ctx["reviewer"]["id"],
        discipline="SEWER",
        comment_text="out of discipline",
        severity="INFO",
    )
    response = api.create_review_comment(
        ctx["application"]["id"], payload, ctx["reviewer_headers"]
    )
    validate_error(response, ApiErrorId.ERR_DISCIPLINE_MISMATCH)


def test_blocking_comments_open_blocks_advance_to_decision(api):
    """PRD 3.6: "From either origin, every `BLOCKING` review comment must stand
    in `VERIFIED` or `WAIVED` — a comment merely `ADDRESSED` but not yet
    verified still blocks, and the rejection is `ERR_BLOCKING_COMMENTS_OPEN`."

    Design: Corner/validations/blocking_comments_open_blocks_advance_to_decision
    """
    ctx = setup_under_review_application(reviewer_disciplines=["TRANSPORTATION"])
    post_comment(
        ctx, severity="BLOCKING", discipline="TRANSPORTATION", comment_text="blocking"
    )

    response = api.advance_to_decision(
        ctx["application"]["id"], ctx["reviewer_headers"]
    )
    validate_error(response, ApiErrorId.ERR_BLOCKING_COMMENTS_OPEN)

    after = get_application(ctx["application"]["id"], ctx["reviewer_headers"])
    assert after["status"] == "UNDER_REVIEW", (
        f"rejected advance must leave the application UNDER_REVIEW, got {after['status']}"
    )


class TestCommentRoundsAndResolutionFork:
    def test_address_verify_branch_and_round_increment(self, api):
        """PRD 3.4: "the applicant answers a comment by marking it `ADDRESSED`.
        The authoring reviewer — and only that reviewer — then either verifies
        an `ADDRESSED` comment, moving it to `VERIFIED`".
        PRD 3.4: "each new batch of comments is a fresh round, recorded on the
        new comments as an incremented `round_number`" and "posting keeps it
        there" (the application stays UNDER_REVIEW through the rounds).

        Design: Difficulty/non_linear_state_machine/review_comment_cyclic_rounds_and_branching_resolution
        """
        ctx = setup_under_review_application(reviewer_disciplines=["TRANSPORTATION"])
        app_id = ctx["application"]["id"]

        round1 = post_comment(
            ctx,
            severity="BLOCKING",
            discipline="TRANSPORTATION",
            comment_text="Round 1 blocking",
        )
        assert round1["status"] == "OPEN"

        addressed = validate_success(
            api.address_review_comment(round1["id"], ctx["applicant_headers"])
        )
        assert addressed["status"] == "ADDRESSED"

        verified = validate_success(
            api.verify_review_comment(round1["id"], ctx["reviewer_headers"])
        )
        assert verified["status"] == "VERIFIED", (
            f"OPEN→ADDRESSED→VERIFIED branch must land VERIFIED, got {verified['status']}"
        )

        round2 = post_comment(
            ctx,
            severity="INFO",
            discipline="TRANSPORTATION",
            comment_text="Round 2 info",
        )
        assert round2["round_number"] == round1["round_number"] + 1, (
            f"second comment round must increment round_number: "
            f"{round1['round_number']} -> {round2['round_number']}"
        )

        after = get_application(app_id, ctx["reviewer_headers"])
        assert after["status"] == "UNDER_REVIEW", (
            "the cyclic review loop must keep the application UNDER_REVIEW, "
            f"got {after['status']}"
        )

    def test_waive_branch_and_terminal_lockout(self, api):
        """PRD 3.4: "The authoring reviewer — and only that reviewer — then
        either verifies an `ADDRESSED` comment, moving it to `VERIFIED`, or
        waives an `OPEN` comment outright, moving it to `WAIVED`. `VERIFIED`
        and `WAIVED` are terminal."
        PRD 2.9: "an entity already in a terminal state accepts no further
        transitions and reports `ERR_ALREADY_TERMINAL` (409)."

        Design: Difficulty/non_linear_state_machine/review_comment_cyclic_rounds_and_branching_resolution
        """
        ctx = setup_under_review_application(reviewer_disciplines=["TRANSPORTATION"])
        comment = post_comment(
            ctx,
            severity="REQUIRED",
            discipline="TRANSPORTATION",
            comment_text="waive me",
        )
        waived = validate_success(
            api.waive_review_comment(comment["id"], ctx["reviewer_headers"])
        )
        assert waived["status"] == "WAIVED", (
            f"OPEN→WAIVED branch must land WAIVED, got {waived['status']}"
        )

        # Terminal: the applicant can no longer mark it ADDRESSED.
        response = api.address_review_comment(comment["id"], ctx["applicant_headers"])
        validate_error(response, ApiErrorId.ERR_ALREADY_TERMINAL)
