"""Refusals along the offer's own lifecycle: the committee floor, the negotiation cap, the
quorum floor, second decisions on decided rows, and pricing against a dead valuation."""

from test_helpers import (
    ApiErrorId,
    EXPECTED_AB_BOOK,
    ENTRY_B_RECORDS,
    ENTRY_B_SPEC,
    MEMBER_1_USER_ID,
    MEMBER_2_USER_ID,
    MEMBER_3_USER_ID,
    TEST_USERS,
    add_book_entry,
    api_client,
    assert_money_equals,
    cast_vote,
    counter_offer_payload,
    create_assessment,
    create_conflict_waiver_payload,
    create_offer_payload,
    draft_offer,
    grant_waiver_payload,
    make_committee_chair_headers,
    open_conflict_check,
    read_assessment,
    read_candidate,
    read_conflict_check,
    read_offer,
    read_practice_group,
    read_questionnaire,
    redraft_offer_payload,
    refuse_waiver_payload,
    request_revision_payload,
    setup_assessed_candidate,
    setup_drafted_offer,
    setup_offer_in_committee_review,
    submit_offer_payload,
    terminate_engagement_payload,
    validate_error,
    validate_success,
)

COORDINATOR = TEST_USERS["recruiting_coordinator_headers"]
COUNSEL = TEST_USERS["conflicts_counsel_headers"]
CHAIR = make_committee_chair_headers("user-chair-1")
PEER_CHAIR = make_committee_chair_headers("user-chair-2")


def test_a_two_person_roll_is_below_the_committee_floor_and_reserves_nothing():
    """Five conditions guard it beyond the status: the candidate's `clearance_status` must be
    `CLEARED`, or `ERR_CLEARANCE_INCOMPLETE`; the referenced assessment's `status` must still
    be `CURRENT`, or `ERR_ASSESSMENT_STALE` / `ERR_ASSESSMENT_INVALID_STATE` as above; the
    submitted `eligible_voter_count` must be at least 3, or `ERR_COMMITTEE_TOO_SMALL`; the
    receiving practice group's `status` must be `OPEN`, or `ERR_PRACTICE_GROUP_FROZEN`; and the
    offer's `guaranteed_comp_usd` must not exceed the group's `available_guarantee_budget_usd`,
    or `ERR_GUARANTEE_BUDGET_EXCEEDED` with HTTP 402.

    Design: Corner/errors/offer_submit_with_a_two_person_committee_is_rejected
    """
    ctx = setup_drafted_offer("SLIM")

    too_small = api_client.submit_offer(
        ctx["offer"]["id"], submit_offer_payload(eligible_voter_count=2), CHAIR
    )
    validate_error(too_small, ApiErrorId.ERR_COMMITTEE_TOO_SMALL.value)

    assert_money_equals(
        read_practice_group(ctx["practice_group"]["id"])["reserved_guarantee_budget_usd"],
        0.00,
        "reserved after the refusal",
    )

    submitted = validate_success(
        api_client.submit_offer(
            ctx["offer"]["id"], submit_offer_payload(eligible_voter_count=3), CHAIR
        )
    )
    assert submitted["eligible_voter_count"] == 3
    assert submitted["status"] == "COMMITTEE_REVIEW"
    assert submitted["round_number"] == 1

    group = read_practice_group(ctx["practice_group"]["id"])
    assert_money_equals(
        group["reserved_guarantee_budget_usd"], 500000.00, "reserved_guarantee_budget_usd"
    )
    assert_money_equals(
        group["available_guarantee_budget_usd"], 4500000.00, "available_guarantee_budget_usd"
    )


