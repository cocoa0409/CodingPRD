"""Shadow payroll record computation: immediate derived fields, the tiered
hypothetical tax with proration, the pinned allowance rounding order, the
employer gross-up fixed point, and the record-creation date/quantity rules
(PRD §2.6, §3.3)."""
import pytest

from test_helpers import (
    ApiErrorId,
    CANONICAL,
    create_draft_record,
    create_record_payload,
    setup_active_assignment,
    validate_error,
    validate_success,
)


def test_shadow_record_create_returns_computed_fields_immediately(api, payroll_headers):
    """PRD §3.3: "The record is created in `DRAFT` with all computed fields derived
    immediately from the `ACTIVE` split's percentages and the assignment's policy,
    recomputed while it remains in `DRAFT` whenever an underlying input changes, and
    frozen at posting."
    PRD §3.3: "`home_gross_cents` is the record's `total_gross_cents` multiplied by
    `home_payroll_pct` and divided by one hundred, rounded half up to integer cents;
    `host_gross_cents` is the residual — total minus home — so the two shares always
    sum back to the total"
    PRD §3.3: "`employer_socsec_cents` is zero while the split's `coc_exempt` flag is
    true, and otherwise seven point six five percent of `host_gross_cents`, rounded
    half up."

    Design: Corner/entities/shadow_record_create_returns_computed_fields_immediately
    """
    ctx = setup_active_assignment(totalization=True)
    record = create_draft_record(
        ctx["assignment"]["id"], tax_year=2026, period_month=9,
        total_gross_cents=900000, per_diem_days=20, housing_receipts_cents=310000)

    assert record["status"] == "DRAFT"
    assert record["home_gross_cents"] == CANONICAL["REC_HOME_GROSS"]
    assert record["host_gross_cents"] == CANONICAL["REC_HOST_GROSS"]
    assert record["home_gross_cents"] + record["host_gross_cents"] == 900000
    assert record["per_diem_cents"] == CANONICAL["REC_PER_DIEM"]
    assert record["housing_cents"] == CANONICAL["REC_HOUSING"]
    assert record["hypothetical_tax_cents"] == CANONICAL["REC_HYPO_TAX"]
    assert record["employer_host_tax_cents"] == CANONICAL["REC_EMPLOYER_HOST_TAX"]
    assert record["employer_socsec_cents"] == CANONICAL["REC_SOCSEC_EXEMPT"], (
        "coc_exempt is true, so employer social security must be zero"
    )


def test_hypothetical_tax_crosses_all_three_brackets(api, payroll_headers):
    """PRD §3.3: "For an annual gross amount, taxable income is the gross minus the
    exemption, floored at zero; the annual tax is ten percent of the first 5000000
    cents of taxable income, plus twenty percent of the portion of taxable income
    between 5000000 and 10000000 cents, plus thirty percent of any taxable income above
    10000000 cents, with the annual figure rounded half up to integer cents."
    PRD §3.3: "Each shadow payroll record applies the PROVISIONAL variant: the record's
    `total_gross_cents` is multiplied by twelve to project an annual gross, the annual
    schedule is applied, and the result is divided by twelve and rounded half up to
    integer cents to yield `hypothetical_tax_cents` — a forward-looking withholding
    estimate."

    Design: Difficulty/combinatorial_formula/hypothetical_tax_tiered_brackets_with_proration
    """
    ctx = setup_active_assignment(totalization=True)
    # 900000 x 12 = 10800000; exemption 2 x 200000 = 400000; taxable 10400000
    # crosses all three brackets: 500000 + 1000000 + 120000 = 1620000; /12 = 135000.
    record = create_draft_record(
        ctx["assignment"]["id"], tax_year=2026, period_month=9,
        total_gross_cents=900000, per_diem_days=0, housing_receipts_cents=0)
    assert record["hypothetical_tax_cents"] == 135000


def test_hypothetical_tax_monthly_division_rounds_half_up(api, payroll_headers):
    """PRD §3.3: "Each shadow payroll record applies the PROVISIONAL variant: the
    record's `total_gross_cents` is multiplied by twelve to project an annual gross,
    the annual schedule is applied, and the result is divided by twelve and rounded
    half up to integer cents to yield `hypothetical_tax_cents` — a forward-looking
    withholding estimate."
    PRD §2.6: "Rounding, where a rule requires it, is always round half up to integer
    cents, applied at exactly the pinned step the rule declares — never earlier, never
    twice."

    Design: Difficulty/combinatorial_formula/hypothetical_tax_tiered_brackets_with_proration
    """
    ctx = setup_active_assignment(totalization=True)
    # 400000 x 12 = 4800000; taxable 4400000 (bracket 1 only); tax 440000;
    # 440000 / 12 = 36666.67 -> round half up 36667 (truncation would give 36666).
    record = create_draft_record(
        ctx["assignment"]["id"], tax_year=2026, period_month=10,
        total_gross_cents=400000, per_diem_days=0, housing_receipts_cents=0)
    assert record["hypothetical_tax_cents"] == 36667


