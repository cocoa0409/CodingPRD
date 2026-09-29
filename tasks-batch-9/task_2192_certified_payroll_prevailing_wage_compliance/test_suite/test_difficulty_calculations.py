"""Dual-variant and combinatorial wage arithmetic."""
from test_helpers import (
    build_contractor_with_staff,
    build_line,
    build_submission,
    build_worker,
    finalize,
    get_success_data,
    make_preparer_headers,
    rule_on_fringe_plan,
    setup_env,
    validate_success,
)


def _plan_env(api):
    """Contractor with a PREPARER staff row, ready to declare a fringe plan."""
    contractor, preparer, _certifier = build_contractor_with_staff(api)
    return contractor, make_preparer_headers(preparer["id"])


def test_fringe_plan_stores_both_annualization_denominators(api, officer_headers):
    """Declaring a plan stores the annualized-all-hours and covered-hours-only credits.

    PRD 3.3: "The **annualized-all-hours** figure is stored in `annualized_credit_cents`
    and is obtained by dividing the plan's `annual_contribution_cents` by its
    `annual_total_hours` and rounding the quotient half up to a whole cent. The
    **covered-hours-only** figure is stored in `claimed_credit_cents` and is obtained by
    dividing the same `annual_contribution_cents` by `annual_public_works_hours` alone,
    again rounded half up to a whole cent."

    Design: Difficulty/dual_variant_calc/fringe_credit_annualized_all_hours_vs_covered_hours_only
    """
    contractor, preparer_headers = _plan_env(api)
    created = get_success_data(
        api.create_fringe_plan(
            contractor["id"],
            {
                "plan_name": "Acme Electric Health Trust",
                "plan_type": "BONA_FIDE_TRUST",
                "annual_contribution_cents": 500000,
                "annual_total_hours": 2100.00,
                "annual_public_works_hours": 1300.00,
            },
            preparer_headers,
        ),
        expected_status=201,
    )
    assert created["annualized_credit_cents"] == 238
    assert created["claimed_credit_cents"] == 385

    approved = rule_on_fringe_plan(api, created["id"], "APPROVED", officer_headers)
    assert approved["approval_status"] == "APPROVED"
    assert approved["annualized_credit_cents"] == 238
    assert approved["claimed_credit_cents"] == 385
    assert approved["claimed_credit_cents"] - approved["annualized_credit_cents"] == 147


def test_only_the_annualized_figure_is_creditable_against_a_deficiency(api, officer_headers):
    """The wage engine credits annualized_credit_cents, never claimed_credit_cents.

    PRD 3.3: "The **annualized-all-hours figure is authoritative for compliance**: it,
    and only it, is what the wage engine may credit against a fringe obligation." PRD 3.6
    step three: "an `APPROVED` plan of any other type contributes its stored
    `annualized_credit_cents` — the authoritative annualized-all-hours figure from §3.3,
    never the contractor-facing `claimed_credit_cents`."

    Design: Difficulty/dual_variant_calc/fringe_credit_annualized_all_hours_vs_covered_hours_only
    """
    env = setup_env(api, rates=[{"fringe_hourly_rate_cents": 2000}])
    plan = get_success_data(
        api.create_fringe_plan(
            env["contractor"]["id"],
            {
                "plan_name": "Acme Electric Health Trust",
                "plan_type": "BONA_FIDE_TRUST",
                "annual_contribution_cents": 500000,
                "annual_total_hours": 2100.00,
                "annual_public_works_hours": 1300.00,
            },
            env["preparer_headers"],
        ),
        expected_status=201,
    )
    rule_on_fringe_plan(api, plan["id"], "APPROVED", officer_headers)

    worker = build_worker(api, env["contractor"]["id"], env["preparer_headers"])
    submission = build_submission(api, env, week_ending_date="2026-08-01T00:00:00.000Z")
    line = build_line(
        api, env, submission["id"], worker["id"],
        straight_hours=40.00, overtime_hours=0.00,
        base_rate_paid_cents=5000, overtime_rate_paid_cents=0,
        fringe_cash_paid_cents=0, fringe_plan_id=plan["id"],
    )
    finalize(api, env, submission["id"])

    priced = get_success_data(api.get_payroll_line(line["id"], env["preparer_headers"]))
    assert priced["required_fringe_cents"] == 2000
    # min(238, 2000) — the authoritative figure, not the 385 covered-hours-only figure.
    assert priced["creditable_fringe_cents"] == 238
    # (5000 + 2000) - (5000 + 0 + 238) = 1762 per hour over 40 hours.
    assert priced["line_underpayment_cents"] == 70480


