"""Calculation scope and clamping: which rows feed the assessment, where the placement
fee stops growing, and what a second assessment does to the first."""

from test_helpers import (
    MEMBER_1_USER_ID,
    MEMBER_2_USER_ID,
    TEST_USERS,
    api_client,
    append_collection_record,
    assert_instant_equals,
    assert_money_equals,
    assert_ratio_equals,
    cast_vote,
    create_assessment,
    create_client_book_entry_payload,
    draft_offer,
    finalize_offer,
    read_assessment,
    read_candidate,
    read_client_book_entry,
    read_practice_group,
    read_questionnaire,
    setup_book,
    setup_cleared_candidate,
    setup_questionnaire_in_draft,
    setup_questionnaire_under_review,
    submit_offer,
    validate_paginated,
    validate_success,
)

COORDINATOR = TEST_USERS["recruiting_coordinator_headers"]


def test_the_assessment_reads_only_verified_in_window_historical_rows_on_active_entries():
    """Begin with the *historical base*: the sum of `amount_usd` across that entry's
    collection records whose `record_type` is `HISTORICAL`, whose `status` is `VERIFIED`,
    and whose `period_end_date` lies in the half-open evidence window.
    Entries whose `status` is `WITHDRAWN` are excluded from the scope entirely and are not
    tested for evidence.
    The entry's third computed field, `verified_record_count`, counts the collection
    records attached to this entry whose `record_type` is `HISTORICAL` and whose `status`
    is `VERIFIED`; it is the evidence counter that the validation step in §3.4 tests
    against a floor of three.

    Design: Corner/calculations/assessment_ignores_unverified_out_of_window_and_withdrawn_book_rows
    """
    ctx = setup_questionnaire_in_draft()
    setup_book(ctx, "SLIM")
    entry_a = ctx["entries"]["Northwind Holdings"]

    # Four decoys that must not reach the historical base.
    for record_type, period_end_date, status in (
        ("HISTORICAL", "2025-06-30T00:00:00.000Z", "UNVERIFIED"),
        ("HISTORICAL", "2023-01-31T00:00:00.000Z", "VERIFIED"),
        ("HISTORICAL", "2026-07-01T00:00:00.000Z", "VERIFIED"),
        ("POST_HIRE", "2026-06-30T00:00:00.000Z", "VERIFIED"),
    ):
        append_collection_record(
            ctx["candidate"]["id"],
            entry_a["id"],
            record_type=record_type,
            period_end_date=period_end_date,
            amount_usd=5000000.00,
            status=status,
        )

    withdrawn = validate_success(
        api_client.create_client_book_entry(
            ctx["questionnaire"]["id"],
            create_client_book_entry_payload(client_name="Ridgeline Foods"),
            ctx["candidate_headers"],
        ),
        expected_status=201,
    )
    validate_success(
        api_client.delete_client_book_entry(withdrawn["id"], ctx["candidate_headers"])
    )

    # The book is disclosed and pruned while the LPQ is still DRAFT — the state PRD
    # makes the client book mutable in — then the LPQ walks DRAFT -> SUBMITTED ->
    # UNDER_REVIEW, which is what an assessment requires.
    ctx["questionnaire"] = validate_success(
        api_client.submit_questionnaire(
            ctx["questionnaire"]["id"], ctx["candidate_headers"]
        )
    )
    ctx["questionnaire"] = validate_success(
        api_client.start_review_questionnaire(ctx["questionnaire"]["id"], COORDINATOR)
    )

    assessment = create_assessment(ctx, governing_basis="VALIDATED")

    assert assessment["status"] == "CURRENT"
    assert_instant_equals(
        assessment["lookback_start_date"],
        "2023-07-01T00:00:00.000Z",
        "lookback_start_date",
    )
    assert assessment["entry_count_in_scope"] == 1

    entry = read_client_book_entry(entry_a["id"])
    # Two of the decoys are HISTORICAL and VERIFIED, so the raw evidence counter sees
    # five rows even though only three of them sit inside the evidence window.
    assert entry["verified_record_count"] == 5
    assert_money_equals(
        entry["baseline_portable_amount_usd"], 1269000.00, "baseline_portable_amount_usd"
    )
    assert_money_equals(
        entry["validated_portable_amount_usd"],
        1269000.00,
        "validated_portable_amount_usd",
    )
    assert entry["portable_status"] == "VALIDATED"

    ridgeline = read_client_book_entry(withdrawn["id"])
    assert ridgeline["status"] == "WITHDRAWN"
    assert ridgeline["portable_status"] == "UNVALIDATED"

    assert_money_equals(
        assessment["gross_baseline_total_usd"], 1269000.00, "gross_baseline_total_usd"
    )
    assert_money_equals(
        assessment["self_reported_total_usd"], 1280000.00, "self_reported_total_usd"
    )
    assert_ratio_equals(assessment["variance_pct"], 0.0086, "variance_pct")
    assert_ratio_equals(assessment["top_client_share"], 1.0000, "top_client_share")
    assert assessment["concentration_grade"] == "HIGH"
    assert_money_equals(
        assessment["adjusted_portable_total_usd"],
        1078650.00,
        "adjusted_portable_total_usd",
    )
    assert read_questionnaire(ctx["questionnaire"]["id"])["entry_count"] == 1


