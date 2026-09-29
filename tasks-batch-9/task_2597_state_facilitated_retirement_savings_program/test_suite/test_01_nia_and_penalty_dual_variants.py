"""
Two places where the programme computes a figure twice and keeps both answers.

An excess-contribution correction always stores both net-income-attributable
variants and then applies exactly one of them, and a penalty assessment always
stores both the per-employee statutory figure and the graduated shortfall figure
and then owes exactly one of them. These tests pin the applied figure and the
figure that lost, because a service that computes only the winner cannot be
audited.
"""

from prd_bench_local_runner.testing import validate_success

from test_helpers import (
    EMPLOYER_HARBOR,
    OFFICER_ASSESSOR,
    OFFICER_ASSESSOR_USER_ID,
    activate_savers,
    add_remittance_line,
    build_active_saver_environment,
    build_employer_environment,
    build_notified_saver,
    complete_excess_case,
    create_remittance,
    elect_correction_method,
    excess_cases_for_account,
    fund_account_by_remittance,
    post_earnings,
    read_account,
    read_employer,
    read_excess_case,
    read_penalty,
    set_clock,
    submit_remittance,
)


def _build_detected_excess_case(api):
    """
    An account funded by two posted batches whose combined credits break the
    annual ceiling, leaving one detected case with a 450000-cent opening balance
    and a 100000-cent excess.
    """
    env = build_active_saver_environment(api)
    fund_account_by_remittance(
        api, env, "2026-02-01", "2026-02-28", "2026-03-05",
        8000000, 400000, "2026-03-06T00:00:00Z",
        posting_reference="PR-2026-0001")
    post_earnings(api, env["account_id"], 50000, "2026-03-06")
    fund_account_by_remittance(
        api, env, "2026-03-01", "2026-03-31", "2026-04-03",
        8000000, 400000, "2026-04-05T00:00:00Z",
        posting_reference="PR-2026-0002")
    cases = excess_cases_for_account(api, env["account_id"])
    assert len(cases) == 1, f"expected one excess case, found {len(cases)}"
    env["excess_case_id"] = cases[0]["id"]
    return env


def _build_refunding_case_at_forty_days(api):
    """
    The detected case above with a refund elected, a further 20000 cents of
    earnings credited and the clock forty days past the computation period start.
    """
    env = _build_detected_excess_case(api)
    elect_correction_method(api, env["excess_case_id"], env["participant_id"],
                            "REFUND_TO_PARTICIPANT")
    set_clock(api, "2026-05-15T00:00:00Z")
    post_earnings(api, env["account_id"], 20000, "2026-05-14")
    return env


def _build_delinquent_five_employee_shop(api):
    """
    A five-employee registered shop holding 800000 cents of withheld deductions
    in a batch submitted late and never posted, with the clock at the year end.
    """
    env = build_employer_environment(api, employer=EMPLOYER_HARBOR)
    build_notified_saver(api, env, hire_date="2025-12-01",
                         annual_compensation_cents=19200000)
    activate_savers(api, env)
    batch = create_remittance(api, env["employer_id"], "2025-12-01", "2025-12-31",
                              "2026-01-02", 800000)
    add_remittance_line(api, batch["id"], env["employer_id"],
                        env["enrollment_id"], 16000000, 800000)
    submit_remittance(api, batch["id"], env["employer_id"])
    env["remittance_id"] = batch["id"]
    set_clock(api, "2026-12-31T00:00:00Z")
    return env


