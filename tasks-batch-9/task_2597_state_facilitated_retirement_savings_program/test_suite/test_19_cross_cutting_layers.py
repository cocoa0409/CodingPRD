"""
The layers that cut across every workflow: optimistic concurrency on the two
aggregates that carry derived money, and the exact instants at which a threshold
turns over.

Both version-guarded endpoints rewrite state the caller must have read first, so
a write that slipped in between has to be reported as a stale read rather than
silently applied — and the refusal must leave no half-recomputed derived field
behind. The two threshold rules are tested on the boundary itself rather than
near it: contributions landing exactly on the annual ceiling are not an excess,
and a payroll batch still on its due date is not yet overdue.
"""

from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers import (
    ADMIN,
    ERR_STALE_ACCOUNT_VERSION,
    ERR_STALE_EMPLOYER_VERSION,
    OFFICER,
    add_remittance_line,
    assert_amounts,
    assert_fields,
    assert_fund_balances,
    assert_total_count,
    build_active_saver_environment,
    build_program_configuration,
    create_employer,
    create_remittance,
    fund_account_by_remittance,
    make_employer_headers,
    make_participant_headers,
    post_earnings,
    read_account,
    read_employer,
    read_remittance,
    register_employer,
    set_clock,
    submit_remittance,
)

MMKT01_IN_FULL = [{"fund_code": "MMKT01", "allocation_bp": 10000}]


def test_an_earnings_credit_makes_a_savers_pending_fund_change_stale(api):
    """
    The account version moves under a write the saver never made — the
    recordkeeper credits investment earnings — so the allocation the saver
    composed against the old balance is refused before any fund or weight check
    runs, and no election row is created. Re-reading and resubmitting the very
    same allocation succeeds and advances the version again.

    "If that value does not equal the account's current `version` — because a
    remittance posting, an excess correction, an earnings credit, a permissible
    withdrawal or a portability debit has advanced the account since the client
    read it — the election is refused with `ERR_STALE_ACCOUNT_VERSION` (HTTP
    412), and the client must re-read the account and resubmit against the fresh
    version."

    Design: Corner/cross_cutting_complexity_layers/stale_account_version_on_an_investment_election_is_rejected
    """
    env = build_active_saver_environment(api)
    fund_account_by_remittance(api, env, "2026-02-01", "2026-02-20",
                               "2026-02-25", 8000000, 400000,
                               "2026-02-26T00:00:00Z")
    saver_headers = make_participant_headers(env["participant_id"])
    version_the_saver_read = validate_success(
        api.get_participant_account(env["account_id"], saver_headers))["version"]

    post_earnings(api, env["account_id"], 5000, "2026-02-26")

    after_earnings = validate_success(
        api.get_participant_account(env["account_id"], saver_headers))
    assert_amounts(after_earnings, {
        "balance_cents": 405000,
        "contribution_basis_cents": 400000,
    }, label="account after the earnings credit")
    assert after_earnings["version"] > version_the_saver_read, (
        "the earnings credit must advance the account version"
    )

    stale = api.create_investment_election(
        env["account_id"],
        {"allocations": MMKT01_IN_FULL,
         "expected_account_version": version_the_saver_read},
        saver_headers)

    validate_error(stale, ERR_STALE_ACCOUNT_VERSION)
    assert_total_count(
        api.list_investment_elections(env["account_id"], ADMIN), 1,
        label="elections of the account after the stale attempt")

    accepted = validate_success(api.create_investment_election(
        env["account_id"],
        {"allocations": MMKT01_IN_FULL,
         "expected_account_version": after_earnings["version"]},
        saver_headers), expected_status=201)
    assert accepted["status"] == "ACTIVE"
    refreshed = read_account(api, env["account_id"])
    assert refreshed["active_election_id"] == accepted["id"]
    assert refreshed["version"] > after_earnings["version"], (
        "a successful election must advance the account version again"
    )
    assert_fund_balances(refreshed,
                         [{"fund_code": "MMKT01", "balance_cents": 405000}])


def test_a_recount_composed_before_registration_is_refused_as_stale(api):
    """
    The employer's own registration moved its version, so a headcount
    restatement composed beforehand is refused — and the refusal leaves both
    derived mandate fields exactly as they were rather than half-recomputing
    them. Resubmitted against the fresh version, the same restatement moves the
    band and the deadline together.

    "If that value does not equal the employer's current `version`, the recount
    is refused with `ERR_STALE_EMPLOYER_VERSION` (HTTP 412)."

    Design: Corner/cross_cutting_complexity_layers/stale_employer_version_on_an_employee_count_recount_is_rejected
    """
    build_program_configuration(api)
    employer = create_employer(api)
    version_before_registration = employer["version"]
    register_employer(api, employer["id"])
    version_after_registration = read_employer(api, employer["id"])["version"]
    assert version_after_registration > version_before_registration, (
        "completing registration must advance the employer version"
    )
    restatement = {"employee_count": 120, "effective_date": "2026-01-15"}
    employer_headers = make_employer_headers(employer["id"])

    stale = api.recount_employees(
        employer["id"],
        dict(restatement,
             expected_employer_version=version_before_registration),
        employer_headers)

    validate_error(stale, ERR_STALE_EMPLOYER_VERSION)
    assert_fields(read_employer(api, employer["id"]), {
        "employee_count": 60,
        "wave_tier": "WAVE_2",
        "registration_deadline": "2026-12-31",
        "last_recount_effective_date": None,
    }, label="employer after the stale recount")

    recounted = validate_success(api.recount_employees(
        employer["id"],
        dict(restatement,
             expected_employer_version=version_after_registration),
        employer_headers))
    assert_fields(recounted, {
        "employee_count": 120,
        "wave_tier": "WAVE_1",
        "registration_deadline": "2026-06-30",
        "last_recount_effective_date": "2026-01-15",
        "registration_status": "REGISTERED",
    }, label="employer after the accepted recount")


