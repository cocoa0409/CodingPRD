"""
Refusals that identify precisely what went wrong.

The programme never answers a violation with a generic conflict: three different
uniqueness keys raise three different identifiers, eight different addressed
collections raise eight different not-found identifiers, an anonymous call is
refused before anything else about it is examined, an operation reaching for
statutory dials that were never configured for the clock's own year is refused
rather than silently borrowing another year's, a fund that cannot be elected into
is unavailable rather than absent, and an automatic default selector with nothing
to pick refuses instead of guessing.

Every refusal below is also checked for what it did *not* do: the incumbent row
keeps its own values, no partial resource is left behind, and the identical
request succeeds once — and only once — the blocking condition is removed.
"""

from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers import (
    ADMIN,
    ERR_DUPLICATE_EIN,
    ERR_DUPLICATE_FUND_CODE,
    ERR_DUPLICATE_PROGRAM_YEAR,
    ERR_ACCOUNT_NOT_FOUND,
    ERR_ENROLLMENT_NOT_FOUND,
    ERR_EXCESS_CASE_NOT_FOUND,
    ERR_EXEMPTION_NOT_FOUND,
    ERR_FUND_NOT_AVAILABLE,
    ERR_FUND_OPTION_NOT_FOUND,
    ERR_NO_DEFAULT_FUND_AVAILABLE,
    ERR_PARTICIPANT_NOT_FOUND,
    ERR_PROGRAM_YEAR_NOT_CONFIGURED,
    ERR_REMITTANCE_NOT_FOUND,
    ERR_TRANSFER_NOT_FOUND,
    ERR_UNAUTHENTICATED,
    EMPLOYER_DELTA,
    FUND_MMKT01,
    FUND_TDF2045,
    PROGRAM_YEAR_2026,
    ROLE_PROGRAM_ADMINISTRATOR,
    account_for_participant,
    active_election,
    assert_basis_points,
    assert_fields,
    assert_total_count,
    build_active_saver_environment,
    build_employer_environment,
    build_notified_saver,
    create_employer,
    create_investment_option,
    create_participant,
    create_program_year,
    headers_without_user_id,
    make_participant_headers,
    read_account,
    read_employer,
    read_enrollment,
    read_investment_option,
    read_participant,
    register_employer,
    set_clock,
)

# The single absent identifier every not-found probe addresses.
ABSENT_ID = "00000000-0000-0000-0000-000000000000"

# A target-date option whose glide path lands well before a 1980-born saver's
# retirement year, so the primary default pool cannot admit it.
FUND_TDF2030 = {
    "fund_code": "TDF2030",
    "name": "Target Retirement 2030",
    "category": "TARGET_DATE",
    "target_year": 2030,
    "expense_ratio_bp": 25,
    "default_eligible": True,
}

# A real, published option that was seeded closed to new money: it may still hold
# a legacy balance but no saver may elect into it.
FUND_CLOSED_TO_NEW = {
    "fund_code": "BND010",
    "name": "Core Bond Index",
    "category": "BOND_INDEX",
    "expense_ratio_bp": 12,
    "default_eligible": False,
    "status": "CLOSED_TO_NEW",
}


def _one_of_each_unique_key(api):
    """
    The clock at the start of 2026, statutory dials for 2026, exactly one fund on
    the menu and exactly one employer in the register — so each of the three
    uniqueness keys in this domain is occupied exactly once.
    """
    set_clock(api, "2026-01-01T00:00:00Z")
    program_year = create_program_year(api, PROGRAM_YEAR_2026)
    option = create_investment_option(api, FUND_TDF2045)
    employer = create_employer(api, EMPLOYER_DELTA)
    return {
        "program_year": program_year,
        "option": option,
        "option_id": option["id"],
        "employer": employer,
        "employer_id": employer["id"],
    }


