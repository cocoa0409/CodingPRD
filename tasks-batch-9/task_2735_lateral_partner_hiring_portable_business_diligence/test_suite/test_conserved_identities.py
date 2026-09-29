"""Compensating actions: rescinding a declination, countering a submitted offer, and
re-voting a second round, each of which must leave a stated identity intact."""

from test_helpers import (
    EXPECTED_AB_BOOK,
    EXPECTED_ENTRY_B_DECLINATION,
    MEMBER_1_USER_ID,
    MEMBER_2_USER_ID,
    MEMBER_3_USER_ID,
    TEST_USERS,
    api_client,
    assert_guarantee_budget_identity,
    assert_money_equals,
    assert_portable_book_identity,
    assert_vote_ledger_identity,
    block_entry_through_refused_waiver,
    cast_vote,
    clear_conflict_check,
    counter_offer_payload,
    declinations_for_entry,
    draft_offer,
    finalize_offer,
    make_committee_chair_headers,
    open_conflict_check,
    read_assessment,
    read_candidate,
    read_client_book_entry,
    read_conflict_check,
    read_offer,
    read_practice_group,
    redraft_offer_payload,
    rescind_declination_payload,
    setup_assessed_candidate,
    setup_cleared_candidate,
    setup_offer_in_committee_review,
    submit_offer,
    submit_offer_payload,
    validate_success,
)

COORDINATOR = TEST_USERS["recruiting_coordinator_headers"]
COUNSEL = TEST_USERS["conflicts_counsel_headers"]
CHAIR = make_committee_chair_headers("user-chair-1")


def test_rescinding_only_one_matter_leaves_the_entry_declined_and_the_book_identity_whole():
    """The **portable book identity** holds on every `PortabilityAssessment`:
    `validated_portable_total_usd` plus `declined_portable_total_usd` always equals
    `gross_baseline_total_usd`, exactly, to the cent.
    Rescinding one of several active declinations on the same entry moves only that row;
    the entry stays `DECLINED`.

    Design: Difficulty/compensating_invariant/declination_rescission_restores_book_identity
    """
    ctx = _setup_blocked_entry_b()

    after_refusal = read_assessment(ctx["assessment"]["id"])
    assert_money_equals(
        after_refusal["gross_baseline_total_usd"],
        EXPECTED_AB_BOOK["gross_baseline_total_usd"],
        "gross after refusal",
    )
    assert_money_equals(
        after_refusal["validated_portable_total_usd"],
        EXPECTED_AB_BOOK["entry_a_baseline"],
        "validated after refusal",
    )
    assert_money_equals(
        after_refusal["declined_portable_total_usd"],
        EXPECTED_AB_BOOK["entry_b_baseline"],
        "declined after refusal",
    )
    assert_portable_book_identity(after_refusal)

    declinations = declinations_for_entry(ctx["entries"]["Calder Manufacturing"]["id"])
    assert len(declinations) == 2
    first = validate_success(
        api_client.rescind_matter_declination(
            declinations[0]["id"],
            rescind_declination_payload(
                rescission_note="Client relented on the litigation matters."
            ),
            COUNSEL,
        )
    )
    assert first["status"] == "RESCINDED"
    assert_money_equals(
        first["foregone_annual_revenue_usd"],
        EXPECTED_ENTRY_B_DECLINATION[first["matter_type"]],
        "rescinded share",
    )

    partway = read_assessment(ctx["assessment"]["id"])
    assert_money_equals(
        partway["gross_baseline_total_usd"],
        EXPECTED_AB_BOOK["gross_baseline_total_usd"],
        "gross after one rescission",
    )
    assert_money_equals(
        partway["validated_portable_total_usd"],
        EXPECTED_AB_BOOK["entry_a_baseline"],
        "validated after one rescission",
    )
    assert_money_equals(
        partway["declined_portable_total_usd"],
        EXPECTED_AB_BOOK["entry_b_baseline"],
        "declined after one rescission",
    )
    assert_portable_book_identity(partway)

    entry_b = read_client_book_entry(ctx["entries"]["Calder Manufacturing"]["id"])
    assert entry_b["portable_status"] == "DECLINED"


