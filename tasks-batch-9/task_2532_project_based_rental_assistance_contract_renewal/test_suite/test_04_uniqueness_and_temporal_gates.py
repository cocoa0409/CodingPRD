"""Uniqueness scopes, the temporal windows and the two inclusive boundaries."""
from test_helpers import (
    ApiErrorId,
    REFERENCE_HOUSEHOLD_ONE,
    TEST_USERS,
    api_client,
    assert_unit_invariant,
    create_owner_payload,
    create_renewal_case_payload,
    create_tenant_household_payload,
    create_tenant_notice_payload,
    create_voucher,
    move_out_payload,
    set_clock_date,
    setup_certified_household,
    setup_portfolio,
    validate_error,
    validate_success,
)

CA_HEADERS = TEST_USERS["contract_administrator_headers"]
CA_APPROVER_HEADERS = TEST_USERS["contract_administrator_approver_headers"]

RELET_HOUSEHOLD = {
    "unit_number": "101",
    "household_name": "Nakamura",
    "annual_adjusted_income_cents": 900000,
    "annual_gross_income_cents": 900000,
    "family_size": 1,
}


def test_uniqueness_rules_reject_a_duplicate_tin_a_live_unit_number_and_a_second_case():
    """"The taxpayer identification number must be unique across all owners; a repeat yields
    `ERR_DUPLICATE_TIN`", "Unit numbers must be unique within a property across all households
    whose `status` is not `MOVED_OUT`", and "if a case already exists on the contract whose
    rent track has not reached `EXECUTED`, the attempt is refused with
    `ERR_OPEN_RENEWAL_CASE_EXISTS`".

    Design: Corner/validations/uniqueness_rules_reject_a_duplicate_tin_a_live_unit_number_and_a_second_open_case
    """
    ctx = setup_portfolio(owner_overrides={"tin": "27-3310011"})
    prop_id = ctx["property"]["id"]
    contract_id = ctx["contract"]["id"]
    owner_headers = ctx["owner_headers"]
    first = setup_certified_household(prop_id, owner_headers, REFERENCE_HOUSEHOLD_ONE)
    set_clock_date("2026-12-01")
    case = validate_success(
        api_client.create_renewal_case(
            create_renewal_case_payload(contract_id), owner_headers
        ),
        expected_status=201,
    )
    assert case["rent_track_status"] == "TERMS_PENDING"

    validate_error(
        api_client.create_owner(
            create_owner_payload(
                legal_name="Cedar Ridge Housing Partners II LP",
                tin="27-3310011",
                contact_email="agent2@cedarridge.example",
            ),
            CA_HEADERS,
        ),
        ApiErrorId.ERR_DUPLICATE_TIN.value,
        expected_status=409,
    )

    validate_error(
        api_client.create_tenant_household(
            create_tenant_household_payload(prop_id, **RELET_HOUSEHOLD), owner_headers
        ),
        ApiErrorId.ERR_DUPLICATE_UNIT_NUMBER.value,
        expected_status=409,
    )

    validate_error(
        api_client.create_renewal_case(
            create_renewal_case_payload(contract_id), owner_headers
        ),
        ApiErrorId.ERR_OPEN_RENEWAL_CASE_EXISTS.value,
        expected_status=409,
    )
    contract_after = validate_success(api_client.get_hap_contract(contract_id, CA_HEADERS))
    assert contract_after["lifecycle_status"] == "RENEWAL_PENDING"

    vacated = validate_success(
        api_client.move_out_tenant_household(
            first["household"]["id"], move_out_payload("2026-12-01"), owner_headers
        )
    )
    assert vacated["status"] == "MOVED_OUT"

    relet = validate_success(
        api_client.create_tenant_household(
            create_tenant_household_payload(prop_id, **RELET_HOUSEHOLD), owner_headers
        ),
        expected_status=201,
    )
    assert relet["unit_number"] == "101", (
        "uniqueness excludes MOVED_OUT rows, so unit 101 is re-lettable"
    )

    prop_after = validate_success(api_client.get_property(prop_id, owner_headers))
    assert prop_after["released_unit_count"] == 1
    assert prop_after["units_under_hap_count"] == 19, (
        "the move-out released one unit and re-letting moves no counter, got "
        f"{prop_after['units_under_hap_count']}"
    )
    assert_unit_invariant(prop_after)


