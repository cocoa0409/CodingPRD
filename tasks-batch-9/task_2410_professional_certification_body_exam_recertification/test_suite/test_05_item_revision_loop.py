"""The item review circuit: revision empties the round and bumps the counter."""

from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers import validate_success
from test_helpers.test_users import (
    ITEM_AUTHOR_ID,
    ITEM_REVIEWER_1_ID,
    ITEM_REVIEWER_2_ID,
    make_item_specialist_headers,
)

AUTHOR = make_item_specialist_headers(ITEM_AUTHOR_ID)
REVIEWER_1 = make_item_specialist_headers(ITEM_REVIEWER_1_ID)
REVIEWER_2 = make_item_specialist_headers(ITEM_REVIEWER_2_ID)

ITEM = {"cognitive_level": "ANALYSIS", "stem": "Revision-loop item"}


def _item_with_one_banked_approval(api):
    """An item in IN_REVIEW carrying exactly one approval, plus the round number
    the first submission left behind.
    """
    program = fx.active_program(api)
    item = fx.draft_item(api, program["id"], **ITEM)
    submitted = validate_success(api.submit_item_for_review(
        item["id"], f.submit_item_payload(revision_note="round one submission"), AUTHOR), 200)
    banked = validate_success(api.review_item(
        item["id"], f.review_item_payload("APPROVE", review_note="round one approval"),
        REVIEWER_1), 200)
    return item["id"], submitted["review_round"], banked


class TestRevisionLoop:
    """DRAFT → IN_REVIEW → REVISION_REQUESTED → IN_REVIEW is a real loop."""

    def test_first_submission_out_of_draft_leaves_the_round_number_where_it_is(self, api):
        """A new item's round is 1, and submitting it for the first time does not
        advance the counter.

        PRD §3.2: "The new item's `status` is `DRAFT`, its `approver_user_ids` list
        is empty, its `review_round` starts at 1".

        PRD §3.2: "`review_round` increases by 1 only when the submission arrives
        from `REVISION_REQUESTED`; a first submission out of `DRAFT` leaves the
        round number where it is."

        Design: Difficulty/non_linear_state_machine/item_revision_loop_bumps_review_round_and_discards_partial_approvals
        """
        program = fx.active_program(api)
        drafted = fx.draft_item(api, program["id"], **ITEM)

        assert drafted["status"] == "DRAFT"
        assert drafted["approver_user_ids"] == []
        assert drafted["review_round"] == 1

        submitted = validate_success(api.submit_item_for_review(
            drafted["id"], f.submit_item_payload(revision_note="round one submission"),
            AUTHOR), 200)

        assert submitted["status"] == "IN_REVIEW"
        assert submitted["review_round"] == 1

    def test_first_approve_of_a_round_banks_the_reviewer_without_promoting(self, api):
        """One approval leaves the item in review, as a self-transition.

        PRD §3.2: "The first `APPROVE` of a round appends the acting user to
        `approver_user_ids` and leaves the item in `IN_REVIEW` — an `IN_REVIEW →
        IN_REVIEW` self-transition."

        Design: Difficulty/non_linear_state_machine/item_revision_loop_bumps_review_round_and_discards_partial_approvals
        """
        item_id, first_round, banked = _item_with_one_banked_approval(api)

        assert banked["status"] == "IN_REVIEW"
        assert banked["approver_user_ids"] == [ITEM_REVIEWER_1_ID]
        assert banked["review_round"] == first_round

    def test_revise_discards_the_partial_approval(self, api):
        """A REVISE decision sends the item back and empties the round's approvals.

        PRD §3.2: "`REVISE` moves the item `IN_REVIEW → REVISION_REQUESTED` and
        discards the round's partial approvals by resetting `approver_user_ids` to
        empty".

        Design: Difficulty/non_linear_state_machine/item_revision_loop_bumps_review_round_and_discards_partial_approvals
        """
        item_id, _first_round, _banked = _item_with_one_banked_approval(api)

        revised = validate_success(api.review_item(
            item_id, f.review_item_payload("REVISE", review_note="stem is double-barrelled"),
            REVIEWER_2), 200)

        assert revised["status"] == "REVISION_REQUESTED"
        assert revised["approver_user_ids"] == []

    def test_resubmission_from_revision_requested_advances_the_round_by_one(self, api):
        """Re-entering review from REVISION_REQUESTED is not idempotent: the round
        number moves on by exactly 1 and the approvals stay empty.

        PRD §3.2: "Submitting an item for review — a transition into `IN_REVIEW`
        from either `DRAFT` or `REVISION_REQUESTED`, optionally annotated with a
        `revision_note` — is reserved to the item's own author."

        PRD §3.2: "First, `approver_user_ids` is reset to the empty list,
        unconditionally: approvals never carry across a round."

        Design: Difficulty/non_linear_state_machine/item_revision_loop_bumps_review_round_and_discards_partial_approvals
        """
        item_id, first_round, _banked = _item_with_one_banked_approval(api)
        validate_success(api.review_item(
            item_id, f.review_item_payload("REVISE", review_note="stem is double-barrelled"),
            REVIEWER_2), 200)

        resubmitted = validate_success(api.submit_item_for_review(
            item_id, f.submit_item_payload(revision_note="stem rewritten"), AUTHOR), 200)

        assert resubmitted["status"] == "IN_REVIEW"
        assert resubmitted["review_round"] == first_round + 1
        assert resubmitted["approver_user_ids"] == []

    def test_two_fresh_approvals_are_needed_after_a_revision(self, api):
        """The approval banked in round one does not survive, so the same reviewer
        may approve again and only the second fresh approval promotes the item.

        PRD §3.2: "an item that had already collected one approval before revision
        must collect two fresh ones afterwards".

        PRD §3.2: "The second `APPROVE`, which is by definition the one where
        `approver_user_ids` held exactly one entry before the call, appends the
        second user so the list length becomes 2 and moves the item `IN_REVIEW →
        APPROVED`."

        Design: Difficulty/non_linear_state_machine/item_revision_loop_bumps_review_round_and_discards_partial_approvals
        """
        item_id, _first_round, _banked = _item_with_one_banked_approval(api)
        validate_success(api.review_item(
            item_id, f.review_item_payload("REVISE", review_note="stem is double-barrelled"),
            REVIEWER_2), 200)
        validate_success(api.submit_item_for_review(
            item_id, f.submit_item_payload(revision_note="stem rewritten"), AUTHOR), 200)

        first_again = validate_success(api.review_item(
            item_id, f.review_item_payload("APPROVE", review_note="round two first approval"),
            REVIEWER_1), 200)
        second = validate_success(api.review_item(
            item_id, f.review_item_payload("APPROVE", review_note="round two second approval"),
            REVIEWER_2), 200)

        assert first_again["status"] == "IN_REVIEW"
        assert first_again["approver_user_ids"] == [ITEM_REVIEWER_1_ID]
        assert second["status"] == "APPROVED"
        assert second["approver_user_ids"] == [ITEM_REVIEWER_1_ID, ITEM_REVIEWER_2_ID]
        assert second["author_user_id"] == ITEM_AUTHOR_ID
        assert second["stat_basis_applied"] == "INSUFFICIENT_DATA"
        assert second["p_value"] is None