def test_underpayment_exposes_straight_time_only_and_full_make_whole(api, officer_headers):
    """One line yields 28000 under STRAIGHT_TIME_ONLY and 34400 under FULL_MAKE_WHOLE.

    PRD 3.6 step four: "`straight_time_underpayment_cents` is the sum of the per-line
    straight-time deficiencies only — the preliminary screen the portal shows, which omits
    every overtime deficiency ... `make_whole_underpayment_cents` is the sum of the
    per-line `line_underpayment_cents` values, and it is the authoritative make-whole
    total".

    Design: Difficulty/dual_variant_calc/underpayment_straight_time_only_vs_full_make_whole
    """
    env = setup_env(api, rates=[{"fringe_hourly_rate_cents": 2000}])
    worker = build_worker(api, env["contractor"]["id"], env["preparer_headers"])
    submission = build_submission(api, env, week_ending_date="2026-08-01T00:00:00.000Z")
    line = build_line(
        api, env, submission["id"], worker["id"],
        straight_hours=40.00, overtime_hours=8.00,
        base_rate_paid_cents=4800, overtime_rate_paid_cents=7200,
        fringe_cash_paid_cents=1500,
    )
    finalized = finalize(api, env, submission["id"])

    priced = get_success_data(api.get_payroll_line(line["id"], officer_headers))
    assert priced["required_base_cents"] == 5000
    assert priced["required_fringe_cents"] == 2000
    assert priced["line_underpayment_cents"] == 34400
    assert finalized["straight_time_underpayment_cents"] == 28000
    assert finalized["make_whole_underpayment_cents"] == 34400
    assert finalized["compliance_status"] == "DEFICIENT"
    assert finalized["workflow_status"] == "PENDING_CERTIFICATION"


def test_underpayment_summary_reports_the_variant_delta(api, officer_headers):
    """The computed read exposes both variants side by side with their delta.

    PRD 3.6: "A read-only summary exposes both variants side by side for any submission,
    echoing the `payroll_submission_id`, reporting `straight_time_underpayment_cents` and
    `make_whole_underpayment_cents`, the `variant_delta_cents` between them — the
    make-whole total minus the straight-time total — plus the submission's
    `excess_apprentice_hours` and the `line_count` of payroll lines it carries."

    Design: Difficulty/dual_variant_calc/underpayment_straight_time_only_vs_full_make_whole
    """
    env = setup_env(api, rates=[{"fringe_hourly_rate_cents": 2000}])
    worker = build_worker(api, env["contractor"]["id"], env["preparer_headers"])
    submission = build_submission(api, env, week_ending_date="2026-08-01T00:00:00.000Z")
    build_line(
        api, env, submission["id"], worker["id"],
        straight_hours=40.00, overtime_hours=8.00,
        base_rate_paid_cents=4800, overtime_rate_paid_cents=7200,
        fringe_cash_paid_cents=1500,
    )
    finalize(api, env, submission["id"])

    resp = api.get_underpayment_summary(submission["id"], officer_headers)
    summary = get_success_data(resp)
    validate_success(resp, expected_status=200)
    assert summary["payroll_submission_id"] == submission["id"]
    assert summary["straight_time_underpayment_cents"] == 28000
    assert summary["make_whole_underpayment_cents"] == 34400
    # The 8 overtime hours contribute the whole delta.
    assert summary["variant_delta_cents"] == 6400
    assert float(summary["excess_apprentice_hours"]) == 0.00
    assert summary["line_count"] == 1


def _short_paid_line(hours):
    """5000 base + 1875 cash fringe is exactly 125 cents/h short of the 7000 required."""
    return {
        "straight_hours": hours,
        "overtime_hours": 0.00,
        "base_rate_paid_cents": 5000,
        "overtime_rate_paid_cents": 0,
        "fringe_cash_paid_cents": 1875,
    }