def test_a_repeated_calendar_year_ein_and_fund_code_each_raise_their_own_conflict(api):
    """
    Three separate uniqueness keys on three separate collections are each refused
    with the identifier that names the key that collided, never with one shared
    conflict identifier.

    "A second record for an `ein` that already exists is refused with
    `ERR_DUPLICATE_EIN`."

    Design: Corner/errors/duplicate_program_year_ein_and_fund_code_are_each_rejected
    """
    _one_of_each_unique_key(api)

    repeated_year = api.create_program_year(
        {"calendar_year": 2026, "ira_annual_limit_cents": 800000,
         "default_contribution_rate_bp": 300}, ADMIN)
    repeated_ein = api.create_employer(
        {"ein": "12-3456789", "legal_name": "Delta Fabrication Holdings LLC",
         "worksite_state": "NV", "employee_count": 200}, ADMIN)
    repeated_code = api.create_investment_option(
        {"fund_code": "TDF2045", "name": "Target Retirement 2045 Institutional",
         "category": "TARGET_DATE", "target_year": 2045, "expense_ratio_bp": 8,
         "default_eligible": False}, ADMIN)

    validate_error(repeated_year, ERR_DUPLICATE_PROGRAM_YEAR)
    validate_error(repeated_ein, ERR_DUPLICATE_EIN)
    validate_error(repeated_code, ERR_DUPLICATE_FUND_CODE)


def test_a_refused_duplicate_leaves_the_incumbent_row_exactly_as_it_was(api):
    """
    The rejected payloads carried different names, states, headcounts and expense
    ratios, and none of that reached the stored rows: a duplicate attempt is a
    refusal, not an upsert. A different calendar year is meanwhile accepted, which
    is what shows the year key is scoped to `calendar_year` rather than admitting
    a single configuration row overall.

    "The fund menu is programme configuration, curated by a
    `ProgramAdministrator` and immutable once published: the programme adds a
    replacement option rather than editing a live one."

    Design: Corner/errors/duplicate_program_year_ein_and_fund_code_are_each_rejected
    """
    fixture = _one_of_each_unique_key(api)
    validate_error(
        api.create_program_year(
            {"calendar_year": 2026, "ira_annual_limit_cents": 800000,
             "default_contribution_rate_bp": 300}, ADMIN),
        ERR_DUPLICATE_PROGRAM_YEAR)
    validate_error(
        api.create_employer(
            {"ein": "12-3456789", "legal_name": "Delta Fabrication Holdings LLC",
             "worksite_state": "NV", "employee_count": 200}, ADMIN),
        ERR_DUPLICATE_EIN)
    validate_error(
        api.create_investment_option(
            {"fund_code": "TDF2045", "name": "Target Retirement 2045 Institutional",
             "category": "TARGET_DATE", "target_year": 2045, "expense_ratio_bp": 8,
             "default_eligible": False}, ADMIN),
        ERR_DUPLICATE_FUND_CODE)

    accepted = api.create_program_year(
        {"calendar_year": 2027, "ira_annual_limit_cents": 700000,
         "default_contribution_rate_bp": 500}, ADMIN)

    validate_success(accepted, expected_status=201)
    employer = read_employer(api, fixture["employer_id"])
    assert_fields(employer, {
        "legal_name": "Delta Fabrication LLC",
        "worksite_state": "CA",
        "employee_count": 60,
        "wave_tier": "WAVE_2",
    }, label="employer after the refused duplicate")
    option = read_investment_option(api, fixture["option_id"])
    assert_fields(option, {
        "name": "Target Retirement 2045",
        "default_eligible": True,
    }, label="fund option after the refused duplicate")
    assert_basis_points(option["expense_ratio_bp"], 30,
                        "fund option expense_ratio_bp")
    assert_total_count(api.list_program_years(ADMIN), 2, label="program years")
    assert_total_count(api.list_investment_options(ADMIN), 1, label="fund menu")


