"""Composite formulas: the interacting ceilings inside one entry, per-entry rounding
before summation, and the pinned five-step offer economics."""

from test_helpers import (
    EXPECTED_FULL_BOOK,
    EXPECTED_SLIM_OFFER,
    TEST_USERS,
    add_book_entry,
    api_client,
    assert_compensation_offer,
    assert_instant_equals,
    assert_money_equals,
    assert_ratio_equals,
    create_assessment,
    draft_offer,
    read_candidate,
    read_client_book_entry,
    setup_cleared_candidate,
    setup_questionnaire_in_draft,
    setup_questionnaire_under_review,
    validate_success,
)

COORDINATOR = TEST_USERS["recruiting_coordinator_headers"]


def test_the_portability_ceiling_and_the_realization_ceiling_bind_on_different_entries():
    """Multiply the average annual collections by the role factor, by the consent
    factor, and by that realization figure, all at full precision. Then apply a hard
    portability ceiling: the result is replaced by the smaller of itself and 90 percent
    of the entry's average annual collections.
    The **realization** input is the lesser of the entry's `claimed_realization_rate`
    and a firm-wide realization ceiling of `0.95`, so a candidate claiming full
    realization is trimmed to that ceiling.

    Design: Difficulty/combinatorial_formula/entry_amount_hard_cap_and_realization_cap_interact_non_linearly
    """
    ctx = setup_questionnaire_under_review("FULL")
    create_assessment(ctx, governing_basis="VALIDATED")

    entry_a = read_client_book_entry(ctx["entries"]["Northwind Holdings"]["id"])
    entry_b = read_client_book_entry(ctx["entries"]["Calder Manufacturing"]["id"])
    entry_c = read_client_book_entry(ctx["entries"]["Ridgeline Foods"]["id"])

    assert_money_equals(
        entry_a["baseline_portable_amount_usd"],
        EXPECTED_FULL_BOOK["entry_a_baseline"],
        "entry A baseline_portable_amount_usd",
    )
    assert_money_equals(
        entry_b["baseline_portable_amount_usd"],
        EXPECTED_FULL_BOOK["entry_b_baseline"],
        "entry B baseline_portable_amount_usd",
    )
    assert_money_equals(
        entry_c["baseline_portable_amount_usd"],
        EXPECTED_FULL_BOOK["entry_c_baseline"],
        "entry C baseline_portable_amount_usd",
    )

    # The 90-percent portability ceiling bit on entry A: the unclamped product would
    # have been 1339500.00.
    assert abs(float(entry_a["baseline_portable_amount_usd"]) - 1339500.00) > 0.005
    # The 0.95 realization ceiling bit on entry C: the claimed 0.99 would have given
    # 228690.00.
    assert abs(float(entry_c["baseline_portable_amount_usd"]) - 228690.00) > 0.005


def test_the_valuation_scope_and_evidence_window_are_derived_from_the_baseline_date():
    """From it the system derives `lookback_start_date` as the `baseline_date` moved
    back by three calendar years, equivalently thirty-six months, and that lower bound
    is **inclusive**.
    The assessment records how many entries it covered in `entry_count_in_scope`, which
    is the count of `ACTIVE` entries on the questionnaire at the moment the assessment
    ran.

    Design: Difficulty/combinatorial_formula/entry_amount_hard_cap_and_realization_cap_interact_non_linearly
    """
    ctx = setup_questionnaire_under_review("FULL")
    assessment = create_assessment(ctx, governing_basis="VALIDATED")

    assert_instant_equals(
        assessment["lookback_start_date"],
        "2023-07-01T00:00:00.000Z",
        "lookback_start_date",
    )
    assert assessment["entry_count_in_scope"] == 3
    assert_money_equals(
        assessment["gross_baseline_total_usd"],
        EXPECTED_FULL_BOOK["gross_baseline_total_usd"],
        "gross_baseline_total_usd",
    )

    entry_a = read_client_book_entry(ctx["entries"]["Northwind Holdings"]["id"])
    assert entry_a["portable_status"] == "VALIDATED"
    assert entry_a["verified_record_count"] == 3