def test_correction_applies_the_adjusted_balance_net_income_figure(api):
    """A correction whose fund mix never moved is settled on the fair-market pair.

    Two batches of 400000 cents each and a 50000-cent earnings credit leave the
    account at 450000 cents before the second posting, which detects a
    100000-cent excess. By completion the balance stands at 870000 cents, so the
    adjusted opening balance is 450000 plus 400000, and the net income
    attributable is 100000 times 20000 over 850000, which is 2353 cents.

    "If the account has any investment election whose `superseded_at` is
    non-null and falls on or after `computation_period_start` and strictly
    before the completion instant, then no single opening-and-closing pair
    fairly represents the excess and `nia_method_applied` is set to
    `DAILY_PRORATA`; otherwise `nia_method_applied` is set to
    `ADJUSTED_BALANCE`."

    Design: Difficulty/dual_variant_calc/nia_adjusted_balance_vs_daily_prorata_on_excess_correction
    """
    env = _build_refunding_case_at_forty_days(api)

    case = complete_excess_case(api, env["excess_case_id"], "NIA-2026-0001")

    assert case["status"] == "COMPLETED"
    assert case["closing_fmv_cents"] == 870000
    assert case["nia_adjusted_balance_cents"] == 2353
    assert case["nia_method_applied"] == "ADJUSTED_BALANCE"
    assert case["applied_nia_cents"] == 2353
    assert case["corrected_amount_cents"] == 102353
    assert case["settlement_reference"] == "NIA-2026-0001"


def test_deemed_daily_rate_figure_is_also_stored_and_diverges(api):
    """The losing deemed-rate figure is persisted alongside the applied one.

    Forty whole days separate the computation period start of 5 April 2026 from
    the completion date of 15 May 2026, so at 2 basis points a day on a
    100000-cent excess the deemed-rate figure is 800 cents — a different answer
    from the 2353 cents the fair-market pair produced on the same case.

    "The deemed-rate variant instead ignores balances: the number of whole days
    from `computation_period_start` to the completion clock date is multiplied by
    the program year's `nia_daily_rate_bp` and by `detected_excess_cents`,
    divided by 10000, and rounded half up to a whole cent, giving
    `nia_daily_prorata_cents`."

    Design: Difficulty/dual_variant_calc/nia_adjusted_balance_vs_daily_prorata_on_excess_correction
    """
    env = _build_refunding_case_at_forty_days(api)

    complete_excess_case(api, env["excess_case_id"], "NIA-2026-0001")

    case = read_excess_case(api, env["excess_case_id"])
    assert case["nia_daily_prorata_cents"] == 800
    assert case["nia_adjusted_balance_cents"] == 2353
    assert case["nia_daily_prorata_cents"] != case["nia_adjusted_balance_cents"]
    assert case["applied_nia_cents"] != case["nia_daily_prorata_cents"]
    assert case["detected_excess_cents"] == 100000
    assert case["opening_fmv_cents"] == 450000
    assert case["period_contributions_cents"] == 400000
    assert case["period_distributions_cents"] == 0


def test_refund_debits_the_excess_plus_the_applied_net_income(api):
    """The refund takes excess plus earnings from the balance, excess from the year.

    The account is debited the full 102353 cents of corrected amount on both its
    balance and its basis, while the year-to-date figure gives back only the
    100000 cents of excess, which returns the saver to exactly the 700000-cent
    ceiling with no room left.

    "Under `REFUND_TO_PARTICIPANT`, the account's `balance_cents` and
    `contribution_basis_cents` are both debited by `corrected_amount_cents`, and
    its `ytd_contribution_cents` is reduced by `detected_excess_cents` — the
    excess itself, not the excess plus earnings."

    Design: Difficulty/dual_variant_calc/nia_adjusted_balance_vs_daily_prorata_on_excess_correction
    """
    env = _build_refunding_case_at_forty_days(api)

    complete_excess_case(api, env["excess_case_id"], "NIA-2026-0001")

    account = read_account(api, env["account_id"])
    assert account["balance_cents"] == 767647
    assert account["contribution_basis_cents"] == 697647
    assert account["ytd_contribution_cents"] == 700000
    assert account["remaining_headroom_cents"] == 0
    assert account["posture"] == "UNRESTRICTED"