def test_temporal_gates_reject_an_early_case_a_short_notice_and_an_unelapsed_period():
    """"the whole days from the clock date to the contract's `expiration_date` must be
    strictly greater than zero and at most 420 days", "a notice that falls short is refused
    outright with `ERR_NOTICE_WINDOW_NOT_MET`", and "the clock date must be at or after the
    first day of the month following `period_month`, and an early submission is refused with
    `ERR_PERIOD_NOT_ELAPSED`".

    Design: Corner/validations/temporal_gates_reject_an_early_case_a_short_notice_and_an_unelapsed_period
    """
    ctx = setup_portfolio()
    contract_id = ctx["contract"]["id"]
    owner_headers = ctx["owner_headers"]
    setup_certified_household(ctx["property"]["id"], owner_headers, REFERENCE_HOUSEHOLD_ONE)

    validate_error(
        api_client.create_renewal_case(
            create_renewal_case_payload(contract_id), owner_headers
        ),
        ApiErrorId.ERR_OUTSIDE_RENEWAL_WINDOW.value,
        expected_status=422,
    )
    assert validate_success(api_client.get_hap_contract(contract_id, CA_HEADERS))[
        "lifecycle_status"
    ] == "ACTIVE", "the refused case left the contract at ACTIVE"

    set_clock_date("2026-12-01")
    case = validate_success(
        api_client.create_renewal_case(
            create_renewal_case_payload(contract_id), owner_headers
        ),
        expected_status=201,
    )
    assert case["days_to_expiration_at_open"] == 395, (
        f"395 days is inside the 420-day window, got {case['days_to_expiration_at_open']}"
    )

    validate_error(
        api_client.create_tenant_notice(
            create_tenant_notice_payload(
                case["id"], notice_type="RENEWAL_INTENT", effective_date="2027-01-01"
            ),
            owner_headers,
        ),
        ApiErrorId.ERR_NOTICE_WINDOW_NOT_MET.value,
        expected_status=422,
    )
    assert validate_success(api_client.get_renewal_case(case["id"], CA_HEADERS))[
        "notice_track_status"
    ] == "NOTICES_PENDING"

    notice = validate_success(
        api_client.create_tenant_notice(
            create_tenant_notice_payload(
                case["id"], notice_type="RENEWAL_INTENT", effective_date="2027-06-01"
            ),
            owner_headers,
        ),
        expected_status=201,
    )
    assert notice["lead_days"] == 182
    assert notice["required_lead_days"] == 120
    assert validate_success(api_client.get_renewal_case(case["id"], CA_HEADERS))[
        "notice_track_status"
    ] == "RENEWAL_NOTICED"

    voucher = create_voucher(contract_id, owner_headers, "2026-12")
    assert voucher["requested_hap_cents"] == 84500

    validate_error(
        api_client.submit_voucher_submission(voucher["id"], owner_headers),
        ApiErrorId.ERR_PERIOD_NOT_ELAPSED.value,
        expected_status=422,
    )
    assert validate_success(api_client.get_voucher_submission(voucher["id"], CA_HEADERS))[
        "state"
    ] == "DRAFT"

    set_clock_date("2027-01-01")
    submitted = validate_success(
        api_client.submit_voucher_submission(voucher["id"], owner_headers)
    )
    assert submitted["state"] == "SUBMITTED", (
        "2027-01-01 is the first day of the month following 2026-12, so the period has "
        f"elapsed, got {submitted['state']}"
    )


def test_inclusive_boundaries_admit_the_exact_notice_lead_and_the_exact_ledger_balance():
    """"The notice is compliant when `lead_days` is at least `required_lead_days` — exactly
    meeting the requirement is compliant", and "`requested_hap_cents` must not exceed the
    contract's `hap_ledger_balance_cents`", so a draw equal to the balance is paid in full.

    Design: Corner/validations/inclusive_boundaries_admit_the_exact_notice_lead_and_the_exact_ledger_balance
    """
    ctx = setup_portfolio(contract_overrides={"authorized_hap_budget_cents": 84500})
    contract_id = ctx["contract"]["id"]
    owner_headers = ctx["owner_headers"]
    setup_certified_household(ctx["property"]["id"], owner_headers, REFERENCE_HOUSEHOLD_ONE)
    set_clock_date("2026-12-01")
    case = validate_success(
        api_client.create_renewal_case(
            create_renewal_case_payload(contract_id), owner_headers
        ),
        expected_status=201,
    )
    voucher = create_voucher(contract_id, owner_headers, "2026-07")
    assert voucher["requested_hap_cents"] == 84500
    validate_success(api_client.submit_voucher_submission(voucher["id"], owner_headers))

    notice = validate_success(
        api_client.create_tenant_notice(
            create_tenant_notice_payload(
                case["id"], notice_type="RENEWAL_INTENT", effective_date="2027-03-31"
            ),
            owner_headers,
        ),
        expected_status=201,
    )
    assert notice["lead_days"] == 120, (
        f"2026-12-01 to 2027-03-31 is exactly 120 whole days, got {notice['lead_days']}"
    )
    assert notice["required_lead_days"] == 120
    assert notice["status"] == "ISSUED"
    assert validate_success(api_client.get_renewal_case(case["id"], CA_HEADERS))[
        "notice_track_status"
    ] == "RENEWAL_NOTICED", "a lead exactly equal to the requirement advances the track"

    paid = validate_success(
        api_client.pay_voucher_submission(voucher["id"], CA_APPROVER_HEADERS)
    )
    assert paid["state"] == "PAID", (
        f"a draw exactly equal to the balance is not an overdraft, got {paid['state']}"
    )
    assert paid["paid_amount_cents"] == 84500

    contract_after = validate_success(api_client.get_hap_contract(contract_id, CA_HEADERS))
    assert contract_after["hap_ledger_balance_cents"] == 0
    assert contract_after["paid_hap_total_cents"] == 84500
