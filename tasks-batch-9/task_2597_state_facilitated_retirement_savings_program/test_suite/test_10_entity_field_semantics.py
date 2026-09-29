"""
Field-level semantics of the programme's records at the moment they come into
existence.

The statutory parameter row and the fund menu are configuration: they are
immutable, so they expose a narrower set of common properties than every other
record, and a parameter row created from its three required inputs still has to
publish a concrete value for every optional dial. Employers and savers, by
contrast, are lifecycle records whose derived and system fields must already be
seeded on the creation response. The remaining tests here pin the two ways a
malformed or unresolvable request is refused — an unknown path identifier is an
existence failure, a missing or out-of-enum body field is a request-shape
failure — and the uniqueness rule that makes an enrolment a pairing of one
employer with one saver.
"""

from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import (
    ADMIN,
    CLOCK_2026_01_01,
    EMPLOYER_DELTA,
    EMPLOYER_SECOND,
    ERR_DUPLICATE_ENROLLMENT,
    ERR_EMPLOYER_NOT_FOUND,
    ERR_INVALID_REQUEST,
    FUND_MMKT01,
    FUND_TDF2040,
    FUND_TDF2045,
    PARTICIPANT_ROSA,
    PROGRAM_YEAR_2026,
    PROGRAM_YEAR_DEFAULTS,
    add_employer,
    assert_common_fields,
    assert_config_fields,
    assert_envelope_meta,
    assert_fields,
    assert_pagination_meta,
    assert_total_count,
    build_employer_environment,
    create_enrollment,
    create_investment_option,
    create_participant,
    create_program_year,
    read_investment_option,
    set_clock,
)
from test_helpers.test_users import make_employer_headers, make_participant_headers

# A well-formed identifier that no record in an empty store can carry.
UNKNOWN_ID = "00000000-0000-4000-8000-000000000404"

# A fund whose category is not a target-date one, so it carries no landing year.
BOND_OPTION = {
    "fund_code": "BND010",
    "name": "Core Bond Index",
    "category": "BOND_INDEX",
    "expense_ratio_bp": 12,
    "default_eligible": False,
}

# The same fund named twice: once under a category the menu does not define, and
# once under one it does.
REAL_ESTATE_OPTION = {
    "fund_code": "REIT01",
    "name": "Global Real Estate",
    "category": "REAL_ESTATE",
    "expense_ratio_bp": 55,
    "default_eligible": True,
}
EQUITY_OPTION = {
    "fund_code": "REIT01",
    "name": "Global Real Estate",
    "category": "EQUITY_INDEX",
    "expense_ratio_bp": 55,
    "default_eligible": True,
}

# Two savers born a single day apart across a New Year boundary.
SAVER_BORN_LAST_DAY_OF_1976 = {
    "full_name": "Ines Ortega",
    "date_of_birth": "1976-12-31",
    "email": "ines.ortega@x.example",
    "ssn_last4": "9001",
    "state_resident": True,
}
SAVER_BORN_FIRST_DAY_OF_1977 = {
    "full_name": "Karl Weiss",
    "date_of_birth": "1977-01-01",
    "email": "karl.weiss@x.example",
    "ssn_last4": "9002",
    "state_resident": True,
}

CERTIFICATION_FILING = {
    "qualified_plan_type": "401K",
    "plan_sponsor_ein": "44-2000002",
    "plan_effective_date": "2026-01-01",
    "attestation_accepted": True,
}


def _configure_year_without_a_fund_menu(api):
    """Move the clock into 2026 and configure that year, leaving the menu empty."""
    set_clock(api, CLOCK_2026_01_01)
    return create_program_year(api, PROGRAM_YEAR_2026)


