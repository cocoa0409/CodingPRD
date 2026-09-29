"""Dealer scorecards, fair-lending markup reviews, and remediation."""
from test_helpers import (
    ADMIN, COMPLIANCE, FUNDER, ApiErrorId, CLOCK_START, api_client, assert_review,
    assert_scorecard, compute_scorecard, finalize_scorecard, fund_contracts_for_cohort_study,
    onboard_dealer, read_contract, read_dealer, record_chargeback_event,
    run_fair_lending_review, set_clock, setup_booked_contract, setup_funded_contract,
    setup_program, validate_error, validate_paginated, validate_success,
    verify_document,
)


def test_a_scorecard_over_an_empty_population_is_unrated(api):
    """PRD 3.8: "When `population_count` is zero, `default_rate_bps`,
    `early_payoff_rate_bps`, `doc_defect_rate_bps`, and `avg_markup_bps` are all zero,
    `composite_score` is null, and `grade` is `UNRATED`."
    PRD 3.8: "The scorecard is created in `DRAFT` with every metric written
    immediately; the dealership itself is not mutated by the computation."

    Design: Difficulty/boundary_precision_check/scorecard_empty_population_returns_unrated_null_score
    """
    program = setup_program()

    response = api.create_scorecard(
        program["dealer_id"],
        {
            "period_start": "2026-08-01T00:00:00Z",
            "period_end": "2026-12-01T00:00:00Z",
            "basis": "TRAILING_WINDOW",
        },
        ADMIN,
    )
    scorecard = validate_success(response, 201)
    assert_scorecard(scorecard)

    assert scorecard["population_count"] == 0
    assert scorecard["composite_score"] is None
    assert scorecard["grade"] == "UNRATED"
    assert scorecard["default_rate_bps"] == 0
    assert scorecard["early_payoff_rate_bps"] == 0
    assert scorecard["doc_defect_rate_bps"] == 0
    assert scorecard["avg_markup_bps"] == 0
    assert scorecard["status"] == "DRAFT"


def test_finalizing_an_unrated_scorecard_publishes_that_grade(api):
    """PRD 3.8: "The dealership's `latest_scorecard_grade` is set to this
    scorecard's `grade` and its `scorecard_stale` is cleared to false — including when
    the grade is `UNRATED`."
    PRD 3.8: "The scorecard moves `DRAFT → FINALIZED` and stamps `finalized_at` with
    the current logical instant."

    Design: Difficulty/boundary_precision_check/scorecard_empty_population_returns_unrated_null_score
    """
    program = setup_program()
    scorecard = compute_scorecard(program["dealer_id"])
    assert scorecard["grade"] == "UNRATED"

    finalized = validate_success(api.finalize_scorecard(scorecard["id"], ADMIN), 200)
    assert finalized["status"] == "FINALIZED"
    assert finalized["finalized_at"] is not None

    dealer = read_dealer(program["dealer_id"])
    assert dealer["latest_scorecard_grade"] == "UNRATED"
    assert dealer["scorecard_stale"] is False


def _setup_two_windows_of_funded_paper():
    """One contract funded 2026-06-15 and later defaulted, one funded 2026-08-10."""
    program = setup_program(clock="2026-06-15T00:00:00Z")
    older = setup_funded_contract(
        program,
        application_overrides={
            "applicant_reference": "APP-Y", "monthly_debt_cents": 180000,
            "amount_financed_cents": 1000000, "collateral_value_cents": 1000000,
            "vehicle_model_year": 2023,
        },
        contract_date="2026-06-15T00:00:00Z", funding_date="2026-06-15T00:00:00Z",
        doc_prefix="IMG-Y",
    )
    set_clock("2026-08-10T00:00:00Z")
    newer = setup_funded_contract(
        program,
        application_overrides={
            "applicant_reference": "APP-X", "monthly_debt_cents": 180000,
            "amount_financed_cents": 1000000, "collateral_value_cents": 1000000,
            "vehicle_model_year": 2023,
        },
        contract_date="2026-08-10T00:00:00Z", funding_date="2026-08-10T00:00:00Z",
        doc_prefix="IMG-X",
    )
    set_clock("2026-08-15T00:00:00Z")
    record_chargeback_event(older["contract"]["id"], "DEFAULT", "2026-08-15T00:00:00Z")
    set_clock("2026-12-01T00:00:00Z")
    return program, older, newer


