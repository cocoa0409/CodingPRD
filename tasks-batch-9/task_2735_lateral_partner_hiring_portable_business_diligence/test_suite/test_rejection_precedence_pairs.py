"""Rejection precedence: when one request breaks two rules, the earlier rung wins."""

from test_helpers import (
    ApiErrorId,
    MEMBER_1_USER_ID,
    SPONSOR_USER_ID,
    TEST_USERS,
    api_client,
    assert_money_equals,
    cast_vote_payload,
    clear_conflict_check,
    create_engagement_payload,
    draft_offer,
    make_committee_chair_headers,
    make_committee_member_headers,
    open_conflict_check,
    read_offer,
    read_practice_group,
    setup_assessed_candidate,
    setup_config,
    setup_offer_in_committee_review,
    submit_offer_payload,
    validate_error,
    validate_success,
)

COORDINATOR = TEST_USERS["recruiting_coordinator_headers"]
CHAIR = make_committee_chair_headers("user-chair-1")


def test_incomplete_clearance_is_reported_before_the_guarantee_budget_ceiling():
    """The ordering reflects the firm's own priorities: professional-responsibility and
    segregation-of-duties questions outrank everything, because a firm may not price or
    vote on a hire it is ethically barred from making; referential integrity of
    cross-aggregate pointers comes next; then temporal and exclusivity geometry; then
    structural caps; and money last, because a partner's guarantee budget is the final
    thing that should stop a lateral hire.
    **Clearance complete** — the candidate's `clearance_status` is `CLEARED`. Failure:
    `ERR_CLEARANCE_INCOMPLETE` (409).

    Design: Difficulty/priority_pair_validation_conflict/offer_submit_clearance_safety_outranks_guarantee_budget_fiscal
    """
    ctx = _setup_unaffordable_offer_with_open_conflict()

    response = api_client.submit_offer(
        ctx["offer"]["id"], submit_offer_payload(eligible_voter_count=3), CHAIR
    )
    error = validate_error(response, ApiErrorId.ERR_CLEARANCE_INCOMPLETE.value)
    assert error["error_id"] != ApiErrorId.ERR_GUARANTEE_BUDGET_EXCEEDED.value

    assert read_offer(ctx["offer"]["id"])["status"] == "DRAFTED"


def test_once_clearance_lands_the_same_submit_falls_through_to_the_budget_ceiling():
    """**Guarantee budget** — `ERR_GUARANTEE_BUDGET_EXCEEDED` (402) on
    `POST /lateral-hiring/offers/{offer_id}/submit`.
    That budget boundary is inclusive — a guarantee exactly equal to the available
    budget is permitted, and exceeding it by a single cent is not.

    Design: Difficulty/priority_pair_validation_conflict/offer_submit_clearance_safety_outranks_guarantee_budget_fiscal
    """
    ctx = _setup_unaffordable_offer_with_open_conflict()

    clear_conflict_check(ctx, "Northwind Holdings")
    assert ctx["candidate"]["clearance_status"] == "CLEARED"

    response = api_client.submit_offer(
        ctx["offer"]["id"], submit_offer_payload(eligible_voter_count=3), CHAIR
    )
    validate_error(response, ApiErrorId.ERR_GUARANTEE_BUDGET_EXCEEDED.value)

    offer = read_offer(ctx["offer"]["id"])
    assert offer["status"] == "DRAFTED"
    assert offer["eligible_voter_count"] is None

    group = read_practice_group(ctx["practice_group"]["id"])
    assert_money_equals(
        group["available_guarantee_budget_usd"], 5000000.00, "available_guarantee_budget_usd"
    )
    assert_money_equals(
        group["reserved_guarantee_budget_usd"], 0.00, "reserved_guarantee_budget_usd"
    )


def test_the_sponsor_bar_is_reported_before_the_vote_round_mismatch():
    """**Sponsor may not vote** — `ERR_SPONSOR_CANNOT_VOTE` (409) on
    `POST /lateral-hiring/offers/{offer_id}/votes`.
    The acting user must not be the candidate's `sponsor_user_id`
    (`ERR_SPONSOR_CANNOT_VOTE`), must not already hold an `ACTIVE` vote on this offer
    (`ERR_DUPLICATE_VOTE`), and the offer's `active_vote_count` must be strictly below
    its `eligible_voter_count` (`ERR_VOTE_ROLL_FULL`).

    Design: Difficulty/priority_pair_validation_conflict/vote_sponsor_safety_outranks_vote_round_referential
    """
    ctx = setup_offer_in_committee_review("SLIM")

    response = api_client.cast_vote(
        ctx["offer"]["id"],
        cast_vote_payload(
            decision="APPROVE", round_number=2, rationale="I sourced this candidate."
        ),
        make_committee_member_headers(SPONSOR_USER_ID),
    )
    error = validate_error(response, ApiErrorId.ERR_SPONSOR_CANNOT_VOTE.value)
    assert error["error_id"] != ApiErrorId.ERR_VOTE_ROUND_MISMATCH.value

    offer = read_offer(ctx["offer"]["id"])
    assert offer["votes_cast_total"] == 0
    assert offer["active_vote_count"] == 0
    assert offer["round_number"] == 1
    assert offer["status"] == "COMMITTEE_REVIEW"


