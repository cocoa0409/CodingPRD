"""Non-linear lifecycles: the bounded revision loop, the two independent candidate
status dimensions, and the three-way committee fork."""

from test_helpers import (
    ApiErrorId,
    MEMBER_1_USER_ID,
    MEMBER_2_USER_ID,
    MEMBER_3_USER_ID,
    TEST_USERS,
    api_client,
    assert_guarantee_budget_identity,
    assert_money_equals,
    cast_vote,
    clear_conflict_check,
    finalize_offer,
    open_conflict_check,
    read_assessment,
    read_candidate,
    read_offer,
    read_practice_group,
    read_questionnaire,
    request_revision_payload,
    setup_assessed_candidate,
    setup_offer_in_committee_review,
    setup_questionnaire_under_review,
    validate_error,
    validate_success,
    withdraw_candidate_payload,
)

COORDINATOR = TEST_USERS["recruiting_coordinator_headers"]


def test_a_fourth_revision_request_is_refused_at_the_loop_cap():
    """The loop is capped: revisions may be requested only while `revision_round` is
    strictly less than 3, so the third revision is the last one permitted and a fourth
    attempt is refused with `ERR_REVISION_LIMIT_EXCEEDED`.

    Design: Difficulty/non_linear_state_machine/questionnaire_revision_loop_is_bounded_at_three_rounds
    """
    ctx = _setup_questionnaire_at_the_revision_cap()

    response = api_client.request_revision_questionnaire(
        ctx["questionnaire"]["id"],
        request_revision_payload(revision_note="Round 4: one more pass."),
        COORDINATOR,
    )
    validate_error(response, ApiErrorId.ERR_REVISION_LIMIT_EXCEEDED.value)

    questionnaire = read_questionnaire(ctx["questionnaire"]["id"])
    assert questionnaire["revision_round"] == 3
    assert questionnaire["status"] == "UNDER_REVIEW"
    assert questionnaire["entry_count"] == 1

    candidate = read_candidate(ctx["candidate"]["id"])
    assert candidate["pipeline_status"] == "DILIGENCE"


def test_the_revision_loop_closes_on_itself_three_times_before_the_cap():
    """The LPQ's lifecycle contains a **bounded revision loop**:
    `SUBMITTED → UNDER_REVIEW → REVISION_REQUESTED → SUBMITTED`, closing back on
    itself.
    From `UNDER_REVIEW` the coordinator may send the LPQ back, supplying a
    `revision_note`, which moves it `UNDER_REVIEW → REVISION_REQUESTED`, increments
    `revision_round` by 1, and makes the client book mutable again — while the LPQ sits
    in `REVISION_REQUESTED`, entries may be created and soft-deleted.

    Design: Difficulty/non_linear_state_machine/questionnaire_revision_loop_is_bounded_at_three_rounds
    """
    ctx = setup_questionnaire_under_review("SLIM")

    for expected_round in (1, 2, 3):
        sent_back = validate_success(
            api_client.request_revision_questionnaire(
                ctx["questionnaire"]["id"], request_revision_payload(), COORDINATOR
            )
        )
        assert sent_back["status"] == "REVISION_REQUESTED"
        assert sent_back["revision_round"] == expected_round

        resubmitted = validate_success(
            api_client.submit_questionnaire(
                ctx["questionnaire"]["id"], ctx["candidate_headers"]
            )
        )
        assert resubmitted["status"] == "SUBMITTED"
        assert resubmitted["revision_round"] == expected_round

        ctx["questionnaire"] = validate_success(
            api_client.start_review_questionnaire(
                ctx["questionnaire"]["id"], COORDINATOR
            )
        )
        assert ctx["questionnaire"]["status"] == "UNDER_REVIEW"


def test_clearing_the_last_check_moves_only_the_clearance_dimension():
    """A candidate record is the pipeline's spine, and unusually it tracks **two
    independent status dimensions on the same row**.
    The candidate becomes `IN_PROGRESS → CLEARED` at the moment a check status change
    leaves zero non-cleared checks — that is, when every check on every `ACTIVE` entry
    of the candidate's questionnaire has `status` `CLEAR`, and the questionnaire's
    `entry_count` is at least 1.

    Design: Difficulty/non_linear_state_machine/candidate_pipeline_and_clearance_dimensions_advance_independently
    """
    ctx = setup_assessed_candidate("SLIM")
    open_conflict_check(ctx, "Northwind Holdings")

    before = read_candidate(ctx["candidate"]["id"])
    assert before["clearance_status"] == "IN_PROGRESS"
    assert before["pipeline_status"] == "DILIGENCE"

    clear_conflict_check(ctx, "Northwind Holdings")

    after = read_candidate(ctx["candidate"]["id"])
    assert after["clearance_status"] == "CLEARED"
    assert after["pipeline_status"] == "DILIGENCE"