def test_program_year_created_from_three_inputs_materialises_every_statutory_dial(api):
    """
    A statutory parameter row configured with only its calendar year, its annual
    ceiling and its default deferral rate must still publish a concrete value for
    each of the fifteen optional dials, because penalty, escalation and
    net-income arithmetic all read them off the stored row.

    "Every remaining dial has a default that is materialised onto the stored row
    when the caller omits it, so a stored program year always exposes a concrete
    value for each one:"

    Design: Corner/entities/program_year_creation_applies_every_statutory_default
    """
    set_clock(api, CLOCK_2026_01_01)

    year = validate_success(
        api.create_program_year(dict(PROGRAM_YEAR_2026), ADMIN),
        expected_status=201)

    assert_fields(year, {
        "calendar_year": 2026,
        "ira_annual_limit_cents": 700000,
        "default_contribution_rate_bp": 500,
    }, label="program year")
    assert_fields(year, dict(PROGRAM_YEAR_DEFAULTS), label="program year defaults")


def test_statutory_parameter_row_and_fund_option_carry_no_version_or_updated_at(api):
    """
    Neither configuration record is ever mutated, so both publish an identifier
    and a creation instant and nothing else from the common properties — a
    version counter or a modification stamp on either one would imply an edit the
    programme does not offer.

    "Two configuration resources are exceptions: a program year and an investment
    option are immutable once created, so each of them carries only `id` and
    `created_at` — both `updated_at` and `version` are absent from those two
    resource shapes entirely."

    Design: Corner/entities/program_year_and_investment_option_carry_no_version_and_no_mutator
    """
    _configure_year_without_a_fund_menu(api)

    option = validate_success(
        api.create_investment_option(dict(FUND_TDF2045), ADMIN),
        expected_status=201)

    assert_config_fields(option, label="fund option on creation")
    assert_config_fields(read_investment_option(api, option["id"]),
                         label="fund option read back")

    rows, _ = validate_paginated(api.list_program_years(ADMIN))
    assert rows, "the configured program year must appear in the listing"
    for row in rows:
        assert_config_fields(row, label="program year row")


def test_fund_option_echoes_every_supplied_field_and_opens_by_default(api):
    """
    A fund added to the menu answers with each supplied value unchanged, opens in
    its selectable state without being told to, and carries no landing year at
    all because its category is not a target-date one.

    "`target_year`, the glide-path landing year, is required when and only when
    `category` is `TARGET_DATE`, must fall between 2020 and 2085 inclusive, and
    must be null for every other category; violating that pairing in either
    direction is refused with `ERR_INVALID_REQUEST`."

    "An option's `status` may be supplied at creation as `OPEN`, `CLOSED_TO_NEW`
    or `TERMINATED` and defaults to `OPEN`, which lets the programme seed a
    legacy option that still holds balances but can no longer be elected into."

    Design: Corner/entities/investment_option_creation_echoes_every_declared_field
    """
    _configure_year_without_a_fund_menu(api)

    response = api.create_investment_option(dict(BOND_OPTION), ADMIN)

    option = validate_success(response, expected_status=201)
    assert_envelope_meta(response)
    assert response.json()["response_type"] == "object"
    assert_fields(option, {
        "fund_code": "BND010",
        "name": "Core Bond Index",
        "category": "BOND_INDEX",
        "expense_ratio_bp": 12,
        "default_eligible": False,
        "target_year": None,
        "status": "OPEN",
    }, label="bond index option")

    assert_fields(read_investment_option(api, option["id"]), {
        "fund_code": "BND010",
        "status": "OPEN",
    }, label="bond index option read back")