def test_each_addressed_collection_answers_with_its_own_not_found_identifier(api):
    """
    One identifier that exists nowhere is addressed through eight different
    collections, and each hop names the collection that failed to resolve rather
    than a single shared not-found identifier.

    "Each addressed collection has its own not-found identifier so that the
    failing hop is unambiguous: `ERR_EMPLOYER_NOT_FOUND`,
    `ERR_PARTICIPANT_NOT_FOUND`, `ERR_ENROLLMENT_NOT_FOUND`,
    `ERR_ACCOUNT_NOT_FOUND`, `ERR_REMITTANCE_NOT_FOUND`,
    `ERR_EXEMPTION_NOT_FOUND`, `ERR_EXCESS_CASE_NOT_FOUND`,
    `ERR_PENALTY_NOT_FOUND`, `ERR_TRANSFER_NOT_FOUND` and
    `ERR_FUND_OPTION_NOT_FOUND`, each HTTP 404."

    Design: Corner/errors/every_addressed_collection_returns_its_own_not_found_error
    """
    set_clock(api, "2026-01-01T00:00:00Z")
    create_program_year(api, PROGRAM_YEAR_2026)

    probes = [
        (api.get_participant(ABSENT_ID, ADMIN), ERR_PARTICIPANT_NOT_FOUND),
        (api.get_enrollment(ABSENT_ID, ADMIN), ERR_ENROLLMENT_NOT_FOUND),
        (api.get_participant_account(ABSENT_ID, ADMIN), ERR_ACCOUNT_NOT_FOUND),
        (api.get_payroll_remittance(ABSENT_ID, ADMIN), ERR_REMITTANCE_NOT_FOUND),
        (api.get_exemption_certification(ABSENT_ID, ADMIN),
         ERR_EXEMPTION_NOT_FOUND),
        (api.get_excess_case(ABSENT_ID, ADMIN), ERR_EXCESS_CASE_NOT_FOUND),
        (api.get_portability_transfer(ABSENT_ID, ADMIN), ERR_TRANSFER_NOT_FOUND),
        (api.get_investment_option(ABSENT_ID, ADMIN), ERR_FUND_OPTION_NOT_FOUND),
    ]

    for response, expected in probes:
        validate_error(response, expected)
        assert response.status_code == 404, (
            f"{expected} must answer HTTP 404, got {response.status_code}")
        body = response.json()
        assert body["response_type"] == "error"
        assert body["data"]["message"].strip(), (
            f"{expected} must carry a human-readable message")


def test_a_read_with_no_acting_principal_is_refused_before_anything_else(api):
    """
    A listing that five different roles are entitled to read is still refused when
    the request names no acting principal at all, and the refusal is the
    authentication identifier rather than a role or existence failure.

    "If `X-User-ID` is absent or empty, the request fails with
    `ERR_UNAUTHENTICATED` (HTTP 401) before anything else about the request —
    including whether the addressed resource exists — is examined."

    Design: Corner/errors/a_call_missing_the_user_header_is_unauthenticated_except_on_the_clock
    """
    anonymous = headers_without_user_id(ROLE_PROGRAM_ADMINISTRATOR)

    response = api.list_program_years(anonymous)

    validate_error(response, ERR_UNAUTHENTICATED)


def test_the_logical_clock_setter_is_the_one_endpoint_that_needs_no_principal(api):
    """
    Time has to be arranged before the programme has any principals to arrange it
    with, so the clock setter alone accepts a request carrying no acting
    principal — and the instant it sets really is the one every later stamp is
    taken from.

    "Every request other than the logical-clock setter must carry two headers:
    `X-User-ID`, identifying the acting principal, and `X-User-Role`, naming the
    principal's role."

    Design: Corner/errors/a_call_missing_the_user_header_is_unauthenticated_except_on_the_clock
    """
    anonymous = headers_without_user_id(ROLE_PROGRAM_ADMINISTRATOR)

    response = api.set_current_utc(
        {"current_utc": "2026-01-01T00:00:00Z"}, anonymous)

    validate_success(response)
    create_program_year(api, PROGRAM_YEAR_2026)
    employer = create_employer(api, EMPLOYER_DELTA)
    registered = register_employer(api, employer["id"])
    assert registered["registered_at"].startswith("2026-01-01"), (
        "registered_at must be stamped from the instant the anonymous clock call "
        f"set, got {registered['registered_at']!r}")


def _registered_employer_and_saver_at_an_unconfigured_clock(api):
    """
    Statutory dials configured for 2026 only, one registered employer, one saver,
    and the clock moved on to a mid-2029 date for which no dials exist.
    """
    env = build_employer_environment(api)
    saver = create_participant(api)
    env["participant_id"] = saver["id"]
    set_clock(api, "2029-06-01T00:00:00Z")
    env["enrollment_payload"] = {
        "participant_id": saver["id"],
        "hire_date": "2029-05-20",
        "annual_compensation_cents": 9600000,
    }
    return env


def test_an_enrolment_is_refused_when_the_clock_year_has_no_statutory_dials(api):
    """
    The dials are read from the calendar year the clock sits in, not from the
    newest configuration on file, so an enrolment attempted in a year that was
    never configured is refused instead of quietly borrowing 2026's default rate
    and notice window.

    "All statutory dials live on a single immutable configuration row per calendar
    year, and any operation that needs those dials reads the row whose
    `calendar_year` equals the calendar year of the current logical clock."

    Design: Corner/errors/an_operation_in_an_unconfigured_calendar_year_is_rejected
    """
    env = _registered_employer_and_saver_at_an_unconfigured_clock(api)

    response = api.create_enrollment(
        env["employer_id"], env["enrollment_payload"], env["employer_headers"])

    validate_error(response, ERR_PROGRAM_YEAR_NOT_CONFIGURED)
    assert_total_count(api.list_enrollments(ADMIN), 0,
                       label="enrolments after the refused attempt")


