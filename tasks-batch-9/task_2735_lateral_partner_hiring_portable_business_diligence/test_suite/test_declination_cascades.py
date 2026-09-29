"""The declination cascade, reached twice: by a counsel's refusal and by a deadline
lapsing on a clock tick."""

from test_helpers import (
    EXPECTED_AB_BOOK,
    EXPECTED_ENTRY_B_DECLINATION,
    MEMBER_1_USER_ID,
    MEMBER_2_USER_ID,
    TEST_USERS,
    api_client,
    assert_instant_equals,
    assert_money_equals,
    assert_portable_book_identity,
    cast_vote,
    clear_conflict_check,
    create_conflict_waiver_payload,
    declinations_for_entry,
    draft_offer,
    open_conflict_check,
    read_assessment,
    read_candidate,
    read_client_book_entry,
    read_conflict_check,
    read_offer,
    read_practice_group,
    refuse_waiver_payload,
    set_logical_clock,
    setup_assessed_candidate,
    submit_offer,
    validate_success,
)

COUNSEL = TEST_USERS["conflicts_counsel_headers"]


def test_a_refused_waiver_blocks_the_check_and_declines_every_matter_on_the_entry():
    """**Hop 3**, caused by the check blocking — the client book entry moves
    `portable_status` `VALIDATED → DECLINED`; its `validated_portable_amount_usd` is set
    to `0.00` while its `baseline_portable_amount_usd` is left **unchanged**, which is
    precisely how the portable-book identity survives; one `MatterDeclination` row is
    created per element of the entry's `matter_types` array; and the candidate's
    `clearance_status` becomes `BLOCKED`.
    Each declination row then receives the per-matter share, and the row corresponding
    to the **first element of the `matter_types` array** additionally receives the entire
    remainder.

    Design: Difficulty/transitive_cascade/waiver_refusal_propagates_five_hops_to_offer_reprice
    """
    ctx = _setup_reprice_scenario()

    refused = validate_success(
        api_client.refuse_conflict_waiver(
            ctx["waiver"]["id"], refuse_waiver_payload(), COUNSEL
        )
    )
    assert refused["status"] == "REFUSED"
    assert_instant_equals(refused["decided_at"], "2026-08-01T00:00:00.000Z", "decided_at")

    assert read_conflict_check(ctx["conflict_checks"]["Calder Manufacturing"]["id"])[
        "status"
    ] == "BLOCKED"
    assert read_conflict_check(ctx["conflict_checks"]["Northwind Holdings"]["id"])[
        "status"
    ] == "CLEAR"

    entry_b = read_client_book_entry(ctx["entries"]["Calder Manufacturing"]["id"])
    assert entry_b["portable_status"] == "DECLINED"
    assert_money_equals(entry_b["validated_portable_amount_usd"], 0.00, "validated amount")
    assert_money_equals(
        entry_b["baseline_portable_amount_usd"],
        EXPECTED_AB_BOOK["entry_b_baseline"],
        "baseline amount",
    )

    entry_a = read_client_book_entry(ctx["entries"]["Northwind Holdings"]["id"])
    assert_money_equals(
        entry_a["validated_portable_amount_usd"],
        EXPECTED_AB_BOOK["entry_a_baseline"],
        "entry A validated amount",
    )

    shares = {
        row["matter_type"]: row["foregone_annual_revenue_usd"]
        for row in declinations_for_entry(entry_b["id"])
    }
    assert set(shares) == set(EXPECTED_ENTRY_B_DECLINATION)
    for matter_type, expected in EXPECTED_ENTRY_B_DECLINATION.items():
        assert_money_equals(shares[matter_type], expected, f"{matter_type} share")

    candidate = read_candidate(ctx["candidate"]["id"])
    assert candidate["clearance_status"] == "BLOCKED"
    assert candidate["pipeline_status"] == "DILIGENCE"


