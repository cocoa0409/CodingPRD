"""Dual-variant pricing: the two valuation bases, the two placement-fee bases,
and the two performance-variance bases."""

from test_helpers import (
    EXPECTED_FULL_BOOK,
    EXPECTED_SLIM_OFFER,
    add_performance_review,
    append_collection_record,
    assert_instant_equals,
    assert_money_equals,
    assert_portability_assessment,
    assert_ratio_equals,
    create_assessment,
    read_assessment,
    read_questionnaire,
    set_logical_clock,
    setup_active_plan,
    setup_approved_offer,
    setup_questionnaire_under_review,
    validate_success,
)


def test_the_two_governing_bases_value_the_same_client_book_at_different_totals():
    """Under `SELF_REPORTED` the governing total is `self_reported_total_usd`: it is
    built purely from `claimed_annual_billings_usd` and `claimed_portability_pct`, and
    it therefore ignores the role factor, the consent factor, the realization ceiling,
    the portability ceiling, and every collection record in the system.
    Under `VALIDATED`, the default, the governing total is
    `validated_portable_total_usd`, built from verified historical collections through
    the role, consent and realization factors and the 90-percent ceiling, and zeroed
    for any declined entry — same client book, materially smaller number.

    Design: Difficulty/dual_variant_calc/book_valuation_self_reported_versus_validated_basis_diverge
    """
    ctx = setup_questionnaire_under_review("FULL")

    validated = create_assessment(ctx, governing_basis="VALIDATED")
    self_reported = create_assessment(ctx, governing_basis="SELF_REPORTED")

    assert_portability_assessment(validated)
    assert_portability_assessment(self_reported)

    assert validated["governing_basis"] == "VALIDATED"
    assert_money_equals(
        validated["gross_baseline_total_usd"],
        EXPECTED_FULL_BOOK["gross_baseline_total_usd"],
        "gross_baseline_total_usd",
    )
    assert_money_equals(
        validated["validated_portable_total_usd"],
        EXPECTED_FULL_BOOK["validated_portable_total_usd"],
        "validated_portable_total_usd",
    )
    assert_money_equals(
        validated["self_reported_total_usd"],
        EXPECTED_FULL_BOOK["self_reported_total_usd"],
        "self_reported_total_usd",
    )
    assert_ratio_equals(
        validated["variance_pct"], EXPECTED_FULL_BOOK["variance_pct"], "variance_pct"
    )
    assert validated["concentration_grade"] == "HIGH"
    assert_ratio_equals(validated["concentration_haircut_pct"], 0.15, "haircut")
    assert_money_equals(
        validated["adjusted_portable_total_usd"],
        EXPECTED_FULL_BOOK["adjusted_portable_total_usd"],
        "validated adjusted_portable_total_usd",
    )

    assert self_reported["governing_basis"] == "SELF_REPORTED"
    assert_money_equals(
        self_reported["self_reported_total_usd"],
        EXPECTED_FULL_BOOK["self_reported_total_usd"],
        "self_reported_total_usd",
    )
    assert_money_equals(
        self_reported["adjusted_portable_total_usd"],
        EXPECTED_FULL_BOOK["self_reported_adjusted_portable_total_usd"],
        "self-reported adjusted_portable_total_usd",
    )


def test_the_second_basis_supersedes_the_first_and_becomes_the_questionnaire_pointer():
    """Creating an assessment writes it with `status` `CURRENT`, turns every earlier
    assessment on the same questionnaire whose `status` is `CURRENT` or `STALE` to
    `SUPERSEDED`, writes the new assessment's identifier into the questionnaire's
    `latest_assessment_id`, and increments the questionnaire's `version` by 1.

    Design: Difficulty/dual_variant_calc/book_valuation_self_reported_versus_validated_basis_diverge
    """
    ctx = setup_questionnaire_under_review("FULL")

    validated = create_assessment(ctx, governing_basis="VALIDATED")
    self_reported = create_assessment(ctx, governing_basis="SELF_REPORTED")

    assert read_assessment(validated["id"])["status"] == "SUPERSEDED"
    assert read_assessment(self_reported["id"])["status"] == "CURRENT"

    questionnaire = read_questionnaire(ctx["questionnaire"]["id"])
    assert questionnaire["latest_assessment_id"] == self_reported["id"]

    divergence = float(self_reported["adjusted_portable_total_usd"]) - float(
        validated["adjusted_portable_total_usd"]
    )
    assert_money_equals(divergence, 424522.17, "basis divergence")