def test_rescinding_the_last_matter_restores_the_entry_and_the_original_totals():
    """When — and only when — this was the **last** `ACTIVE` declination on the entry, so
    that zero remain active afterwards, the reversal chain runs: the entry moves
    `portable_status` `DECLINED → VALIDATED` with `validated_portable_amount_usd` restored
    exactly to `baseline_portable_amount_usd` with no drift; the parent check moves
    `BLOCKED → CLEAR`; every assessment on that questionnaire whose `status` is `CURRENT`
    or `STALE` recomputes `validated_portable_total_usd`, `declined_portable_total_usd`,
    and `adjusted_portable_total_usd`; and the candidate's `clearance_status` is
    recomputed, which may return it to `CLEARED`.

    Design: Difficulty/compensating_invariant/declination_rescission_restores_book_identity
    """
    ctx = _setup_blocked_entry_b()

    entry_b_id = ctx["entries"]["Calder Manufacturing"]["id"]
    for row in declinations_for_entry(entry_b_id):
        validate_success(
            api_client.rescind_matter_declination(
                row["id"], rescind_declination_payload(), COUNSEL
            )
        )

    entry_b = read_client_book_entry(entry_b_id)
    assert entry_b["portable_status"] == "VALIDATED"
    assert_money_equals(
        entry_b["validated_portable_amount_usd"],
        EXPECTED_AB_BOOK["entry_b_baseline"],
        "validated_portable_amount_usd",
    )
    assert_money_equals(
        entry_b["baseline_portable_amount_usd"],
        EXPECTED_AB_BOOK["entry_b_baseline"],
        "baseline_portable_amount_usd",
    )

    assert read_conflict_check(ctx["conflict_checks"]["Calder Manufacturing"]["id"])[
        "status"
    ] == "CLEAR"
    assert read_candidate(ctx["candidate"]["id"])["clearance_status"] == "CLEARED"

    assessment = read_assessment(ctx["assessment"]["id"])
    assert_money_equals(
        assessment["gross_baseline_total_usd"],
        EXPECTED_AB_BOOK["gross_baseline_total_usd"],
        "gross_baseline_total_usd",
    )
    assert_money_equals(
        assessment["validated_portable_total_usd"],
        EXPECTED_AB_BOOK["gross_baseline_total_usd"],
        "validated_portable_total_usd",
    )
    assert_money_equals(
        assessment["declined_portable_total_usd"], 0.00, "declined_portable_total_usd"
    )
    assert_money_equals(
        assessment["adjusted_portable_total_usd"],
        EXPECTED_AB_BOOK["adjusted_portable_total_usd"],
        "adjusted_portable_total_usd",
    )
    assert_portable_book_identity(assessment)
    assert assessment["status"] == "STALE"
    assert read_offer(ctx["offer"]["id"])["status"] == "REPRICE_REQUIRED"


def test_a_counter_releases_the_whole_reservation_and_the_resubmit_reserves_the_new_figure():
    """The **guarantee budget identity** holds on every `PracticeGroup`:
    `guarantee_budget_total_usd` always equals `available_guarantee_budget_usd` plus
    `reserved_guarantee_budget_usd` plus `committed_guarantee_total_usd`.
    `reserved_guarantee_budget_usd` is the sum of `guaranteed_comp_usd` over every
    `CompensationOffer` in status `COMMITTEE_REVIEW` whose candidate targets this group;
    `committed_guarantee_total_usd` is the same sum over offers in status `ACCEPTED` for
    candidates targeting this group; and `available_guarantee_budget_usd` is
    `guarantee_budget_total_usd` less both of those.

    Design: Difficulty/compensating_invariant/offer_counter_release_restores_guarantee_budget_identity
    """
    ctx = setup_cleared_candidate("SLIM")
    draft_offer(ctx, chair_headers=CHAIR)
    submit_offer(ctx, eligible_voter_count=3, chair_headers=CHAIR)

    after_submit = read_practice_group(ctx["practice_group"]["id"])
    assert_money_equals(
        after_submit["available_guarantee_budget_usd"], 4500000.00, "available after submit"
    )
    assert_money_equals(
        after_submit["reserved_guarantee_budget_usd"], 500000.00, "reserved after submit"
    )
    assert_money_equals(
        after_submit["committed_guarantee_total_usd"], 0.00, "committed after submit"
    )
    assert_guarantee_budget_identity(after_submit)

    validate_success(
        api_client.counter_offer(ctx["offer"]["id"], counter_offer_payload(), CHAIR)
    )

    after_counter = read_practice_group(ctx["practice_group"]["id"])
    assert_money_equals(
        after_counter["available_guarantee_budget_usd"], 5000000.00, "available after counter"
    )
    assert_money_equals(
        after_counter["reserved_guarantee_budget_usd"], 0.00, "reserved after counter"
    )
    assert_money_equals(
        after_counter["committed_guarantee_total_usd"], 0.00, "committed after counter"
    )
    assert_guarantee_budget_identity(after_counter)

    validate_success(
        api_client.redraft_offer(
            ctx["offer"]["id"],
            redraft_offer_payload(
                guaranteed_comp_usd=600000.00, signing_bonus_usd=50000.00
            ),
            CHAIR,
        )
    )
    validate_success(
        api_client.submit_offer(
            ctx["offer"]["id"], submit_offer_payload(eligible_voter_count=3), CHAIR
        )
    )

    after_resubmit = read_practice_group(ctx["practice_group"]["id"])
    assert_money_equals(
        after_resubmit["available_guarantee_budget_usd"], 4400000.00, "available after resubmit"
    )
    assert_money_equals(
        after_resubmit["reserved_guarantee_budget_usd"], 600000.00, "reserved after resubmit"
    )
    assert_money_equals(
        after_resubmit["committed_guarantee_total_usd"], 0.00, "committed after resubmit"
    )
    assert_guarantee_budget_identity(after_resubmit)


