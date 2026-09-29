"""
The arithmetic in the corners: edges, bands, aggregation windows and rounding.

A rate escalation that admits an enrolment one day too early is wrong even though
it produces a plausible number, a wave band that puts fifty employees in the wrong
tier moves a statutory deadline by six months, an annual ceiling that ignores
catch-up eligibility short-changes an older saver, a year-to-date figure that stops
at one employer under-detects excess contributions, and a deduction check that
truncates instead of rounding half up rejects payroll that is exactly right. These
tests pin the boundary value rather than a comfortable value in the middle.
"""

from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import (
    ADMIN,
    ERR_DEDUCTION_AMOUNT_MISMATCH,
    activate_savers,
    add_employer,
    add_remittance_line,
    apply_bp,
    assert_basis_points,
    assert_cents,
    build_active_saver_environment,
    build_employer_environment,
    build_notified_saver,
    build_program_configuration,
    complete_excess_case,
    create_enrollment,
    create_participant,
    create_remittance,
    elect_allocations,
    elect_correction_method,
    elect_rate,
    excess_cases_for_account,
    fund_account_by_remittance,
    make_employer_headers,
    post_earnings,
    post_remittance,
    read_account,
    read_enrollment,
    read_participant,
    read_remittance,
    read_remittance_line,
    run_annual_escalation,
    set_clock,
    submit_remittance,
)

# A saver who files their own rate election and asks to be left out of the annual
# nudge, so that a run which filters on status alone would escalate them anyway.
PARTICIPANT_BEN = {
    "full_name": "Ben Ortiz",
    "date_of_birth": "1985-07-22",
    "email": "ben.ortiz@x.example",
    "ssn_last4": "5678",
    "state_resident": True,
}

# Turns 56 inside program year 2026, so the catch-up allowance applies to her.
PARTICIPANT_MARTA = {
    "full_name": "Marta Cruz",
    "date_of_birth": "1970-03-15",
    "email": "marta.cruz@x.example",
    "ssn_last4": "9012",
    "state_resident": True,
}

# A second covered employer, so that one saver can be paid by two payrolls.
EMPLOYER_FREIGHT = {
    "ein": "33-2221110",
    "legal_name": "Harbor Freight Lines Inc",
    "worksite_state": "CA",
    "employee_count": 30,
}

# Four headcounts that sit exactly on the wave-band boundaries.
EMPLOYER_AT_FORTY_NINE = {
    "ein": "10-0000049",
    "legal_name": "Boundary Forty Nine LLC",
    "worksite_state": "CA",
    "employee_count": 49,
}
EMPLOYER_AT_FIFTY = {
    "ein": "10-0000050",
    "legal_name": "Boundary Fifty LLC",
    "worksite_state": "CA",
    "employee_count": 50,
}
EMPLOYER_AT_NINETY_NINE = {
    "ein": "10-0000099",
    "legal_name": "Boundary Ninety Nine LLC",
    "worksite_state": "CA",
    "employee_count": 99,
}
EMPLOYER_AT_ONE_HUNDRED = {
    "ein": "10-0000100",
    "legal_name": "Boundary One Hundred LLC",
    "worksite_state": "CA",
    "employee_count": 100,
}


def _build_two_savers_with_a_march_pay_date(api):
    """
    Two savers at one employer, both activated and both credited by a single batch
    with a 5 March 2026 pay date, one of whom has elected out of escalation.
    """
    env = build_employer_environment(api)
    build_notified_saver(api, env)
    ben = create_participant(api, PARTICIPANT_BEN)
    ben_enrollment = create_enrollment(api, env["employer_id"], ben["id"],
                                       "2026-01-05", 9600000)
    activate_savers(api, env)
    elect_rate(api, ben_enrollment["id"], ben["id"], 500, escalation_opt_out=True)

    set_clock(api, "2026-03-06T00:00:00Z")
    batch = create_remittance(api, env["employer_id"], "2026-02-01", "2026-02-28",
                              "2026-03-05", 800000)
    add_remittance_line(api, batch["id"], env["employer_id"],
                        env["enrollment_id"], 8000000, 400000)
    add_remittance_line(api, batch["id"], env["employer_id"],
                        ben_enrollment["id"], 8000000, 400000)
    submit_remittance(api, batch["id"], env["employer_id"])
    post_remittance(api, batch["id"], "PR-2026-0001")

    env["ben_id"] = ben["id"]
    env["ben_enrollment_id"] = ben_enrollment["id"]
    return env


