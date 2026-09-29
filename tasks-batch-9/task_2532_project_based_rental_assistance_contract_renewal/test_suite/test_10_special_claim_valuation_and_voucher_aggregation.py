"""The two vacancy valuation branches, the aggregate vacancy-day cap, the month's HAP
aggregation and the three fiscal floors and ceilings."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    api_client,
    certify_household,
    create_household,
    create_vacancy_claim,
    create_direct_ledger_claim,
    create_voucher,
    move_out_household,
    set_clock_date,
    setup_accepted_study,
    setup_adjustment_elected,
    setup_portfolio,
    submit_claim,
    validate_error,
    validate_success,
)

CA_HEADERS = TEST_USERS["contract_administrator_headers"]
CA_APPROVER_HEADERS = TEST_USERS["contract_administrator_approver_headers"]

HOUSEHOLD_PAYING_THIRTY_PERCENT = {
    "unit_number": "101",
    "household_name": "Alvarez",
    "annual_adjusted_income_cents": 1800000,
    "annual_gross_income_cents": 1920000,
    "family_size": 3,
}
HOUSEHOLD_AT_MINIMUM_RENT = {
    "unit_number": "102",
    "household_name": "Boone",
    "annual_adjusted_income_cents": 60000,
    "annual_gross_income_cents": 60000,
    "family_size": 1,
}
HOUSEHOLD_NEVER_CERTIFIED = {
    "unit_number": "103",
    "household_name": "Castillo",
    "annual_adjusted_income_cents": 1200000,
    "annual_gross_income_cents": 1200000,
    "family_size": 2,
}
HOUSEHOLD_FULL_MONTH = {
    "unit_number": "104",
    "household_name": "Dunbar",
    "annual_adjusted_income_cents": 1200000,
    "annual_gross_income_cents": 1200000,
    "family_size": 2,
}
MAPLE_COURT = {
    "address_label": "418 Maple Court",
    "raw_rent_cents": 128649,
    "adjustment_total_cents": 55,
    "utility_adjustment_cents": 1500,
    "weight": 1,
}


def test_the_two_vacancy_variants_diverge_on_the_same_forty_four_vacant_days():
    """"A vacancy claim whose `vacancy_end_date` is non-null, meaning the unit has been
    re-rented, takes the `ACTUAL_CHRONOLOGICAL` variant ... A vacancy claim whose
    `vacancy_end_date` is null, meaning the unit is still vacant, takes the
    `PROJECTED_ESTIMATE` variant instead".

    Design: Difficulty/dual_variant_calc/special_claim_actual_chronological_versus_projected_estimate_on_identical_vacancy_length
    """
    ctx = setup_portfolio()
    contract_id = ctx["contract"]["id"]
    owner_headers = ctx["owner_headers"]
    assert ctx["contract"]["contract_rent_per_unit_cents"] == 118000
    assert ctx["contract"]["renewed_rent_per_unit_cents"] is None, (
        "the valuation basis is the unrenewed contract rent"
    )
    set_clock_date("2027-03-10")

    settled = create_vacancy_claim(
        contract_id,
        owner_headers,
        "101",
        "2027-01",
        "2027-01-20",
        vacancy_end_date="2027-03-05",
    )
    still_vacant = create_vacancy_claim(
        contract_id,
        owner_headers,
        "102",
        "2027-01",
        "2027-01-20",
        estimated_vacancy_days=44,
    )

    assert settled["valuation_variant"] == "ACTUAL_CHRONOLOGICAL"
    assert settled["vacancy_days_claimed"] == 44, (
        "2027-01-20 to 2027-03-05 counts the first vacant day and not the re-rental day, "
        f"got {settled['vacancy_days_claimed']}"
    )
    assert settled["computed_amount_cents"] == 178888, (
        "12 January days at 3806 is 45672, 28 February days at 4214 is 117992 and 4 March "
        f"days at 3806 is 15224, got {settled['computed_amount_cents']}"
    )

    assert still_vacant["valuation_variant"] == "PROJECTED_ESTIMATE", (
        "the variant is chosen by the absence of an end date, not by a client field, got "
        f"{still_vacant['valuation_variant']}"
    )
    assert still_vacant["vacancy_days_claimed"] == 44
    assert still_vacant["computed_amount_cents"] == 138453, (
        "80 percent of 118000 is 94400, times 44 over a flat 30-day month is 138453.33, "
        f"which rounds to 138453, got {still_vacant['computed_amount_cents']}"
    )

    divergence = (
        settled["computed_amount_cents"] - still_vacant["computed_amount_cents"]
    )
    assert divergence == 40435, (
        "the same 44 vacant days diverge by exactly 40435 cents on the variant alone, got "
        f"{divergence}"
    )

    assert submit_claim(settled["id"], owner_headers)["state"] == "SUBMITTED"
    assert submit_claim(still_vacant["id"], owner_headers)["state"] == "SUBMITTED", (
        "44 days on each of two different units is inside the per-unit cap"
    )


def test_the_settled_variant_follows_the_calendar_while_the_estimate_ignores_it():
    """"The month-by-month divisor matters: February's 28-day divisor yields a higher daily
    rate than January's 31-day divisor, so identical vacancy lengths in different months
    produce different amounts", while on the projected branch "The calendar is ignored
    entirely".

    Design: Difficulty/dual_variant_calc/special_claim_actual_chronological_versus_projected_estimate_on_identical_vacancy_length
    """
    ctx = setup_portfolio()
    contract_id = ctx["contract"]["id"]
    owner_headers = ctx["owner_headers"]
    set_clock_date("2027-04-01")

    january = create_vacancy_claim(
        contract_id,
        owner_headers,
        "101",
        "2027-01",
        "2027-01-01",
        vacancy_end_date="2027-01-21",
    )
    february = create_vacancy_claim(
        contract_id,
        owner_headers,
        "102",
        "2027-02",
        "2027-02-01",
        vacancy_end_date="2027-02-21",
    )
    assert january["vacancy_days_claimed"] == 20
    assert february["vacancy_days_claimed"] == 20
    assert january["computed_amount_cents"] == 76120, (
        "round_half_up(118000 / 31) is 3806 and 20 days of that is 76120, got "
        f"{january['computed_amount_cents']}"
    )
    assert february["computed_amount_cents"] == 84280, (
        "round_half_up(118000 / 28) is 4214 and 20 days of that is 84280, got "
        f"{february['computed_amount_cents']}"
    )
    assert february["computed_amount_cents"] > january["computed_amount_cents"], (
        "the shorter month carries the higher daily rate"
    )

    january_estimate = create_vacancy_claim(
        contract_id,
        owner_headers,
        "103",
        "2027-01",
        "2027-01-01",
        estimated_vacancy_days=20,
    )
    february_estimate = create_vacancy_claim(
        contract_id,
        owner_headers,
        "104",
        "2027-02",
        "2027-02-01",
        estimated_vacancy_days=20,
    )
    assert january_estimate["computed_amount_cents"] == 62933, (
        "94400 times 20 over 30 is 62933.33, which rounds to 62933, got "
        f"{january_estimate['computed_amount_cents']}"
    )
    assert february_estimate["computed_amount_cents"] == 62933, (
        "the projected branch never touches the calendar, so February matches January, got "
        f"{february_estimate['computed_amount_cents']}"
    )

    clamped = create_vacancy_claim(
        contract_id,
        owner_headers,
        "105",
        "2027-01",
        "2027-01-01",
        vacancy_end_date="2027-03-12",
    )
    assert clamped["vacancy_days_claimed"] == 60, (
        "the 70 elapsed days are cut to the lesser of 60 and the elapsed count, got "
        f"{clamped['vacancy_days_claimed']}"
    )
    assert clamped["computed_amount_cents"] == 239784, (
        "the walk covers exactly 60 days: 31 January days at 3806 is 117986, 28 February "
        "days at 4214 is 117992 and 1 March day is 3806, got "
        f"{clamped['computed_amount_cents']}"
    )
    assert clamped["state"] == "DRAFT"


def test_the_month_s_hap_includes_only_the_certifications_the_period_covers():
    """"A household with no such certification is skipped. If the household is `MOVED_OUT` with
    a `move_out_date` at or before the last day of the month, its term is prorated: count the
    whole days from the first day of the month to the `move_out_date`, not counting the
    move-out day itself, multiply the certification's `hap_cents` by that day count, divide by
    the number of days in the month, and round half up to whole cents".

    Design: Corner/calculations/monthly_voucher_includes_only_the_households_and_certifications_the_period_covers
    """
    ctx = setup_portfolio()
    prop_id = ctx["property"]["id"]
    contract_id = ctx["contract"]["id"]
    owner_headers = ctx["owner_headers"]

    staying = create_household(prop_id, owner_headers, **HOUSEHOLD_PAYING_THIRTY_PERCENT)
    departing = create_household(prop_id, owner_headers, **HOUSEHOLD_AT_MINIMUM_RENT)
    uncertified = create_household(prop_id, owner_headers, **HOUSEHOLD_NEVER_CERTIFIED)
    full_month = create_household(prop_id, owner_headers, **HOUSEHOLD_FULL_MONTH)

    cert_staying = certify_household(staying["id"], owner_headers, "2026-07-01")
    cert_departing = certify_household(departing["id"], owner_headers, "2026-07-01")
    cert_full = certify_household(full_month["id"], owner_headers, "2026-07-01")
    assert cert_staying["hap_cents"] == 84500
    assert cert_departing["hap_cents"] == 127000
    assert cert_full["hap_cents"] == 99500

    gone = move_out_household(departing["id"], owner_headers, "2026-07-20")
    assert gone["status"] == "MOVED_OUT"

    july = create_voucher(contract_id, owner_headers, "2026-07")
    assert july["included_certification_count"] == 3, (
        "the uncertified household is a candidate by status but contributes no "
        f"certification, got {july['included_certification_count']}"
    )
    assert july["requested_hap_cents"] == 261839, (
        "84500 plus round_half_up(127000 * 19 / 31) = 77839 plus 99500 is 261839, got "
        f"{july['requested_hap_cents']}"
    )

    august = create_voucher(contract_id, owner_headers, "2026-08")
    assert august["included_certification_count"] == 2, (
        "a household that left on or before the first day contributes nothing, got "
        f"{august['included_certification_count']}"
    )
    assert august["requested_hap_cents"] == 184000, (
        f"84500 plus 99500 is 184000, got {august['requested_hap_cents']}"
    )

    assert validate_success(
        api_client.get_tenant_household(uncertified["id"], CA_HEADERS)
    )["status"] == "ACTIVE", "the skip is a certification-set outcome, not a status change"
    contract_after = validate_success(api_client.get_hap_contract(contract_id, CA_HEADERS))
    assert contract_after["hap_ledger_balance_cents"] == 30000000, (
        "creating vouchers moves no money, got "
        f"{contract_after['hap_ledger_balance_cents']}"
    )


def test_vacancy_days_aggregate_per_unit_up_to_the_sixty_day_cap():
    """"the vacancy day cap is enforced in aggregate, not per claim: this claim's
    `vacancy_days_claimed` plus the sum of `vacancy_days_claimed` over every other claim on the
    same `contract_id` and the same `unit_number` in state `SUBMITTED`, `APPROVED`, or `PAID`
    must not exceed 60 days, and a breach is refused with `ERR_VACANCY_DAYS_CAP_EXCEEDED`".

    Design: Corner/validations/vacancy_days_aggregate_across_claims_on_one_unit_up_to_the_sixty_day_cap
    """
    ctx = setup_portfolio()
    contract_id = ctx["contract"]["id"]
    owner_headers = ctx["owner_headers"]
    set_clock_date("2027-04-01")

    fifty_days = create_vacancy_claim(
        contract_id,
        owner_headers,
        "101",
        "2027-01",
        "2027-01-01",
        vacancy_end_date="2027-02-20",
    )
    assert fifty_days["vacancy_days_claimed"] == 50
    assert fifty_days["valuation_variant"] == "ACTUAL_CHRONOLOGICAL"
    assert fifty_days["computed_amount_cents"] == 198052, (
        "3806 across all 31 January days is 117986 and 4214 across 19 February days is "
        f"80066, got {fifty_days['computed_amount_cents']}"
    )
    assert submit_claim(fifty_days["id"], owner_headers)["state"] == "SUBMITTED"

    eleven_same_unit = create_vacancy_claim(
        contract_id, owner_headers, "101", "2027-03", "2027-03-01", estimated_vacancy_days=11
    )
    ten_same_unit = create_vacancy_claim(
        contract_id, owner_headers, "101", "2027-03", "2027-03-01", estimated_vacancy_days=10
    )
    eleven_other_unit = create_vacancy_claim(
        contract_id, owner_headers, "102", "2027-03", "2027-03-01", estimated_vacancy_days=11
    )
    assert eleven_same_unit["vacancy_days_claimed"] == 11
    assert eleven_same_unit["valuation_variant"] == "PROJECTED_ESTIMATE"
    assert eleven_same_unit["computed_amount_cents"] == 34613, (
        "94400 times 11 over 30 is 34613.33, got "
        f"{eleven_same_unit['computed_amount_cents']}"
    )
    assert ten_same_unit["computed_amount_cents"] == 31467, (
        "94400 times 10 over 30 is 31466.67, which rounds up, got "
        f"{ten_same_unit['computed_amount_cents']}"
    )

    validate_error(
        api_client.submit_special_claim(eleven_same_unit["id"], owner_headers),
        ApiErrorId.ERR_VACANCY_DAYS_CAP_EXCEEDED.value,
        expected_status=422,
    )
    assert validate_success(
        api_client.get_special_claim(eleven_same_unit["id"], CA_HEADERS)
    )["state"] == "DRAFT", "neither claim breaches the cap alone, but 50 plus 11 is 61"

    other_unit = submit_claim(eleven_other_unit["id"], owner_headers)
    assert other_unit["state"] == "SUBMITTED", (
        "the cap is scoped to unit_number, so unit 102 is unaffected, got "
        f"{other_unit['state']}"
    )
    assert other_unit["vacancy_days_claimed"] == 11

    exactly_at_cap = submit_claim(ten_same_unit["id"], owner_headers)
    assert exactly_at_cap["state"] == "SUBMITTED", (
        "50 plus 10 is exactly 60, which does not exceed the cap, got "
        f"{exactly_at_cap['state']}"
    )


def test_three_fiscal_floors_and_ceilings_are_each_reachable_on_one_contract():
    """"the budget-based track reports `ERR_BUDGET_RENT_EXCEEDS_CAP`", "The recomputed
    `requested_hap_cents` must also be strictly greater than zero, or the submission is refused
    with `ERR_ZERO_VOUCHER_REQUEST` (HTTP 422)", and "The amount must be strictly positive, so
    a claim fully offset by the security deposit or a zero-day vacancy is refused with
    `ERR_ZERO_CLAIM_AMOUNT` (HTTP 422)".

    Design: Corner/errors/three_fiscal_floors_and_ceilings_are_each_reachable_on_one_contract
    """
    ctx = setup_adjustment_elected(
        renewal_option="OPTION_2_OCAF",
        adjustment_method="BUDGET_BASED",
        contract_overrides={"operating_expense_per_unit_cents": 130000},
    )
    case = ctx["case"]
    contract_id = ctx["contract"]["id"]
    owner_headers = ctx["owner_headers"]
    assert case["rcs_required"] is True
    assert case["budget_rent_per_unit_cents"] == 179820, (
        "the subtotal 130000 + 32000 + 4500 is 166500 and the single 8-percent fee is 13320, "
        f"got {case['budget_rent_per_unit_cents']}"
    )

    study = setup_accepted_study(case["id"], owner_headers, [MAPLE_COURT])
    assert study["study"]["estimated_market_rent_cents"] == 130200
    priced = validate_success(api_client.get_renewal_case(case["id"], CA_HEADERS))
    assert priced["comparable_market_rent_cents"] == 130200

    validate_error(
        api_client.approve_rents(case["id"], CA_APPROVER_HEADERS),
        ApiErrorId.ERR_BUDGET_RENT_EXCEEDS_CAP.value,
        expected_status=422,
    )
    refused = validate_success(api_client.get_renewal_case(case["id"], CA_HEADERS))
    assert refused["rent_track_status"] == "RCS_IN_PROGRESS", (
        "179820 strictly exceeds the ceiling round_half_up(1.1 * 130200) of 143220, and the "
        f"rent is refused rather than trimmed, got {refused['rent_track_status']}"
    )
    assert refused["approved_rent_per_unit_cents"] is None

    empty_voucher = create_voucher(contract_id, owner_headers, "2026-11")
    assert empty_voucher["requested_hap_cents"] == 0, (
        "the property has no households at all, got "
        f"{empty_voucher['requested_hap_cents']}"
    )
    assert empty_voucher["included_certification_count"] == 0
    assert empty_voucher["state"] == "DRAFT", (
        "the floor is checked at submit, not at create, got " f"{empty_voucher['state']}"
    )
    validate_error(
        api_client.submit_voucher_submission(empty_voucher["id"], owner_headers),
        ApiErrorId.ERR_ZERO_VOUCHER_REQUEST.value,
        expected_status=422,
    )
    assert validate_success(
        api_client.get_voucher_submission(empty_voucher["id"], CA_HEADERS)
    )["state"] == "DRAFT"

    offset_claim = create_direct_ledger_claim(
        contract_id,
        owner_headers,
        "UNPAID_RENT",
        "101",
        "2026-11",
        claimed_amount_cents=20000,
        security_deposit_balance_cents=20000,
    )
    assert offset_claim["computed_amount_cents"] == 0, (
        "the lesser of 20000 and one month of unit rent, less the 20000 deposit, is zero, "
        f"got {offset_claim['computed_amount_cents']}"
    )
    assert offset_claim["valuation_variant"] == "DIRECT_LEDGER"
    assert offset_claim["vacancy_days_claimed"] == 0
    validate_error(
        api_client.submit_special_claim(offset_claim["id"], owner_headers),
        ApiErrorId.ERR_ZERO_CLAIM_AMOUNT.value,
        expected_status=422,
    )
    assert validate_success(
        api_client.get_special_claim(offset_claim["id"], CA_HEADERS)
    )["state"] == "DRAFT"

    contract_after = validate_success(api_client.get_hap_contract(contract_id, CA_HEADERS))
    assert contract_after["hap_ledger_balance_cents"] == 30000000, (
        "not one of the three refusals moved money, got "
        f"{contract_after['hap_ledger_balance_cents']}"
    )