def test_a_non_sponsor_voting_on_the_wrong_round_gets_the_round_mismatch():
    """**Vote round agreement** — the submitted `round_number` equals the offer's current
    `round_number`. Failure: `ERR_VOTE_ROUND_MISMATCH` (409).
    The submitted `round_number` must equal the offer's current `round_number`, or the
    vote is refused with `ERR_VOTE_ROUND_MISMATCH` — this is what stops a voter from
    unknowingly voting on a superseded round.

    Design: Difficulty/priority_pair_validation_conflict/vote_sponsor_safety_outranks_vote_round_referential
    """
    ctx = setup_offer_in_committee_review("SLIM")

    response = api_client.cast_vote(
        ctx["offer"]["id"],
        cast_vote_payload(decision="APPROVE", round_number=2),
        make_committee_member_headers(MEMBER_1_USER_ID),
    )
    validate_error(response, ApiErrorId.ERR_VOTE_ROUND_MISMATCH.value)

    offer = read_offer(ctx["offer"]["id"])
    assert offer["votes_cast_total"] == 0
    assert offer["active_vote_count"] == 0
    assert offer["round_number"] == 1


def test_the_exclusivity_conflict_is_reported_before_the_firm_fee_ceiling():
    """**Practice-group exclusivity geometry** — `ERR_ENGAGEMENT_EXCLUSIVITY_CONFLICT`
    (409) on `POST /lateral-hiring/search-firm-engagements`.
    On the **practice group** side, the requested half-open window must not overlap the
    half-open window of any existing engagement on the same `practice_group_id` whose
    `status` is `ACTIVE`, and in addition the requested `exclusivity_start_date` must
    fall at or after that existing engagement's `exclusivity_end_date` advanced by its
    own `tail_off_days` days.

    Design: Difficulty/priority_pair_validation_conflict/engagement_temporal_geometry_outranks_fee_pct_constraint
    """
    ctx = setup_config()

    response = api_client.create_search_firm_engagement(
        create_engagement_payload(
            ctx["search_firm"]["id"],
            ctx["practice_group"]["id"],
            fee_pct=0.4000,
            exclusivity_start_date="2026-10-01T00:00:00.000Z",
            exclusivity_end_date="2027-01-01T00:00:00.000Z",
        ),
        COORDINATOR,
    )
    error = validate_error(
        response, ApiErrorId.ERR_ENGAGEMENT_EXCLUSIVITY_CONFLICT.value
    )
    assert error["error_id"] != ApiErrorId.ERR_FEE_PCT_ABOVE_FIRM_MAX.value


def test_a_compliant_window_with_an_excessive_fee_hits_the_fee_ceiling():
    """**Fee ceiling** — `ERR_FEE_PCT_ABOVE_FIRM_MAX` (422) on
    `POST /lateral-hiring/search-firm-engagements`.
    Separately, the requested `fee_pct` must not exceed the firm's `max_fee_pct`, or the
    create is refused with `ERR_FEE_PCT_ABOVE_FIRM_MAX`; and `exclusivity_end_date` must
    be strictly later than `exclusivity_start_date`, or the create is refused with
    `ERR_LOOKBACK_WINDOW_INVALID`.

    Design: Difficulty/priority_pair_validation_conflict/engagement_temporal_geometry_outranks_fee_pct_constraint
    """
    ctx = setup_config()

    compliant_window = {
        "exclusivity_start_date": "2027-03-01T00:00:00.000Z",
        "exclusivity_end_date": "2027-06-01T00:00:00.000Z",
    }

    response = api_client.create_search_firm_engagement(
        create_engagement_payload(
            ctx["search_firm"]["id"],
            ctx["practice_group"]["id"],
            fee_pct=0.4000,
            **compliant_window,
        ),
        COORDINATOR,
    )
    validate_error(response, ApiErrorId.ERR_FEE_PCT_ABOVE_FIRM_MAX.value)

    second = validate_success(
        api_client.create_search_firm_engagement(
            create_engagement_payload(
                ctx["search_firm"]["id"],
                ctx["practice_group"]["id"],
                fee_pct=0.3000,
                **compliant_window,
            ),
            COORDINATOR,
        ),
        expected_status=201,
    )
    assert second["status"] == "ACTIVE"
    assert abs(float(second["fee_pct"]) - 0.3000) < 0.00005
    assert second["fee_status"] == "NOT_DUE"

    firm = validate_success(
        api_client.get_search_firm(ctx["search_firm"]["id"], COORDINATOR)
    )
    assert firm["engagement_count"] == 2


# ----------------------------------------------------------------------
# Local scenario glue
# ----------------------------------------------------------------------


def _setup_unaffordable_offer_with_open_conflict():
    """A DRAFTED offer whose guarantee exceeds the whole group budget, on a candidate
    whose clearance is still IN_PROGRESS."""
    ctx = setup_assessed_candidate("SLIM")
    open_conflict_check(ctx, "Northwind Holdings")
    draft_offer(ctx, guaranteed_comp_usd=6000000.00, signing_bonus_usd=50000.00)
    return ctx
