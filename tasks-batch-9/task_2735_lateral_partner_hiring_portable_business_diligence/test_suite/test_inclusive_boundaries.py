"""Inclusive boundaries: the concentration grade, the quorum and approval rules, and
the guarantee-budget ceiling, each probed exactly on its edge."""

from test_helpers import (
    ApiErrorId,
    MEMBER_1_USER_ID,
    MEMBER_2_USER_ID,
    MEMBER_3_USER_ID,
    TEST_USERS,
    add_book_entry,
    api_client,
    assert_money_equals,
    assert_ratio_equals,
    cast_vote,
    counter_offer_payload,
    create_assessment,
    draft_offer,
    finalize_offer,
    make_committee_chair_headers,
    read_client_book_entry,
    read_offer,
    read_practice_group,
    redraft_offer_payload,
    setup_cleared_candidate,
    setup_offer_in_committee_review,
    setup_questionnaire_in_draft,
    submit_offer,
    submit_offer_payload,
    validate_error,
    validate_success,
)

COORDINATOR = TEST_USERS["recruiting_coordinator_headers"]
CHAIR = make_committee_chair_headers("user-chair-1")
PEER_CHAIR = make_committee_chair_headers("user-chair-2")


def test_a_top_client_share_of_exactly_thirty_percent_grades_high():
    """`concentration_grade` is decided by `top_client_share` alone, on **inclusive**
    boundaries: `HIGH` when the share is at least `0.30`, otherwise `MEDIUM` when it is
    at least `0.20`, otherwise `LOW`. A share of exactly `0.30` is `HIGH`, and a share of
    exactly `0.20` is `MEDIUM`.

    Design: Difficulty/boundary_precision_check/concentration_top_share_exactly_thirty_percent_grades_high
    """
    ctx = _setup_four_entry_book()
    assessment = create_assessment(ctx, governing_basis="VALIDATED")

    assert_money_equals(
        assessment["gross_baseline_total_usd"], 9000000.00, "gross_baseline_total_usd"
    )
    assert_money_equals(
        assessment["validated_portable_total_usd"],
        9000000.00,
        "validated_portable_total_usd",
    )
    assert_money_equals(
        assessment["self_reported_total_usd"], 10000000.00, "self_reported_total_usd"
    )
    assert_ratio_equals(assessment["variance_pct"], 0.1000, "variance_pct")
    assert_ratio_equals(assessment["top_client_share"], 0.3000, "top_client_share")
    assert_ratio_equals(assessment["top3_client_share"], 0.8000, "top3_client_share")

    assert assessment["concentration_grade"] == "HIGH"
    assert assessment["concentration_grade"] != "MEDIUM"
    assert_ratio_equals(assessment["concentration_haircut_pct"], 0.15, "haircut")
    assert_money_equals(
        assessment["adjusted_portable_total_usd"],
        7650000.00,
        "adjusted_portable_total_usd",
    )
    # 8370000.00 is what the MEDIUM haircut of 0.07 would have produced.
    assert abs(float(assessment["adjusted_portable_total_usd"]) - 8370000.00) > 0.005
    assert assessment["entry_count_in_scope"] == 4


def test_the_hard_portability_ceiling_sets_every_baseline_in_that_book():
    """Then apply a hard portability ceiling: the result is replaced by the smaller of
    itself and 90 percent of the entry's average annual collections.
    `top_client_share` is the highest-ranked entry's `baseline_portable_amount_usd`
    divided by `gross_baseline_total_usd`, rounded half up to four decimal places;
    `top3_client_share` is the sum of the three highest-ranked entries' baseline amounts
    (or all of them, if fewer than three exist) divided by the same denominator and
    rounded the same way.

    Design: Difficulty/boundary_precision_check/concentration_top_share_exactly_thirty_percent_grades_high
    """
    ctx = _setup_four_entry_book()
    create_assessment(ctx, governing_basis="VALIDATED")

    assert_money_equals(
        read_client_book_entry(ctx["entries"]["Alpha Trust"]["id"])[
            "baseline_portable_amount_usd"
        ],
        2700000.00,
        "largest entry baseline",
    )
    assert_money_equals(
        read_client_book_entry(ctx["entries"]["Delta Mutual"]["id"])[
            "baseline_portable_amount_usd"
        ],
        1800000.00,
        "smallest entry baseline",
    )


