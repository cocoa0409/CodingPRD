"""Subsidy, MAGI, proration, and reconciliation calculation depth tests (queue A)."""
from test_helpers import (
    validate_success,
    setup_reconciliation,
    setup_determined_sep_application,
    create_enrollment,
    create_household_with_primary,
    add_member,
    setup_determined_application,
    create_household,
    create_application,
    submit_application,
    determine_application,
)


def test_aptc_reconciliation_estimated_vs_reconciled_repayment(api):
    """PRD §3.7: "The **advanced total** is the estimated rollup of what was actually advanced during the year: the enrollment's `applied_aptc_monthly_cents`, drawn from the enrollment-time determination on projected MAGI, multiplied by `months_enrolled`."
    PRD §3.7: "The **settlement** in `settlement_cents` is the advanced total minus the allowed total: a positive settlement is an amount the household must repay, while a negative settlement is an additional credit owed to the household."

    Design: Difficulty/dual_variant_calc/aptc_estimated_vs_reconciled_settlement
    """
    ctx = setup_reconciliation("app-1", actual_annual_magi_cents=3_300_000,
                               months_enrolled=12, income_cents=3_000_000,
                               elected_aptc_monthly_cents=45_000, benchmark_gross=50_000)
    rec = ctx["reconciliation"]
    assert rec["advanced_aptc_total_cents"] == 540000
    assert rec["allowed_aptc_total_cents"] == 507600
    assert rec["settlement_cents"] == 32400


def test_aptc_reconciliation_realized_equals_projected_zero_settlement_components(api):
    """PRD §3.7: "the allowed monthly APTC as the larger of 0 and the benchmark premium minus that contribution; and multiply the allowed monthly figure by `months_enrolled` to obtain `allowed_aptc_total_cents`."

    Design: Difficulty/dual_variant_calc/aptc_estimated_vs_reconciled_settlement
    """
    # Realized MAGI equals projected: advanced and allowed match, settlement 0.
    ctx = setup_reconciliation("app-1b", actual_annual_magi_cents=3_000_000,
                               months_enrolled=12, income_cents=3_000_000,
                               elected_aptc_monthly_cents=45_000, benchmark_gross=50_000)
    rec = ctx["reconciliation"]
    assert rec["advanced_aptc_total_cents"] == 540000
    assert rec["allowed_aptc_total_cents"] == 540000
    assert rec["settlement_cents"] == 0


def test_birth_sep_retroactive_effective_date_and_prorated_first_month(api):
    """PRD §3.5: "When the event is `BIRTH` or `ADOPTION`, the effective date is retroactive to the `event_date` itself."
    PRD §3.5: "the daily rate is the net monthly premium divided by the month length as an exact rational; and `first_month_premium_cents` is the daily rate multiplied by the covered days, rounded half up to whole cents (the rounding is applied once, after multiplying the daily rate by the covered days)."

    Design: Difficulty/dual_variant_calc/effective_date_retroactive_vs_prospective_first_month
    """
    ctx = setup_determined_sep_application(
        "app-2", qualifying_event_type="BIRTH", event_date="2026-06-16",
        event_clock="2026-06-18T00:00:00Z", submit_clock="2026-06-20T00:00:00Z",
        income_cents=3_000_000, benchmark_gross=50_000)
    enr = create_enrollment(ctx["application"]["id"], ctx["household"]["id"],
                            ctx["plan"]["id"], "app-2", elected_aptc_monthly_cents=45_000)
    assert enr["effective_date"] == "2026-06-16"
    assert enr["net_premium_monthly_cents"] == 5000
    assert enr["first_month_premium_cents"] == 2500


