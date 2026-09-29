"""The utility-allowance apply cascade, the three optimistic-concurrency parents, and the
immediate visibility of everything the cascade touches."""
from test_helpers import (
    ApiErrorId,
    REFERENCE_HOUSEHOLD_ONE,
    TEST_USERS,
    api_client,
    apply_ua_analysis,
    apply_utility_allowance_payload,
    certify_household,
    create_household,
    create_tenant_certification_payload,
    create_voucher,
    create_voucher_submission_payload,
    current_contract_version,
    current_property_version,
    current_tenant_version,
    set_clock_date,
    setup_approved_ua_analysis,
    setup_portfolio,
    setup_reference_households,
    setup_submitted_voucher,
    validate_error,
    validate_paginated,
    validate_success,
)

CA_HEADERS = TEST_USERS["contract_administrator_headers"]


def test_the_apply_cascade_recomputes_both_households_and_the_next_voucher():
    """"Caused by that, every household of the property whose `status` is `ACTIVE`,
    `OPT_OUT_NOTICED`, or `EV_ISSUED`, processed in `created_at` ascending order, has its
    `ACTIVE` certification flipped to `SUPERSEDED` and a replacement certification created with
    `cert_type` `UA_ADJUSTMENT` and `effective_date` equal to the analysis's effective date,
    whose `ttp_cents`, `tenant_rent_cents`, `utility_reimbursement_cents`, `gross_rent_cents`,
    and `hap_cents` are all recomputed against the new allowance; the household's
    `current_ttp_cents` and `current_hap_cents` are re-pointed and its `version` increments by 1;
    and `recertified_tenant_count` is set to the number of certifications created."

    Design: Difficulty/transitive_cascade/utility_allowance_apply_propagates_through_property_certifications_households_into_the_monthly_voucher
    """
    ctx = setup_portfolio()
    prop_id = ctx["property"]["id"]
    contract_id = ctx["contract"]["id"]
    owner_headers = ctx["owner_headers"]
    households = setup_reference_households(prop_id, owner_headers, "2026-07-01")
    one = households["household_one"]
    two = households["household_two"]
    assert households["certification_one"]["utility_allowance_cents"] == 11500
    assert households["certification_one"]["hap_cents"] == 84500
    assert households["certification_two"]["hap_cents"] == 127000

    analysis = setup_approved_ua_analysis(prop_id, owner_headers)
    assert analysis["baseline_allowance_cents"] == 11500
    assert analysis["proposed_allowance_cents"] == 12535, (
        "round_half_up(11500 * 1.09) is 12535, got "
        f"{analysis['proposed_allowance_cents']}"
    )
    assert analysis["change_pct"] == 0.09
    assert analysis["requires_field_office_approval"] is False
    assert analysis["state"] == "APPROVED"
    assert analysis["recertified_tenant_count"] == 0

    applied = apply_ua_analysis(analysis["id"], prop_id)
    assert applied["state"] == "APPLIED"
    assert applied["recertified_tenant_count"] == 2, (
        "one certification was created per eligible household, got "
        f"{applied['recertified_tenant_count']}"
    )

    prop = validate_success(api_client.get_property(prop_id, CA_HEADERS))
    assert prop["current_utility_allowance_cents"] == 12535
    assert prop["last_applied_ua_effective_date"] == "2026-09-01"

    for predecessor in ("certification_one", "certification_two"):
        stale = validate_success(
            api_client.get_tenant_certification(
                households[predecessor]["id"], owner_headers
            )
        )
        assert stale["status"] == "SUPERSEDED", (
            f"{predecessor} is demoted by the cascade, got {stale['status']}"
        )

    all_one, meta_one = validate_paginated(
        api_client.list_household_certifications(one["id"], owner_headers)
    )
    assert meta_one["total_count"] == 2, (
        f"the predecessor is kept alongside the replacement, got {meta_one['total_count']}"
    )
    assert len(all_one) == 2
    adjusted_one = validate_paginated(
        api_client.list_household_certifications(
            one["id"], owner_headers, cert_type="UA_ADJUSTMENT"
        )
    )[0][0]
    assert adjusted_one["effective_date"] == "2026-09-01"
    assert adjusted_one["status"] == "ACTIVE"
    assert adjusted_one["utility_allowance_cents"] == 12535
    assert adjusted_one["gross_rent_cents"] == 130535, (
        f"118000 plus 12535 is 130535, got {adjusted_one['gross_rent_cents']}"
    )
    assert adjusted_one["ttp_cents"] == 45000, (
        "the allowance does not touch the income-based payment, got "
        f"{adjusted_one['ttp_cents']}"
    )
    assert adjusted_one["tenant_rent_cents"] == 32465, (
        f"45000 less 12535 is 32465, got {adjusted_one['tenant_rent_cents']}"
    )
    assert adjusted_one["utility_reimbursement_cents"] == 0
    assert adjusted_one["hap_cents"] == 85535, (
        f"130535 less 45000 is 85535, got {adjusted_one['hap_cents']}"
    )

    adjusted_two = validate_paginated(
        api_client.list_household_certifications(
            two["id"], owner_headers, cert_type="UA_ADJUSTMENT"
        )
    )[0][0]
    assert adjusted_two["ttp_cents"] == 2500
    assert adjusted_two["tenant_rent_cents"] == 0, (
        "the minimum-rent household owes nothing once the allowance exceeds its payment, got "
        f"{adjusted_two['tenant_rent_cents']}"
    )
    assert adjusted_two["utility_reimbursement_cents"] == 10035, (
        f"12535 less 2500 is 10035, got {adjusted_two['utility_reimbursement_cents']}"
    )
    assert adjusted_two["hap_cents"] == 128035

    household_one = validate_success(api_client.get_tenant_household(one["id"], CA_HEADERS))
    household_two = validate_success(api_client.get_tenant_household(two["id"], CA_HEADERS))
    assert household_one["current_ttp_cents"] == 45000
    assert household_one["current_hap_cents"] == 85535
    assert household_two["current_ttp_cents"] == 2500
    assert household_two["current_hap_cents"] == 128035

    set_clock_date("2026-10-01")
    september = create_voucher(contract_id, owner_headers, "2026-09")
    assert september["included_certification_count"] == 2
    assert september["requested_hap_cents"] == 213570, (
        "85535 plus 128035 is 213570 — the voucher never reads the analysis, only the "
        f"certifications the analysis created, got {september['requested_hap_cents']}"
    )
    assert september["requested_hap_cents"] - 211500 == 2070, (
        "the whole 1035-cent allowance rise reaches HUD twice over"
    )