def test_trailing_window_excludes_paper_funded_before_the_period(api):
    """PRD 3.8: "Under `TRAILING_WINDOW`, the population is further filtered to
    contracts whose `funded_at` lies at or after `period_start` and strictly before
    `period_end`; a contract funded before `period_start` is invisible, so an older
    default cannot depress the score."
    PRD 3.8: "`grade` is `A` when `composite_score` is at least 850, `B` when it is
    at least 700, `C` when it is at least 550, and `D` otherwise."

    Design: Difficulty/dual_variant_calc/scorecard_trailing_window_vs_inception_to_date_on_dealer
    """
    program, older, newer = _setup_two_windows_of_funded_paper()

    scorecard = compute_scorecard(
        program["dealer_id"], basis="TRAILING_WINDOW",
        period_start="2026-08-01T00:00:00Z", period_end="2026-12-01T00:00:00Z",
    )
    assert scorecard["population_count"] == 1
    assert scorecard["default_rate_bps"] == 0
    assert scorecard["avg_markup_bps"] == 200
    assert scorecard["composite_score"] == 995
    assert scorecard["grade"] == "A"


def test_inception_to_date_ignores_the_period_and_sees_every_funded_contract(api):
    """PRD 3.8: "Under `INCEPTION_TO_DATE`, `period_start` and `period_end` are
    ignored entirely and every eligible contract the dealership has ever had funded is
    included. For the same dealership at the same instant the two bases yield a
    different `population_count`, a different `default_rate_bps`, and in general a
    different `grade`."
    PRD 3.8: "The default deduction is 6.0 multiplied by `default_rate_bps` divided
    by 100, rounded half up."

    Design: Difficulty/dual_variant_calc/scorecard_trailing_window_vs_inception_to_date_on_dealer
    """
    program, older, newer = _setup_two_windows_of_funded_paper()

    scorecard = compute_scorecard(
        program["dealer_id"], basis="INCEPTION_TO_DATE",
        period_start="2026-08-01T00:00:00Z", period_end="2026-12-01T00:00:00Z",
    )
    assert scorecard["population_count"] == 2
    assert scorecard["default_rate_bps"] == 5000
    assert scorecard["composite_score"] == 695
    assert scorecard["grade"] == "C"


def test_document_defects_drive_their_own_composite_deduction(api):
    """PRD 3.8: "Otherwise three counts are taken over the population: the number of
    contracts in `DEFAULTED`; the number in `PAID_OFF` whose `payoff_months_seasoned`
    is strictly less than twelve months; and the number whose `doc_defect_count` is
    greater than zero."
    PRD 3.8: "The document-defect deduction is 1.5 multiplied by
    `doc_defect_rate_bps` divided by 100, rounded half up."
    PRD 3.8: "The markup deduction is 1.0 multiplied by the excess of
    `avg_markup_bps` over the 150-basis-point markup benchmark — floored at zero, so a
    dealership pricing at or below the benchmark suffers no deduction — divided by 10,
    rounded half up."

    Design: Corner/calculations/scorecard_doc_defect_rate_drives_its_own_deduction
    """
    program = setup_program()
    booked = setup_booked_contract(program, doc_prefix="IMG-dd")
    documents = booked["documents"]
    for document in documents.values():
        verify_document(document["id"])
    verify_document(
        documents["RETAIL_INSTALLMENT_CONTRACT"]["id"], outcome="REJECT",
        defect_code="MISSING_SIGNATURE",
    )
    verify_document(documents["RETAIL_INSTALLMENT_CONTRACT"]["id"])
    validate_success(
        api.fund_contract(booked["contract"]["id"], {"funding_date": CLOCK_START}, FUNDER),
        200,
    )

    contract = read_contract(booked["contract"]["id"])
    assert contract["doc_defect_count"] == 1
    assert contract["funding_status"] == "FUNDED"

    scorecard = compute_scorecard(program["dealer_id"])
    assert scorecard["population_count"] == 1
    assert scorecard["doc_defect_rate_bps"] == 10000
    assert scorecard["default_rate_bps"] == 0
    assert scorecard["early_payoff_rate_bps"] == 0
    assert scorecard["avg_markup_bps"] == 200
    assert scorecard["composite_score"] == 845
    assert scorecard["grade"] == "B"