def test_rounding_happens_once_per_line_not_once_per_submission(api, officer_headers):
    """Two half-cent lines round up individually and sum to 3756, never to 3755.

    PRD 3.6 step four: "Rounding happens exactly once per line per hour category and never
    anywhere else in this step: the alternative of accumulating exact per-hour products
    across every line and rounding once at the very end is explicitly rejected, since it
    can differ from the pinned order by as much as one cent per line."

    Design: Difficulty/combinatorial_formula/per_line_rounding_then_sum_beats_aggregate_then_round_by_one_cent
    """
    env = setup_env(api, rates=[{"fringe_hourly_rate_cents": 2000}])
    worker_a = build_worker(api, env["contractor"]["id"], env["preparer_headers"])
    worker_b = build_worker(api, env["contractor"]["id"], env["preparer_headers"])
    submission = build_submission(api, env, week_ending_date="2026-08-01T00:00:00.000Z")
    line1 = build_line(api, env, submission["id"], worker_a["id"], **_short_paid_line(10.02))
    line2 = build_line(api, env, submission["id"], worker_b["id"], **_short_paid_line(20.02))
    finalized = finalize(api, env, submission["id"])

    priced1 = get_success_data(api.get_payroll_line(line1["id"], officer_headers))
    priced2 = get_success_data(api.get_payroll_line(line2["id"], officer_headers))
    # Exact products are 1252.5 and 2502.5; round half up gives 1253 and 2503.
    assert priced1["line_underpayment_cents"] == 1253
    assert priced2["line_underpayment_cents"] == 2503
    assert finalized["make_whole_underpayment_cents"] == 3756
    assert finalized["straight_time_underpayment_cents"] == 3756
    assert float(finalized["total_hours_reported"]) == 30.04
    # AGGREGATE_THEN_ROUND would sum 3755.0 exactly and answer 3755.
    assert finalized["make_whole_underpayment_cents"] != 3755


def test_the_same_hours_on_one_line_round_only_once(api):
    """30.04 hours on a single line yield 3755, one cent below the two-line split.

    PRD 3.6 step four: "The line's straight-time deficiency in cents is then the scaled
    straight-time hourly deficiency multiplied by the still-scaled straight hours, plus the
    journeyworker straight-time hourly deficiency multiplied by the reclassified
    straight-time hours, with that sum rounded half up to a whole cent."

    Design: Difficulty/combinatorial_formula/per_line_rounding_then_sum_beats_aggregate_then_round_by_one_cent
    """
    env = setup_env(api, rates=[{"fringe_hourly_rate_cents": 2000}])
    worker = build_worker(api, env["contractor"]["id"], env["preparer_headers"])
    submission = build_submission(api, env, week_ending_date="2026-08-01T00:00:00.000Z")
    line = build_line(api, env, submission["id"], worker["id"], **_short_paid_line(30.04))
    finalized = finalize(api, env, submission["id"])

    priced = get_success_data(api.get_payroll_line(line["id"], env["preparer_headers"]))
    # 125 * 30.04 = 3755.0 exactly, so this single line rounds to 3755.
    assert priced["line_underpayment_cents"] == 3755
    assert finalized["make_whole_underpayment_cents"] == 3755
    assert float(finalized["total_hours_reported"]) == 30.04


def _apprentice_crew_env(api):
    """ACTIVE project, ELEC rate 5000/2000 with scale [50,60,70,80], REGISTERED program."""
    return setup_env(
        api,
        rates=[{"fringe_hourly_rate_cents": 2000, "apprentice_scale_pct": [50, 60, 70, 80]}],
        with_program={"allowed_apprentice_hours_per_100_journey": 25, "period_count": 4},
    )


