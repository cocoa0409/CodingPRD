"""Declared transitions, refused transitions, and a terminal state that stays shut."""

from test_helpers import ApiErrorId
from test_helpers import assertions as ax
from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers import validate_error, validate_success
from test_helpers.test_users import (
    ITEM_AUTHOR_ID,
    ITEM_REVIEWER_1_ID,
    ITEM_REVIEWER_2_ID,
    make_item_specialist_headers,
)

AUTHOR = make_item_specialist_headers(ITEM_AUTHOR_ID)
REVIEWER_ONE = make_item_specialist_headers(ITEM_REVIEWER_1_ID)
REVIEWER_TWO = make_item_specialist_headers(ITEM_REVIEWER_2_ID)


class TestProgramActivationTransition:
    """DRAFT leaves only through the activate call, and only once."""

    def test_activation_moves_draft_to_active_and_advances_the_version(self, api):
        """The one declared exit from DRAFT answers 200, sets ACTIVE, moves the version
        from 1 to 2, and leaves the inputs and the derived counters where they were.

        PRD §3.1: "Activation is the `ProgramAdmin`'s gate, optionally annotated with an
        `activation_note`, and it moves the program `DRAFT → ACTIVE`."

        PRD §2.10: "Operations that modify an existing resource — every action sub-path,
        the logical-clock capability, and the maintenance run — answer with **HTTP 200**."

        PRD §2.4: "`version` is an integer that starts at 1 when the resource is created
        and increments by 1 on every mutation of that record, including mutations reached
        indirectly through a cascade."

        Design: Corner/state_machines/program_activation_moves_draft_to_active_and_bumps_the_version
        """
        program = fx.create_program(api)
        assert program["status"] == "DRAFT"
        assert program["version"] == 1

        activated = validate_success(api.activate_program(
            program["id"], f.activate_program_payload(activation_note="board approved"),
            fx.PROGRAM_ADMIN), 200)

        assert activated["status"] == "ACTIVE"
        assert activated["version"] == 2
        assert activated["credential_code"] == "CPX"
        assert activated["form_length"] == 1
        assert activated["operational_item_count"] == 0
        assert activated["certificants_issued_count"] == 0
        ax.assert_certification_program(activated, expected_version=2)

    def test_a_second_activation_is_refused_and_does_not_bump_the_version_again(self, api):
        """ACTIVE has no self-loop: the repeat call is rejected rather than treated as
        idempotent, and the version stops at 2.

        PRD §3.1: "The program must currently be `DRAFT` — otherwise `ERR_INVALID_STATE`
        — and the blueprint weights are re-checked at this moment, so a program whose
        `domain_specs` no longer sum to exactly 100 is refused with
        `ERR_BLUEPRINT_WEIGHTS_INVALID` even though it was accepted at creation."

        Design: Corner/state_machines/program_activation_repeated_on_an_active_program_returns_invalid_state
        """
        program = fx.active_program(api)
        assert program["version"] == 2

        refused = api.activate_program(
            program["id"], f.activate_program_payload(activation_note="second attempt"),
            fx.PROGRAM_ADMIN)

        validate_error(refused, ApiErrorId.ERR_INVALID_STATE.value, 409)
        unchanged = fx.read_program(api, program["id"])
        assert unchanged["status"] == "ACTIVE"
        assert unchanged["version"] == 2


class TestItemInitialState:
    """A fresh item sits in the declared initial state with nothing computed."""

    def test_a_new_item_is_draft_with_no_approvals_and_no_statistics(self, api):
        """The accumulators are zero, both statistics are null, the applied basis reads
        INSUFFICIENT_DATA, and no flag has been raised.

        PRD §3.2: "The new item's `status` is `DRAFT`, its `approver_user_ids` list is
        empty, its `review_round` starts at 1, all twelve of its response accumulators
        start at 0, and its `stat_basis_applied` starts at `INSUFFICIENT_DATA` with both
        `p_value` and `discrimination_index` null."

        PRD §3.3: "If `stat_basis_applied` is `INSUFFICIENT_DATA`, `flag_reason` is null
        — unknown is not the same as good, but it is not a flag either."

        Design: Corner/state_machines/item_creation_starts_in_draft_with_no_approvals_and_no_statistics
        """
        program = fx.active_program(api)

        item = validate_success(api.create_item(
            f.create_item_payload(program["id"], cognitive_level="RECALL",
                                  stem="Fresh item"), AUTHOR), 201)

        assert item["status"] == "DRAFT"
        assert item["approver_user_ids"] == []
        assert item["review_round"] == 1
        assert item["flag_reason"] is None
        assert item["pretest_response_count"] == 0
        assert item["operational_response_count"] == 0
        assert item["p_value"] is None
        assert item["discrimination_index"] is None
        assert item["stat_basis_applied"] == "INSUFFICIENT_DATA"
        ax.assert_item(item)


class TestRejectedItemIsTerminal:
    """Nothing leaves REJECTED — not a rescuing approval, not a resubmission."""

    def test_neither_a_further_review_nor_a_resubmission_reopens_a_rejected_item(
            self, api):
        """Both attempts are refused on state, the approver list stays empty, and the
        round counter stops advancing.

        PRD §3.2: "`REJECT` moves the item `IN_REVIEW → REJECTED`, which is terminal, and
        a `REJECTED` item may never appear among the item identifiers of a newly assembled
        form — an attempt to cite one is refused with `ERR_ITEM_NOT_ELIGIBLE_FOR_FORM`."

        PRD §3.2: "Submitting an item for review — a transition into `IN_REVIEW` from
        either `DRAFT` or `REVISION_REQUESTED`, optionally annotated with a
        `revision_note` — is reserved to the item's own author."

        Design: Corner/state_machines/item_review_after_rejection_is_locked_out_of_the_terminal_state
        """
        program = fx.active_program(api)
        item = fx.item_in_review(api, program["id"], stem="Doomed item")
        rejected = validate_success(api.review_item(
            item["id"], f.review_item_payload("REJECT", review_note="off blueprint"),
            REVIEWER_ONE), 200)
        assert rejected["status"] == "REJECTED"
        round_at_rejection = rejected["review_round"]

        refused_review = api.review_item(
            item["id"], f.review_item_payload("APPROVE", review_note="rescue attempt"),
            REVIEWER_TWO)
        refused_submit = api.submit_item_for_review(
            item["id"], f.submit_item_payload(revision_note="resubmission attempt"),
            AUTHOR)

        validate_error(refused_review, ApiErrorId.ERR_INVALID_STATE.value, 409)
        validate_error(refused_submit, ApiErrorId.ERR_INVALID_STATE.value, 409)
        unchanged = fx.read_item(api, item["id"])
        assert unchanged["status"] == "REJECTED"
        assert unchanged["approver_user_ids"] == []
        assert unchanged["review_round"] == round_at_rejection