def test_each_entry_is_rounded_once_before_the_book_total_adds_it_in():
    """That final value, and only that value, is rounded — half up, to two decimal
    places, exactly once — and written to `baseline_portable_amount_usd`.
    In every one of those four totals the summands are already rounded to two decimal
    places and **the total itself is not rounded again**; summing at full precision and
    rounding once at the end produces a different number of cents and is not what this
    specification asks for.

    Design: Difficulty/combinatorial_formula/book_totals_round_per_entry_then_sum_never_sum_then_round
    """
    ctx = _setup_half_cent_book()
    assessment = create_assessment(ctx, governing_basis="VALIDATED")

    pemberton = read_client_book_entry(ctx["entries"]["Pemberton Group"]["id"])
    quill = read_client_book_entry(ctx["entries"]["Quill Industries"]["id"])

    assert_money_equals(
        pemberton["baseline_portable_amount_usd"], 285000.29, "Pemberton baseline"
    )
    assert_money_equals(quill["baseline_portable_amount_usd"], 171000.29, "Quill baseline")

    assert_money_equals(
        assessment["gross_baseline_total_usd"], 456000.58, "gross_baseline_total_usd"
    )
    assert abs(float(assessment["gross_baseline_total_usd"]) - 456000.57) > 0.005
    assert_money_equals(
        assessment["validated_portable_total_usd"],
        456000.58,
        "validated_portable_total_usd",
    )


def test_the_self_reported_total_rounds_per_line_before_it_is_added_up():
    """And `self_reported_total_usd` is the sum, over the same entries, of each entry's
    `claimed_annual_billings_usd` multiplied by its `claimed_portability_pct` and
    rounded half up to two decimal places **per line** before being added in.

    Design: Difficulty/combinatorial_formula/book_totals_round_per_entry_then_sum_never_sum_then_round
    """
    ctx = _setup_half_cent_book()
    assessment = create_assessment(ctx, governing_basis="VALIDATED")

    assert_money_equals(
        assessment["self_reported_total_usd"], 2000000.02, "self_reported_total_usd"
    )
    assert abs(float(assessment["self_reported_total_usd"]) - 2000000.01) > 0.005

    assert_ratio_equals(assessment["variance_pct"], 0.7720, "variance_pct")
    assert_ratio_equals(assessment["top_client_share"], 0.6250, "top_client_share")
    assert assessment["concentration_grade"] == "HIGH"
    assert_money_equals(
        assessment["adjusted_portable_total_usd"],
        387600.49,
        "adjusted_portable_total_usd",
    )


def test_the_offer_economics_evaluate_in_the_pinned_five_step_order():
    """`total_first_year_comp_usd` is `guaranteed_comp_usd` plus `signing_bonus_usd`.
    It **excludes** `guarantee_true_up_amount_usd` entirely; this exclusion is the cut
    that makes the graph acyclic.
    `integration_cost_total_usd` is the sum of four terms: `search_fee_amount_usd`, a
    fixed office build-out charge of `50000.00`, a fixed paralegal support charge of
    `35000.00`, and an onboarding overhead of four percent — a factor of `0.04` — of
    `total_first_year_comp_usd` rounded half up to two decimal places before being
    added.

    Design: Difficulty/combinatorial_formula/net_first_year_economics_pinned_evaluation_order_breaks_the_cycle
    """
    ctx = setup_cleared_candidate("SLIM")
    offer = draft_offer(ctx)

    assert_compensation_offer(offer)
    assert_money_equals(
        offer["adjusted_portable_total_snapshot_usd"],
        EXPECTED_SLIM_OFFER["adjusted_portable_total_snapshot_usd"],
        "adjusted_portable_total_snapshot_usd",
    )
    assert_money_equals(
        offer["expected_contribution_usd"],
        EXPECTED_SLIM_OFFER["expected_contribution_usd"],
        "expected_contribution_usd",
    )
    assert_money_equals(
        offer["total_first_year_comp_usd"],
        EXPECTED_SLIM_OFFER["total_first_year_comp_usd"],
        "total_first_year_comp_usd",
    )
    # 575000.00 is what folding the true-up into step 1 would have produced.
    assert abs(float(offer["total_first_year_comp_usd"]) - 575000.00) > 0.005
    assert_money_equals(
        offer["search_fee_amount_usd"],
        EXPECTED_SLIM_OFFER["search_fee_amount_usd"],
        "search_fee_amount_usd",
    )
    # 143750.00 is the fee a comp base contaminated by the true-up would have produced.
    assert abs(float(offer["search_fee_amount_usd"]) - 143750.00) > 0.005
    assert_money_equals(
        offer["integration_cost_total_usd"],
        EXPECTED_SLIM_OFFER["integration_cost_total_usd"],
        "integration_cost_total_usd",
    )