def test_annual_nudge_admits_only_seasoned_savers_who_did_not_opt_out(api):
    """Seasoning is measured in whole days from the first contribution, and 179 is not 180.

    Both savers were first credited on 5 March 2026. A run on 31 August 2026 sits
    179 days after that date and raises nobody, while a run one day later sits on
    the 180-day mark and raises Rosa Lim from 500 to 600 basis points. Ben Ortiz
    is left exactly where he was on both runs, because he elected out of the nudge
    even though his enrolment is every bit as active and as seasoned as hers.

    "The batch considers **only** enrolments that satisfy all four conditions: the
    status is `ACTIVE`; `escalation_opt_out` is false; `first_contribution_date` is
    non-null; and the number of whole days from `first_contribution_date` to the
    effective date is at least the program year's `escalation_seasoning_days`, six
    months of seasoning under the default configuration."

    Design: Corner/calculations/escalation_run_admits_only_seasoned_non_opted_out_enrollments
    """
    env = _build_two_savers_with_a_march_pay_date(api)
    set_clock(api, "2026-08-31T00:00:00Z")

    one_day_early = run_annual_escalation(api)

    assert one_day_early["escalated_count"] == 0
    assert one_day_early["capped_count"] == 0

    unmoved = read_enrollment(api, env["enrollment_id"])
    assert_basis_points(unmoved["contribution_rate_bp"], 500,
                        "contribution_rate_bp")
    assert unmoved["rate_source"] == "DEFAULT"
    assert unmoved["first_contribution_date"] == "2026-03-05"
    assert read_enrollment(
        api, env["ben_enrollment_id"])["first_contribution_date"] == "2026-03-05"

    set_clock(api, "2026-09-01T00:00:00Z")
    on_the_mark = run_annual_escalation(api)

    assert on_the_mark["escalated_count"] == 1
    assert on_the_mark["capped_count"] == 0

    escalated = read_enrollment(api, env["enrollment_id"])
    assert_basis_points(escalated["contribution_rate_bp"], 600,
                        "contribution_rate_bp")
    assert escalated["rate_source"] == "ESCALATED"

    opted_out = read_enrollment(api, env["ben_enrollment_id"])
    assert_basis_points(opted_out["contribution_rate_bp"], 500,
                        "contribution_rate_bp")
    assert opted_out["rate_source"] == "PARTICIPANT_ELECTED"
    assert opted_out["escalation_opt_out"] is True


def test_escalation_clamps_at_the_cap_and_then_reports_the_saver_skipped(api):
    """The cap is a ceiling to land on, not a reason to refuse or to overshoot.

    A saver sitting at 750 basis points with a 100-point increment and an 800-point
    cap is raised to exactly 800 — the run counts that enrolment as escalated and
    as clamped in the same pass. Run the nudge again and there is nothing left to
    give: the enrolment is reported as skipped rather than escalated, and its rate
    and its provenance are both untouched.

    "The cap clamps, it does not reject: an enrolment at 750 basis points with a
    100-basis-point increment and an 800-basis-point cap lands on exactly 800,
    never on 850."

    "If it is not — the enrolment already sits at or above the cap — the enrolment
    is left completely untouched and is reported as skipped rather than escalated."

    Design: Corner/calculations/escalation_clamps_at_the_cap_then_reports_the_enrollment_skipped
    """
    env = build_active_saver_environment(api)
    elect_rate(api, env["enrollment_id"], env["participant_id"], 750)
    fund_account_by_remittance(
        api, env, "2026-02-01", "2026-02-28", "2026-03-05",
        8000000, 600000, "2026-03-06T00:00:00Z",
        posting_reference="PR-2026-0001")
    set_clock(api, "2026-09-01T00:00:00Z")

    clamping_run = run_annual_escalation(api)

    assert clamping_run["escalated_count"] == 1
    assert clamping_run["capped_count"] == 1
    assert clamping_run["skipped_count"] == 0

    clamped = read_enrollment(api, env["enrollment_id"])
    assert_basis_points(clamped["contribution_rate_bp"], 800,
                        "contribution_rate_bp")
    assert clamped["contribution_rate_bp"] != 850
    assert clamped["rate_source"] == "ESCALATED"

    second_run = run_annual_escalation(api)

    assert second_run["escalated_count"] == 0
    assert second_run["capped_count"] == 0
    assert second_run["skipped_count"] == 1

    still_capped = read_enrollment(api, env["enrollment_id"])
    assert_basis_points(still_capped["contribution_rate_bp"], 800,
                        "contribution_rate_bp")
    assert still_capped["rate_source"] == "ESCALATED"