def test_configuring_the_clocks_own_year_lets_the_identical_enrolment_through(api):
    """
    Nothing about the enrolment payload changes; what changes is that the clock's
    own calendar year finally has a configuration row, and the enrolment then
    opens at that year's default rate with that year's notice window.

    "The enrolment is created in status `NOTIFIED`, and its `opt_out_deadline` is
    the date of creation plus the program year's `opt_out_window_days` — thirty
    days of notice under the default configuration."

    Design: Corner/errors/an_operation_in_an_unconfigured_calendar_year_is_rejected
    """
    env = _registered_employer_and_saver_at_an_unconfigured_clock(api)
    validate_error(
        api.create_enrollment(env["employer_id"], env["enrollment_payload"],
                              env["employer_headers"]),
        ERR_PROGRAM_YEAR_NOT_CONFIGURED)

    create_program_year(api, {"calendar_year": 2029,
                              "ira_annual_limit_cents": 750000,
                              "default_contribution_rate_bp": 500})
    response = api.create_enrollment(
        env["employer_id"], env["enrollment_payload"], env["employer_headers"])

    enrollment = validate_success(response, expected_status=201)
    assert_fields(enrollment, {
        "enrollment_status": "NOTIFIED",
        "opt_out_deadline": "2029-07-01",
        "rate_source": "DEFAULT",
    }, label="enrolment created in the newly configured year")
    assert_basis_points(enrollment["contribution_rate_bp"], 500,
                        "enrolment contribution_rate_bp")
    saver = read_participant(api, env["participant_id"])
    assert saver["age_at_year_end"] == 49, (
        "age_at_year_end is whole years of age on 31 December of the year the "
        f"clock sits in, got {saver['age_at_year_end']!r}")


def _saver_with_a_menu_holding_one_unelectable_fund(api):
    """
    A live saver with an open account, and a menu of three funds one of which was
    published closed to new money so it still holds balances but can no longer be
    elected into.
    """
    env = build_active_saver_environment(
        api, funds=[FUND_TDF2045, FUND_MMKT01, FUND_CLOSED_TO_NEW])
    env["account_version"] = read_account(api, env["account_id"])["version"]
    return env


def _election_payload(fund_code, expected_account_version):
    """The whole of what a saver sends to move their balance into one fund."""
    return {
        "allocations": [{"fund_code": fund_code, "allocation_bp": 10000}],
        "expected_account_version": expected_account_version,
    }


def test_an_election_naming_a_code_on_no_menu_option_is_unavailable_not_absent(api):
    """
    The fund menu is addressed by its business code rather than by a resource
    identifier, so a code that matches nothing at all is reported as unavailable
    with the 409 coherence identifier and never as a missing fund resource.

    "An investment election naming a fund code that matches no option, or one
    whose option status is not `OPEN`, yields `ERR_FUND_NOT_AVAILABLE`."

    Design: Corner/errors/investment_election_rejects_an_unknown_fund_and_a_closed_fund
    """
    env = _saver_with_a_menu_holding_one_unelectable_fund(api)

    response = api.create_investment_election(
        env["account_id"],
        _election_payload("NOPE99", env["account_version"]),
        make_participant_headers(env["participant_id"]))

    validate_error(response, ERR_FUND_NOT_AVAILABLE)
    assert response.json()["data"]["error_id"] != ERR_FUND_OPTION_NOT_FOUND