def test_the_true_up_is_keyed_on_the_net_and_feeds_back_into_nothing():
    """`net_first_year_economics_usd` is `expected_contribution_usd` less
    `total_first_year_comp_usd` less `integration_cost_total_usd`, rounded half up to
    two decimal places.
    `guarantee_true_up_amount_usd` is keyed on that net, on **inclusive** boundaries:
    ten percent of `guaranteed_comp_usd` — a factor of `0.10` — when the net is at
    least `500000.00`, otherwise five percent of `guaranteed_comp_usd` — a factor of
    `0.05` — when the net is at least `0.00`, otherwise `0.00`.

    Design: Difficulty/combinatorial_formula/net_first_year_economics_pinned_evaluation_order_breaks_the_cycle
    """
    ctx = setup_cleared_candidate("SLIM")
    offer = draft_offer(ctx)

    assert_money_equals(
        offer["net_first_year_economics_usd"],
        EXPECTED_SLIM_OFFER["net_first_year_economics_usd"],
        "net_first_year_economics_usd",
    )
    assert_money_equals(
        offer["guarantee_true_up_amount_usd"],
        EXPECTED_SLIM_OFFER["guarantee_true_up_amount_usd"],
        "guarantee_true_up_amount_usd",
    )
    assert offer["status"] == "DRAFTED"
    assert offer["round_number"] == 1

    candidate = read_candidate(ctx["candidate"]["id"])
    assert candidate["open_offer_id"] == offer["id"]


# ----------------------------------------------------------------------
# Local scenario glue
# ----------------------------------------------------------------------

PEMBERTON_SPEC = {
    "client_name": "Pemberton Group",
    "relationship_role": "BILLING_ATTORNEY",
    "client_consent_status": "CONSENT_PENDING",
    "claimed_annual_billings_usd": 2500000.01,
    "claimed_portability_pct": 0.5000,
    "claimed_realization_rate": 1.0000,
    "matter_types": ["M_AND_A"],
}
PEMBERTON_RECORDS = [
    ("2023-12-31T00:00:00.000Z", 500000.50),
    ("2024-12-31T00:00:00.000Z", 500000.50),
    ("2025-12-31T00:00:00.000Z", 500000.50),
]

QUILL_SPEC = {
    "client_name": "Quill Industries",
    "relationship_role": "BILLING_ATTORNEY",
    "client_consent_status": "CONSENT_PENDING",
    "claimed_annual_billings_usd": 1500000.01,
    "claimed_portability_pct": 0.5000,
    "claimed_realization_rate": 1.0000,
    "matter_types": ["LITIGATION"],
}
QUILL_RECORDS = [
    ("2023-12-31T00:00:00.000Z", 300000.50),
    ("2024-12-31T00:00:00.000Z", 300000.50),
    ("2025-12-31T00:00:00.000Z", 300000.50),
]


def _setup_half_cent_book():
    """Two entries whose per-entry raw amounts each land on exactly half a cent."""
    ctx = setup_questionnaire_in_draft()
    add_book_entry(ctx, PEMBERTON_SPEC, PEMBERTON_RECORDS)
    add_book_entry(ctx, QUILL_SPEC, QUILL_RECORDS)
    ctx["questionnaire"] = validate_success(
        api_client.submit_questionnaire(
            ctx["questionnaire"]["id"], ctx["candidate_headers"]
        )
    )
    ctx["questionnaire"] = validate_success(
        api_client.start_review_questionnaire(ctx["questionnaire"]["id"], COORDINATOR)
    )
    return ctx