def test_the_third_round_is_the_last_so_a_further_counter_is_refused():
    """The negotiation loop `COMMITTEE_REVIEW → COUNTER_REQUESTED → DRAFTED →
    COMMITTEE_REVIEW` is bounded: a counter is permitted only while `round_number` is strictly
    less than 3, and an attempt beyond that is refused with
    `ERR_NEGOTIATION_ROUND_LIMIT_EXCEEDED`.

    Design: Corner/errors/fourth_counter_at_the_round_cap_is_rejected
    """
    ctx = setup_offer_in_committee_review("SLIM", eligible_voter_count=3)
    _counter_and_resubmit(ctx, 480000.00, 40000.00)
    _counter_and_resubmit(ctx, 460000.00, 40000.00)

    at_the_cap = read_offer(ctx["offer"]["id"])
    assert at_the_cap["round_number"] == 3
    assert at_the_cap["status"] == "COMMITTEE_REVIEW"

    refused = api_client.counter_offer(
        ctx["offer"]["id"],
        counter_offer_payload(counter_note="Committee wants a lower guarantee."),
        CHAIR,
    )
    validate_error(refused, ApiErrorId.ERR_NEGOTIATION_ROUND_LIMIT_EXCEEDED.value)

    offer = read_offer(ctx["offer"]["id"])
    assert offer["round_number"] == 3
    assert offer["status"] == "COMMITTEE_REVIEW"
    assert_money_equals(offer["guaranteed_comp_usd"], 460000.00, "guaranteed_comp_usd")
    assert offer["eligible_voter_count"] == 3
    assert offer["votes_cast_total"] == 0

    group = read_practice_group(ctx["practice_group"]["id"])
    assert_money_equals(
        group["reserved_guarantee_budget_usd"], 460000.00, "reserved_guarantee_budget_usd"
    )
    assert_money_equals(
        group["available_guarantee_budget_usd"], 4540000.00, "available_guarantee_budget_usd"
    )


def test_two_of_five_misses_the_rounded_up_quorum_and_the_third_ballot_supplies_it():
    """The quorum minimum is sixty percent of `eligible_voter_count`, **rounded up to the next
    whole voter**; quorum is met when the cast count is at least that minimum. If quorum is not
    met the request itself fails with `ERR_QUORUM_NOT_MET` and the offer does not move.
    On approval the offer moves `COMMITTEE_REVIEW → APPROVED` and the candidate moves
    `DILIGENCE → OFFER_OUT` with the approved offer's identifier recorded in `open_offer_id`;
    the guarantee stays **reserved** and is not yet committed.

    Design: Corner/errors/finalize_below_quorum_is_rejected
    """
    ctx = setup_offer_in_committee_review("SLIM", eligible_voter_count=5)
    cast_vote(ctx, MEMBER_1_USER_ID, "APPROVE")
    cast_vote(ctx, MEMBER_2_USER_ID, "APPROVE")

    short = api_client.finalize_offer(ctx["offer"]["id"], PEER_CHAIR)
    validate_error(short, ApiErrorId.ERR_QUORUM_NOT_MET.value)
    assert read_offer(ctx["offer"]["id"])["status"] == "COMMITTEE_REVIEW"

    cast_vote(ctx, MEMBER_3_USER_ID, "APPROVE")

    approved = validate_success(
        api_client.finalize_offer(ctx["offer"]["id"], PEER_CHAIR)
    )
    assert approved["status"] == "APPROVED"
    assert approved["active_vote_count"] == 3
    assert approved["votes_cast_total"] == 3
    assert approved["eligible_voter_count"] == 5

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