def test_the_apply_cascade_reaches_draft_vouchers_but_not_submitted_ones():
    """"Caused by that, every voucher submission of the property's contract still in state
    `DRAFT` has its `requested_hap_cents` and `included_certification_count` recomputed against
    the new certifications, so a draft month never bills a superseded allowance."

    Design: Difficulty/transitive_cascade/utility_allowance_apply_propagates_through_property_certifications_households_into_the_monthly_voucher
    """
    ctx = setup_portfolio()
    prop_id = ctx["property"]["id"]
    contract_id = ctx["contract"]["id"]
    owner_headers = ctx["owner_headers"]
    setup_reference_households(prop_id, owner_headers, "2026-07-01")

    submitted = setup_submitted_voucher(contract_id, owner_headers, "2026-07")
    assert submitted["state"] == "SUBMITTED"
    assert submitted["requested_hap_cents"] == 211500

    draft = create_voucher(contract_id, owner_headers, "2026-09")
    assert draft["state"] == "DRAFT"
    assert draft["requested_hap_cents"] == 211500, (
        "before the apply the September draft still bills the 11500 allowance, got "
        f"{draft['requested_hap_cents']}"
    )

    analysis = setup_approved_ua_analysis(prop_id, owner_headers)
    applied = apply_ua_analysis(analysis["id"], prop_id)
    assert applied["state"] == "APPLIED"
    assert applied["applied_on_date"] == "2026-08-01", (
        f"the apply stamps the clock date, got {applied['applied_on_date']}"
    )

    redrawn = validate_success(
        api_client.get_voucher_submission(draft["id"], owner_headers)
    )
    assert redrawn["state"] == "DRAFT"
    assert redrawn["requested_hap_cents"] == 213570, (
        "the fourth hop reaches the draft month without any client action, got "
        f"{redrawn['requested_hap_cents']}"
    )
    assert redrawn["included_certification_count"] == 2

    frozen = validate_success(
        api_client.get_voucher_submission(submitted["id"], owner_headers)
    )
    assert frozen["state"] == "SUBMITTED"
    assert frozen["requested_hap_cents"] == 211500, (
        "a voucher that has left DRAFT is outside the cascade, got "
        f"{frozen['requested_hap_cents']}"
    )


