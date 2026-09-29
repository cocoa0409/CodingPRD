"""
The placement-team decision record: its revision cycle, the documentation
completeness gate at submission, and the state gate on revision.
"""

from prd_bench_local_runner.testing import (
    get_success_data,
    validate_error,
    validate_success,
)

from test_helpers import factories as f
from test_helpers.api_errors import (
    ERR_INVALID_STATE_TRANSITION,
    ERR_LRE_DOCUMENTATION_INCOMPLETE,
    ERR_MAX_ROUNDS_EXCEEDED,
)
from test_helpers.fixtures import (
    make_student,
    read_decision,
    read_student,
    reset_clock,
)
from test_helpers.test_users import (
    COORDINATOR_HEADERS,
    TEAM_CHAIR_HEADERS,
    USER_TEAM_CHAIR,
)

SHORT_JUSTIFICATION = "Team met and discussed options."

REVISED_JUSTIFICATION = (
    "A four-week diagnostic placement in the district separate class produced "
    "regression on two of three communication goals and three restraint incidents."
)


def _draft_decision(api, **overrides):
    """One student and one DRAFT decision authored by the coordinator."""
    reset_clock(api)
    student = make_student(api)
    decision = get_success_data(
        api.create_placement_decision(
            f.placement_decision_payload(student["id"], **overrides),
            COORDINATOR_HEADERS,
        ),
        201,
    )
    return student, decision


def _decision_at_revision_round_three(api):
    """Round-trip a decision three times, leaving it in TEAM_REVIEW at round 3."""
    student, decision = _draft_decision(api)
    decision_id = decision["id"]
    for round_index in range(1, 4):
        get_success_data(
            api.submit_placement_decision(decision_id, COORDINATOR_HEADERS)
        )
        returned = get_success_data(
            api.return_decision_for_revision(
                decision_id,
                f.reviewer_notes_payload(f"Round {round_index} rework."),
                TEAM_CHAIR_HEADERS,
            )
        )
        assert returned["revision_round"] == round_index
    submitted = get_success_data(
        api.submit_placement_decision(decision_id, COORDINATOR_HEADERS)
    )
    assert submitted["status"] == "TEAM_REVIEW"
    assert submitted["revision_round"] == 3
    return student, decision_id


class TestDecisionRevisionCycleBound:
    def test_fourth_return_for_revision_is_refused_and_writes_nothing(self, api):
        """
        A fourth return on a decision already at revision_round three is refused,
        and the refusal leaves the round counter and the status untouched.

        PRD: "A fourth attempt to return the same record is refused with `ERR_MAX_ROUNDS_EXCEEDED`."

        Design: Difficulty/non_linear_state_machine/placement_decision_revision_cycle_bounded_at_three_rounds
        """
        _, decision_id = _decision_at_revision_round_three(api)

        response = api.return_decision_for_revision(
            decision_id,
            f.reviewer_notes_payload("Round 4 attempt."),
            TEAM_CHAIR_HEADERS,
        )
        validate_error(response, ERR_MAX_ROUNDS_EXCEEDED, 409)

        after = read_decision(api, decision_id)
        assert after["revision_round"] == 3
        assert after["status"] == "TEAM_REVIEW"

    def test_row_is_not_wedged_and_still_approves_after_the_refused_return(self, api):
        """
        The bounded review loop does not strand the record: after the fourth return
        is refused the same record still approves out of TEAM_REVIEW.

        PRD: "*Approving* moves the record `TEAM_REVIEW → APPROVED` and is terminal."

        Design: Difficulty/non_linear_state_machine/placement_decision_revision_cycle_bounded_at_three_rounds
        """
        student, decision_id = _decision_at_revision_round_three(api)
        validate_error(
            api.return_decision_for_revision(
                decision_id,
                f.reviewer_notes_payload("Round 4 attempt."),
                TEAM_CHAIR_HEADERS,
            ),
            ERR_MAX_ROUNDS_EXCEEDED,
            409,
        )

        approved = validate_success(
            api.approve_placement_decision(
                decision_id, TEAM_CHAIR_HEADERS, f.reviewer_notes_payload()
            )
        )
        assert approved["status"] == "APPROVED"
        assert approved["decided_at"] is not None
        assert approved["reviewed_by_user_id"] == USER_TEAM_CHAIR
        assert approved["revision_round"] == 3
        assert read_student(api, student["id"])["placement_status"] == "DECISION_APPROVED"