def test_oep_prospective_effective_date_full_first_month(api):
    """PRD §3.5: "For an `OEP` application, coverage begins on the first day of the month following the month of `submitted_at` (interpreting `submitted_at` by its UTC date)."
    PRD §3.5: "If the effective day is 1, the coverage spans the whole month and `first_month_premium_cents` equals `net_premium_monthly_cents` with no proration."

    Design: Difficulty/dual_variant_calc/effective_date_retroactive_vs_prospective_first_month
    """
    ctx = setup_determined_application("app-2b", income_cents=3_000_000,
                                       benchmark_gross=50_000, clock="2026-06-20T00:00:00Z")
    enr = create_enrollment(ctx["application"]["id"], ctx["household"]["id"],
                            ctx["plan"]["id"], "app-2b", elected_aptc_monthly_cents=45_000)
    assert enr["effective_date"] == "2026-07-01"
    assert enr["net_premium_monthly_cents"] == 5000
    assert enr["first_month_premium_cents"] == 5000


def test_household_magi_excludes_low_income_dependent_nonfiler(api):
    """PRD §3.1: "A member is countable for income unless it is simultaneously a `DEPENDENT_NONFILER` and has `annual_income_cents` below the dependent filing threshold of $14,600 (that is, below 1,460,000 cents); the member's `is_countable_income` flag mirrors exactly this predicate, being false only for a `DEPENDENT_NONFILER` whose income is under that threshold and true otherwise."
    PRD §3.1: "a `DEPENDENT_NONFILER` excluded from the income sum still adds to `countable_size` if it is applying for coverage, because `countable_size` is the size used as the denominator in the Federal Poverty Level calculation."

    Design: Difficulty/combinatorial_formula/household_magi_conditional_dependent_exclusion
    """
    hh, _ = create_household_with_primary("app-3", income_cents=2_800_000,
                                          full_name="Primary P")
    dep = add_member(hh["id"], "app-3", full_name="Dep D", relationship="DEPENDENT",
                     tax_filing_status="DEPENDENT_NONFILER", annual_income_cents=300_000,
                     applies_for_coverage=True)
    got = validate_success(api.get_household(hh["id"], __headers("app-3")), 200)
    assert got["household_magi_cents"] == 2800000
    assert got["countable_size"] == 2
    assert got["fpl_percent"] == 137.93
    assert dep["is_countable_income"] is False


def test_household_magi_counts_filer_dependent_income(api):
    """PRD §3.1: "The household's `household_magi_cents` is the sum of `annual_income_cents` across the countable members; because all operands are integer cents, no rounding occurs."

    Design: Difficulty/combinatorial_formula/household_magi_conditional_dependent_exclusion
    """
    # A DEPENDENT_FILER (not NONFILER) is always countable, so its income is summed.
    hh, _ = create_household_with_primary("app-3b", income_cents=2_800_000)
    dep = add_member(hh["id"], "app-3b", full_name="Dep Filer", relationship="DEPENDENT",
                     tax_filing_status="DEPENDENT_FILER", annual_income_cents=300_000,
                     applies_for_coverage=True)
    got = validate_success(api.get_household(hh["id"], __headers("app-3b")), 200)
    assert got["household_magi_cents"] == 3100000
    assert got["countable_size"] == 2
    assert dep["is_countable_income"] is True


def test_first_month_proration_rounds_once_after_multiply(api):
    """PRD §3.5: "the daily rate is the net monthly premium divided by the month length as an exact rational; and `first_month_premium_cents` is the daily rate multiplied by the covered days, rounded half up to whole cents (the rounding is applied once, after multiplying the daily rate by the covered days)."

    Design: Difficulty/combinatorial_formula/first_month_proration_round_then_sum_order
    """
    # net 5000, June (30 days), effective day 16 -> cov_days 15 -> 5000/30*15 = 2500 exact.
    # The reject-alternative (round daily to 167 first, *15 = 2505) must NOT be produced.
    ctx = setup_determined_sep_application(
        "app-4", qualifying_event_type="BIRTH", event_date="2026-06-16",
        event_clock="2026-06-18T00:00:00Z", submit_clock="2026-06-20T00:00:00Z",
        rating_area="RA02", income_cents=3_000_000, benchmark_gross=50_000)
    enr = create_enrollment(ctx["application"]["id"], ctx["household"]["id"],
                            ctx["plan"]["id"], "app-4", elected_aptc_monthly_cents=45_000)
    assert enr["net_premium_monthly_cents"] == 5000
    assert enr["first_month_premium_cents"] == 2500