def test_a_refused_waiver_stales_the_assessment_and_reprices_the_offer_under_review():
    """**Hop 4**, caused by the entry being declined — every assessment on that entry's
    questionnaire whose `status` is `CURRENT` moves to `STALE`, recomputing
    `validated_portable_total_usd`, `declined_portable_total_usd`, and
    `adjusted_portable_total_usd`.
    **Hop 5**, caused by the assessment going stale — every compensation offer priced
    against that assessment whose `status` is `COMMITTEE_REVIEW` moves to
    `REPRICE_REQUIRED`, voiding its live votes and releasing its guarantee reservation
    as described in §3.6.

    Design: Difficulty/transitive_cascade/waiver_refusal_propagates_five_hops_to_offer_reprice
    """
    ctx = _setup_reprice_scenario()

    group_before = read_practice_group(ctx["practice_group"]["id"])
    assert_money_equals(
        group_before["reserved_guarantee_budget_usd"], 850000.00, "reserved before"
    )
    assert_money_equals(
        group_before["available_guarantee_budget_usd"], 4150000.00, "available before"
    )

    validate_success(
        api_client.refuse_conflict_waiver(
            ctx["waiver"]["id"], refuse_waiver_payload(), COUNSEL
        )
    )

    assessment = read_assessment(ctx["assessment"]["id"])
    assert assessment["status"] == "STALE"
    assert_money_equals(
        assessment["gross_baseline_total_usd"],
        EXPECTED_AB_BOOK["gross_baseline_total_usd"],
        "gross_baseline_total_usd",
    )
    assert_money_equals(
        assessment["validated_portable_total_usd"],
        EXPECTED_AB_BOOK["entry_a_baseline"],
        "validated_portable_total_usd",
    )
    assert_money_equals(
        assessment["declined_portable_total_usd"],
        EXPECTED_AB_BOOK["entry_b_baseline"],
        "declined_portable_total_usd",
    )
    assert_money_equals(
        assessment["adjusted_portable_total_usd"], 1078650.00, "adjusted_portable_total_usd"
    )
    assert_portable_book_identity(assessment)

    offer = read_offer(ctx["offer"]["id"])
    assert offer["status"] == "REPRICE_REQUIRED"
    assert offer["active_vote_count"] == 0
    assert offer["voided_vote_count"] == 2
    assert offer["votes_cast_total"] == 2

    group = read_practice_group(ctx["practice_group"]["id"])
    assert_money_equals(group["reserved_guarantee_budget_usd"], 0.00, "reserved after")
    assert_money_equals(
        group["available_guarantee_budget_usd"], 5000000.00, "available after"
    )


def test_a_lapsed_deadline_runs_the_identical_cascade_on_a_clock_tick():
    """**Expired**: on a clock move, any waiver still in `REQUESTED` whose
    `response_deadline_date` is strictly earlier than the new clock instant becomes
    `REQUESTED → EXPIRED` with `decided_at` set to the new clock, and it runs the
    *identical* downstream cascade as a refusal.

    Design: Difficulty/transitive_cascade/waiver_deadline_lapse_on_one_clock_tick_drives_two_disjoint_cascades
    """
    ctx = _setup_reprice_scenario()

    set_logical_clock("2027-03-01T00:00:00.000Z")

    waiver = validate_success(
        api_client.get_conflict_waiver(ctx["waiver"]["id"], COUNSEL)
    )
    assert waiver["status"] == "EXPIRED"
    assert_instant_equals(waiver["decided_at"], "2027-03-01T00:00:00.000Z", "decided_at")

    assert read_conflict_check(ctx["conflict_checks"]["Calder Manufacturing"]["id"])[
        "status"
    ] == "BLOCKED"

    entry_b = read_client_book_entry(ctx["entries"]["Calder Manufacturing"]["id"])
    assert entry_b["portable_status"] == "DECLINED"
    assert_money_equals(entry_b["validated_portable_amount_usd"], 0.00, "validated amount")

    shares = {
        row["matter_type"]: row["foregone_annual_revenue_usd"]
        for row in declinations_for_entry(entry_b["id"])
    }
    for matter_type, expected in EXPECTED_ENTRY_B_DECLINATION.items():
        assert_money_equals(shares[matter_type], expected, f"{matter_type} share")

    assessment = read_assessment(ctx["assessment"]["id"])
    assert assessment["status"] == "STALE"
    assert_money_equals(
        assessment["adjusted_portable_total_usd"], 1078650.00, "adjusted_portable_total_usd"
    )

    offer = read_offer(ctx["offer"]["id"])
    assert offer["status"] == "REPRICE_REQUIRED"
    assert offer["active_vote_count"] == 0
    assert offer["voided_vote_count"] == 2

    group = read_practice_group(ctx["practice_group"]["id"])
    assert_money_equals(group["reserved_guarantee_budget_usd"], 0.00, "reserved after")
    assert_money_equals(
        group["available_guarantee_budget_usd"], 5000000.00, "available after"
    )

    candidate = read_candidate(ctx["candidate"]["id"])
    assert candidate["clearance_status"] == "BLOCKED"
    assert candidate["pipeline_status"] == "DILIGENCE"