def _setup_sg_assignment():
    """SG policy 6333/day, cola 7, housing cap 250000; 50/50 split; no totalization."""
    return setup_active_assignment(
        policy_overrides={
            "policy_name": "SG Alt", "host_country_code": "SG",
            "effective_from": "2027-01-01", "effective_to": "2028-01-01",
            "per_diem_daily_cents": 6333, "housing_monthly_cap_cents": 250000,
            "cola_pct": 7,
        },
        employee_overrides={"employee_ref": "E2002", "full_name": "Ben Traveler",
                            "family_size": 1, "annual_base_salary_cents": 6000000},
        assignment_overrides={
            "host_country_code": "SG", "host_business_unit": "BU-SG",
            "start_date": "2027-01-01", "planned_end_date": "2027-12-31",
        },
        home_pct=50, host_pct=50,
    )


def test_allowance_accrual_rounds_daily_rate_before_multiplying(api, payroll_headers):
    """PRD §3.3: "`per_diem_cents` is the policy's `per_diem_daily_cents` uplifted by
    `cola_pct` — multiplied by one hundred plus `cola_pct` and divided by one hundred,
    rounded half up to integer cents at the daily-rate step — then multiplied by
    `per_diem_days` with no second rounding; computing the monthly product first and
    rounding once at the end is forbidden, because the two orders diverge by cents
    whenever the daily rate is non-integral."
    PRD §3.3: "`housing_cents` is the lesser of the policy's `housing_monthly_cap_cents`
    and the month's `housing_receipts_cents`."

    Design: Difficulty/combinatorial_formula/allowance_accrual_nested_rounding_order
    """
    ctx = _setup_sg_assignment()
    # round_half_up(6333 x 107 / 100) = 6776 per day; x 20 = 135520. The forbidden
    # multiply-then-round order would give 135526. Receipts 260000 clamp to 250000.
    record = create_draft_record(
        ctx["assignment"]["id"], tax_year=2027, period_month=2,
        total_gross_cents=500000, per_diem_days=20, housing_receipts_cents=260000)
    assert record["per_diem_cents"] == 135520
    assert record["housing_cents"] == 250000


def test_allowance_accrual_second_month_and_split_conservation(api, payroll_headers):
    """PRD §3.3: "`per_diem_cents` is the policy's `per_diem_daily_cents` uplifted by
    `cola_pct` — multiplied by one hundred plus `cola_pct` and divided by one hundred,
    rounded half up to integer cents at the daily-rate step — then multiplied by
    `per_diem_days` with no second rounding; computing the monthly product first and
    rounding once at the end is forbidden, because the two orders diverge by cents
    whenever the daily rate is non-integral."
    PRD §3.3: "`home_gross_cents` is the record's `total_gross_cents` multiplied by
    `home_payroll_pct` and divided by one hundred, rounded half up to integer cents;
    `host_gross_cents` is the residual — total minus home — so the two shares always
    sum back to the total"

    Design: Difficulty/combinatorial_formula/allowance_accrual_nested_rounding_order
    """
    ctx = _setup_sg_assignment()
    # Same pinned daily rate 6776, x 10 days = 67760; receipts under the cap pass
    # through; the 50/50 split conserves the 500000 total.
    record = create_draft_record(
        ctx["assignment"]["id"], tax_year=2027, period_month=3,
        total_gross_cents=500000, per_diem_days=10, housing_receipts_cents=100000)
    assert record["per_diem_cents"] == 67760
    assert record["housing_cents"] == 100000
    assert record["home_gross_cents"] == 250000
    assert record["host_gross_cents"] == 250000
    assert record["home_gross_cents"] + record["host_gross_cents"] == 500000


def test_employer_tax_gross_up_fixed_point_on_round_host_share(api, payroll_headers):
    """PRD §3.3: "`employer_host_tax_cents` is a fixed-point gross-up at a host tax
    rate of forty percent, circular by definition because the employer-paid tax is
    itself a taxable benefit: the initial estimate is forty percent of
    `host_gross_cents` rounded half up; each subsequent estimate is forty percent of
    the sum of `host_gross_cents` and the current estimate, rounded half up at every
    round; iteration stops when two consecutive estimates agree, after at most fifty
    rounds, and the final estimate is stored."
    PRD §3.3: "`employer_socsec_cents` is zero while the split's `coc_exempt` flag is
    true, and otherwise seven point six five percent of `host_gross_cents`, rounded
    half up."

    Design: Difficulty/combinatorial_formula/employer_tax_gross_up_fixed_point_iteration
    """
    ctx = setup_active_assignment(totalization=False)
    # host 360000 converges to the exact fixed point 240000: 0.40 x 600000 = 240000.
    record = create_draft_record(
        ctx["assignment"]["id"], tax_year=2026, period_month=9,
        total_gross_cents=900000, per_diem_days=20, housing_receipts_cents=310000)
    assert record["host_gross_cents"] == 360000
    assert record["employer_host_tax_cents"] == 240000
    assert record["employer_socsec_cents"] == 27540, (
        "no certificate: round_half_up(360000 x 0.0765) = 27540"
    )


