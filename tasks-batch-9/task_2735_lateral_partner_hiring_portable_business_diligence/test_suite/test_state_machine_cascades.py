"""Multi-hop state machine behaviour: the clearance cycle, the finalization fork, the
negotiation loop, the withdrawal cascade and the conditional abandonment cascade."""

from test_helpers import (
    ApiErrorId,
    MEMBER_1_USER_ID,
    MEMBER_2_USER_ID,
    TEST_USERS,
    abandon_plan_payload,
    add_introduction,
    api_client,
    assert_money_equals,
    cast_vote,
    clear_conflict_check_payload,
    counter_offer_payload,
    create_conflict_check_payload,
    draft_plan,
    make_committee_chair_headers,
    read_assessment,
    read_candidate,
    read_conflict_check,
    read_integration_plan,
    read_offer,
    read_practice_group,
    read_questionnaire,
    redraft_offer_payload,
    setup_active_plan,
    setup_approved_offer,
    setup_cleared_candidate,
    setup_offer_in_committee_review,
    validate_error,
    validate_paginated,
    validate_success,
    withdraw_candidate_payload,
)

COORDINATOR = TEST_USERS["recruiting_coordinator_headers"]
COUNSEL = TEST_USERS["conflicts_counsel_headers"]
CHAIR = make_committee_chair_headers("user-chair-1")
PEER_CHAIR = make_committee_chair_headers("user-chair-2")


def test_a_fresh_check_reopens_clearance_and_clearing_it_closes_the_cycle_again():
    """Conversely, opening a fresh check after clearance was already complete moves the
    candidate `CLEARED → IN_PROGRESS`, which applies when at least one check on those
    entries is `PENDING` or `WAIVER_PENDING` and none is `BLOCKED`.
    The candidate becomes `IN_PROGRESS → CLEARED` at the moment a check status change
    leaves zero non-cleared checks — that is, when every check on every `ACTIVE` entry of
    the candidate's questionnaire has `status` `CLEAR`, and the questionnaire's
    `entry_count` is at least 1.

    Design: Corner/state_machines/clearance_dimension_cycles_back_to_cleared_after_a_new_check
    """
    ctx = setup_cleared_candidate("SLIM")
    first_check_id = ctx["conflict_checks"]["Northwind Holdings"]["id"]
    entry_id = ctx["entries"]["Northwind Holdings"]["id"]
    assert read_candidate(ctx["candidate"]["id"])["clearance_status"] == "CLEARED"

    second = validate_success(
        api_client.create_conflict_check(
            entry_id,
            create_conflict_check_payload(
                adverse_party_name="Orion Capital Partners",
                affected_matter_types=["M_AND_A"],
                severity="IMPUTED",
            ),
            COUNSEL,
        ),
        expected_status=201,
    )
    assert read_candidate(ctx["candidate"]["id"])["clearance_status"] == "IN_PROGRESS"

    validate_success(
        api_client.clear_conflict_check(
            second["id"],
            clear_conflict_check_payload(
                resolution_note="Imputed only; the Orion matter closed in 2024."
            ),
            COUNSEL,
        )
    )

    candidate = read_candidate(ctx["candidate"]["id"])
    assert candidate["clearance_status"] == "CLEARED"
    assert candidate["pipeline_status"] == "DILIGENCE"
    assert read_conflict_check(first_check_id)["status"] == "CLEAR"
    assert read_conflict_check(second["id"])["status"] == "CLEAR"

    _rows, meta = validate_paginated(
        api_client.list_conflict_checks(
            COUNSEL, params={"client_book_entry_id": entry_id}
        )
    )
    assert meta["total_count"] == 2


def test_the_drafting_chair_is_barred_from_closing_the_tally_but_a_peer_may():
    """The chair whose `X-User-ID` was recorded as `created_by_user_id` when an offer was
    drafted may not be the one who closes voting on it; that attempt is rejected with
    `ERR_OFFER_CREATOR_CANNOT_FINALIZE` (HTTP 409).
    On approval the offer moves `COMMITTEE_REVIEW → APPROVED` and the candidate moves
    `DILIGENCE → OFFER_OUT` with the approved offer's identifier recorded in
    `open_offer_id`; the guarantee stays **reserved** and is not yet committed.

    Design: Corner/state_machines/offer_finalize_by_its_own_creator_rejected
    """
    ctx = setup_offer_in_committee_review("SLIM", eligible_voter_count=3)
    assert ctx["offer"]["created_by_user_id"] == "user-chair-1"
    cast_vote(ctx, MEMBER_1_USER_ID, "APPROVE")
    cast_vote(ctx, MEMBER_2_USER_ID, "APPROVE")

    by_creator = api_client.finalize_offer(ctx["offer"]["id"], CHAIR)
    validate_error(by_creator, ApiErrorId.ERR_OFFER_CREATOR_CANNOT_FINALIZE.value)
    assert read_offer(ctx["offer"]["id"])["status"] == "COMMITTEE_REVIEW"

    approved = validate_success(
        api_client.finalize_offer(ctx["offer"]["id"], PEER_CHAIR)
    )
    assert approved["status"] == "APPROVED"
    assert approved["active_vote_count"] == 2
    assert approved["votes_cast_total"] == 2

    candidate = read_candidate(ctx["candidate"]["id"])
    assert candidate["pipeline_status"] == "OFFER_OUT"
    assert candidate["open_offer_id"] == ctx["offer"]["id"]

    group = read_practice_group(ctx["practice_group"]["id"])
    assert_money_equals(
        group["reserved_guarantee_budget_usd"], 500000.00, "reserved_guarantee_budget_usd"
    )
    assert_money_equals(
        group["committed_guarantee_total_usd"], 0.00, "committed_guarantee_total_usd"
    )