def test_a_grade_d_finalization_suspends_the_active_dealership(api):
    """PRD 3.8: "Each becomes a rate in whole basis points — ten thousand multiplied
    by the count, divided by `population_count`, rounded half up — giving
    `default_rate_bps`, `early_payoff_rate_bps`, and `doc_defect_rate_bps`
    respectively."
    PRD 3.8: "when the `grade` is `D` and the dealership is currently `ACTIVE`, the
    dealership advances `ACTIVE → SUSPENDED` with `suspension_reason` set to the
    sentinel `AUTO_SCORECARD_GRADE_D`, and every one of its applications in
    `SUBMITTED`, `CONDITIONED`, `RESUBMITTED`, or `APPROVED` captures its status into
    `held_from_status` and moves to `ON_HOLD`."
    PRD 3.8: "The dealership's `latest_scorecard_grade` is set to this scorecard's
    `grade` and its `scorecard_stale` is cleared to false"

    Design: Corner/state_machines/scorecard_grade_d_finalization_suspends_dealer
    """
    program = setup_program()
    first = setup_funded_contract(
        program,
        application_overrides={
            "applicant_reference": "APP-g1", "monthly_debt_cents": 180000,
            "amount_financed_cents": 1000000, "collateral_value_cents": 1000000,
        },
        doc_prefix="IMG-g1",
    )
    second = setup_funded_contract(
        program,
        application_overrides={
            "applicant_reference": "APP-g2", "monthly_debt_cents": 180000,
            "amount_financed_cents": 1000000, "collateral_value_cents": 1000000,
        },
        doc_prefix="IMG-g2",
    )
    set_clock("2026-09-01T00:00:00Z")
    record_chargeback_event(first["contract"]["id"], "DEFAULT", "2026-09-01T00:00:00Z")
    record_chargeback_event(second["contract"]["id"], "DEFAULT", "2026-09-01T00:00:00Z")

    scorecard = compute_scorecard(program["dealer_id"])
    assert scorecard["population_count"] == 2
    assert scorecard["default_rate_bps"] == 10000
    assert scorecard["avg_markup_bps"] == 200
    assert scorecard["composite_score"] == 395
    assert scorecard["grade"] == "D"

    finalized = finalize_scorecard(scorecard["id"])
    assert finalized["status"] == "FINALIZED"

    dealer = read_dealer(program["dealer_id"])
    assert dealer["latest_scorecard_grade"] == "D"
    assert dealer["scorecard_stale"] is False
    assert dealer["status"] == "SUSPENDED"
    assert dealer["suspension_reason"] == "AUTO_SCORECARD_GRADE_D"
    assert dealer["default_count"] == 2
    assert dealer["early_payoff_count"] == 0


def test_the_scorecard_subresource_lists_newest_period_first_per_dealer(api):
    """PRD 2.3: "The one deliberate exception is the per-dealer scorecard listing,
    which is ordered by `period_start` descending so that the most recent scoring
    window is read first"
    PRD 3.8: "Scorecards can be listed per dealership and narrowed by `basis` and by
    `status`."
    PRD 3.8: "The scorecard is created in `DRAFT` with every metric written
    immediately; the dealership itself is not mutated by the computation."
    PRD 3.8: "When `population_count` is zero, `default_rate_bps`,
    `early_payoff_rate_bps`, `doc_defect_rate_bps`, and `avg_markup_bps` are all zero,
    `composite_score` is null, and `grade` is `UNRATED`."

    Design: Corner/endpoints/dealer_scorecards_subresource_lists_only_that_dealer
    """
    program = setup_program()
    other = onboard_dealer(legal_name="Second Street Motors", state_code="NV")

    earlier = compute_scorecard(
        program["dealer_id"], period_start="2026-06-01T00:00:00Z",
        period_end="2026-08-01T00:00:00Z", basis="TRAILING_WINDOW",
    )
    later = compute_scorecard(
        program["dealer_id"], period_start="2026-08-01T00:00:00Z",
        period_end="2026-12-01T00:00:00Z", basis="TRAILING_WINDOW",
    )

    rows, meta = validate_paginated(
        api.list_dealer_scorecards(program["dealer_id"], ADMIN)
    )
    assert meta["total_count"] == 2
    assert rows[0]["id"] == later["id"]
    assert rows[1]["id"] == earlier["id"]
    for row in rows:
        assert row["dealer_id"] == program["dealer_id"]
        assert row["status"] == "DRAFT"
        assert row["grade"] == "UNRATED"

    _, other_meta = validate_paginated(api.list_dealer_scorecards(other["id"], ADMIN))
    assert other_meta["total_count"] == 0