def test_accepting_the_repriced_offer_converts_the_reservation_into_a_commitment():
    """The ledger is maintained incrementally as offers move, but it must always agree
    with those definitions, and it must agree after every release path as well as after
    every reservation.
    `guarantee_true_up_amount_usd` is keyed on that net, on **inclusive** boundaries:
    ten percent of `guaranteed_comp_usd` — a factor of `0.10` — when the net is at least
    `500000.00`, otherwise five percent of `guaranteed_comp_usd` — a factor of `0.05` —
    when the net is at least `0.00`, otherwise `0.00`.

    Design: Difficulty/compensating_invariant/offer_counter_release_restores_guarantee_budget_identity
    """
    ctx = _setup_repriced_offer(600000.00, 50000.00, eligible_voter_count=3)

    cast_vote(ctx, MEMBER_1_USER_ID, "APPROVE")
    cast_vote(ctx, MEMBER_2_USER_ID, "APPROVE")
    finalize_offer(ctx)

    accepted = validate_success(
        api_client.accept_offer(ctx["offer"]["id"], ctx["candidate_headers"])
    )
    assert accepted["status"] == "ACCEPTED"
    assert accepted["round_number"] == 2
    assert_money_equals(accepted["guaranteed_comp_usd"], 600000.00, "guaranteed_comp_usd")
    assert_money_equals(
        accepted["total_first_year_comp_usd"], 650000.00, "total_first_year_comp_usd"
    )
    assert_money_equals(
        accepted["search_fee_amount_usd"], 162500.00, "search_fee_amount_usd"
    )
    assert_money_equals(
        accepted["integration_cost_total_usd"], 273500.00, "integration_cost_total_usd"
    )
    assert_money_equals(
        accepted["net_first_year_economics_usd"], 130481.27, "net_first_year_economics_usd"
    )
    assert_money_equals(
        accepted["guarantee_true_up_amount_usd"], 30000.00, "guarantee_true_up_amount_usd"
    )

    group = read_practice_group(ctx["practice_group"]["id"])
    assert_money_equals(
        group["guarantee_budget_total_usd"], 5000000.00, "guarantee_budget_total_usd"
    )
    assert_money_equals(
        group["available_guarantee_budget_usd"], 4400000.00, "available_guarantee_budget_usd"
    )
    assert_money_equals(
        group["reserved_guarantee_budget_usd"], 0.00, "reserved_guarantee_budget_usd"
    )
    assert_money_equals(
        group["committed_guarantee_total_usd"], 600000.00, "committed_guarantee_total_usd"
    )
    assert_guarantee_budget_identity(group)

    assert read_candidate(ctx["candidate"]["id"])["pipeline_status"] == "HIRED"

    engagement = validate_success(
        api_client.get_search_firm_engagement(ctx["engagement"]["id"], COORDINATOR)
    )
    assert engagement["fee_status"] == "FEE_DUE"
    assert_money_equals(engagement["fee_amount_usd"], 162500.00, "fee_amount_usd")


def test_countering_voids_the_live_ballots_without_reducing_the_cast_total():
    """The **vote ledger identity** holds on every `CompensationOffer`: `votes_cast_total`
    always equals `active_vote_count` plus `voided_vote_count`.
    `active_vote_count` is the number of `CommitteeVote` rows on the offer whose `status`
    is `ACTIVE`; `voided_vote_count` is the number whose `status` is `VOIDED`; and
    `votes_cast_total` counts every vote row on the offer across all rounds and both
    statuses.

    Design: Difficulty/compensating_invariant/counter_voiding_preserves_votes_cast_total_identity
    """
    ctx = setup_offer_in_committee_review("SLIM", eligible_voter_count=3)
    cast_vote(ctx, MEMBER_1_USER_ID, "APPROVE")
    cast_vote(ctx, MEMBER_2_USER_ID, "APPROVE")

    before = read_offer(ctx["offer"]["id"])
    assert before["votes_cast_total"] == 2
    assert before["active_vote_count"] == 2
    assert before["voided_vote_count"] == 0
    assert_vote_ledger_identity(before)

    validate_success(
        api_client.counter_offer(ctx["offer"]["id"], counter_offer_payload(), CHAIR)
    )

    after = read_offer(ctx["offer"]["id"])
    assert after["votes_cast_total"] == 2
    assert after["active_vote_count"] == 0
    assert after["voided_vote_count"] == 2
    assert_vote_ledger_identity(after)