def test_a_granted_waiver_a_drafted_offer_and_a_dead_engagement_each_refuse_a_replay():
    """Granting or refusing a waiver that is not `REQUESTED` is refused with
    `ERR_WAIVER_INVALID_STATE`.
    Failure yields the invalid-state code for that entity:
    `ERR_CANDIDATE_INVALID_STATE`, `ERR_QUESTIONNAIRE_INVALID_STATE`,
    `ERR_ENGAGEMENT_INVALID_STATE`, `ERR_ASSESSMENT_INVALID_STATE`,
    `ERR_CONFLICT_CHECK_INVALID_STATE`, `ERR_WAIVER_INVALID_STATE`,
    `ERR_DECLINATION_INVALID_STATE`, `ERR_OFFER_INVALID_STATE`,
    `ERR_INTEGRATION_PLAN_INVALID_STATE`, or `ERR_INTRODUCTION_INVALID_STATE` (all 409).

    Design: Corner/errors/already_decided_rows_refuse_a_second_decision
    """
    ctx = setup_assessed_candidate("SLIM")
    check = open_conflict_check(ctx, "Northwind Holdings", severity="IMPUTED")
    waiver = validate_success(
        api_client.create_conflict_waiver(
            check["id"],
            create_conflict_waiver_payload(requested_from_client="Northwind Holdings"),
            COUNSEL,
        ),
        expected_status=201,
    )
    validate_success(
        api_client.grant_conflict_waiver(waiver["id"], grant_waiver_payload(), COUNSEL)
    )
    assert read_candidate(ctx["candidate"]["id"])["clearance_status"] == "CLEARED"
    draft_offer(ctx)

    late_refusal = api_client.refuse_conflict_waiver(
        waiver["id"],
        refuse_waiver_payload(
            resolution_note="Counsel changed their mind after the grant."
        ),
        COUNSEL,
    )
    waiver_error = validate_error(late_refusal, ApiErrorId.ERR_WAIVER_INVALID_STATE.value)

    early_redraft = api_client.redraft_offer(
        ctx["offer"]["id"],
        redraft_offer_payload(guaranteed_comp_usd=450000.00, signing_bonus_usd=50000.00),
        CHAIR,
    )
    offer_error = validate_error(early_redraft, ApiErrorId.ERR_OFFER_INVALID_STATE.value)

    validate_success(
        api_client.terminate_search_firm_engagement(
            ctx["engagement"]["id"],
            terminate_engagement_payload(
                reason="Search mandate withdrawn after the lateral stalled."
            ),
            COORDINATOR,
        )
    )
    second_termination = api_client.terminate_search_firm_engagement(
        ctx["engagement"]["id"],
        terminate_engagement_payload(reason="Duplicate termination request."),
        COORDINATOR,
    )
    engagement_error = validate_error(
        second_termination, ApiErrorId.ERR_ENGAGEMENT_INVALID_STATE.value
    )

    ids = {
        waiver_error["error_id"],
        offer_error["error_id"],
        engagement_error["error_id"],
    }
    assert len(ids) == 3

    assert (
        validate_success(api_client.get_conflict_waiver(waiver["id"], COUNSEL))["status"]
        == "GRANTED"
    )
    assert read_conflict_check(check["id"])["status"] == "CLEAR"

    offer = read_offer(ctx["offer"]["id"])
    assert offer["status"] == "DRAFTED"
    assert_money_equals(offer["guaranteed_comp_usd"], 500000.00, "guaranteed_comp_usd")
    assert_money_equals(
        offer["total_first_year_comp_usd"], 550000.00, "total_first_year_comp_usd"
    )

    engagement = validate_success(
        api_client.get_search_firm_engagement(ctx["engagement"]["id"], COORDINATOR)
    )
    assert engagement["status"] == "TERMINATED"
    assert engagement["fee_status"] == "FEE_WAIVED"
    assert engagement["fee_basis"] == "NONE"
    assert_money_equals(engagement["fee_amount_usd"], 0.00, "fee_amount_usd")