DISPARATE_BOOK = [
    {
        "applicant_reference": "APP-f1", "monitoring_cohort": "CONTROL",
        "monthly_income_cents": 900000, "monthly_debt_cents": 200000,
        "amount_financed_cents": 2000000, "collateral_value_cents": 2000000,
        "vehicle_model_year": 2023, "requested_apr_bps": 599, "contract_apr_bps": 599,
    },
    {
        "applicant_reference": "APP-f2", "monitoring_cohort": "CONTROL",
        "monthly_income_cents": 900000, "monthly_debt_cents": 200000,
        "amount_financed_cents": 3000000, "collateral_value_cents": 3000000,
        "vehicle_model_year": 2023, "requested_apr_bps": 649, "contract_apr_bps": 649,
    },
    {
        "applicant_reference": "APP-f3", "monitoring_cohort": "MONITORED",
        "monthly_income_cents": 900000, "monthly_debt_cents": 200000,
        "amount_financed_cents": 2000000, "collateral_value_cents": 2000000,
        "vehicle_model_year": 2023, "requested_apr_bps": 749, "contract_apr_bps": 749,
    },
    {
        "applicant_reference": "APP-f4", "monitoring_cohort": "MONITORED",
        "monthly_income_cents": 900000, "monthly_debt_cents": 200000,
        "amount_financed_cents": 1000000, "collateral_value_cents": 1000000,
        "vehicle_model_year": 2023, "requested_apr_bps": 699, "contract_apr_bps": 699,
    },
]

EVENHANDED_BOOK = [
    {
        "applicant_reference": "APP-w1", "monitoring_cohort": "CONTROL",
        "monthly_income_cents": 900000, "monthly_debt_cents": 200000,
        "amount_financed_cents": 2000000, "collateral_value_cents": 2000000,
        "vehicle_model_year": 2024, "requested_apr_bps": 649, "contract_apr_bps": 649,
    },
    {
        "applicant_reference": "APP-w2", "monitoring_cohort": "CONTROL",
        "monthly_income_cents": 900000, "monthly_debt_cents": 200000,
        "amount_financed_cents": 2000000, "collateral_value_cents": 2000000,
        "vehicle_model_year": 2024, "requested_apr_bps": 649, "contract_apr_bps": 649,
    },
    {
        "applicant_reference": "APP-w3", "monitoring_cohort": "MONITORED",
        "monthly_income_cents": 900000, "monthly_debt_cents": 200000,
        "amount_financed_cents": 2000000, "collateral_value_cents": 2000000,
        "vehicle_model_year": 2024, "requested_apr_bps": 649, "contract_apr_bps": 649,
    },
    {
        "applicant_reference": "APP-w4", "monitoring_cohort": "MONITORED",
        "monthly_income_cents": 900000, "monthly_debt_cents": 200000,
        "amount_financed_cents": 2000000, "collateral_value_cents": 2000000,
        "vehicle_model_year": 2024, "requested_apr_bps": 669, "contract_apr_bps": 669,
    },
]


def test_the_benchmark_is_dollar_weighted_over_the_whole_population(api):
    """PRD 3.8: "`benchmark_markup_bps` is computed first, over the **whole**
    population — including the `MONITORED` contracts that may be about to be
    remediated. It is dollar-weighted: the sum, across every population contract, of
    that contract's `markup_bps` multiplied by its `amount_financed_cents`, divided by
    the sum of `amount_financed_cents` across the same population, rounded half up to
    whole basis points."
    PRD 3.8: "`disparity_bps` is `monitored_avg_markup_bps` less
    `control_avg_markup_bps`, and it is signed: a monitored cohort priced more cheaply
    than the control cohort yields a negative disparity."
    PRD 3.8: "`finding` is `EXCEEDS_THRESHOLD` when `disparity_bps` is **strictly
    greater than** 25 basis points, and `WITHIN_TOLERANCE` otherwise"

    Design: Difficulty/combinatorial_formula/fair_lending_benchmark_frozen_evaluation_order
    """
    program = setup_program()
    fund_contracts_for_cohort_study(program, DISPARATE_BOOK)
    assert read_dealer(program["dealer_id"])["reserve_balance_cents"] == 281250

    response = api.create_fair_lending_review(
        {
            "dealer_id": program["dealer_id"],
            "window_start": "2026-08-01T00:00:00Z",
            "window_end": "2026-12-01T00:00:00Z",
        },
        COMPLIANCE,
    )
    review = validate_success(response, 201)
    assert_review(review)

    assert review["population_count"] == 4
    assert review["benchmark_markup_bps"] == 119
    assert review["control_avg_markup_bps"] == 75
    assert review["monitored_avg_markup_bps"] == 175
    assert review["disparity_bps"] == 100
    assert review["finding"] == "EXCEEDS_THRESHOLD"

    reread = validate_success(api.get_fair_lending_review(review["id"], ADMIN), 200)
    assert reread["benchmark_markup_bps"] == 119, (
        "the benchmark is frozen on the review row at creation"
    )