def test_all_three_declared_occ_rules_reject_a_stale_parent_and_bump_it_on_success():
    """"Creating a tenant certification requires `expected_tenant_version` carrying the client's
    last observed `version` of the target `TenantHousehold`." "Creating a monthly voucher
    submission requires `expected_contract_version` carrying the client's last observed `version`
    of the target `HapContract`." "Applying an approved utility allowance analysis requires
    `expected_property_version` carrying the client's last observed `version` of the analysis's
    `Property`."

    Design: Corner/cross_cutting_complexity_layers/all_three_declared_occ_rules_reject_a_stale_parent_version_and_bump_it_on_success
    """
    ctx = setup_portfolio()
    prop_id = ctx["property"]["id"]
    contract_id = ctx["contract"]["id"]
    owner_headers = ctx["owner_headers"]
    household = create_household(prop_id, owner_headers, **REFERENCE_HOUSEHOLD_ONE)
    analysis = setup_approved_ua_analysis(prop_id, owner_headers)
    assert analysis["proposed_allowance_cents"] == 12535
    assert analysis["requires_field_office_approval"] is False
    assert analysis["state"] == "APPROVED"

    tenant_version = current_tenant_version(household["id"])
    validate_error(
        api_client.create_tenant_certification(
            create_tenant_certification_payload(
                household["id"],
                tenant_version - 1,
                cert_type="INITIAL",
                effective_date="2026-07-01",
            ),
            owner_headers,
        ),
        ApiErrorId.ERR_STALE_TENANT_VERSION.value,
        expected_status=412,
    )
    assert validate_paginated(
        api_client.list_household_certifications(household["id"], owner_headers)
    )[1]["total_count"] == 0, "a refused certification write creates no row"

    certification = certify_household(
        household["id"],
        owner_headers,
        "2026-07-01",
        expected_tenant_version=tenant_version,
    )
    assert certification["hap_cents"] == 84500
    assert current_tenant_version(household["id"]) == tenant_version + 1, (
        "the child write bumped its parent exactly once"
    )

    contract_version = current_contract_version(contract_id)
    validate_error(
        api_client.create_voucher_submission(
            create_voucher_submission_payload(
                contract_id, contract_version - 1, period_month="2026-07"
            ),
            owner_headers,
        ),
        ApiErrorId.ERR_STALE_CONTRACT_VERSION.value,
        expected_status=412,
    )
    assert validate_paginated(
        api_client.list_contract_voucher_submissions(contract_id, CA_HEADERS)
    )[1]["total_count"] == 0, "no voucher row exists for 2026-07 after the refusal"

    voucher = create_voucher(
        contract_id,
        owner_headers,
        "2026-07",
        expected_contract_version=contract_version,
    )
    assert voucher["requested_hap_cents"] == 84500
    assert current_contract_version(contract_id) == contract_version + 1

    property_version = current_property_version(prop_id)
    before = validate_success(api_client.get_property(prop_id, CA_HEADERS))
    assert before["current_utility_allowance_cents"] == 11500
    validate_error(
        api_client.apply_utility_allowance_analysis(
            analysis["id"],
            apply_utility_allowance_payload(property_version - 1),
            CA_HEADERS,
        ),
        ApiErrorId.ERR_STALE_PROPERTY_VERSION.value,
        expected_status=412,
    )
    refused = validate_success(
        api_client.get_utility_allowance_analysis(analysis["id"], CA_HEADERS)
    )
    assert refused["state"] == "APPROVED", (
        f"a refusal advances nothing, got {refused['state']}"
    )
    assert refused["applied_on_date"] is None

    applied = apply_ua_analysis(
        analysis["id"], prop_id, expected_property_version=property_version
    )
    assert applied["state"] == "APPLIED"
    assert applied["recertified_tenant_count"] == 1

    after = validate_success(api_client.get_property(prop_id, CA_HEADERS))
    assert after["current_utility_allowance_cents"] == 12535
    assert after["version"] == property_version + 1, (
        "exactly one version step for the whole cascade, got "
        f"{after['version']} against {property_version}"
    )