def test_the_counter_loop_returns_the_offer_to_drafted_and_reprices_every_economic():
    """A counter is permitted from `COMMITTEE_REVIEW` and from `REPRICE_REQUIRED`, and
    both edges move the offer to `COUNTER_REQUESTED` with an identical side-effect set:
    every `ACTIVE` vote on the offer becomes `VOIDED`, `active_vote_count` is set to `0`
    and `voided_vote_count` grows by the number just voided while `votes_cast_total` stays
    exactly where it was; the group's `reserved_guarantee_budget_usd` is reduced by
    `guaranteed_comp_usd` and `available_guarantee_budget_usd` increased by the same
    amount; `round_number` is incremented by 1; and `eligible_voter_count` is reset to
    null, so the next submission must re-declare the roll.

    Design: Corner/state_machines/offer_counter_loop_returns_to_drafted_and_recomputes_all_six_economics
    """
    ctx = setup_offer_in_committee_review("SLIM", eligible_voter_count=3)
    cast_vote(ctx, MEMBER_1_USER_ID, "APPROVE")
    cast_vote(ctx, MEMBER_2_USER_ID, "APPROVE")

    validate_success(
        api_client.counter_offer(
            ctx["offer"]["id"],
            counter_offer_payload(
                counter_note="Committee wants the guarantee at 400000.00."
            ),
            CHAIR,
        )
    )

    mid = read_practice_group(ctx["practice_group"]["id"])
    assert_money_equals(mid["reserved_guarantee_budget_usd"], 0.00, "reserved mid")
    assert_money_equals(
        mid["available_guarantee_budget_usd"], 5000000.00, "available mid"
    )

    redrafted = validate_success(
        api_client.redraft_offer(
            ctx["offer"]["id"],
            redraft_offer_payload(
                guaranteed_comp_usd=400000.00, signing_bonus_usd=40000.00
            ),
            CHAIR,
        )
    )

    assert redrafted["status"] == "DRAFTED"
    assert redrafted["round_number"] == 2
    assert redrafted["eligible_voter_count"] is None
    assert redrafted["active_vote_count"] == 0
    assert redrafted["voided_vote_count"] == 2
    assert redrafted["votes_cast_total"] == 2
    assert_money_equals(redrafted["guaranteed_comp_usd"], 400000.00, "guaranteed")
    assert_money_equals(
        redrafted["adjusted_portable_total_snapshot_usd"], 1078650.00, "snapshot"
    )
    assert_money_equals(
        redrafted["expected_contribution_usd"], 1053981.27, "expected_contribution_usd"
    )
    assert_money_equals(
        redrafted["total_first_year_comp_usd"], 440000.00, "total_first_year_comp_usd"
    )
    assert_money_equals(
        redrafted["search_fee_amount_usd"], 110000.00, "search_fee_amount_usd"
    )
    assert_money_equals(
        redrafted["integration_cost_total_usd"], 212600.00, "integration_cost_total_usd"
    )
    assert_money_equals(
        redrafted["net_first_year_economics_usd"],
        401381.27,
        "net_first_year_economics_usd",
    )
    assert_money_equals(
        redrafted["guarantee_true_up_amount_usd"], 20000.00, "guarantee_true_up_amount_usd"
    )