def test_the_remediation_pool_rounds_each_monitored_contribution_alone(api):
    """PRD 3.8: "When the `finding` is `EXCEEDS_THRESHOLD`, it is built contract by
    contract over the `MONITORED` contracts only, processed in ascending `funded_at`
    order and tie-broken by ascending `created_at`. Each contract contributes its
    `amount_financed_cents`, multiplied by the excess of its own `markup_bps` over the
    frozen `benchmark_markup_bps` expressed as a fraction of ten thousand — floored at
    zero, so a monitored contract priced at or below the benchmark contributes nothing
    — multiplied by its `term_months` divided by twelve, multiplied by the
    participation factor of 0.55."
    PRD 3.8: "**Each contract's contribution is rounded half up to whole cents on its
    own, and only then are the contributions summed**, exactly the discipline the
    chargeback rule of §3.6 uses."

    Design: Difficulty/combinatorial_formula/fair_lending_benchmark_frozen_evaluation_order
    """
    program = setup_program()
    fund_contracts_for_cohort_study(program, DISPARATE_BOOK)

    review = run_fair_lending_review(program["dealer_id"])
    assert review["benchmark_markup_bps"] == 119
    assert review["remediation_pool_cents"] == 53075, (
        "44550 from the 2000000 monitored deal plus 8525 from the 1000000 one"
    )


def test_an_evenhanded_book_lands_within_tolerance_with_no_pool(api):
    """PRD 3.8: "The two cohort averages are unweighted. `control_avg_markup_bps` is
    the sum of `markup_bps` over population contracts whose `monitoring_cohort` is
    `CONTROL`, divided by the number of such contracts, rounded half up — and zero when
    there are none."
    PRD 3.8: "`remediation_pool_cents` is zero when the `finding` is
    `WITHIN_TOLERANCE`."
    PRD 3.8: "a disparity of exactly 25 basis points is within tolerance."

    Design: Corner/calculations/fair_lending_within_tolerance_publishes_without_remediation
    """
    program = setup_program()
    fund_contracts_for_cohort_study(program, EVENHANDED_BOOK)

    review = run_fair_lending_review(program["dealer_id"])
    assert review["population_count"] == 4
    assert review["benchmark_markup_bps"] == 105
    assert review["control_avg_markup_bps"] == 100
    assert review["monitored_avg_markup_bps"] == 110
    assert review["disparity_bps"] == 10
    assert review["finding"] == "WITHIN_TOLERANCE"
    assert review["remediation_pool_cents"] == 0

    assert read_dealer(program["dealer_id"])["compliance_hold"] is False
    _, meta = validate_paginated(
        api.list_reserve_entries(
            ADMIN,
            params={"dealer_id": program["dealer_id"], "entry_type": "REMEDIATION"},
        )
    )
    assert meta["total_count"] == 0


def test_a_review_over_fewer_than_four_contracts_is_refused(api):
    """PRD 3.8: "If `population_count` is fewer than 4 contracts, the review is
    refused with `ERR_INSUFFICIENT_REVIEW_POPULATION` (HTTP 422) — a disparity computed
    over three deals is noise."

    Design: Corner/validations/fair_lending_review_below_minimum_population_rejected
    """
    program = setup_program()
    setup_funded_contract(program, doc_prefix="IMG-rp")

    response = api.create_fair_lending_review(
        {
            "dealer_id": program["dealer_id"],
            "window_start": "2026-08-01T00:00:00Z",
            "window_end": "2026-12-01T00:00:00Z",
        },
        COMPLIANCE,
    )
    validate_error(response, ApiErrorId.ERR_INSUFFICIENT_REVIEW_POPULATION.value, 422)

    _, meta = validate_paginated(
        api.list_fair_lending_reviews(
            ADMIN, params={"dealer_id": program["dealer_id"]}
        )
    )
    assert meta["total_count"] == 0
