"""Calculation corner cases: CSR boundary, APTC clamp, effective-date branches,
negative settlement (queue B)."""
from test_helpers import (
    validate_success,
    set_clock,
    register_benchmark_plan,
    register_plan,
    create_household_with_primary,
    create_application,
    submit_application,
    determine_application,
    create_enrollment,
    setup_determined_sep_application,
    setup_reconciliation,
    make_applicant_headers,
)


def test_csr_plus_tier_at_150_pct_boundary(api):
    """PRD §3.3: "When *p* is at least 100 and at most 150, the tier is `CSR94` — the top "CSR Plus" tier."
    PRD §3.3: "The 150 boundary is inclusive in the `CSR94` band: a snapshot of exactly 150 yields `CSR94`, while 150.01 yields `CSR87`."
    PRD §3.3: "Every band's upper edge is inclusive: a snapshot of exactly 200 yields 0.02 (not the next band's interpolation), and a snapshot of exactly 150 yields 0."

    Design: Corner/calculations/csr_plus_tier_at_150_pct_boundary
    """
    # income 2250000, size 1 -> fpl 150.00. applicable_pct 0 -> max_aptc = full benchmark.
    set_clock("2026-01-10T00:00:00Z")
    register_benchmark_plan(gross_premium_cents=50_000)
    hh, _ = create_household_with_primary("c-16", income_cents=2_250_000)
    app = create_application(hh["id"], "c-16", enrollment_window="OEP")
    submit_application(app["id"], hh["id"], "c-16")
    det = determine_application(app["id"])
    assert det["fpl_percent_snapshot"] == 150.00
    assert det["csr_tier"] == "CSR94"
    assert det["applicable_pct"] == 0.000000
    assert det["max_aptc_monthly_cents"] == 50000


def test_applied_aptc_clamped_by_plan_gross_premium(api):
    """PRD §3.5: "The **applied APTC** in `applied_aptc_monthly_cents` is the smallest of three figures: the elected amount, the determination's `max_aptc_monthly_cents`, and the plan's `gross_premium_cents`. The **net monthly premium** in `net_premium_monthly_cents` is the plan's `gross_premium_cents` minus the applied APTC."

    Design: Corner/calculations/applied_aptc_clamped_by_plan_gross_premium
    """
    set_clock("2026-01-10T00:00:00Z")
    register_benchmark_plan(gross_premium_cents=50_000)
    bronze = register_plan(metal_tier="BRONZE", gross_premium_cents=30_000)
    hh, _ = create_household_with_primary("c-17", income_cents=3_000_000)
    app = create_application(hh["id"], "c-17", enrollment_window="OEP")
    submit_application(app["id"], hh["id"], "c-17")
    determine_application(app["id"])
    enr = create_enrollment(app["id"], hh["id"], bronze["id"], "c-17",
                            elected_aptc_monthly_cents=45_000)
    assert enr["applied_aptc_monthly_cents"] == 30000
    assert enr["net_premium_monthly_cents"] == 0


def test_oep_effective_date_first_of_next_month_full_premium(api):
    """PRD §3.5: "For an `OEP` application, coverage begins on the first day of the month following the month of `submitted_at` (interpreting `submitted_at` by its UTC date)."
    PRD §3.5: "If the effective day is 1, the coverage spans the whole month and `first_month_premium_cents` equals `net_premium_monthly_cents` with no proration."

    Design: Corner/calculations/oep_effective_date_first_of_next_month_full_premium
    """
    set_clock("2026-01-10T00:00:00Z")
    plan = register_benchmark_plan(gross_premium_cents=50_000)
    hh, _ = create_household_with_primary("c-18", income_cents=3_000_000)
    app = create_application(hh["id"], "c-18", enrollment_window="OEP")
    submit_application(app["id"], hh["id"], "c-18")
    determine_application(app["id"])
    enr = create_enrollment(app["id"], hh["id"], plan["id"], "c-18",
                            elected_aptc_monthly_cents=45_000)
    assert enr["effective_date"] == "2026-02-01"
    assert enr["net_premium_monthly_cents"] == 5000
    assert enr["first_month_premium_cents"] == 5000


def test_loss_of_coverage_after_15th_effective_month_after_next(api):
    """PRD §3.5: "When the event is `LOSS_OF_COVERAGE`, the regular cutoff rule applies: take the day-of-month of `submitted_at`; the base date is the first day of the month following the submission month; if that day-of-month is at most 15 the effective date is the base date, and if it is greater than 15 the effective date is one month after the base date."

    Design: Corner/calculations/loss_of_coverage_after_15th_effective_month_after_next
    """
    # event 2026-06-01, submitted 2026-06-20 (day 20 > 15) -> base 2026-07-01 +1 month = 2026-08-01.
    ctx = setup_determined_sep_application(
        "c-19", qualifying_event_type="LOSS_OF_COVERAGE", event_date="2026-06-01",
        event_clock="2026-06-10T00:00:00Z", submit_clock="2026-06-20T00:00:00Z",
        income_cents=3_000_000, benchmark_gross=50_000)
    enr = create_enrollment(ctx["application"]["id"], ctx["household"]["id"],
                            ctx["plan"]["id"], "c-19", elected_aptc_monthly_cents=45_000)
    assert enr["effective_date"] == "2026-08-01"


def test_reconciliation_negative_settlement_additional_credit(api):
    """PRD §3.7: "The **settlement** in `settlement_cents` is the advanced total minus the allowed total: a positive settlement is an amount the household must repay, while a negative settlement is an additional credit owed to the household."

    Design: Corner/calculations/reconciliation_negative_settlement_additional_credit
    """
    # projected income 3000000 -> applied 45000/mo; realized 2250000 (fpl 150 -> rate 0)
    # allowed monthly = 50000 -> allowed 600000; advanced 540000; settlement -60000.
    ctx = setup_reconciliation("c-20", actual_annual_magi_cents=2_250_000, months_enrolled=12,
                               income_cents=3_000_000, elected_aptc_monthly_cents=45_000,
                               benchmark_gross=50_000)
    rec = ctx["reconciliation"]
    assert rec["advanced_aptc_total_cents"] == 540000
    assert rec["allowed_aptc_total_cents"] == 600000
    assert rec["settlement_cents"] == -60000