def test_withdrawing_from_offer_out_lapses_the_approved_offer_and_frees_the_money():
    """The candidate's `pipeline_status` becomes `WITHDRAWN`, `open_offer_id` is cleared to
    null, and then four hops run inside the same request:
    In the same hop, the candidate's `CompensationOffer` becomes `LAPSED` if its `status`
    is any of `DRAFTED`, `COMMITTEE_REVIEW`, `APPROVED`, `COUNTER_REQUESTED`, or
    `REPRICE_REQUIRED`; an offer already `ACCEPTED`, `REJECTED`, or `LAPSED` is left alone.
    `committed_guarantee_total_usd` is never touched by a withdrawal, because a withdrawn
    candidate's offer was by definition never accepted.

    Design: Corner/state_machines/withdraw_from_offer_out_lapses_the_approved_offer_and_releases_the_reserve
    """
    ctx = setup_approved_offer("SLIM")

    before = read_practice_group(ctx["practice_group"]["id"])
    assert_money_equals(
        before["reserved_guarantee_budget_usd"], 500000.00, "reserved before"
    )
    assert_money_equals(
        before["available_guarantee_budget_usd"], 4500000.00, "available before"
    )

    withdrawn = validate_success(
        api_client.withdraw_candidate(
            ctx["candidate"]["id"],
            withdraw_candidate_payload(
                withdrawal_reason="Candidate re-signed with the prior firm."
            ),
            COORDINATOR,
        )
    )
    assert withdrawn["pipeline_status"] == "WITHDRAWN"
    assert withdrawn["clearance_status"] == "CLEARED"
    assert withdrawn["open_offer_id"] is None
    assert withdrawn["hire_date"] is None

    offer = read_offer(ctx["offer"]["id"])
    assert offer["status"] == "LAPSED"
    assert offer["accepted_at"] is None

    assert read_questionnaire(ctx["questionnaire"]["id"])["status"] == "ABANDONED"
    assert (
        read_conflict_check(ctx["conflict_checks"]["Northwind Holdings"]["id"])["status"]
        == "CLEAR"
    )
    assert read_assessment(ctx["assessment"]["id"])["status"] == "CURRENT"

    group = read_practice_group(ctx["practice_group"]["id"])
    assert_money_equals(
        group["reserved_guarantee_budget_usd"], 0.00, "reserved_guarantee_budget_usd"
    )
    assert_money_equals(
        group["available_guarantee_budget_usd"], 5000000.00, "available_guarantee_budget_usd"
    )
    assert_money_equals(
        group["committed_guarantee_total_usd"], 0.00, "committed_guarantee_total_usd"
    )
    assert group["active_onboarding_count"] == 0


def test_only_the_active_plans_abandonment_returns_the_onboarding_slot():
    """A leader may abandon a plan, supplying an `abandonment_reason`, from either `DRAFT`
    or `ACTIVE`; both edges set `status` to `ABANDONED`, and both require that the acting
    `X-User-ID` equals the plan's own `practice_group_id`, failing with
    `ERR_NOT_RESOURCE_OWNER` otherwise.
    The two edges then diverge in exactly one respect: when the plan had been `ACTIVE`, a
    third hop decrements the group's `active_onboarding_count` by 1 and advances the
    group's `version`; when it was still `DRAFT`, that count is left untouched, because a
    draft plan never consumed a slot in the first place.
    In both cases a second hop cancels every `CrossSellIntroduction` on the plan whose
    `status` is `PROPOSED`.

    Design: Corner/state_machines/plan_abandon_returns_the_onboarding_slot_only_when_the_plan_was_active
    """
    ctx = setup_active_plan("SLIM")
    active_plan_id = ctx["plan"]["id"]
    introduction = add_introduction(ctx)
    assert introduction["status"] == "PROPOSED"
    assert read_practice_group(ctx["practice_group"]["id"])["active_onboarding_count"] == 1

    draft_plan(
        ctx,
        onboarding_start_date="2026-11-01T00:00:00.000Z",
        onboarding_end_date="2027-05-31T00:00:00.000Z",
    )
    draft_plan_id = ctx["plan"]["id"]
    assert draft_plan_id != active_plan_id

    abandoned_draft = validate_success(
        api_client.abandon_integration_plan(
            draft_plan_id,
            abandon_plan_payload(abandonment_reason="Duplicate plan opened in error."),
            ctx["leader_headers"],
        )
    )
    assert abandoned_draft["status"] == "ABANDONED"
    assert abandoned_draft["introduction_count"] == 0
    assert read_practice_group(ctx["practice_group"]["id"])["active_onboarding_count"] == 1

    abandoned_active = validate_success(
        api_client.abandon_integration_plan(
            active_plan_id,
            abandon_plan_payload(
                abandonment_reason="The lateral washed out during onboarding."
            ),
            ctx["leader_headers"],
        )
    )
    assert abandoned_active["status"] == "ABANDONED"
    assert abandoned_active["completed_introduction_count"] == 0

    group = read_practice_group(ctx["practice_group"]["id"])
    assert group["active_onboarding_count"] == 0
    assert_money_equals(
        group["committed_guarantee_total_usd"], 500000.00, "committed_guarantee_total_usd"
    )

    cancelled = validate_success(
        api_client.get_introduction(introduction["id"], ctx["leader_headers"])
    )
    assert cancelled["status"] == "CANCELLED"
    assert cancelled["completed_at"] is None

    assert read_integration_plan(active_plan_id)["status"] == "ABANDONED"
    assert read_candidate(ctx["candidate"]["id"])["pipeline_status"] == "HIRED"
