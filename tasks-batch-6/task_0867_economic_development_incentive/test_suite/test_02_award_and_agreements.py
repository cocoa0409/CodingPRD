"""Agreement execution: the award-cap formulas (GRANT / ABATEMENT round-then-sum / TIF),
the referential-before-fiscal validation ordering, budget reservation, and FK integrity."""
from test_helpers import (
    validate_success, validate_error, ApiErrorId, NONEXISTENT_UUID,
    create_program, create_parcel, create_application, submit_application,
    start_review, execute_agreement,
    setup_approved_application, create_agreement_payload,
    make_director_headers,
)

DIRECTOR = make_director_headers("director-1")


def test_abatement_award_cap_rounds_per_year_then_sums(api):
    """PRD §3.3: "For both `ABATEMENT` and `TIF`, the rounding order is pinned: round each
    year's amount to whole cents first, then sum across the term. Summing the raw per-year
    amounts and rounding once at the end is incorrect and can differ by cents." per_year
    round(100004*12.5/100)=12501; over term 3 -> 37503 (sum-then-round would give 37502).

    Design: Difficulty/combinatorial_formula/abatement_award_cap_round_then_sum
    """
    ctx = setup_approved_application(
        program_overrides={"incentive_type": "ABATEMENT", "abatement_rate_pct": 12.5,
                           "grant_per_job_cents": 0, "tif_capture_pct": 0,
                           "min_jobs_required": 10, "min_investment_cents": 10_000_000},
        app_overrides={"proposed_jobs": 10, "proposed_investment_cents": 10_000_000,
                       "but_for_attested": True})
    parcel = create_parcel(current_assessed_value_cents=100004)
    agr = validate_success(api.create_agreement(
        create_agreement_payload(ctx["application"]["id"], parcel["id"], term_years=3,
                                 awarded_jobs=10, awarded_investment_cents=10_000_000), DIRECTOR),
        expected_status=201)
    assert agr["max_incentive_cents"] == 37503, agr["max_incentive_cents"]


def test_abatement_agreement_copies_incentive_type(api):
    """PRD §3.3: "On success the agreement copies the `program_id` and the `incentive_type`
    from the source application's program, records `effective_date` as the current logical
    clock, and is created in status `EXECUTED`."

    Design: Difficulty/combinatorial_formula/abatement_award_cap_round_then_sum
    """
    ctx = setup_approved_application(
        program_overrides={"incentive_type": "ABATEMENT", "abatement_rate_pct": 12.5,
                           "grant_per_job_cents": 0, "tif_capture_pct": 0,
                           "min_jobs_required": 10, "min_investment_cents": 10_000_000},
        app_overrides={"proposed_jobs": 10, "proposed_investment_cents": 10_000_000,
                       "but_for_attested": True})
    parcel = create_parcel(current_assessed_value_cents=100004)
    agr = validate_success(api.create_agreement(
        create_agreement_payload(ctx["application"]["id"], parcel["id"], term_years=3,
                                 awarded_jobs=10, awarded_investment_cents=10_000_000), DIRECTOR),
        expected_status=201)
    assert agr["incentive_type"] == "ABATEMENT"
    assert agr["status"] == "EXECUTED"


def test_grant_award_cap_computed(api):
    """PRD §3.3: "For a `GRANT` program, the cap is `awarded_jobs` multiplied by the program's
    `grant_per_job_cents`." awarded_jobs 100 * 500000 = 50,000,000.

    Design: Corner/calculations/grant_award_cap_computed
    """
    ctx = setup_approved_application(app_overrides={"but_for_attested": True})
    agr = validate_success(api.create_agreement(
        create_agreement_payload(ctx["application"]["id"], ctx["parcel"]["id"],
                                 awarded_jobs=100), DIRECTOR), expected_status=201)
    assert agr["max_incentive_cents"] == 50_000_000, agr["max_incentive_cents"]
    assert agr["incentive_type"] == "GRANT"