def test_withdrawal_moves_only_the_pipeline_dimension_and_leaves_clearance_intact():
    """Neither dimension's transitions read the other's current value except where this
    document says so explicitly, and the clearance dimension is entirely derived — it is
    recomputed from the candidate's conflicts checks and is never set directly by a
    caller.
    **Hop 2** — every `LateralQuestionnaire` of that candidate whose `status` is not
    already `ACCEPTED` or `ABANDONED` becomes `ABANDONED`, whichever of `DRAFT`,
    `SUBMITTED`, `UNDER_REVIEW`, or `REVISION_REQUESTED` it held.

    Design: Difficulty/non_linear_state_machine/candidate_pipeline_and_clearance_dimensions_advance_independently
    """
    ctx = setup_assessed_candidate("SLIM")
    check = open_conflict_check(ctx, "Northwind Holdings")
    clear_conflict_check(ctx, "Northwind Holdings")

    withdrawn = validate_success(
        api_client.withdraw_candidate(
            ctx["candidate"]["id"], withdraw_candidate_payload(), COORDINATOR
        )
    )

    assert withdrawn["pipeline_status"] == "WITHDRAWN"
    assert withdrawn["clearance_status"] == "CLEARED"

    assert validate_success(
        api_client.get_conflict_check(check["id"], TEST_USERS["conflicts_counsel_headers"])
    )["status"] == "CLEAR"
    assert read_questionnaire(ctx["questionnaire"]["id"])["status"] == "ABANDONED"
    assert read_assessment(ctx["assessment"]["id"])["status"] == "CURRENT"


def test_the_rejection_branch_releases_the_reservation_and_terminates_the_candidate():
    """On rejection the offer moves `COMMITTEE_REVIEW → REJECTED`, the group's
    `reserved_guarantee_budget_usd` is reduced by `guaranteed_comp_usd` and its
    `available_guarantee_budget_usd` increased by the same amount, the candidate's
    `pipeline_status` becomes `DECLINED`, and `open_offer_id` is cleared to null.

    Design: Difficulty/non_linear_state_machine/offer_committee_review_fork_has_divergent_side_effect_sets
    """
    ctx = setup_offer_in_committee_review("SLIM")

    group_mid = read_practice_group(ctx["practice_group"]["id"])
    assert_money_equals(
        group_mid["reserved_guarantee_budget_usd"], 500000.00, "reserved while in review"
    )
    assert_money_equals(
        group_mid["available_guarantee_budget_usd"], 4500000.00, "available while in review"
    )

    cast_vote(ctx, MEMBER_1_USER_ID, "APPROVE")
    cast_vote(ctx, MEMBER_2_USER_ID, "REJECT")
    cast_vote(ctx, MEMBER_3_USER_ID, "REJECT")

    finalized = finalize_offer(ctx)

    assert finalized["status"] == "REJECTED"
    assert finalized["active_vote_count"] == 3
    assert finalized["votes_cast_total"] == 3
    assert finalized["round_number"] == 1

    candidate = read_candidate(ctx["candidate"]["id"])
    assert candidate["pipeline_status"] == "DECLINED"
    assert candidate["open_offer_id"] is None

    group = read_practice_group(ctx["practice_group"]["id"])
    assert_money_equals(group["reserved_guarantee_budget_usd"], 0.00, "reserved")
    assert_money_equals(group["available_guarantee_budget_usd"], 5000000.00, "available")
    assert_money_equals(group["committed_guarantee_total_usd"], 0.00, "committed")
    assert_guarantee_budget_identity(group)


def test_the_approval_branch_keeps_the_guarantee_reserved_without_committing_it():
    """On approval the offer moves `COMMITTEE_REVIEW → APPROVED` and the candidate moves
    `DILIGENCE → OFFER_OUT` with the approved offer's identifier recorded in
    `open_offer_id`; the guarantee stays **reserved** and is not yet committed.
    Rejection releases the money and terminates the candidate; approval does neither.

    Design: Difficulty/non_linear_state_machine/offer_committee_review_fork_has_divergent_side_effect_sets
    """
    ctx = setup_offer_in_committee_review("SLIM")

    cast_vote(ctx, MEMBER_1_USER_ID, "APPROVE")
    cast_vote(ctx, MEMBER_2_USER_ID, "APPROVE")

    finalized = finalize_offer(ctx)

    assert finalized["status"] == "APPROVED"
    assert read_offer(finalized["id"])["round_number"] == 1

    candidate = read_candidate(ctx["candidate"]["id"])
    assert candidate["pipeline_status"] == "OFFER_OUT"
    assert candidate["open_offer_id"] == finalized["id"]

    group = read_practice_group(ctx["practice_group"]["id"])
    assert_money_equals(group["reserved_guarantee_budget_usd"], 500000.00, "reserved")
    assert_money_equals(group["available_guarantee_budget_usd"], 4500000.00, "available")
    assert_money_equals(group["committed_guarantee_total_usd"], 0.00, "committed")
    assert_guarantee_budget_identity(group)


# ----------------------------------------------------------------------
# Local scenario glue
# ----------------------------------------------------------------------


def _setup_questionnaire_at_the_revision_cap():
    """Traverse the revision loop three times, landing back in UNDER_REVIEW with
    revision_round 3."""
    ctx = setup_questionnaire_under_review("SLIM")
    for _round in (1, 2, 3):
        validate_success(
            api_client.request_revision_questionnaire(
                ctx["questionnaire"]["id"], request_revision_payload(), COORDINATOR
            )
        )
        validate_success(
            api_client.submit_questionnaire(
                ctx["questionnaire"]["id"], ctx["candidate_headers"]
            )
        )
        ctx["questionnaire"] = validate_success(
            api_client.start_review_questionnaire(
                ctx["questionnaire"]["id"], COORDINATOR
            )
        )
    return ctx