class TestDecisionDocumentationGate:
    def test_short_lre_justification_stores_but_fails_at_submission(self, api):
        """
        A thirty-one character justification is accepted at creation and refused only
        when the DRAFT to TEAM_REVIEW transition is attempted.

        PRD: "Submission is where the documentation completeness gate bites: the `lre_justification`, once leading and trailing whitespace is stripped, must be at least 40 characters long; `continuum_options_considered` must hold at least three entries, each with a non-empty `setting` and a non-empty `rejected_reason`; and `recommended_placement_type` must be set."

        Design: Corner/state_machines/decision_submit_rejected_when_lre_justification_below_forty_characters
        """
        reset_clock(api)
        student = make_student(api)
        created = validate_success(
            api.create_placement_decision(
                f.placement_decision_payload(
                    student["id"], lre_justification=SHORT_JUSTIFICATION
                ),
                COORDINATOR_HEADERS,
            ),
            201,
        )
        assert len(created["continuum_options_considered"]) == 3

        response = api.submit_placement_decision(created["id"], COORDINATOR_HEADERS)
        validate_error(response, ERR_LRE_DOCUMENTATION_INCOMPLETE, 409)

        after = read_decision(api, created["id"])
        assert after["status"] == "DRAFT"
        assert after["submitted_at"] is None
        assert after["revision_round"] == 0
        assert after["version"] == 1

    def test_two_continuum_options_is_one_short_of_the_documented_floor(self, api):
        """
        Two rejected continuum options fail the count arm of the same gate even
        though the justification is well over the length floor, and the stored array
        is not rewritten by the refusal.

        PRD: "Submission is where the documentation completeness gate bites: the `lre_justification`, once leading and trailing whitespace is stripped, must be at least 40 characters long; `continuum_options_considered` must hold at least three entries, each with a non-empty `setting` and a non-empty `rejected_reason`; and `recommended_placement_type` must be set."

        Design: Corner/validations/decision_submit_with_only_two_continuum_options_rejected
        """
        two_options = [dict(o) for o in f.DAY_CONTINUUM_OPTIONS[:2]]
        student, decision = _draft_decision(api, continuum_options_considered=two_options)
        assert len(f.DAY_LRE_JUSTIFICATION.strip()) > 40

        response = api.submit_placement_decision(decision["id"], COORDINATOR_HEADERS)
        validate_error(response, ERR_LRE_DOCUMENTATION_INCOMPLETE, 409)

        after = read_decision(api, decision["id"])
        assert after["status"] == "DRAFT"
        assert after["submitted_at"] is None
        assert after["continuum_options_considered"] == two_options