def test_first_month_no_proration_when_effective_day_is_one(api):
    """PRD §3.5: "If the effective day is 1, the coverage spans the whole month and `first_month_premium_cents` equals `net_premium_monthly_cents` with no proration."

    Design: Difficulty/combinatorial_formula/first_month_proration_round_then_sum_order
    """
    # A prospective (OEP) enrollment lands on the 1st: first_month equals the full net.
    ctx = setup_determined_application("app-4b", income_cents=3_000_000,
                                       benchmark_gross=50_000, clock="2026-06-20T00:00:00Z")
    enr = create_enrollment(ctx["application"]["id"], ctx["household"]["id"],
                            ctx["plan"]["id"], "app-4b", elected_aptc_monthly_cents=45_000)
    assert enr["effective_date"] == "2026-07-01"
    assert enr["net_premium_monthly_cents"] == 5000
    assert enr["first_month_premium_cents"] == 5000


def test_applicable_pct_band_edge_inclusive_at_200(api):
    """PRD §3.3: "Every band's upper edge is inclusive: a snapshot of exactly 200 yields
    0.02 (not the next band's interpolation), and a snapshot of exactly 150 yields 0."
    PRD §3.3: "The maximum monthly APTC stored in `max_aptc_monthly_cents` is the larger of 0 and the benchmark premium minus that monthly contribution."

    Design: Difficulty/boundary_precision_check/applicable_pct_band_edge_inclusive_at_200
    """
    # income 3000000, size 1 -> fpl 200.00 exactly. contribution = 3000000*0.02/12 = 5000.
    # max_aptc = 50000 - 5000 = 45000.
    hh = create_household("app-11")
    add_member(hh["id"], "app-11", full_name="Band Edge", relationship="PRIMARY",
               tax_filing_status="FILER", annual_income_cents=3_000_000)
    # benchmark plan + clock are needed for determine.
    from test_helpers import set_clock, register_benchmark_plan
    set_clock("2026-01-10T00:00:00Z")
    register_benchmark_plan(rating_area="RA01", coverage_year=2026, gross_premium_cents=50_000)
    app = create_application(hh["id"], "app-11", enrollment_window="OEP")
    submit_application(app["id"], hh["id"], "app-11")
    det = determine_application(app["id"])
    assert det["fpl_percent_snapshot"] == 200.00
    assert det["applicable_pct"] == 0.020000
    assert det["max_aptc_monthly_cents"] == 45000


def test_applicable_pct_just_above_200_uses_next_band(api):
    """PRD §3.3: "If *p* is greater than 200 and at most 250, it is 0.02 plus (p − 200) ÷ (250 − 200) multiplied by (0.04 − 0.02)."

    Design: Difficulty/boundary_precision_check/applicable_pct_band_edge_inclusive_at_200
    """
    # income 3015000, size 1 -> fpl 201.00 -> next band interpolation, strictly above 0.02.
    from test_helpers import set_clock, register_benchmark_plan
    set_clock("2026-01-10T00:00:00Z")
    register_benchmark_plan(rating_area="RA01", coverage_year=2026, gross_premium_cents=50_000)
    hh = create_household("app-11b")
    add_member(hh["id"], "app-11b", full_name="Above Edge", relationship="PRIMARY",
               tax_filing_status="FILER", annual_income_cents=3_015_000)
    app = create_application(hh["id"], "app-11b", enrollment_window="OEP")
    submit_application(app["id"], hh["id"], "app-11b")
    det = determine_application(app["id"])
    assert det["fpl_percent_snapshot"] == 201.00
    assert det["applicable_pct"] > 0.020000


# ── local helper ──
def __headers(user_id):
    from test_helpers import make_applicant_headers
    return make_applicant_headers(user_id)