def test_the_same_clock_tick_expires_the_engagement_on_a_disjoint_path():
    """When the logical clock is moved, every engagement whose `status` is `ACTIVE` and
    whose `exclusivity_end_date` advanced by its `tail_off_days` days falls **at or
    before** the new clock instant transitions `ACTIVE → EXPIRED`.
    Expiry leaves `fee_status` untouched, so a fee that had already crystallised as
    `FEE_DUE` survives the engagement's own expiry.

    Design: Difficulty/transitive_cascade/waiver_deadline_lapse_on_one_clock_tick_drives_two_disjoint_cascades
    """
    ctx = _setup_reprice_scenario()

    set_logical_clock("2027-03-01T00:00:00.000Z")

    engagement = validate_success(
        api_client.get_search_firm_engagement(
            ctx["engagement"]["id"], TEST_USERS["recruiting_coordinator_headers"]
        )
    )
    assert engagement["status"] == "EXPIRED"
    assert engagement["fee_status"] == "NOT_DUE"
    assert engagement["fee_basis"] == "NONE"
    assert_money_equals(engagement["fee_amount_usd"], 0.00, "fee_amount_usd")

    # The waiver path ran independently in the same tick.
    assert validate_success(
        api_client.get_conflict_waiver(ctx["waiver"]["id"], COUNSEL)
    )["status"] == "EXPIRED"


# ----------------------------------------------------------------------
# Local scenario glue
# ----------------------------------------------------------------------


def _setup_reprice_scenario():
    """AB BOOK assessed, entry A cleared, an offer of 850000.00 + 100000.00 in
    COMMITTEE_REVIEW carrying two APPROVE votes, and a second IMPUTED check on entry B
    waiting on a REQUESTED waiver."""
    ctx = setup_assessed_candidate("AB")

    open_conflict_check(ctx, "Northwind Holdings")
    clear_conflict_check(ctx, "Northwind Holdings")

    draft_offer(ctx, guaranteed_comp_usd=850000.00, signing_bonus_usd=100000.00)
    submit_offer(ctx, eligible_voter_count=3)
    cast_vote(ctx, MEMBER_1_USER_ID, "APPROVE")
    cast_vote(ctx, MEMBER_2_USER_ID, "APPROVE")

    check_b = open_conflict_check(ctx, "Calder Manufacturing", severity="IMPUTED")
    ctx["waiver"] = validate_success(
        api_client.create_conflict_waiver(
            check_b["id"],
            create_conflict_waiver_payload(
                requested_from_client="Calder Manufacturing",
                response_deadline_date="2026-09-01T00:00:00.000Z",
            ),
            COUNSEL,
        ),
        expected_status=201,
    )
    ctx["conflict_checks"]["Calder Manufacturing"] = read_conflict_check(check_b["id"])
    return ctx
