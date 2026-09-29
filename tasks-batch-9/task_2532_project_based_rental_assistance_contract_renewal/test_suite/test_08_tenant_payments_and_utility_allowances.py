"""Total tenant payment arithmetic, the certification spacing rule, and the utility
allowance escalation threshold and coverage interval."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    api_client,
    apply_ua_analysis,
    apply_utility_allowance_payload,
    certify_household,
    create_household,
    create_tenant_certification_payload,
    create_ua_analysis,
    current_property_version,
    current_tenant_version,
    decide_utility_allowance_payload,
    setup_approved_ua_analysis,
    setup_certified_household,
    setup_portfolio,
    setup_property_only,
    validate_error,
    validate_paginated,
    validate_success,
)

CA_HEADERS = TEST_USERS["contract_administrator_headers"]
CA_USER_ID = TEST_USERS["contract_administrator_user_id"]
HUD_HEADERS = TEST_USERS["hud_field_office_headers"]
HUD_USER_ID = TEST_USERS["hud_field_office_user_id"]

HOUSEHOLD_ADJUSTED_ARM = {
    "unit_number": "101",
    "household_name": "Alvarez",
    "annual_adjusted_income_cents": 1800000,
    "annual_gross_income_cents": 1920000,
    "family_size": 3,
}
HOUSEHOLD_GROSS_ARM = {
    "unit_number": "102",
    "household_name": "Esparza",
    "annual_adjusted_income_cents": 100000,
    "annual_gross_income_cents": 3600000,
    "family_size": 2,
}
HOUSEHOLD_MINIMUM_RENT = {
    "unit_number": "103",
    "household_name": "Boone",
    "annual_adjusted_income_cents": 60000,
    "annual_gross_income_cents": 60000,
    "family_size": 1,
}
HOUSEHOLD_HALF_CENT = {
    "unit_number": "101",
    "household_name": "Fairweather",
    "annual_adjusted_income_cents": 600174,
    "annual_gross_income_cents": 600174,
    "family_size": 2,
}


def test_a_ten_percent_utility_swing_stays_with_the_contract_administrator():
    """"`requires_field_office_approval` is true exactly when the magnitude of `change_pct`
    is strictly greater than 0.10, so a swing whose magnitude is exactly ten percent stays
    with the contract administrator".

    Design: Difficulty/boundary_precision_check/utility_allowance_change_exactly_at_the_ten_percent_threshold_stays_with_the_contract_administrator
    """
    ctx = setup_property_only(property_overrides={"project_name": "Cedar Ridge Phase I"})
    at_threshold = create_ua_analysis(
        ctx["property"]["id"],
        ctx["owner_headers"],
        method="FACTOR_BASED",
        effective_date="2026-09-01",
        utility_rate_change_pct=0.10,
    )
    assert at_threshold["baseline_allowance_cents"] == 11500
    assert at_threshold["proposed_allowance_cents"] == 12650, (
        "round_half_up(11500 * 1.10) is 12650, got "
        f"{at_threshold['proposed_allowance_cents']}"
    )
    assert at_threshold["change_pct"] == 0.10, (
        f"(12650 - 11500) / 11500 is 0.1000 to four places, got {at_threshold['change_pct']}"
    )
    assert at_threshold["requires_field_office_approval"] is False, (
        "exactly ten percent is not strictly greater than 0.10, got "
        f"{at_threshold['requires_field_office_approval']}"
    )

    validate_success(
        api_client.submit_utility_allowance_analysis(
            at_threshold["id"], ctx["owner_headers"]
        )
    )
    decided = validate_success(
        api_client.decide_utility_allowance_analysis(
            at_threshold["id"], decide_utility_allowance_payload("ACCEPT"), CA_HEADERS
        )
    )
    assert decided["state"] == "APPROVED", (
        "the contract administrator keeps authority at the boundary, got "
        f"{decided['state']}"
    )
    assert decided["approver_user_id"] == CA_USER_ID


def test_a_twelve_percent_utility_swing_must_be_decided_by_the_field_office():
    """"when `requires_field_office_approval` is true only a `HudFieldOffice` user may
    decide, and a `ContractAdministrator` attempt is refused with
    `ERR_UA_CHANGE_REQUIRES_FIELD_OFFICE`".

    Design: Difficulty/boundary_precision_check/utility_allowance_change_exactly_at_the_ten_percent_threshold_stays_with_the_contract_administrator
    """
    ctx = setup_property_only(
        property_overrides={
            "project_name": "Cedar Ridge Phase II",
            "total_units": 18,
            "assisted_unit_count": 12,
        }
    )
    over_threshold = create_ua_analysis(
        ctx["property"]["id"],
        ctx["owner_headers"],
        method="FACTOR_BASED",
        effective_date="2026-09-01",
        utility_rate_change_pct=0.12,
    )
    assert over_threshold["baseline_allowance_cents"] == 11500
    assert over_threshold["proposed_allowance_cents"] == 12880, (
        "round_half_up(11500 * 1.12) is 12880, got "
        f"{over_threshold['proposed_allowance_cents']}"
    )
    assert over_threshold["change_pct"] == 0.12
    assert over_threshold["requires_field_office_approval"] is True

    validate_success(
        api_client.submit_utility_allowance_analysis(
            over_threshold["id"], ctx["owner_headers"]
        )
    )
    validate_error(
        api_client.decide_utility_allowance_analysis(
            over_threshold["id"], decide_utility_allowance_payload("ACCEPT"), CA_HEADERS
        ),
        ApiErrorId.ERR_UA_CHANGE_REQUIRES_FIELD_OFFICE.value,
        expected_status=403,
    )
    still_submitted = validate_success(
        api_client.get_utility_allowance_analysis(over_threshold["id"], CA_HEADERS)
    )
    assert still_submitted["state"] == "SUBMITTED"
    assert still_submitted["approver_user_id"] is None

    escalated = validate_success(
        api_client.decide_utility_allowance_analysis(
            over_threshold["id"], decide_utility_allowance_payload("ACCEPT"), HUD_HEADERS
        )
    )
    assert escalated["state"] == "APPROVED"
    assert escalated["approver_user_id"] == HUD_USER_ID


def test_the_twelve_month_coverage_anniversary_is_admitted_and_moves_the_baseline():
    """"the analysis's `effective_date` must be at or after the property's
    `last_applied_ua_effective_date` advanced by twelve whole months, an inclusive boundary,
    so an effective date landing exactly on the anniversary is accepted".

    Design: Difficulty/resource_temporal_overlap/applied_utility_allowances_must_be_twelve_whole_months_apart_on_the_same_property
    """
    ctx = setup_property_only()
    prop_id = ctx["property"]["id"]
    assert ctx["property"]["last_applied_ua_effective_date"] is None

    first = setup_approved_ua_analysis(
        prop_id,
        ctx["owner_headers"],
        method="FACTOR_BASED",
        effective_date="2026-09-01",
        utility_rate_change_pct=0.09,
    )
    assert first["proposed_allowance_cents"] == 12535, (
        f"round_half_up(11500 * 1.09) is 12535, got {first['proposed_allowance_cents']}"
    )
    applied_first = apply_ua_analysis(first["id"], prop_id)
    assert applied_first["state"] == "APPLIED"
    assert applied_first["recertified_tenant_count"] == 0, (
        "the property has no households, so the cascade recertified nobody, got "
        f"{applied_first['recertified_tenant_count']}"
    )
    after_first = validate_success(api_client.get_property(prop_id, CA_HEADERS))
    assert after_first["current_utility_allowance_cents"] == 12535
    assert after_first["last_applied_ua_effective_date"] == "2026-09-01"

    second = setup_approved_ua_analysis(
        prop_id,
        ctx["owner_headers"],
        method="FACTOR_BASED",
        effective_date="2027-09-01",
        utility_rate_change_pct=0.09,
    )
    assert second["baseline_allowance_cents"] == 12535, (
        "the second analysis snapshots the moved baseline, got "
        f"{second['baseline_allowance_cents']}"
    )
    assert second["proposed_allowance_cents"] == 13663, (
        f"round_half_up(12535 * 1.09) is 13663, got {second['proposed_allowance_cents']}"
    )
    applied_second = apply_ua_analysis(second["id"], prop_id)
    assert applied_second["state"] == "APPLIED", (
        "2027-09-01 is exactly twelve whole months after 2026-09-01 and the boundary is "
        f"inclusive, got {applied_second['state']}"
    )
    after_second = validate_success(api_client.get_property(prop_id, CA_HEADERS))
    assert after_second["current_utility_allowance_cents"] == 13663
    assert after_second["last_applied_ua_effective_date"] == "2027-09-01"


def test_one_day_inside_the_coverage_window_is_refused_at_apply_time():
    """"anything earlier is refused with `ERR_UA_INTERVAL_OVERLAP` (HTTP 409)", and the
    conflict is a guard on the apply, so the analysis may sit in `APPROVED` untouched.

    Design: Difficulty/resource_temporal_overlap/applied_utility_allowances_must_be_twelve_whole_months_apart_on_the_same_property
    """
    ctx = setup_property_only()
    prop_id = ctx["property"]["id"]
    first = setup_approved_ua_analysis(
        prop_id,
        ctx["owner_headers"],
        method="FACTOR_BASED",
        effective_date="2026-09-01",
        utility_rate_change_pct=0.09,
    )
    apply_ua_analysis(first["id"], prop_id)

    early = setup_approved_ua_analysis(
        prop_id,
        ctx["owner_headers"],
        method="FACTOR_BASED",
        effective_date="2027-08-31",
        utility_rate_change_pct=0.09,
    )
    assert early["baseline_allowance_cents"] == 12535
    assert early["proposed_allowance_cents"] == 13663
    assert early["change_pct"] == 0.09
    assert early["state"] == "APPROVED", (
        "the conflict is only detected at apply time, so approval succeeded, got "
        f"{early['state']}"
    )

    version = current_property_version(prop_id)
    validate_error(
        api_client.apply_utility_allowance_analysis(
            early["id"], apply_utility_allowance_payload(version), CA_HEADERS
        ),
        ApiErrorId.ERR_UA_INTERVAL_OVERLAP.value,
        expected_status=409,
    )

    assert validate_success(
        api_client.get_utility_allowance_analysis(early["id"], CA_HEADERS)
    )["state"] == "APPROVED", "the refused apply left the analysis in APPROVED"
    unchanged = validate_success(api_client.get_property(prop_id, CA_HEADERS))
    assert unchanged["current_utility_allowance_cents"] == 12535
    assert unchanged["last_applied_ua_effective_date"] == "2026-09-01"
    assert unchanged["version"] == version, (
        f"the refused apply bumped no version, got {unchanged['version']}"
    )


def test_a_certification_exactly_thirty_days_later_is_refused_and_costs_no_version():
    """"a new certification's `effective_date` must be strictly more than 30 days after the
    `effective_date` of the household's currently `ACTIVE` certification, so a certification
    landing exactly 30 days later is refused with `ERR_CERT_INTERVAL_CONFLICT` (HTTP 409)".

    Design: Difficulty/resource_temporal_overlap/tenant_certifications_need_a_strictly_longer_than_thirty_day_gap_on_the_same_household
    """
    ctx = setup_portfolio()
    bundle = setup_certified_household(
        ctx["property"]["id"],
        ctx["owner_headers"],
        HOUSEHOLD_ADJUSTED_ARM,
        effective_date="2026-07-01",
    )
    tenant_id = bundle["household"]["id"]
    first_cert = bundle["certification"]
    assert first_cert["status"] == "ACTIVE"
    assert first_cert["utility_allowance_cents"] == 11500
    assert first_cert["contract_rent_per_unit_cents"] == 118000
    assert first_cert["ttp_cents"] == 45000, (
        "round_half_up(1800000 / 12) is 150000 and 30 percent of that is 45000, got "
        f"{first_cert['ttp_cents']}"
    )
    assert first_cert["hap_cents"] == 84500, (
        f"129500 gross rent less the 45000 payment is 84500, got {first_cert['hap_cents']}"
    )

    unconsumed_version = current_tenant_version(tenant_id)
    validate_error(
        api_client.create_tenant_certification(
            create_tenant_certification_payload(
                tenant_id,
                unconsumed_version,
                cert_type="ANNUAL",
                effective_date="2026-07-31",
            ),
            ctx["owner_headers"],
        ),
        ApiErrorId.ERR_CERT_INTERVAL_CONFLICT.value,
        expected_status=409,
    )

    assert validate_success(
        api_client.get_tenant_certification(first_cert["id"], CA_HEADERS)
    )["status"] == "ACTIVE", (
        "2026-07-01 plus thirty days is 2026-07-31 and the comparison is strict, so the "
        "incumbent certification was never superseded"
    )
    household_after = validate_success(
        api_client.get_tenant_household(tenant_id, CA_HEADERS)
    )
    assert household_after["version"] == unconsumed_version, (
        "the refused certification consumed no household version, got "
        f"{household_after['version']}"
    )
    assert household_after["current_ttp_cents"] == 45000
    assert household_after["current_hap_cents"] == 84500
    _, meta = validate_paginated(
        api_client.list_household_certifications(tenant_id, CA_HEADERS)
    )
    assert meta["total_count"] == 1, (
        f"the refused write persisted no certification, got {meta['total_count']}"
    )


def test_day_thirty_one_is_accepted_and_reuses_the_unconsumed_household_version():
    """"only day 31 onward is accepted", and creating it "flips the household's previously
    `ACTIVE` certification to the terminal `SUPERSEDED` and increments that older
    certification's `version` by 1, re-points the household's `current_ttp_cents` at the new
    `ttp_cents` and its `current_hap_cents` at the new `hap_cents`".

    Design: Difficulty/resource_temporal_overlap/tenant_certifications_need_a_strictly_longer_than_thirty_day_gap_on_the_same_household
    """
    ctx = setup_portfolio()
    bundle = setup_certified_household(
        ctx["property"]["id"],
        ctx["owner_headers"],
        HOUSEHOLD_ADJUSTED_ARM,
        effective_date="2026-07-01",
    )
    tenant_id = bundle["household"]["id"]
    first_cert = bundle["certification"]
    first_cert_version = first_cert["version"]
    unconsumed_version = current_tenant_version(tenant_id)

    validate_error(
        api_client.create_tenant_certification(
            create_tenant_certification_payload(
                tenant_id,
                unconsumed_version,
                cert_type="ANNUAL",
                effective_date="2026-07-31",
            ),
            ctx["owner_headers"],
        ),
        ApiErrorId.ERR_CERT_INTERVAL_CONFLICT.value,
        expected_status=409,
    )

    second_cert = validate_success(
        api_client.create_tenant_certification(
            create_tenant_certification_payload(
                tenant_id,
                unconsumed_version,
                cert_type="ANNUAL",
                effective_date="2026-08-01",
            ),
            ctx["owner_headers"],
        ),
        expected_status=201,
    )
    assert second_cert["status"] == "ACTIVE", (
        "day thirty-one clears the strict comparison, and the stale-version check passed "
        f"because the refusal bumped nothing, got {second_cert['status']}"
    )
    assert second_cert["cert_type"] == "ANNUAL"
    assert second_cert["ttp_cents"] == 45000, (
        "income is read from the household once per certification and the figures are "
        f"unchanged, got {second_cert['ttp_cents']}"
    )
    assert second_cert["hap_cents"] == 84500

    superseded = validate_success(
        api_client.get_tenant_certification(first_cert["id"], CA_HEADERS)
    )
    assert superseded["status"] == "SUPERSEDED"
    assert superseded["version"] == first_cert_version + 1, (
        f"the superseded row's version incremented, got {superseded['version']}"
    )

    household_after = validate_success(
        api_client.get_tenant_household(tenant_id, CA_HEADERS)
    )
    assert household_after["current_ttp_cents"] == 45000
    assert household_after["current_hap_cents"] == 84500
    assert household_after["version"] == unconsumed_version + 1, (
        "the accepted certification consumed exactly one household version, got "
        f"{household_after['version']}"
    )

    rows, meta = validate_paginated(
        api_client.list_household_certifications(tenant_id, CA_HEADERS)
    )
    assert meta["total_count"] == 2
    assert [row["effective_date"] for row in rows] == ["2026-07-01", "2026-08-01"], (
        "the certifications of a household come back ordered by effective_date ascending, "
        f"got {[row['effective_date'] for row in rows]}"
    )


def test_the_total_tenant_payment_is_a_three_way_maximum_over_two_arms_and_a_floor():
    """"The `ttp_cents` is the greatest of those two rounded products and the minimum rent of
    2,500 cents — a three-way maximum", and "`utility_reimbursement_cents` is the utility
    allowance less the total tenant payment, floored at zero".

    Design: Corner/calculations/ttp_applies_the_thirty_percent_ten_percent_and_minimum_rent_constants_as_a_three_way_max
    """
    ctx = setup_portfolio()
    prop_id = ctx["property"]["id"]
    owner_headers = ctx["owner_headers"]

    h_adj = create_household(prop_id, owner_headers, **HOUSEHOLD_ADJUSTED_ARM)
    h_gross = create_household(prop_id, owner_headers, **HOUSEHOLD_GROSS_ARM)
    h_min = create_household(prop_id, owner_headers, **HOUSEHOLD_MINIMUM_RENT)

    cert_adj = certify_household(h_adj["id"], owner_headers, "2026-07-01")
    cert_gross = certify_household(h_gross["id"], owner_headers, "2026-07-01")
    cert_min = certify_household(h_min["id"], owner_headers, "2026-07-01")

    for cert in (cert_adj, cert_gross, cert_min):
        assert cert["utility_allowance_cents"] == 11500, (
            "every certification snapshots the property's current allowance, got "
            f"{cert['utility_allowance_cents']}"
        )
        assert cert["gross_rent_cents"] == 129500, (
            "118000 contract rent plus the 11500 allowance is 129500 for all three, got "
            f"{cert['gross_rent_cents']}"
        )

    assert cert_adj["ttp_cents"] == 45000, (
        "the thirty-percent-of-adjusted arm wins: 0.30 * 150000 is 45000 against 16000 and "
        f"the 2500 floor, got {cert_adj['ttp_cents']}"
    )
    assert cert_adj["tenant_rent_cents"] == 33500
    assert cert_adj["utility_reimbursement_cents"] == 0
    assert cert_adj["hap_cents"] == 84500

    assert cert_gross["ttp_cents"] == 30000, (
        "the ten-percent-of-gross arm wins: 0.10 * 300000 is 30000 while the adjusted arm "
        f"gives only the 2500 floor, got {cert_gross['ttp_cents']}"
    )
    assert cert_gross["tenant_rent_cents"] == 18500
    assert cert_gross["utility_reimbursement_cents"] == 0
    assert cert_gross["hap_cents"] == 99500

    assert cert_min["ttp_cents"] == 2500, (
        "the minimum rent wins over 1500 and 500, got " f"{cert_min['ttp_cents']}"
    )
    assert cert_min["tenant_rent_cents"] == 0, (
        "the tenant rent is floored at zero, got " f"{cert_min['tenant_rent_cents']}"
    )
    assert cert_min["utility_reimbursement_cents"] == 9000, (
        "the mirror figure 11500 - 2500 is paid to the tenant, got "
        f"{cert_min['utility_reimbursement_cents']}"
    )
    assert cert_min["hap_cents"] == 127000

    household_min = validate_success(
        api_client.get_tenant_household(h_min["id"], CA_HEADERS)
    )
    assert household_min["current_ttp_cents"] == 2500
    assert household_min["current_hap_cents"] == 127000


def test_the_monthly_income_rounds_before_the_percentage_and_the_cent_propagates():
    """"The rounding order is pinned: each monthly income is rounded before its percentage is
    applied, and each percentage product is rounded before the three-way comparison; applying
    the percentage to the annual figure and dividing afterwards is not permitted".

    Design: Corner/calculations/ttp_rounds_the_monthly_income_before_the_percentage_not_after
    """
    ctx = setup_portfolio()
    household = create_household(
        ctx["property"]["id"], ctx["owner_headers"], **HOUSEHOLD_HALF_CENT
    )
    cert = certify_household(household["id"], ctx["owner_headers"], "2026-07-01")

    assert cert["ttp_cents"] == 15005, (
        "600174 / 12 is 50014.5, which rounds half up to 50015, and 0.30 * 50015 is 15004.5, "
        f"which rounds half up to 15005, got {cert['ttp_cents']}"
    )
    assert cert["ttp_cents"] != 15004, (
        "15004 is what deferring the division gives, since 0.30 * 50014.5 is 15004.35, and "
        "that order is not permitted"
    )
    assert cert["tenant_rent_cents"] == 3505, (
        f"15005 less the 11500 allowance is 3505, got {cert['tenant_rent_cents']}"
    )
    assert cert["utility_reimbursement_cents"] == 0
    assert cert["hap_cents"] == 114495, (
        f"129500 less 15005 is 114495, got {cert['hap_cents']}"
    )
    assert cert["gross_rent_cents"] == 129500

    household_after = validate_success(
        api_client.get_tenant_household(household["id"], CA_HEADERS)
    )
    assert household_after["current_ttp_cents"] == 15005, (
        "the single-cent difference propagates onto the household, got "
        f"{household_after['current_ttp_cents']}"
    )
    assert household_after["current_hap_cents"] == 114495