def test_employer_tax_gross_up_fixed_point_on_odd_host_share(api, payroll_headers):
    """PRD §3.3: "`employer_host_tax_cents` is a fixed-point gross-up at a host tax
    rate of forty percent, circular by definition because the employer-paid tax is
    itself a taxable benefit: the initial estimate is forty percent of
    `host_gross_cents` rounded half up; each subsequent estimate is forty percent of
    the sum of `host_gross_cents` and the current estimate, rounded half up at every
    round; iteration stops when two consecutive estimates agree, after at most fifty
    rounds, and the final estimate is stored."

    Design: Difficulty/combinatorial_formula/employer_tax_gross_up_fixed_point_iteration
    """
    ctx = setup_active_assignment(totalization=False)
    # total 1203188: home round_half_up(721912.8) = 721913, host residual 481275;
    # the pinned iteration converges to 320850: 0.40 x 802125 = 320850 exactly.
    record = create_draft_record(
        ctx["assignment"]["id"], tax_year=2026, period_month=10,
        total_gross_cents=1203188, per_diem_days=20, housing_receipts_cents=300000)
    assert record["host_gross_cents"] == 481275
    assert record["employer_host_tax_cents"] == 320850
    assert record["employer_socsec_cents"] == 36818, (
        "round_half_up(481275 x 0.0765) = round_half_up(36817.5375) = 36818"
    )


def test_temporal_beats_constraint_on_record_create(api, payroll_headers):
    """PRD §3.3: "Creation is gated in pipeline order: the assignment must be `ACTIVE`
    (`ERR_INVALID_STATE`); an `ACTIVE` payroll split must exist (`ERR_SPLIT_NOT_ACTIVE`);
    within the date-window family the period-window check precedes the remaining record
    checks, so the record's month must intersect the assignment's
    `start_date`–`planned_end_date` window (`ERR_PERIOD_OUTSIDE_ASSIGNMENT`, HTTP 422)
    before the uniqueness sweep runs"
    PRD §2.10: "Every request is evaluated against a fixed validation pipeline, and the
    earliest failing check determines the error returned:"

    Design: Difficulty/priority_pair_validation_conflict/temporal_beats_constraint_on_record_create
    """
    ctx = setup_active_assignment()
    # June 2026 is entirely before the 2026-09-01 start, AND June has only 30 days
    # so 31 per-diem days is also invalid. The temporal error must win.
    res = api.create_record(
        create_record_payload(
            ctx["assignment"]["id"], tax_year=2026, period_month=6,
            total_gross_cents=900000, per_diem_days=31, housing_receipts_cents=0),
        payroll_headers)
    validate_error(res, ApiErrorId.ERR_PERIOD_OUTSIDE_ASSIGNMENT)


def test_per_diem_days_invalid_isolated_inside_window(api, payroll_headers):
    """PRD §3.3: "at most one record per assignment, tax year, and period month may
    exist in `DRAFT` or `POSTED` status — a `VOIDED` record frees the slot — else
    `ERR_DUPLICATE_PAYROLL_PERIOD`; and `per_diem_days` must not exceed the number of
    days in the period month, else `ERR_PER_DIEM_DAYS_INVALID` (HTTP 422)."

    Design: Difficulty/priority_pair_validation_conflict/temporal_beats_constraint_on_record_create
    """
    ctx = setup_active_assignment()
    # September 2026 (30 days) is inside the window; 31 days violates the
    # month-length constraint alone.
    res = api.create_record(
        create_record_payload(
            ctx["assignment"]["id"], tax_year=2026, period_month=9,
            total_gross_cents=900000, per_diem_days=31, housing_receipts_cents=0),
        payroll_headers)
    validate_error(res, ApiErrorId.ERR_PER_DIEM_DAYS_INVALID)


def test_per_diem_days_above_month_length_rejected(api, payroll_headers):
    """PRD §3.3: "at most one record per assignment, tax year, and period month may
    exist in `DRAFT` or `POSTED` status — a `VOIDED` record frees the slot — else
    `ERR_DUPLICATE_PAYROLL_PERIOD`; and `per_diem_days` must not exceed the number of
    days in the period month, else `ERR_PER_DIEM_DAYS_INVALID` (HTTP 422)."

    Design: Corner/validations/per_diem_days_above_month_length_rejected
    """
    ctx = setup_active_assignment(
        assignment_overrides={"start_date": "2027-01-01", "planned_end_date": "2027-12-31"},
    )
    # February 2027 has 28 days.
    res = api.create_record(
        create_record_payload(
            ctx["assignment"]["id"], tax_year=2027, period_month=2,
            total_gross_cents=900000, per_diem_days=29, housing_receipts_cents=0),
        payroll_headers)
    validate_error(res, ApiErrorId.ERR_PER_DIEM_DAYS_INVALID)