def test_apprentice_ratio_makes_one_pass_and_does_not_chase_the_loop(api, officer_headers):
    """80 journey hours permit 20.00 apprentice hours, so 40.00 leaves exactly 20.00 excess.

    PRD 3.6 step one: "The permitted apprentice hours for the family are then the
    journeyworker hour total multiplied by that permitted ratio and divided by 100, rounded
    half up to two decimal places." PRD 3.6 step one also pins the single pass: "This
    allocation makes one pass and one pass only, using the journeyworker hour total as it
    stood *before* any reclassification. ... There is no second pass and no fixed-point
    iteration".

    Design: Difficulty/combinatorial_formula/apprentice_ratio_single_pass_pins_circular_reclassification
    """
    env = _apprentice_crew_env(api)
    j1 = build_worker(api, env["contractor"]["id"], env["preparer_headers"])
    j2 = build_worker(api, env["contractor"]["id"], env["preparer_headers"])
    apprentice = build_worker(
        api, env["contractor"]["id"], env["preparer_headers"],
        apprentice_program_id=env["program"]["id"], apprentice_period=1,
    )
    submission = build_submission(api, env, week_ending_date="2026-08-01T00:00:00.000Z")
    compliant = {
        "straight_hours": 40.00, "overtime_hours": 0.00,
        "base_rate_paid_cents": 5000, "overtime_rate_paid_cents": 0,
        "fringe_cash_paid_cents": 2000,
    }
    line1 = build_line(api, env, submission["id"], j1["id"], **compliant)
    line2 = build_line(api, env, submission["id"], j2["id"], **compliant)
    line3 = build_line(
        api, env, submission["id"], apprentice["id"],
        straight_hours=40.00, overtime_hours=0.00,
        base_rate_paid_cents=2500, overtime_rate_paid_cents=0,
        fringe_cash_paid_cents=2000, reported_as_apprentice=True,
    )
    finalized = finalize(api, env, submission["id"])

    assert float(finalized["excess_apprentice_hours"]) == 20.00
    priced3 = get_success_data(api.get_payroll_line(line3["id"], officer_headers))
    assert float(priced3["reclassified_journey_hours"]) == 20.00
    assert priced3["required_base_cents"] == 2500
    assert priced3["required_fringe_cents"] == 2000
    # 20 reclassified hours owed the full 7000 journeyworker requirement against 4500 paid.
    assert priced3["line_underpayment_cents"] == 50000
    for line_id in (line1["id"], line2["id"]):
        priced = get_success_data(api.get_payroll_line(line_id, officer_headers))
        assert priced["line_underpayment_cents"] == 0
    assert finalized["make_whole_underpayment_cents"] == 50000
    assert finalized["compliance_status"] == "DEFICIENT"


def test_apprentice_hours_exactly_at_the_permitted_allowance_are_compliant(api, officer_headers):
    """20.00 apprentice hours against 80.00 journey hours leave no excess at all.

    PRD 3.6 step one: "The excess for the family is the apprentice hour total minus the
    permitted hours when that difference is positive, and zero otherwise; an apprentice
    total exactly equal to the permitted hours is compliant, not excessive."

    Design: Difficulty/combinatorial_formula/apprentice_ratio_single_pass_pins_circular_reclassification
    """
    env = _apprentice_crew_env(api)
    j1 = build_worker(api, env["contractor"]["id"], env["preparer_headers"])
    j2 = build_worker(api, env["contractor"]["id"], env["preparer_headers"])
    apprentice = build_worker(
        api, env["contractor"]["id"], env["preparer_headers"],
        apprentice_program_id=env["program"]["id"], apprentice_period=1,
    )
    submission = build_submission(api, env, week_ending_date="2026-08-01T00:00:00.000Z")
    compliant = {
        "straight_hours": 40.00, "overtime_hours": 0.00,
        "base_rate_paid_cents": 5000, "overtime_rate_paid_cents": 0,
        "fringe_cash_paid_cents": 2000,
    }
    build_line(api, env, submission["id"], j1["id"], **compliant)
    build_line(api, env, submission["id"], j2["id"], **compliant)
    apprentice_line = build_line(
        api, env, submission["id"], apprentice["id"],
        straight_hours=20.00, overtime_hours=0.00,
        base_rate_paid_cents=2500, overtime_rate_paid_cents=0,
        fringe_cash_paid_cents=2000, reported_as_apprentice=True,
    )
    finalized = finalize(api, env, submission["id"])

    assert float(finalized["excess_apprentice_hours"]) == 0.00
    priced = get_success_data(api.get_payroll_line(apprentice_line["id"], officer_headers))
    assert float(priced["reclassified_journey_hours"]) == 0.00
    assert priced["line_underpayment_cents"] == 0
    assert finalized["make_whole_underpayment_cents"] == 0
    assert finalized["compliance_status"] == "COMPLIANT"