def test_fund_menu_listing_reports_the_filtered_total_not_the_page(api):
    """
    With three funds on the menu, a two-row page still reports three matching
    records and flags that more remain, the following page flags that none do,
    and narrowing by category shrinks the reported total to the one fund that
    matches while the page counters fall back to their defaults.

    "The `meta` object of a list response carries `limit`, `offset`,
    `total_count` and `has_more`, where `total_count` is the number of records
    matching the filters before pagination is applied and `has_more` indicates
    whether any matching record remains beyond the current page."

    "The fund menu may be filtered by `category`, by `status`, and by
    `default_eligible`."

    Design: Corner/entities/investment_option_listing_paginates_and_filters_with_total_count
    """
    _configure_year_without_a_fund_menu(api)
    create_investment_option(api, FUND_TDF2045)
    create_investment_option(api, FUND_TDF2040)
    create_investment_option(api, FUND_MMKT01)
    saver = create_participant(api, PARTICIPANT_ROSA)

    first_page = api.list_investment_options(ADMIN, {"limit": 2, "offset": 0})
    second_page = api.list_investment_options(ADMIN, {"limit": 2, "offset": 2})
    filtered = api.list_investment_options(
        make_participant_headers(saver["id"]),
        {"category": "CAPITAL_PRESERVATION"})

    rows = assert_pagination_meta(first_page, limit=2, offset=0, total_count=3,
                                 has_more=True, label="first menu page")
    assert first_page.json()["response_type"] == "array"
    assert len(rows) == 2, f"expected a full first page, got {len(rows)} rows"

    rows = assert_pagination_meta(second_page, limit=2, offset=2, total_count=3,
                                 has_more=False, label="second menu page")
    assert len(rows) == 1, f"expected one trailing row, got {len(rows)} rows"

    rows = assert_pagination_meta(filtered, limit=10, offset=0, total_count=1,
                                 has_more=False,
                                 label="capital preservation filter")
    assert len(rows) == 1, f"expected one matching fund, got {len(rows)} rows"
    assert rows[0]["fund_code"] == "MMKT01"


def test_reading_an_unknown_employer_identifier_is_an_existence_failure(api):
    """
    A syntactically valid identifier that matches no employer is refused as a
    missing record, not as a malformed request, because nothing about the path
    segment itself is wrong — only the store lookup can reject it.

    "On every endpoint with an identifier segment in its path, an unknown
    identifier yields that collection's not-found error."

    Design: Corner/entities/employer_read_with_unknown_uuid_returns_employer_not_found
    """
    _configure_year_without_a_fund_menu(api)

    response = api.get_employer(UNKNOWN_ID, ADMIN)

    error = validate_error(response, ERR_EMPLOYER_NOT_FOUND)
    assert response.json()["response_type"] == "error"
    assert error["error_id"] != ERR_INVALID_REQUEST


def test_employer_creation_without_a_headcount_is_a_request_shape_failure(api):
    """
    The eligible-employee headcount is what fixes an employer's mandate wave and
    deadline, so a filing that omits it cannot be completed; the request is
    refused on its shape rather than stored as an employer without a wave.

    "On every endpoint with a body or query parameters, a missing required field,
    a wrong type, an unknown enum member, a numeric field outside its declared
    range, a non-ISO-8601 date, a `limit` outside 1 to 100 or a negative `offset`
    yields `ERR_INVALID_REQUEST`."

    Design: Corner/entities/employer_creation_without_employee_count_is_rejected_as_invalid_request
    """
    _configure_year_without_a_fund_menu(api)

    response = api.create_employer({
        "ein": "44-1000001",
        "legal_name": "Missing Count Partners",
        "worksite_state": "CA",
    }, ADMIN)

    validate_error(response, ERR_INVALID_REQUEST)


def test_year_end_age_and_catch_up_flag_turn_on_the_birth_year(api):
    """
    Age is measured at the end of the calendar year the clock sits in, so with
    the clock in January 2026 a saver born on the last day of 1976 is already
    fifty for the year and wins the catch-up allowance, while a saver born the
    very next day is forty-nine and does not.

    "Three figures on the record are derived rather than supplied:
    `age_at_year_end`, the saver's whole years of age on 31 December of the
    calendar year in which the logical clock currently sits; `catch_up_eligible`,
    true exactly when `age_at_year_end` is at least 50; and
    `indirect_rollover_count`, the number of this saver's portability transfers
    whose kind is `INDIRECT_60_DAY` and whose status is `SETTLED`."

    Design: Corner/entities/participant_age_and_catch_up_flag_are_computed_from_date_of_birth
    """
    _configure_year_without_a_fund_menu(api)

    elder = create_participant(api, SAVER_BORN_LAST_DAY_OF_1976)
    younger = create_participant(api, SAVER_BORN_FIRST_DAY_OF_1977)

    assert_fields(elder, {
        "age_at_year_end": 50,
        "catch_up_eligible": True,
        "indirect_rollover_count": 0,
    }, label="saver born 31 December 1976")
    assert_fields(younger, {
        "age_at_year_end": 49,
        "catch_up_eligible": False,
        "indirect_rollover_count": 0,
    }, label="saver born 1 January 1977")