def test_an_election_naming_a_fund_closed_to_new_money_is_refused_as_unavailable(api):
    """
    A published option that is closed to new money is a perfectly real fund and is
    still refused, because availability asks whether the option is open rather
    than whether it exists. Neither refusal advances the account, so the saver's
    next election reuses the very same observed version and succeeds.

    "Every named `fund_code` must match a menu option whose `status` is `OPEN`; a
    code matching nothing, or matching an option that is `CLOSED_TO_NEW` or
    `TERMINATED`, is refused with `ERR_FUND_NOT_AVAILABLE`."

    Design: Corner/errors/investment_election_rejects_an_unknown_fund_and_a_closed_fund
    """
    env = _saver_with_a_menu_holding_one_unelectable_fund(api)
    saver_headers = make_participant_headers(env["participant_id"])
    validate_error(
        api.create_investment_election(
            env["account_id"],
            _election_payload("NOPE99", env["account_version"]), saver_headers),
        ERR_FUND_NOT_AVAILABLE)

    refused = api.create_investment_election(
        env["account_id"],
        _election_payload("BND010", env["account_version"]), saver_headers)

    validate_error(refused, ERR_FUND_NOT_AVAILABLE)
    assert read_account(api, env["account_id"])["version"] == (
        env["account_version"]), (
        "a refused election must not advance the account's version")
    accepted = api.create_investment_election(
        env["account_id"],
        _election_payload("MMKT01", env["account_version"]), saver_headers)
    election = validate_success(accepted, expected_status=201)
    assert_fields(election, {
        "status": "ACTIVE",
        "source": "PARTICIPANT_ELECTED",
    }, label="election accepted after the two refusals")
    account = read_account(api, env["account_id"])
    assert account["active_election_id"] == election["id"]


def _saver_whose_menu_offers_no_default_at_all(api):
    """
    A notified saver whose opt-out window has run out, in a programme whose only
    fund is a target-date option landing fifteen years before her retirement year
    and which offers no capital-preservation option to fall back on.
    """
    env = build_employer_environment(api, funds=[FUND_TDF2030])
    build_notified_saver(api, env)
    set_clock(api, "2026-02-01T00:00:00Z")
    return env


def test_the_auto_enrolment_run_refuses_when_neither_default_pool_can_offer_a_fund(api):
    """
    The primary pool is empty because the only target-date fund lands before the
    saver's retirement year and the fallback pool is empty because no
    capital-preservation fund exists, so the batch refuses rather than reaching for
    the nearest glide path — and leaves neither an account nor an activation
    behind.

    "If both pools are empty the batch cannot invest an account it would be
    opening, so it fails with `ERR_NO_DEFAULT_FUND_AVAILABLE`, creates no partial
    account, and leaves the enrolment in `NOTIFIED`."

    Design: Corner/errors/auto_enrollment_run_is_rejected_when_no_default_fund_can_be_selected
    """
    env = _saver_whose_menu_offers_no_default_at_all(api)

    response = api.run_auto_enrollment(ADMIN)

    validate_error(response, ERR_NO_DEFAULT_FUND_AVAILABLE)
    assert read_enrollment(api, env["enrollment_id"])["enrollment_status"] == (
        "NOTIFIED")
    assert_total_count(api.list_participant_accounts(ADMIN), 0,
                       label="accounts after the refused batch")


def test_adding_a_capital_preservation_fund_lets_the_same_batch_run_through(api):
    """
    Publishing one capital-preservation option fills the fallback pool, and the
    identical batch then activates the saver, opens her account and seeds it
    entirely into that fallback fund.

    "If the first pool is empty, the selector falls back to a second pool of every
    option whose `category` is `CAPITAL_PRESERVATION`, whose `status` is `OPEN` and
    whose `default_eligible` is true, picking the smallest `expense_ratio_bp` and
    breaking ties on the earliest creation; that election records
    `selection_basis` as `CAPITAL_PRESERVATION_FALLBACK`."

    Design: Corner/errors/auto_enrollment_run_is_rejected_when_no_default_fund_can_be_selected
    """
    env = _saver_whose_menu_offers_no_default_at_all(api)
    validate_error(api.run_auto_enrollment(ADMIN), ERR_NO_DEFAULT_FUND_AVAILABLE)

    create_investment_option(api, FUND_MMKT01)
    response = api.run_auto_enrollment(ADMIN)

    summary = validate_success(response)
    assert summary["activated_count"] == 1
    assert summary["accounts_opened_count"] == 1
    assert read_enrollment(api, env["enrollment_id"])["enrollment_status"] == (
        "ACTIVE")
    account = account_for_participant(api, env["participant_id"])
    election = active_election(api, account["id"])
    assert_fields(election, {
        "selection_basis": "CAPITAL_PRESERVATION_FALLBACK",
        "source": "SYSTEM_DEFAULT",
    }, label="seeded default election")
    assert len(election["allocations"]) == 1
    assert election["allocations"][0]["fund_code"] == "MMKT01"
    assert_basis_points(election["allocations"][0]["allocation_bp"], 10000,
                        "fallback allocation weight")