def test_exactly_two_thirds_approval_over_a_met_quorum_approves_the_offer():
    """If quorum is met, approval is decided by a two-thirds rule over the
    non-abstaining votes, evaluated in whole numbers with no floating-point comparison
    anywhere: the approval count multiplied by three must be at least twice the sum of
    the approval count and the rejection count.
    The boundary is inclusive, so exactly two thirds approves.

    Design: Difficulty/boundary_precision_check/quorum_two_thirds_approval_exact_boundary_approves
    """
    ctx = setup_offer_in_committee_review("SLIM", eligible_voter_count=5)

    group_before = read_practice_group(ctx["practice_group"]["id"])
    assert_money_equals(
        group_before["reserved_guarantee_budget_usd"], 500000.00, "reserved before"
    )
    assert_money_equals(
        group_before["available_guarantee_budget_usd"], 4500000.00, "available before"
    )

    cast_vote(ctx, MEMBER_1_USER_ID, "APPROVE")
    cast_vote(ctx, MEMBER_2_USER_ID, "APPROVE")
    cast_vote(ctx, MEMBER_3_USER_ID, "REJECT")

    finalized = finalize_offer(ctx)

    assert finalized["status"] == "APPROVED"
    assert finalized["status"] != "REJECTED"
    assert finalized["eligible_voter_count"] == 5
    assert finalized["active_vote_count"] == 3
    assert finalized["voided_vote_count"] == 0
    assert finalized["votes_cast_total"] == 3
    assert finalized["round_number"] == 1

    group = read_practice_group(ctx["practice_group"]["id"])
    assert_money_equals(group["reserved_guarantee_budget_usd"], 500000.00, "reserved")
    assert_money_equals(group["available_guarantee_budget_usd"], 4500000.00, "available")
    assert_money_equals(group["committed_guarantee_total_usd"], 0.00, "committed")


def test_one_ballot_short_of_the_rounded_up_quorum_fails_the_finalization():
    """The quorum minimum is sixty percent of `eligible_voter_count`, **rounded up to the
    next whole voter**; quorum is met when the cast count is at least that minimum. If
    quorum is not met the request itself fails with `ERR_QUORUM_NOT_MET` and the offer
    does not move.

    Design: Difficulty/boundary_precision_check/quorum_two_thirds_approval_exact_boundary_approves
    """
    ctx = setup_offer_in_committee_review("SLIM", eligible_voter_count=5)

    cast_vote(ctx, MEMBER_1_USER_ID, "APPROVE")
    cast_vote(ctx, MEMBER_2_USER_ID, "APPROVE")

    response = api_client.finalize_offer(ctx["offer"]["id"], PEER_CHAIR)
    validate_error(response, ApiErrorId.ERR_QUORUM_NOT_MET.value)

    offer = read_offer(ctx["offer"]["id"])
    assert offer["status"] == "COMMITTEE_REVIEW"
    assert offer["active_vote_count"] == 2


def test_a_guarantee_exactly_equal_to_the_available_budget_may_be_submitted():
    """That budget boundary is inclusive — a guarantee exactly equal to the available
    budget is permitted, and exceeding it by a single cent is not.
    On success the group's `reserved_guarantee_budget_usd` increases by
    `guaranteed_comp_usd` and its `available_guarantee_budget_usd` decreases by the same
    amount, so the budget identity of §2.8 is preserved.

    Design: Difficulty/boundary_precision_check/guarantee_budget_exact_equality_permits_submit
    """
    ctx = setup_cleared_candidate(
        "SLIM", pg_overrides={"guarantee_budget_total_usd": 500000.00}
    )
    draft_offer(ctx)

    submitted = submit_offer(ctx, eligible_voter_count=3)
    assert submitted["status"] == "COMMITTEE_REVIEW"

    group = read_practice_group(ctx["practice_group"]["id"])
    assert_money_equals(group["available_guarantee_budget_usd"], 0.00, "available after")
    assert_money_equals(
        group["reserved_guarantee_budget_usd"], 500000.00, "reserved after"
    )