def test_a_hire_after_exclusivity_crystallises_the_halved_tail_off_fee():
    """If instead the hire instant falls in the **tail-off period** — at or after
    `exclusivity_end_date` and strictly before `exclusivity_end_date` advanced by
    `tail_off_days` days — the `fee_basis` is `TAIL_OFF_CLAIM`. Here the fee base is
    `guaranteed_comp_usd` alone, with the signing bonus **excluded**, multiplied by
    `fee_pct` and then halved by a tail-off discount of `0.50`, and rounded half up to
    two decimal places.

    Design: Difficulty/dual_variant_calc/search_fee_direct_placement_versus_tail_off_claim_diverge
    """
    ctx = setup_approved_offer("SLIM")

    set_logical_clock("2027-01-15T00:00:00.000Z")
    accepted = _accept(ctx)

    assert accepted["status"] == "ACCEPTED"

    engagement = _read_engagement(ctx)
    assert engagement["fee_basis"] == "TAIL_OFF_CLAIM"
    assert_money_equals(engagement["fee_amount_usd"], 62500.00, "fee_amount_usd")
    assert engagement["fee_status"] == "FEE_DUE"
    assert engagement["status"] == "ACTIVE"

    candidate = _read_candidate(ctx)
    assert candidate["pipeline_status"] == "HIRED"
    assert_instant_equals(candidate["hire_date"], "2027-01-15T00:00:00.000Z", "hire_date")
    assert_instant_equals(
        candidate["earliest_start_date"], "2027-03-01T00:00:00.000Z", "earliest_start_date"
    )


def test_the_speculative_direct_placement_fee_exceeds_the_crystallised_tail_off_fee():
    """The two variants differ substantially on identical offer inputs.
    When the offer's economics are being modelled the hire instant is taken to be the
    current logical clock, a speculative probe; when the fee actually crystallises on
    acceptance the hire instant is the candidate's `hire_date`.

    Design: Difficulty/dual_variant_calc/search_fee_direct_placement_versus_tail_off_claim_diverge
    """
    ctx = setup_approved_offer("SLIM")

    assert_money_equals(
        ctx["offer"]["search_fee_amount_usd"],
        EXPECTED_SLIM_OFFER["search_fee_amount_usd"],
        "modelled search_fee_amount_usd",
    )
    assert_money_equals(
        ctx["offer"]["total_first_year_comp_usd"],
        EXPECTED_SLIM_OFFER["total_first_year_comp_usd"],
        "total_first_year_comp_usd",
    )
    assert_money_equals(
        ctx["offer"]["integration_cost_total_usd"],
        EXPECTED_SLIM_OFFER["integration_cost_total_usd"],
        "integration_cost_total_usd",
    )

    set_logical_clock("2027-01-15T00:00:00.000Z")
    _accept(ctx)

    engagement = _read_engagement(ctx)
    gap = float(ctx["offer"]["search_fee_amount_usd"]) - float(
        engagement["fee_amount_usd"]
    )
    assert_money_equals(gap, 75000.00, "fee divergence")