def test_contributions_landing_exactly_on_the_annual_ceiling_are_not_excess(api):
    """
    A posting that fills the saver's annual room to the cent leaves zero
    headroom, an unrestricted account and no correction case, so the rule is
    strictly "more than the ceiling" and not "at the ceiling". A second batch
    carrying a single hundred cents then trips it by the smallest possible
    margin, and only that hundred is the detected excess.

    "For each line, the room available before that line is the ceiling minus the
    year-to-date total accumulated so far, floored at zero; the line's
    `excess_cents` is its `allocated_cents` minus that room, likewise floored at
    zero."

    Design: Corner/cross_cutting_complexity_layers/contributions_exactly_at_the_annual_limit_open_no_excess_case
    """
    env = build_active_saver_environment(api, annual_compensation_cents=14000000)

    to_the_ceiling = fund_account_by_remittance(
        api, env, "2026-01-01", "2026-01-31", "2026-02-05",
        14000000, 700000, "2026-02-05T00:00:00Z",
        posting_reference="ACH-CEILING-01")["remittance"]

    assert_amounts(to_the_ceiling, {
        "total_allocated_cents": 700000,
        "total_excess_cents": 0,
    }, label="batch that fills the annual room exactly")
    at_the_ceiling = read_account(api, env["account_id"])
    assert_amounts(at_the_ceiling, {
        "ytd_contribution_cents": 700000,
        "remaining_headroom_cents": 0,
        "uncorrected_excess_cents": 0,
    }, label="account sitting exactly on the ceiling")
    assert at_the_ceiling["posture"] == "UNRESTRICTED"
    assert_total_count(api.list_account_excess_cases(env["account_id"], ADMIN), 0,
                       label="correction cases at the ceiling")

    one_cent_band_over = fund_account_by_remittance(
        api, env, "2026-02-01", "2026-02-28", "2026-03-05",
        2000, 100, posting_reference="ACH-CEILING-02")["remittance"]

    assert_amounts(one_cent_band_over, {
        "total_allocated_cents": 100,
        "total_excess_cents": 100,
    }, label="batch that breaches the ceiling")
    over_the_ceiling = read_account(api, env["account_id"])
    assert_amounts(over_the_ceiling, {
        "ytd_contribution_cents": 700100,
        "remaining_headroom_cents": 0,
    }, label="account past the ceiling")
    assert over_the_ceiling["posture"] == "RESTRICTED"
    cases = assert_total_count(
        api.list_account_excess_cases(env["account_id"], ADMIN), 1,
        label="correction cases past the ceiling")
    assert_fields(cases[0], {
        "status": "DETECTED",
        "calendar_year": 2026,
    }, label="the correction case the breach opened")
    assert_amounts(cases[0], {"detected_excess_cents": 100},
                   label="the correction case the breach opened")


def test_delinquency_holds_on_the_due_date_and_trips_the_day_after(api):
    """
    A batch withheld on 5 February is due seven days later, and the delinquency
    test is a strict comparison: a sweep run on the due date itself finds nothing
    overdue, while the very next day finds the whole withheld amount unremitted.
    The lateness frozen on the batch at submission is a different quantity and
    stays at zero throughout.

    "First the programme computes `unremitted_deduction_cents`, the sum of
    `total_deducted_cents` over that employer's remittance batches whose status
    is `DRAFT` or `SUBMITTED` and whose `pay_date` plus the program year's
    `remittance_due_days` is strictly earlier than the current clock date."

    Design: Corner/cross_cutting_complexity_layers/delinquency_threshold_holds_on_the_due_date_and_trips_the_day_after
    """
    env = build_active_saver_environment(api)
    set_clock(api, "2026-02-05T00:00:00Z")
    batch = create_remittance(api, env["employer_id"], "2026-01-01",
                              "2026-01-31", "2026-02-05", 400000)
    add_remittance_line(api, batch["id"], env["employer_id"],
                        env["enrollment_id"], 8000000, 400000)
    set_clock(api, "2026-02-12T00:00:00Z")
    submitted = submit_remittance(api, batch["id"], env["employer_id"])
    assert_fields(submitted, {"status": "SUBMITTED"}, label="submitted batch")
    assert_amounts(submitted, {"days_late": 0}, label="submitted batch")

    on_the_due_date = validate_success(api.run_compliance_sweep(OFFICER))

    assert_fields(on_the_due_date, {
        "delinquent_employer_count": 0,
        "assessments_created_count": 0,
    }, label="sweep run on the due date")
    assert_fields(read_employer(api, env["employer_id"]), {
        "compliance_status": "COMPLIANT",
    }, label="employer on the due date")
    assert_amounts(read_employer(api, env["employer_id"]),
                   {"unremitted_deduction_cents": 0},
                   label="employer on the due date")

    set_clock(api, "2026-02-13T00:00:00Z")
    the_day_after = validate_success(api.run_compliance_sweep(OFFICER))

    assert_fields(the_day_after, {
        "delinquent_employer_count": 1,
        "assessments_created_count": 0,
    }, label="sweep run the day after the due date")
    assert_fields(read_employer(api, env["employer_id"]), {
        "compliance_status": "DELINQUENT",
    }, label="employer the day after the due date")
    assert_amounts(read_employer(api, env["employer_id"]),
                   {"unremitted_deduction_cents": 400000},
                   label="employer the day after the due date")
    assert_amounts(read_remittance(api, batch["id"]), {"days_late": 0},
                   label="batch whose lateness was frozen at submission")