def test_a_single_cent_above_the_available_budget_is_refused_on_resubmission():
    """All seven computed economics fields — `expected_contribution_usd`,
    `total_first_year_comp_usd`, `search_fee_amount_usd`, `integration_cost_total_usd`,
    `net_first_year_economics_usd`, `guarantee_true_up_amount_usd`, and the derived fee
    figures — are recomputed from the new inputs against the **same** pinned
    `adjusted_portable_total_snapshot_usd`.
    and the offer's `guaranteed_comp_usd` must not exceed the group's
    `available_guarantee_budget_usd`, or `ERR_GUARANTEE_BUDGET_EXCEEDED` with HTTP 402.

    Design: Difficulty/boundary_precision_check/guarantee_budget_exact_equality_permits_submit
    """
    ctx = setup_cleared_candidate(
        "SLIM", pg_overrides={"guarantee_budget_total_usd": 500000.00}
    )
    draft_offer(ctx)
    submit_offer(ctx, eligible_voter_count=3)

    countered = validate_success(
        api_client.counter_offer(ctx["offer"]["id"], counter_offer_payload(), CHAIR)
    )
    assert countered["status"] == "COUNTER_REQUESTED"
    assert countered["round_number"] == 2

    redrafted = validate_success(
        api_client.redraft_offer(
            ctx["offer"]["id"],
            redraft_offer_payload(
                guaranteed_comp_usd=500000.01, signing_bonus_usd=50000.00
            ),
            CHAIR,
        )
    )
    assert redrafted["status"] == "DRAFTED"
    assert_money_equals(
        redrafted["guaranteed_comp_usd"], 500000.01, "guaranteed_comp_usd"
    )
    assert_money_equals(
        redrafted["total_first_year_comp_usd"], 550000.01, "total_first_year_comp_usd"
    )
    assert_money_equals(
        redrafted["net_first_year_economics_usd"],
        259481.26,
        "net_first_year_economics_usd",
    )

    response = api_client.submit_offer(
        ctx["offer"]["id"], submit_offer_payload(eligible_voter_count=3), CHAIR
    )
    validate_error(response, ApiErrorId.ERR_GUARANTEE_BUDGET_EXCEEDED.value)

    offer = read_offer(ctx["offer"]["id"])
    assert offer["status"] == "DRAFTED"
    assert offer["round_number"] == 2
    assert offer["eligible_voter_count"] is None

    group = read_practice_group(ctx["practice_group"]["id"])
    assert_money_equals(group["available_guarantee_budget_usd"], 500000.00, "available")
    assert_money_equals(group["reserved_guarantee_budget_usd"], 0.00, "reserved")
    assert_money_equals(group["committed_guarantee_total_usd"], 0.00, "committed")


# ----------------------------------------------------------------------
# Local scenario glue
# ----------------------------------------------------------------------


def _four_entry_spec(name, average_collections, claimed_billings):
    return {
        "client_name": name,
        "relationship_role": "BILLING_ATTORNEY",
        "client_consent_status": "CONSENT_CONFIRMED",
        "claimed_annual_billings_usd": claimed_billings,
        "claimed_portability_pct": 1.0000,
        "claimed_realization_rate": 1.0000,
        "matter_types": ["M_AND_A"],
    }, [
        ("2023-12-31T00:00:00.000Z", average_collections),
        ("2024-12-31T00:00:00.000Z", average_collections),
        ("2025-12-31T00:00:00.000Z", average_collections),
    ]


def _setup_four_entry_book():
    """Four entries on which the 90-percent ceiling binds, giving baselines of
    2700000.00, 2250000.00, 2250000.00 and 1800000.00."""
    ctx = setup_questionnaire_in_draft()
    for name, average, billings in (
        ("Alpha Trust", 3000000.00, 3000000.00),
        ("Bravo Systems", 2500000.00, 2500000.00),
        ("Charlie Foods", 2500000.00, 2500000.00),
        ("Delta Mutual", 2000000.00, 2000000.00),
    ):
        spec, records = _four_entry_spec(name, average, billings)
        add_book_entry(ctx, spec, records)
    ctx["questionnaire"] = validate_success(
        api_client.submit_questionnaire(
            ctx["questionnaire"]["id"], ctx["candidate_headers"]
        )
    )
    ctx["questionnaire"] = validate_success(
        api_client.start_review_questionnaire(ctx["questionnaire"]["id"], COORDINATOR)
    )
    return ctx