def test_new_employer_row_opens_with_every_lifecycle_field_at_its_seed(api):
    """
    Creation supplies four facts about the firm, yet the answer already carries
    both state dimensions, the derived mandate wave and deadline, an untouched
    acknowledgement flag, an empty unremitted total and a first version — an
    employer is never brought into being part-way through its lifecycle.

    "On creation, an employer whose tier resolves to `NOT_COVERED` is placed
    directly in `EXEMPT_SMALL` rather than in `PENDING_REGISTRATION`; every
    covered employer starts in `PENDING_REGISTRATION`."

    "Before registration both `payroll_contact_email` and `registered_at` are
    null."

    Design: Corner/entities/employer_system_and_computed_fields_are_server_generated_on_creation
    """
    _configure_year_without_a_fund_menu(api)

    employer = validate_success(
        api.create_employer(dict(EMPLOYER_DELTA), ADMIN), expected_status=201)

    assert_common_fields(employer, expected_version=1, label="new employer")
    assert_fields(employer, {
        "registration_status": "PENDING_REGISTRATION",
        "compliance_status": "COMPLIANT",
        "non_fiduciary_acknowledged": False,
        "payroll_contact_email": None,
        "registered_at": None,
        "unremitted_deduction_cents": 0,
        "last_recount_effective_date": None,
        "wave_tier": "WAVE_2",
        "registration_deadline": "2026-12-31",
    }, label="new employer")


def test_fund_option_outside_the_four_documented_categories_is_refused(api):
    """
    The menu defines exactly four categories, and a fifth is rejected on the
    request's shape rather than stored: the automatic default selector partitions
    the menu by those categories alone, so an unknown one would be invisible to
    both of its candidate pools. Renaming the same fund into a defined category
    then succeeds and opens it.

    "Each option carries a `fund_code` — a short stable code of 4 to 12 uppercase
    alphanumeric characters, unique across the menu, and the token by which
    allocations name it — a human-readable `name`, a `category` of `TARGET_DATE`,
    `CAPITAL_PRESERVATION`, `EQUITY_INDEX` or `BOND_INDEX`, an `expense_ratio_bp`
    from 0 through 500 basis points, and `default_eligible`, the flag that says
    whether the automatic default selector is allowed to pick this option."

    Design: Corner/entities/investment_option_rejects_a_category_outside_the_declared_enum
    """
    _configure_year_without_a_fund_menu(api)

    refused = api.create_investment_option(dict(REAL_ESTATE_OPTION), ADMIN)

    validate_error(refused, ERR_INVALID_REQUEST)
    assert_total_count(api.list_investment_options(ADMIN), 0,
                       label="fund menu after the refusal")

    accepted = validate_success(
        api.create_investment_option(dict(EQUITY_OPTION), ADMIN),
        expected_status=201)
    assert_fields(accepted, {
        "fund_code": "REIT01",
        "category": "EQUITY_INDEX",
        "status": "OPEN",
    }, label="equity index option")
    assert read_investment_option(api, accepted["id"])["status"] == "OPEN"


def test_filing_a_certification_under_an_unknown_employer_reports_the_employer_hop(api):
    """
    A certification hangs off an employer, so the employer segment of the address
    is resolved before the filing's own body, its enforcement interlock or its
    coverage window are considered at all: an otherwise perfect filing under a
    firm that does not exist reports the missing employer.

    "Path segments are resolved strictly left to right, and the first segment that
    fails to resolve determines the response."

    Design: Corner/entities/exemption_certification_under_an_unknown_employer_is_not_found
    """
    _configure_year_without_a_fund_menu(api)

    response = api.create_exemption_certification(
        UNKNOWN_ID, dict(CERTIFICATION_FILING), ADMIN)

    error = validate_error(response, ERR_EMPLOYER_NOT_FOUND)
    assert error["error_id"] != "ERR_ENFORCEMENT_HOLD"
    assert error["error_id"] != "ERR_EXEMPTION_WINDOW_CLOSED"