class TestDecisionStateGates:
    def test_replayed_submit_on_a_record_under_review_is_refused(self, api):
        """
        TEAM_REVIEW carries no submit edge, so replaying the submission is a state
        error rather than an absorbed no-op, and it bumps nothing.

        PRD: "This rung covers terminal-state lockdown and any second invocation of a transition already taken."

        Design: Corner/state_machines/duplicate_submit_on_team_review_decision_rejected
        """
        _, decision = _draft_decision(api)
        first = validate_success(
            api.submit_placement_decision(decision["id"], COORDINATOR_HEADERS)
        )
        assert first["status"] == "TEAM_REVIEW"
        assert first["version"] == 2

        response = api.submit_placement_decision(decision["id"], COORDINATOR_HEADERS)
        validate_error(response, ERR_INVALID_STATE_TRANSITION, 409)

        after = read_decision(api, decision["id"])
        assert after["status"] == "TEAM_REVIEW"
        assert after["revision_round"] == 0
        assert after["version"] == 2

    def test_patch_walks_the_editable_states_and_is_refused_from_the_others(self, api):
        """
        Revision is available from DRAFT and from RETURNED_FOR_REVISION, refused from
        TEAM_REVIEW and from the terminal APPROVED state, and each accepted revision
        bumps the version by exactly one while each refusal bumps nothing.

        PRD: "Revision is refused once the record has entered `TEAM_REVIEW`, and refused permanently once it reaches the terminal `APPROVED` state — in both cases with `ERR_INVALID_STATE_TRANSITION`."

        Design: Corner/endpoints/placement_decision_patch_revises_a_draft_and_is_rejected_from_team_review
        """
        student, decision = _draft_decision(api)
        decision_id = decision["id"]
        assert decision["version"] == 1

        first = validate_success(
            api.patch_placement_decision(
                decision_id,
                {"lre_justification": REVISED_JUSTIFICATION},
                COORDINATOR_HEADERS,
            )
        )
        assert first["lre_justification"] == REVISED_JUSTIFICATION
        assert first["status"] == "DRAFT"
        assert first["recommended_placement_type"] == "DAY"
        assert first["version"] == 2

        residential_options = [dict(o) for o in f.RESIDENTIAL_CONTINUUM_OPTIONS]
        second = validate_success(
            api.patch_placement_decision(
                decision_id,
                {
                    "recommended_placement_type": "RESIDENTIAL",
                    "continuum_options_considered": residential_options,
                },
                TEAM_CHAIR_HEADERS,
            )
        )
        assert second["recommended_placement_type"] == "RESIDENTIAL"
        assert len(second["continuum_options_considered"]) == 3
        assert second["version"] == 3

        submitted = validate_success(
            api.submit_placement_decision(decision_id, COORDINATOR_HEADERS)
        )
        assert submitted["status"] == "TEAM_REVIEW"
        assert submitted["submitted_at"] is not None
        assert submitted["version"] == 4

        validate_error(
            api.patch_placement_decision(
                decision_id,
                {"lre_justification": f.RESIDENTIAL_LRE_JUSTIFICATION},
                COORDINATOR_HEADERS,
            ),
            ERR_INVALID_STATE_TRANSITION,
            409,
        )

        returned = validate_success(
            api.return_decision_for_revision(
                decision_id,
                f.reviewer_notes_payload("Document the residential nursing rationale."),
                TEAM_CHAIR_HEADERS,
            )
        )
        assert returned["status"] == "RETURNED_FOR_REVISION"
        assert returned["revision_round"] == 1
        assert returned["reviewed_by_user_id"] == USER_TEAM_CHAIR
        assert returned["version"] == 5

        revised = validate_success(
            api.patch_placement_decision(
                decision_id,
                {"lre_justification": f.RESIDENTIAL_LRE_JUSTIFICATION},
                COORDINATOR_HEADERS,
            )
        )
        assert revised["status"] == "RETURNED_FOR_REVISION"
        assert revised["version"] == 6

        resubmitted = validate_success(
            api.submit_placement_decision(decision_id, COORDINATOR_HEADERS)
        )
        assert resubmitted["status"] == "TEAM_REVIEW"
        assert resubmitted["revision_round"] == 1
        assert resubmitted["version"] == 7

        approved = validate_success(
            api.approve_placement_decision(
                decision_id,
                TEAM_CHAIR_HEADERS,
                f.reviewer_notes_payload("Residential placement authorized."),
            )
        )
        assert approved["status"] == "APPROVED"
        assert approved["decided_at"] is not None
        assert approved["version"] == 8

        validate_error(
            api.patch_placement_decision(
                decision_id, {"recommended_placement_type": "DAY"}, COORDINATOR_HEADERS
            ),
            ERR_INVALID_STATE_TRANSITION,
            409,
        )

        after = read_decision(api, decision_id)
        assert after["recommended_placement_type"] == "RESIDENTIAL"
        assert after["version"] == 8
        assert read_student(api, student["id"])["placement_status"] == "DECISION_APPROVED"