def test_the_apply_cascade_is_fully_visible_to_the_next_read():
    """"The analysis moves `APPROVED` → `APPLIED` and stamps `applied_on_date` with the clock
    date. Caused by that, the property's `current_utility_allowance_cents` takes
    `proposed_allowance_cents`, its `last_applied_ua_effective_date` takes the analysis's
    `effective_date`, and its `version` increments by 1."

    Design: Corner/consistency_model/the_apply_cascade_is_fully_visible_to_the_next_read_with_no_settling_delay
    """
    ctx = setup_portfolio()
    prop_id = ctx["property"]["id"]
    contract_id = ctx["contract"]["id"]
    owner_headers = ctx["owner_headers"]
    household = create_household(prop_id, owner_headers, **REFERENCE_HOUSEHOLD_ONE)
    certification = certify_household(household["id"], owner_headers, "2026-07-01")
    assert certification["utility_allowance_cents"] == 11500
    assert certification["hap_cents"] == 84500

    analysis = setup_approved_ua_analysis(prop_id, owner_headers)
    assert analysis["baseline_allowance_cents"] == 11500
    assert analysis["proposed_allowance_cents"] == 12535
    before = validate_success(api_client.get_property(prop_id, CA_HEADERS))
    assert before["current_utility_allowance_cents"] == 11500

    applied = apply_ua_analysis(
        analysis["id"], prop_id, expected_property_version=before["version"]
    )
    assert applied["state"] == "APPLIED"
    assert applied["applied_on_date"] == "2026-08-01", (
        "the cascade result is in the apply response itself, got "
        f"{applied['applied_on_date']}"
    )
    assert applied["recertified_tenant_count"] == 1

    after = validate_success(api_client.get_property(prop_id, CA_HEADERS))
    assert after["current_utility_allowance_cents"] == 12535, (
        "the very next read carries the new allowance with no retry, got "
        f"{after['current_utility_allowance_cents']}"
    )
    assert after["last_applied_ua_effective_date"] == "2026-09-01"
    assert after["version"] == before["version"] + 1

    rows, meta = validate_paginated(
        api_client.list_household_certifications(
            household["id"], owner_headers, cert_type="UA_ADJUSTMENT"
        )
    )
    assert meta["total_count"] == 1
    adjustment = rows[0]
    assert adjustment["effective_date"] == "2026-09-01"
    assert adjustment["status"] == "ACTIVE"
    assert adjustment["utility_allowance_cents"] == 12535
    assert adjustment["ttp_cents"] == 45000
    assert adjustment["tenant_rent_cents"] == 32465, (
        f"45000 less 12535 is 32465, got {adjustment['tenant_rent_cents']}"
    )
    assert adjustment["hap_cents"] == 85535, (
        f"118000 plus 12535 less 45000 is 85535, got {adjustment['hap_cents']}"
    )

    predecessor = validate_success(
        api_client.get_tenant_certification(certification["id"], owner_headers)
    )
    assert predecessor["status"] == "SUPERSEDED", (
        "the predecessor is already demoted in the same window, got "
        f"{predecessor['status']}"
    )

    september = create_voucher(contract_id, owner_headers, "2026-09")
    assert september["included_certification_count"] == 1
    assert september["requested_hap_cents"] == 85535, (
        "a voucher created immediately afterwards already uses the recomputed "
        f"certification rather than the pre-apply 84500, got "
        f"{september['requested_hap_cents']}"
    )