def test_the_two_variance_bases_diverge_on_identical_actual_collections():
    """Under `PLAN_BASIS` it is `actual_collections_usd` less `plan_target_usd`,
    rounded half up to two decimal places, and it ignores `realized_standard_rate_usd`
    entirely — the partner is measured against the plan exactly as committed.
    Under `RATE_ADJUSTED_BASIS` it is `actual_collections_usd` less
    `plan_target_adjusted_usd`, rounded the same way, which measures the partner on
    volume rather than on discounting: for identical collections over an identical
    period, a realized rate below the planned rate makes this variance strictly less
    negative than the plan basis would.

    Design: Difficulty/dual_variant_calc/performance_variance_plan_basis_versus_rate_adjusted_basis_diverge
    """
    ctx = _setup_measured_plan()

    plan_basis = add_performance_review(ctx, variance_basis="PLAN_BASIS")
    rate_basis = add_performance_review(ctx, variance_basis="RATE_ADJUSTED_BASIS")

    assert plan_basis["period_days"] == 91
    assert_money_equals(
        plan_basis["actual_collections_usd"], 250000.00, "actual_collections_usd"
    )
    assert_money_equals(plan_basis["plan_target_usd"], 262773.41, "plan_target_usd")
    assert_money_equals(
        plan_basis["plan_target_adjusted_usd"], 248943.23, "plan_target_adjusted_usd"
    )
    assert_money_equals(plan_basis["variance_usd"], -12773.41, "PLAN_BASIS variance_usd")

    assert_money_equals(
        rate_basis["plan_target_usd"], 262773.41, "plan_target_usd on the rate basis"
    )
    assert_money_equals(
        rate_basis["plan_target_adjusted_usd"],
        248943.23,
        "plan_target_adjusted_usd on the rate basis",
    )
    assert_money_equals(
        rate_basis["variance_usd"], 1056.77, "RATE_ADJUSTED_BASIS variance_usd"
    )

    divergence = float(rate_basis["variance_usd"]) - float(plan_basis["variance_usd"])
    assert_money_equals(divergence, 13830.18, "variance divergence")


def test_attainment_and_the_performance_flag_ignore_the_rate_adjusted_target():
    """Note carefully that `attainment_pct` — and therefore the flag below —
    **always** uses `plan_target_usd` and never the rate-adjusted target, no matter
    which `variance_basis` was requested; only `variance_usd` is basis-dependent.

    Design: Difficulty/dual_variant_calc/performance_variance_plan_basis_versus_rate_adjusted_basis_diverge
    """
    ctx = _setup_measured_plan()

    plan_basis = add_performance_review(ctx, variance_basis="PLAN_BASIS")
    rate_basis = add_performance_review(ctx, variance_basis="RATE_ADJUSTED_BASIS")

    assert_ratio_equals(plan_basis["attainment_pct"], 0.9514, "PLAN_BASIS attainment_pct")
    assert plan_basis["performance_flag"] == "ON_PLAN"
    assert_ratio_equals(
        rate_basis["attainment_pct"], 0.9514, "RATE_ADJUSTED_BASIS attainment_pct"
    )
    assert rate_basis["performance_flag"] == "ON_PLAN"


# ----------------------------------------------------------------------
# Local scenario glue
# ----------------------------------------------------------------------


def _accept(ctx):
    from test_helpers import api_client

    return validate_success(
        api_client.accept_offer(ctx["offer"]["id"], ctx["candidate_headers"])
    )


def _read_engagement(ctx):
    from test_helpers import TEST_USERS, api_client

    return validate_success(
        api_client.get_search_firm_engagement(
            ctx["engagement"]["id"], TEST_USERS["recruiting_coordinator_headers"]
        )
    )


def _read_candidate(ctx):
    from test_helpers import TEST_USERS, api_client

    return validate_success(
        api_client.get_candidate(
            ctx["candidate"]["id"], TEST_USERS["recruiting_coordinator_headers"]
        )
    )


def _setup_measured_plan():
    """A hired lateral on an ACTIVE plan with 250000.00 of verified post-hire
    collections inside the closed review period, plus one unverified row."""
    ctx = setup_active_plan("SLIM", plan_overrides={"planned_standard_rate_usd": 950.00})
    set_logical_clock("2027-04-10T00:00:00.000Z")
    append_collection_record(
        ctx["candidate"]["id"],
        record_type="POST_HIRE",
        period_end_date="2027-02-01T00:00:00.000Z",
        amount_usd=150000.00,
        status="VERIFIED",
        source="FIRM_LEDGER",
    )
    append_collection_record(
        ctx["candidate"]["id"],
        record_type="POST_HIRE",
        period_end_date="2027-03-15T00:00:00.000Z",
        amount_usd=100000.00,
        status="VERIFIED",
        source="FIRM_LEDGER",
    )
    append_collection_record(
        ctx["candidate"]["id"],
        record_type="POST_HIRE",
        period_end_date="2027-03-20T00:00:00.000Z",
        amount_usd=400000.00,
        status="UNVERIFIED",
        source="CANDIDATE_ATTESTATION",
    )
    return ctx