def test_late_remittance_penalty_settles_on_the_larger_graduated_amount(api):
    """A shortfall penalty owes the graduated track when it beats the head count.

    The batch fell due on 9 January 2026 and the assessment is raised on
    31 December 2026, 356 days later, so twelve whole thirty-day blocks have run
    against an 800000-cent shortfall at 150 basis points a month, giving 144000
    cents, which is neither floored at 10000 nor capped at 400000.

    "A raw amount is then `shortfall_basis_cents` multiplied by
    `remit_penalty_monthly_rate_bp` multiplied by `months_late`, divided by 10000
    and rounded half up."

    "A `FAILURE_TO_REMIT` violation owes whichever of `statutory_amount_cents`
    and `graduated_amount_cents` is larger."

    Design: Difficulty/dual_variant_calc/statutory_per_employee_vs_graduated_shortfall_penalty
    """
    env = _build_delinquent_five_employee_shop(api)

    penalty = validate_success(api.create_penalty_assessment(
        env["employer_id"],
        {"violation_type": "FAILURE_TO_REMIT", "notice_date": "2026-10-02",
         "cure_days": 30},
        OFFICER_ASSESSOR), 201)

    assert penalty["months_late"] == 12
    assert penalty["graduated_amount_cents"] == 144000
    assert penalty["assessed_cents"] == 144000
    assert penalty["violation_type"] == "FAILURE_TO_REMIT"


def test_per_employee_statutory_amount_is_also_stored_and_loses(api):
    """The head-count figure is computed too, and it is the smaller of the pair.

    Notice was given on 2 October 2026 and the assessment falls on 31 December
    2026, exactly 90 days later, so the initial per-employee tier applies to all
    five employees for 125000 cents while the 180-day sustained tier does not,
    and the assessment does not settle on that number.

    "Starting from zero, if that day count is at least the program year's
    `notice_period_days`, the figure gains `employee_count_at_assessment`
    multiplied by `register_penalty_initial_cents_per_employee`; then, if the day
    count is also at least `sustained_notice_days`, the figure gains a further
    `employee_count_at_assessment` multiplied by
    `register_penalty_sustained_cents_per_employee`."

    Design: Difficulty/dual_variant_calc/statutory_per_employee_vs_graduated_shortfall_penalty
    """
    env = _build_delinquent_five_employee_shop(api)

    created = validate_success(api.create_penalty_assessment(
        env["employer_id"],
        {"violation_type": "FAILURE_TO_REMIT", "notice_date": "2026-10-02",
         "cure_days": 30},
        OFFICER_ASSESSOR), 201)

    penalty = read_penalty(api, created["id"])
    assert penalty["statutory_amount_cents"] == 125000
    assert penalty["statutory_amount_cents"] != penalty["graduated_amount_cents"]
    assert penalty["assessed_cents"] != penalty["statutory_amount_cents"]
    assert penalty["employee_count_at_assessment"] == 5


def test_assessment_snapshots_the_shortfall_and_penalises_the_employer(api):
    """The assessment freezes the shortfall it was priced from and its own trail.

    The 800000 cents of withheld money still sitting in an unposted batch is the
    basis the graduated figure was priced on, the notice date plus thirty cure
    days lands the cure deadline on 1 November 2026, and the employer's
    enforcement dimension moves to penalised.

    "The assessment records `cure_deadline` as `notice_date` plus `cure_days`,
    snapshots `employee_count_at_assessment` from the employer's current
    `employee_count`, records `origin` as `MANUAL`, sets `assessed_by_user_id` to
    the calling officer's `X-User-ID`, opens in status `ASSESSED`, and drives the
    employer's `compliance_status` to `PENALIZED` while incrementing its
    `version`."

    Design: Difficulty/dual_variant_calc/statutory_per_employee_vs_graduated_shortfall_penalty
    """
    env = _build_delinquent_five_employee_shop(api)

    penalty = validate_success(api.create_penalty_assessment(
        env["employer_id"],
        {"violation_type": "FAILURE_TO_REMIT", "notice_date": "2026-10-02",
         "cure_days": 30},
        OFFICER_ASSESSOR), 201)

    assert penalty["shortfall_basis_cents"] == 800000
    assert penalty["cure_deadline"] == "2026-11-01"
    assert penalty["status"] == "ASSESSED"
    assert penalty["origin"] == "MANUAL"
    assert penalty["assessed_by_user_id"] == OFFICER_ASSESSOR_USER_ID

    employer = read_employer(api, env["employer_id"])
    assert employer["compliance_status"] == "PENALIZED"
    assert employer["unremitted_deduction_cents"] == 800000