def test_staleness_and_supersession_are_distinct_refusals_on_the_same_assessment():
    """And the assessment's `status` must be `CURRENT`: an assessment that has gone `STALE` is
    refused with `ERR_ASSESSMENT_STALE`, and one that has been `SUPERSEDED` is refused with
    `ERR_ASSESSMENT_INVALID_STATE`. The distinction matters — staleness means the book moved,
    supersession means a newer assessment exists.
    It copies the assessment's `adjusted_portable_total_usd` into its own
    `adjusted_portable_total_snapshot_usd`, and that snapshot is **pinned for the life of the
    offer**: it is never refreshed, not even when the assessment it came from goes `STALE`.

    Design: Corner/errors/offer_create_against_a_stale_or_superseded_assessment_is_rejected
    """
    ctx = setup_assessed_candidate("SLIM")
    first_assessment_id = ctx["assessment"]["id"]

    validate_success(
        api_client.request_revision_questionnaire(
            ctx["questionnaire"]["id"], request_revision_payload(), COORDINATOR
        )
    )
    add_book_entry(ctx, ENTRY_B_SPEC, ENTRY_B_RECORDS)
    assert read_assessment(first_assessment_id)["status"] == "STALE"

    validate_success(
        api_client.submit_questionnaire(
            ctx["questionnaire"]["id"], ctx["candidate_headers"]
        )
    )
    validate_success(
        api_client.start_review_questionnaire(ctx["questionnaire"]["id"], COORDINATOR)
    )

    against_stale = api_client.create_offer(
        ctx["candidate"]["id"],
        create_offer_payload(
            first_assessment_id,
            read_candidate(ctx["candidate"]["id"])["version"],
            guaranteed_comp_usd=400000.00,
            signing_bonus_usd=40000.00,
        ),
        CHAIR,
    )
    stale_error = validate_error(against_stale, ApiErrorId.ERR_ASSESSMENT_STALE.value)

    second = create_assessment(ctx)

    against_superseded = api_client.create_offer(
        ctx["candidate"]["id"],
        create_offer_payload(
            first_assessment_id,
            read_candidate(ctx["candidate"]["id"])["version"],
            guaranteed_comp_usd=400000.00,
            signing_bonus_usd=40000.00,
        ),
        CHAIR,
    )
    superseded_error = validate_error(
        against_superseded, ApiErrorId.ERR_ASSESSMENT_INVALID_STATE.value
    )
    assert stale_error["error_id"] != superseded_error["error_id"]

    offer = validate_success(
        api_client.create_offer(
            ctx["candidate"]["id"],
            create_offer_payload(
                second["id"],
                read_candidate(ctx["candidate"]["id"])["version"],
                guaranteed_comp_usd=400000.00,
                signing_bonus_usd=40000.00,
            ),
            CHAIR,
        ),
        expected_status=201,
    )

    assert read_assessment(first_assessment_id)["status"] == "SUPERSEDED"
    assert read_assessment(second["id"])["status"] == "CURRENT"
    assert_money_equals(
        second["gross_baseline_total_usd"],
        EXPECTED_AB_BOOK["gross_baseline_total_usd"],
        "gross_baseline_total_usd",
    )
    assert_money_equals(
        second["adjusted_portable_total_usd"],
        EXPECTED_AB_BOOK["adjusted_portable_total_usd"],
        "adjusted_portable_total_usd",
    )
    assert_money_equals(
        offer["adjusted_portable_total_snapshot_usd"],
        EXPECTED_AB_BOOK["adjusted_portable_total_usd"],
        "adjusted_portable_total_snapshot_usd",
    )
    assert offer["status"] == "DRAFTED"

    questionnaire = read_questionnaire(ctx["questionnaire"]["id"])
    assert questionnaire["entry_count"] == 2
    assert questionnaire["revision_round"] == 1


# ----------------------------------------------------------------------
# Local scenario glue
# ----------------------------------------------------------------------


def _counter_and_resubmit(ctx, guaranteed, signing):
    """One full negotiation lap: counter, redraft at a new package, resubmit."""
    validate_success(
        api_client.counter_offer(ctx["offer"]["id"], counter_offer_payload(), CHAIR)
    )
    validate_success(
        api_client.redraft_offer(
            ctx["offer"]["id"],
            redraft_offer_payload(
                guaranteed_comp_usd=guaranteed, signing_bonus_usd=signing
            ),
            CHAIR,
        )
    )
    ctx["offer"] = validate_success(
        api_client.submit_offer(
            ctx["offer"]["id"], submit_offer_payload(eligible_voter_count=3), CHAIR
        )
    )
    return ctx["offer"]