def _two_registered_employers_and_one_saver(api):
    """
    Two registered firms and one saver already enrolled at the first of them, so
    the same person can be offered to the second firm as well.
    """
    env = build_employer_environment(api, employer=EMPLOYER_DELTA)
    env["second_employer"] = add_employer(api, env, EMPLOYER_SECOND)
    saver = create_participant(api, PARTICIPANT_ROSA)
    env["saver_id"] = saver["id"]
    env["first_enrollment"] = create_enrollment(
        api, env["employer_id"], saver["id"], "2026-01-05", 9600000)
    return env


def test_the_same_saver_may_hold_one_enrolment_at_each_of_two_employers(api):
    """
    A saver working two covered jobs is enrolled once by each firm, and each
    enrolment names the firm that created it together with the saver it covers,
    so the pairing rather than either side alone is what the record identifies.

    "The payload carries only facts the employer legitimately owns: the
    `participant_id` of the saver, the `hire_date` at this employer, and
    `annual_compensation_cents`, the annualised compensation as the employer
    reports it."

    Design: Corner/entities/enrollment_is_the_employer_participant_junction_and_is_unique_per_pair
    """
    env = _two_registered_employers_and_one_saver(api)
    second_employer_id = env["second_employer"]["id"]

    response = api.create_enrollment(second_employer_id, {
        "participant_id": env["saver_id"],
        "hire_date": "2026-01-06",
        "annual_compensation_cents": 4800000,
    }, make_employer_headers(second_employer_id))

    second = validate_success(response, expected_status=201)
    assert_fields(second, {
        "employer_id": second_employer_id,
        "participant_id": env["saver_id"],
    }, label="enrolment at the second employer")
    assert_fields(env["first_enrollment"], {
        "employer_id": env["employer_id"],
        "participant_id": env["saver_id"],
    }, label="enrolment at the first employer")

    assert_total_count(
        api.list_enrollments(ADMIN, {"participant_id": env["saver_id"]}), 2,
        label="enrolments of one saver")
    assert_total_count(
        api.list_enrollments(ADMIN, {"employer_id": env["employer_id"]}), 1,
        label="enrolments of the first employer")


def test_a_second_live_enrolment_for_the_same_pair_is_refused(api):
    """
    Uniqueness bites on the pairing, not on either side of it: the firm that has
    already enrolled this saver and left that enrolment live cannot enrol them
    again, even though enrolling the same saver at a different firm was fine.

    "An attempt that duplicates a live pairing — an enrolment already exists for
    this employer and this saver in status `NOTIFIED`, `ACTIVE` or `OPTED_OUT` —
    is refused with `ERR_DUPLICATE_ENROLLMENT`; re-hiring someone whose prior
    enrolment is `TERMINATED` is allowed and creates a fresh row, whereas someone
    sitting in `OPTED_OUT` must be re-enrolled rather than duplicated."

    Design: Corner/entities/enrollment_is_the_employer_participant_junction_and_is_unique_per_pair
    """
    env = _two_registered_employers_and_one_saver(api)
    assert env["first_enrollment"]["enrollment_status"] == "NOTIFIED"

    response = api.create_enrollment(env["employer_id"], {
        "participant_id": env["saver_id"],
        "hire_date": "2026-01-07",
        "annual_compensation_cents": 9600000,
    }, make_employer_headers(env["employer_id"]))

    validate_error(response, ERR_DUPLICATE_ENROLLMENT)
    assert_total_count(
        api.list_enrollments(ADMIN, {"employer_id": env["employer_id"]}), 1,
        label="enrolments of the first employer")