def test_year_to_date_room_aggregates_two_employers_for_one_saver(api):
    """One saver, two payrolls, one annual ceiling — and the second payroll breaches it.

    Rosa Lim is on the books at both employers. The first payroll credited 400000
    cents against her 700000-cent ceiling, so when the second employer's 400000-cent
    line posts, only 300000 cents of it fit and the remaining 100000 are recorded as
    excess on that line and on its batch. The full amount is still credited — the
    programme corrects excess afterwards rather than refusing money — so her balance
    reads 800000 cents with no room left, and one correction case is now open.

    "`ytd_contribution_cents` aggregates `allocated_cents` over **every** posted
    line that credits this saver, across all of their employers, whose parent
    batch's `pay_date` falls inside the program year's `calendar_year`; that
    cross-employer aggregation is what makes the limit a per-person rule rather than
    a per-employer one."

    Design: Corner/calculations/headroom_aggregates_posted_lines_across_two_employers_for_one_participant
    """
    env = build_employer_environment(api)
    freight = add_employer(api, env, EMPLOYER_FREIGHT)
    build_notified_saver(api, env)
    freight_enrollment = create_enrollment(api, freight["id"],
                                           env["participant_id"], "2026-01-05",
                                           9600000)
    activate_savers(api, env)

    first_payroll = fund_account_by_remittance(
        api, env, "2026-02-01", "2026-02-28", "2026-03-05",
        8000000, 400000, "2026-03-06T00:00:00Z",
        posting_reference="PR-DELTA-0001")

    set_clock(api, "2026-03-10T00:00:00Z")
    second_batch = create_remittance(api, freight["id"], "2026-02-01",
                                     "2026-02-28", "2026-03-09", 400000)
    second_line = add_remittance_line(api, second_batch["id"], freight["id"],
                                      freight_enrollment["id"], 8000000, 400000)
    submit_remittance(api, second_batch["id"], freight["id"])

    posted = post_remittance(api, second_batch["id"], "PR-FREIGHT-0001")

    within_room = read_remittance_line(api, first_payroll["remittance_id"],
                                       first_payroll["line_id"])
    assert_cents(within_room["excess_cents"], 0, "excess_cents")
    assert_cents(within_room["allocated_cents"], 400000, "allocated_cents")

    breaching = read_remittance_line(api, second_batch["id"], second_line["id"])
    assert_cents(breaching["excess_cents"], 100000, "excess_cents")
    assert_cents(breaching["allocated_cents"], 400000, "allocated_cents")
    assert_cents(posted["total_excess_cents"], 100000, "total_excess_cents")

    account = read_account(api, env["account_id"])
    assert_cents(account["ytd_contribution_cents"], 800000,
                 "ytd_contribution_cents")
    assert_cents(account["remaining_headroom_cents"], 0,
                 "remaining_headroom_cents")
    assert_cents(account["balance_cents"], 800000, "balance_cents")
    assert account["posture"] == "RESTRICTED"

    cases, meta = validate_paginated(
        api.list_account_excess_cases(env["account_id"], ADMIN))
    assert meta["total_count"] == 1
    assert_cents(cases[0]["detected_excess_cents"], 100000,
                 "detected_excess_cents")


def test_catch_up_eligible_saver_is_measured_against_the_higher_ceiling(api):
    """A saver who turns fifty-six this year gets 800000 cents of room, not 700000.

    Marta Cruz is 56 at the year end, so her annual ceiling is the 700000-cent limit
    plus the 100000-cent catch-up allowance. A single 750000-cent credit therefore
    breaches nothing: the line carries no excess, no correction case is opened, and
    she still has 50000 cents of room. A service that ignored catch-up eligibility
    would have flagged 50000 cents of excess here.

    "A saver's annual ceiling is the program year's `ira_annual_limit_cents`, plus
    the program year's `catch_up_limit_cents` when the saver's `age_at_year_end` is
    at least 50, and nothing extra otherwise."

    Design: Corner/calculations/catch_up_eligible_participant_receives_the_higher_annual_ceiling
    """
    env = build_employer_environment(api)
    build_notified_saver(api, env, participant=PARTICIPANT_MARTA,
                         annual_compensation_cents=18000000)
    activate_savers(api, env)

    payroll = fund_account_by_remittance(
        api, env, "2026-02-01", "2026-02-28", "2026-03-05",
        15000000, 750000, "2026-03-06T00:00:00Z",
        posting_reference="PR-2026-0001")

    saver = read_participant(api, env["participant_id"])
    assert saver["age_at_year_end"] == 56
    assert saver["catch_up_eligible"] is True

    line = read_remittance_line(api, payroll["remittance_id"], payroll["line_id"])
    assert_cents(line["excess_cents"], 0, "excess_cents")
    assert_cents(line["allocated_cents"], 750000, "allocated_cents")

    batch = read_remittance(api, payroll["remittance_id"])
    assert_cents(batch["total_excess_cents"], 0, "total_excess_cents")

    account = read_account(api, env["account_id"])
    assert_cents(account["ytd_contribution_cents"], 750000,
                 "ytd_contribution_cents")
    assert_cents(account["remaining_headroom_cents"], 50000,
                 "remaining_headroom_cents")
    assert account["posture"] == "UNRESTRICTED"

    _, meta = validate_paginated(
        api.list_account_excess_cases(env["account_id"], ADMIN))
    assert meta["total_count"] == 0, (
        "a credit inside the catch-up ceiling opens no correction case")