def test_tif_award_cap_from_increment(api):
    """PRD §3.3: "For a `TIF` program, the increment is the parcel's
    `current_assessed_value_cents` minus its `base_assessed_value_cents`, floored at zero
    (never negative). A single year's amount is that increment multiplied by the program's
    `tif_capture_pct`, divided by 100, and rounded half up to whole cents. The cap is that
    rounded per-year amount summed over the term." increment 20,000,000 * 75% = 15,000,000;
    term 2 -> 30,000,000.

    Design: Corner/calculations/tif_award_cap_increment_computed
    """
    ctx = setup_approved_application(
        program_overrides={"incentive_type": "TIF", "tif_capture_pct": 75,
                           "grant_per_job_cents": 0, "abatement_rate_pct": 0,
                           "min_jobs_required": 10, "min_investment_cents": 10_000_000},
        app_overrides={"proposed_jobs": 10, "proposed_investment_cents": 10_000_000,
                       "but_for_attested": True})
    parcel = create_parcel(base_assessed_value_cents=10_000_000, current_assessed_value_cents=30_000_000)
    agr = validate_success(api.create_agreement(
        create_agreement_payload(ctx["application"]["id"], parcel["id"], term_years=2,
                                 awarded_jobs=10, awarded_investment_cents=10_000_000), DIRECTOR),
        expected_status=201)
    assert agr["max_incentive_cents"] == 30_000_000, agr["max_incentive_cents"]
    assert agr["incentive_type"] == "TIF"


def test_execute_unapproved_over_budget_reports_referential_first(api):
    """PRD §2.10: "then cross-entity referential preconditions on linked resources, then
    remaining domain constraints, then interval-overlap checks, and finally fiscal-capacity
    checks." With the source application still UNDER_REVIEW and the budget too small, the
    referential ERR_APPLICATION_NOT_APPROVED is returned before the fiscal check.

    Design: Difficulty/priority_pair_validation_conflict/referential_vs_fiscal_on_execute
    """
    prog = create_program(total_budget_cents=1000)
    parcel = create_parcel()
    app = create_application(prog["id"], but_for_attested=True)
    submit_application(app["id"], "applicant-1")
    start_review(app["id"], "analyst-1")  # left UNDER_REVIEW, never approved
    validate_error(api.create_agreement(
        create_agreement_payload(app["id"], parcel["id"], awarded_jobs=100), DIRECTOR),
        ApiErrorId.ERR_APPLICATION_NOT_APPROVED)


def test_execute_from_under_review_rejected_not_approved(api):
    """PRD §3.3: "The source application must be in `APPROVED`; otherwise the request is
    rejected with `ERR_APPLICATION_NOT_APPROVED` (HTTP 409)." Budget is ample here, so the
    referential precondition is the only failing check.

    Design: Difficulty/priority_pair_validation_conflict/referential_vs_fiscal_on_execute
    """
    prog = create_program()
    parcel = create_parcel()
    app = create_application(prog["id"], but_for_attested=True)
    submit_application(app["id"], "applicant-1")
    start_review(app["id"], "analyst-1")
    validate_error(api.create_agreement(
        create_agreement_payload(app["id"], parcel["id"], awarded_jobs=100), DIRECTOR),
        ApiErrorId.ERR_APPLICATION_NOT_APPROVED)


def test_execute_exceeding_budget_returns_402(api):
    """PRD §3.3: "Execution reserves budget: it requires that the program's
    `available_budget_cents` is greater than or equal to the computed `max_incentive_cents`,
    failing with `ERR_PROGRAM_BUDGET_EXCEEDED` (HTTP 402) when the pool cannot cover the
    award." Cap 50,000,000 against a 1000-cent pool.

    Design: Corner/validations/program_budget_exceeded_on_execute_returns_402
    """
    ctx = setup_approved_application(program_overrides={"total_budget_cents": 1000},
                                     app_overrides={"but_for_attested": True})
    validate_error(api.create_agreement(
        create_agreement_payload(ctx["application"]["id"], ctx["parcel"]["id"],
                                 awarded_jobs=100), DIRECTOR),
        ApiErrorId.ERR_PROGRAM_BUDGET_EXCEEDED)


def test_execute_unknown_parcel_returns_404(api):
    """PRD §2.4: "an unknown program yields `ERR_PROGRAM_NOT_FOUND`, an unknown parcel
    `ERR_PARCEL_NOT_FOUND`". Executing against a parcel_id that does not resolve fails
    before the agreement is created.

    Design: Corner/errors/create_agreement_unknown_parcel_returns_404
    """
    ctx = setup_approved_application(app_overrides={"but_for_attested": True})
    validate_error(api.create_agreement(
        create_agreement_payload(ctx["application"]["id"], NONEXISTENT_UUID,
                                 awarded_jobs=100), DIRECTOR),
        ApiErrorId.ERR_PARCEL_NOT_FOUND)