def test_the_placement_fee_stops_at_the_engagement_cap_all_the_way_through_the_hire():
    """The fee base is `total_first_year_comp_usd`, that is guaranteed compensation *and*
    signing bonus together, multiplied by the engagement's `fee_pct` and rounded half up
    to two decimal places.
    `integration_cost_total_usd` is the sum of four terms: `search_fee_amount_usd`, a
    fixed office build-out charge of `50000.00`, a fixed paralegal support charge of
    `35000.00`, and an onboarding overhead of four percent — a factor of `0.04` — of
    `total_first_year_comp_usd` rounded half up to two decimal places before being added.

    Design: Corner/calculations/search_fee_is_clamped_by_the_engagement_fee_cap_at_hire
    """
    ctx = setup_cleared_candidate("SLIM")
    draft_offer(ctx, guaranteed_comp_usd=1600000.00, signing_bonus_usd=100000.00)
    submit_offer(ctx, eligible_voter_count=3)
    cast_vote(ctx, MEMBER_1_USER_ID, "APPROVE")
    cast_vote(ctx, MEMBER_2_USER_ID, "APPROVE")
    finalize_offer(ctx)

    accepted = validate_success(
        api_client.accept_offer(ctx["offer"]["id"], ctx["candidate_headers"])
    )

    assert_money_equals(
        accepted["total_first_year_comp_usd"], 1700000.00, "total_first_year_comp_usd"
    )
    assert_money_equals(
        accepted["search_fee_amount_usd"], 400000.00, "search_fee_amount_usd"
    )
    # 425000.00 is the uncapped 0.2500 x 1700000.00 figure.
    assert abs(float(accepted["search_fee_amount_usd"]) - 425000.00) > 0.005
    assert_money_equals(
        accepted["integration_cost_total_usd"], 553000.00, "integration_cost_total_usd"
    )
    assert_money_equals(
        accepted["expected_contribution_usd"], 1053981.27, "expected_contribution_usd"
    )
    assert_money_equals(
        accepted["net_first_year_economics_usd"],
        -1199018.73,
        "net_first_year_economics_usd",
    )
    assert accepted["status"] == "ACCEPTED"

    engagement = validate_success(
        api_client.get_search_firm_engagement(ctx["engagement"]["id"], COORDINATOR)
    )
    assert engagement["fee_basis"] == "DIRECT_PLACEMENT"
    assert_money_equals(engagement["fee_amount_usd"], 400000.00, "fee_amount_usd")
    assert engagement["fee_status"] == "FEE_DUE"

    candidate = read_candidate(ctx["candidate"]["id"])
    assert candidate["pipeline_status"] == "HIRED"
    assert_instant_equals(candidate["hire_date"], "2026-08-01T00:00:00.000Z", "hire_date")
    assert_instant_equals(
        candidate["earliest_start_date"], "2026-09-15T00:00:00.000Z", "earliest_start_date"
    )

    group = read_practice_group(ctx["practice_group"]["id"])
    assert_money_equals(
        group["reserved_guarantee_budget_usd"], 0.00, "reserved_guarantee_budget_usd"
    )
    assert_money_equals(
        group["committed_guarantee_total_usd"], 1600000.00, "committed_guarantee_total_usd"
    )
    assert_money_equals(
        group["available_guarantee_budget_usd"], 3400000.00, "available_guarantee_budget_usd"
    )


def test_the_validated_rerun_supersedes_the_self_reported_basis_and_takes_the_pointer():
    """Under `SELF_REPORTED` the governing total is `self_reported_total_usd`: it is built
    purely from `claimed_annual_billings_usd` and `claimed_portability_pct`, and it
    therefore ignores the role factor, the consent factor, the realization ceiling, the
    portability ceiling, and every collection record in the system.
    **Supersession and staleness.** Creating an assessment writes it with `status`
    `CURRENT`, turns every earlier assessment on the same questionnaire whose `status` is
    `CURRENT` or `STALE` to `SUPERSEDED`, writes the new assessment's identifier into the
    questionnaire's `latest_assessment_id`, and increments the questionnaire's `version`
    by 1.

    Design: Corner/calculations/a_newer_assessment_supersedes_the_prior_basis_and_rewrites_the_pointer
    """
    ctx = setup_questionnaire_under_review("SLIM")
    first = create_assessment(ctx, governing_basis="SELF_REPORTED")
    assert first["status"] == "CURRENT"

    second = create_assessment(ctx, governing_basis="VALIDATED")

    superseded = read_assessment(first["id"])
    assert superseded["status"] == "SUPERSEDED"
    assert superseded["governing_basis"] == "SELF_REPORTED"
    assert_money_equals(
        superseded["self_reported_total_usd"], 1280000.00, "self_reported_total_usd"
    )
    assert_money_equals(
        superseded["adjusted_portable_total_usd"],
        1088000.00,
        "self-reported adjusted total",
    )

    assert second["status"] == "CURRENT"
    assert second["governing_basis"] == "VALIDATED"
    assert_money_equals(
        second["validated_portable_total_usd"],
        1269000.00,
        "validated_portable_total_usd",
    )
    assert_money_equals(
        second["adjusted_portable_total_usd"],
        1078650.00,
        "validated adjusted total",
    )
    assert_ratio_equals(
        second["concentration_haircut_pct"], 0.15, "concentration_haircut_pct"
    )

    assert (
        read_questionnaire(ctx["questionnaire"]["id"])["latest_assessment_id"]
        == second["id"]
    )

    _rows, meta = validate_paginated(
        api_client.list_portability_assessments(
            COORDINATOR, params={"questionnaire_id": ctx["questionnaire"]["id"]}
        )
    )
    assert meta["total_count"] == 2