def test_wave_bands_hold_at_forty_nine_fifty_ninety_nine_and_one_hundred(api):
    """The headcount bands are inclusive where the statute says so, to the employee.

    Forty-nine employees is still the small-employer band with a 30 June 2027
    deadline, but fifty crosses into the middle band and pulls the deadline forward
    to 31 December 2026. Ninety-nine stays there and one hundred crosses again into
    the earliest band, due 30 June 2026. None of the four has registered yet, so all
    four sit in pending registration.

    "The headcount is matched against four descending bands, and the band fixes both
    `wave_tier` and `registration_deadline`: a headcount of at least 100 lands in
    `WAVE_1` with a deadline of 30 June 2026; a headcount from 50 through 99
    inclusive lands in `WAVE_2` with a deadline of 31 December 2026; a headcount from
    5 through 49 inclusive lands in `WAVE_3` with a deadline of 30 June 2027; and a
    headcount of 4 or fewer lands in `NOT_COVERED`, whose `registration_deadline` is
    null because there is nothing to register for."

    Design: Corner/calculations/wave_tier_thresholds_hold_at_forty_nine_fifty_ninety_nine_and_one_hundred
    """
    build_program_configuration(api)

    forty_nine = validate_success(
        api.create_employer(EMPLOYER_AT_FORTY_NINE, ADMIN), 201)
    fifty = validate_success(api.create_employer(EMPLOYER_AT_FIFTY, ADMIN), 201)
    ninety_nine = validate_success(
        api.create_employer(EMPLOYER_AT_NINETY_NINE, ADMIN), 201)
    one_hundred = validate_success(
        api.create_employer(EMPLOYER_AT_ONE_HUNDRED, ADMIN), 201)

    assert forty_nine["wave_tier"] == "WAVE_3"
    assert forty_nine["registration_deadline"] == "2027-06-30"
    assert fifty["wave_tier"] == "WAVE_2"
    assert fifty["registration_deadline"] == "2026-12-31"
    assert ninety_nine["wave_tier"] == "WAVE_2"
    assert ninety_nine["registration_deadline"] == "2026-12-31"
    assert one_hundred["wave_tier"] == "WAVE_1"
    assert one_hundred["registration_deadline"] == "2026-06-30"

    for employer in (forty_nine, fifty, ninety_nine, one_hundred):
        assert employer["registration_status"] == "PENDING_REGISTRATION", (
            f"{employer['legal_name']} should not be registered yet")