def test_the_second_rounds_ballots_add_to_a_cast_total_that_never_went_down():
    """Because a negotiation round reset voids votes rather than deleting them,
    `votes_cast_total` never decreases.

    Design: Difficulty/compensating_invariant/counter_voiding_preserves_votes_cast_total_identity
    """
    ctx = setup_offer_in_committee_review("SLIM", eligible_voter_count=3)
    cast_vote(ctx, MEMBER_1_USER_ID, "APPROVE")
    cast_vote(ctx, MEMBER_2_USER_ID, "APPROVE")

    _reprice_after_counter(ctx, 450000.00, 50000.00, eligible_voter_count=3)

    cast_vote(ctx, MEMBER_1_USER_ID, "APPROVE")
    cast_vote(ctx, MEMBER_2_USER_ID, "APPROVE")
    cast_vote(ctx, MEMBER_3_USER_ID, "APPROVE")

    finalized = finalize_offer(ctx)

    assert finalized["status"] == "APPROVED"
    assert finalized["round_number"] == 2
    assert finalized["votes_cast_total"] == 5
    assert finalized["active_vote_count"] == 3
    assert finalized["voided_vote_count"] == 2
    assert_vote_ledger_identity(finalized)

    assert_money_equals(finalized["guaranteed_comp_usd"], 450000.00, "guaranteed_comp_usd")
    assert_money_equals(
        finalized["total_first_year_comp_usd"], 500000.00, "total_first_year_comp_usd"
    )
    assert_money_equals(
        finalized["integration_cost_total_usd"], 230000.00, "integration_cost_total_usd"
    )
    assert_money_equals(
        finalized["net_first_year_economics_usd"], 323981.27, "net_first_year_economics_usd"
    )
    assert_money_equals(
        finalized["guarantee_true_up_amount_usd"], 22500.00, "guarantee_true_up_amount_usd"
    )

    assert read_candidate(ctx["candidate"]["id"])["pipeline_status"] == "OFFER_OUT"

    group = read_practice_group(ctx["practice_group"]["id"])
    assert_money_equals(
        group["reserved_guarantee_budget_usd"], 450000.00, "reserved_guarantee_budget_usd"
    )
    assert_money_equals(
        group["available_guarantee_budget_usd"], 4550000.00, "available_guarantee_budget_usd"
    )


# ----------------------------------------------------------------------
# Local scenario glue
# ----------------------------------------------------------------------


def _setup_blocked_entry_b():
    """AB BOOK with entry A cleared and an offer under review, then entry B blocked
    through a refused waiver so it carries two ACTIVE declinations."""
    ctx = setup_assessed_candidate("AB")
    open_conflict_check(ctx, "Northwind Holdings")
    clear_conflict_check(ctx, "Northwind Holdings")
    draft_offer(ctx, guaranteed_comp_usd=850000.00, signing_bonus_usd=100000.00)
    submit_offer(ctx, eligible_voter_count=3)
    cast_vote(ctx, MEMBER_1_USER_ID, "APPROVE")
    cast_vote(ctx, MEMBER_2_USER_ID, "APPROVE")
    block_entry_through_refused_waiver(ctx, "Calder Manufacturing")
    return ctx


def _reprice_after_counter(ctx, guaranteed, signing, eligible_voter_count):
    """Counter the offer under review, redraft it at a new package, and resubmit."""
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
            ctx["offer"]["id"],
            submit_offer_payload(eligible_voter_count=eligible_voter_count),
            CHAIR,
        )
    )
    return ctx["offer"]


def _setup_repriced_offer(guaranteed, signing, eligible_voter_count):
    """A cleared candidate whose offer has been countered once and resubmitted in
    round 2 at a new package."""
    ctx = setup_cleared_candidate("SLIM")
    draft_offer(ctx, chair_headers=CHAIR)
    submit_offer(ctx, eligible_voter_count=eligible_voter_count, chair_headers=CHAIR)
    _reprice_after_counter(ctx, guaranteed, signing, eligible_voter_count)
    return ctx