def test_moving_funds_inside_the_window_selects_the_deemed_rate_variant(api):
    """A fund switch during the correction window disqualifies the fair-market pair.

    The correction period opened on 5 April 2026, and Rosa moved the whole account
    into the money-market fund five days later, superseding the election the
    programme had seeded for her. No single opening-and-closing balance pair
    represents the excess honestly after that, so the deemed-rate variant is the one
    applied: forty whole days to 15 May 2026 at 2 basis points a day on a
    100000-cent excess is 800 cents, and the refund therefore takes 100800 cents
    rather than the 102353 the fair-market pair would have produced.

    "If the account has any investment election whose `superseded_at` is non-null and
    falls on or after `computation_period_start` and strictly before the completion
    instant, then no single opening-and-closing pair fairly represents the excess and
    `nia_method_applied` is set to `DAILY_PRORATA`; otherwise `nia_method_applied` is
    set to `ADJUSTED_BALANCE`."

    "`applied_nia_cents` takes the value of whichever variant field the applied
    method names, and `corrected_amount_cents` is `detected_excess_cents` plus
    `applied_nia_cents`."

    Design: Corner/calculations/nia_daily_prorata_variant_is_selected_when_an_election_is_superseded_in_window
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
    assert len(cases) == 1, f"expected one correction case, found {len(cases)}"
    case_id = cases[0]["id"]
    elect_correction_method(api, case_id, env["participant_id"],
                            "REFUND_TO_PARTICIPANT")

    set_clock(api, "2026-04-10T00:00:00Z")
    before_switch = read_account(api, env["account_id"])
    switched = elect_allocations(
        api, env["account_id"], env["participant_id"],
        [{"fund_code": "MMKT01", "allocation_bp": 10000}],
        before_switch["version"])
    set_clock(api, "2026-05-15T00:00:00Z")
    post_earnings(api, env["account_id"], 20000, "2026-05-14")

    case = complete_excess_case(api, case_id, "NIA-2026-0002")

    assert switched["status"] == "ACTIVE"
    assert switched["source"] == "PARTICIPANT_ELECTED"

    assert case["status"] == "COMPLETED"
    assert_cents(case["closing_fmv_cents"], 870000, "closing_fmv_cents")
    assert_cents(case["nia_adjusted_balance_cents"], 2353,
                 "nia_adjusted_balance_cents")
    assert_cents(case["nia_daily_prorata_cents"], 800, "nia_daily_prorata_cents")
    assert case["nia_method_applied"] == "DAILY_PRORATA"
    assert_cents(case["applied_nia_cents"], 800, "applied_nia_cents")
    assert_cents(case["corrected_amount_cents"], 100800,
                 "corrected_amount_cents")

    account = read_account(api, env["account_id"])
    assert_cents(account["balance_cents"], 769200, "balance_cents")
    assert_cents(account["contribution_basis_cents"], 699200,
                 "contribution_basis_cents")
    assert_cents(account["ytd_contribution_cents"], 700000,
                 "ytd_contribution_cents")
    assert_cents(account["remaining_headroom_cents"], 0,
                 "remaining_headroom_cents")
    assert account["posture"] == "UNRESTRICTED"


def test_expected_deduction_rounds_half_up_on_an_odd_gross_wage(api):
    """333333 cents at five percent is 16666.65, and the answer is 16667, not 16666.

    The programme recomputes the withholding itself and insists on an exact match, so
    the truncated figure is refused outright and only the half-up figure is accepted.
    The discarded fraction here is .65, which rules out any argument about ties: a
    service that floors the result rejects payroll that is exactly right.

    "The programme independently derives `expected_deduction_cents` at line-creation
    time as the line's `gross_wages_cents` multiplied by the enrolment's current
    `contribution_rate_bp`, divided by 10000 and rounded half up to a whole cent; if
    `deducted_cents` does not equal that figure exactly, the line is refused with
    `ERR_DEDUCTION_AMOUNT_MISMATCH`."

    Design: Corner/calculations/expected_deduction_rounds_half_up_on_odd_gross_wages
    """
    env = build_active_saver_environment(api)
    set_clock(api, "2026-03-06T00:00:00Z")
    batch = create_remittance(api, env["employer_id"], "2026-02-01", "2026-02-28",
                              "2026-03-05", 16667)
    employer_headers = make_employer_headers(env["employer_id"])

    validate_error(api.create_remittance_line(
        batch["id"],
        {"enrollment_id": env["enrollment_id"], "gross_wages_cents": 333333,
         "deducted_cents": 16666},
        employer_headers), ERR_DEDUCTION_AMOUNT_MISMATCH)

    line = validate_success(api.create_remittance_line(
        batch["id"],
        {"enrollment_id": env["enrollment_id"], "gross_wages_cents": 333333,
         "deducted_cents": 16667},
        employer_headers), 201)

    assert_cents(line["gross_wages_cents"], 333333, "gross_wages_cents")
    assert_cents(line["deducted_cents"], 16667, "deducted_cents")
    assert_cents(line["expected_deduction_cents"], 16667,
                 "expected_deduction_cents")
    assert_cents(line["expected_deduction_cents"], apply_bp(333333, 500),
                 "expected_deduction_cents")

    unchanged = read_remittance(api, batch["id"])
    assert unchanged["line_count"] == 1
    assert unchanged["status"] == "DRAFT"
