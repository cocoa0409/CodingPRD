"""Entity contracts: creation envelopes, defaults, derived fields and reference resolution."""
from test_helpers import (
    ApiErrorId,
    api_client,
    assert_common_fields,
    assert_hap_contract,
    assert_owner,
    assert_pagination_meta,
    assert_property,
    assert_tenant_certification,
    assert_tenant_household,
    create_comparable_payload,
    create_hap_contract_payload,
    create_owner_payload,
    create_owner_with_headers,
    create_property,
    create_property_payload,
    create_renewal_case_payload,
    create_study_payload,
    create_tenant_certification_payload,
    create_tenant_household_payload,
    create_voucher_submission_payload,
    create_ua_analysis,
    challenge_study_payload,
    is_iso8601_timestamp,
    is_valid_uuid,
    setup_portfolio,
    setup_submitted_study,
    validate_error,
    validate_paginated,
    validate_success,
    TEST_USERS,
    REFERENCE_HOUSEHOLD_ONE,
    REFERENCE_HOUSEHOLD_TWO,
    create_household,
    make_owner_agent_headers,
    setup_adjustment_elected,
)

CA_HEADERS = TEST_USERS["contract_administrator_headers"]

UNKNOWN_IDS = {
    "owner": "00000000-0000-4000-8000-000000000001",
    "property": "00000000-0000-4000-8000-000000000002",
    "contract": "00000000-0000-4000-8000-000000000003",
    "case": "00000000-0000-4000-8000-000000000004",
    "study": "00000000-0000-4000-8000-000000000005",
    "analysis": "00000000-0000-4000-8000-000000000006",
    "tenant": "00000000-0000-4000-8000-000000000007",
    "certification": "00000000-0000-4000-8000-000000000008",
    "notice": "00000000-0000-4000-8000-000000000009",
    "determination": "00000000-0000-4000-8000-00000000000a",
    "enhanced_voucher": "00000000-0000-4000-8000-00000000000b",
    "voucher": "00000000-0000-4000-8000-00000000000c",
    "claim": "00000000-0000-4000-8000-00000000000d",
}


def test_owner_registration_returns_every_field_in_the_success_envelope():
    """A newly registered owner starts with `portfolio_property_count` of 0 and a
    `compliance_flag` of `OK`, wrapped in the standard success envelope.

    Design: Corner/entities/owner_creation_returns_every_declared_field_in_the_success_envelope
    """
    payload = create_owner_payload(
        legal_name="Cedar Ridge Housing Partners LP",
        tin="27-3310011",
        contact_email="agent@cedarridge.example",
    )
    response = api_client.create_owner(payload, CA_HEADERS)
    owner = validate_success(response, expected_status=201)

    assert_owner(owner)
    assert owner["legal_name"] == "Cedar Ridge Housing Partners LP"
    assert owner["tin"] == "27-3310011"
    assert owner["contact_email"] == "agent@cedarridge.example"
    assert owner["portfolio_property_count"] == 0, (
        f"a new owner opens with no properties, got {owner['portfolio_property_count']}"
    )
    assert owner["compliance_flag"] == "OK", (
        f"a new owner opens with compliance_flag OK, got {owner['compliance_flag']}"
    )
    assert owner["version"] == 1, f"a created resource is version 1, got {owner['version']}"

    body = response.json()
    assert body["response_type"] == "object", (
        f"a single resource is response_type object, got {body['response_type']}"
    )
    assert body["meta"]["api_request_id"].startswith("req_"), (
        f"api_request_id must start with req_, got {body['meta']['api_request_id']}"
    )
    assert is_iso8601_timestamp(body["meta"]["api_request_timestamp"])
    for pagination_field in ("limit", "offset", "total_count", "has_more"):
        assert pagination_field not in body["meta"], (
            f"single-resource responses omit {pagination_field}"
        )


def test_property_read_returns_the_stored_row_and_the_owner_counter_moved():
    """Registering a property "also increments the owning owner's
    `portfolio_property_count` by 1 and that owner's `version` by 1", and a read of the
    property returns exactly what was stored.

    Design: Corner/entities/property_retrieval_returns_the_stored_row_and_bumps_the_owner_portfolio_counter
    """
    owner, owner_headers = create_owner_with_headers()
    prop = create_property(owner["id"], owner_headers)

    fetched = validate_success(api_client.get_property(prop["id"], owner_headers))
    assert_property(fetched)
    assert fetched["owner_id"] == owner["id"]
    assert fetched["state_code"] == "IL"
    assert fetched["total_units"] == 24
    assert fetched["assisted_unit_count"] == 20
    assert fetched["published_fmr_cents"] == 126000

    owner_after = validate_success(api_client.get_owner(owner["id"], owner_headers))
    assert owner_after["portfolio_property_count"] == 1, (
        "one property means portfolio_property_count 1, got "
        f"{owner_after['portfolio_property_count']}"
    )
    assert owner_after["version"] == owner["version"] + 1, (
        "registering a property increments the owner's version by 1, got "
        f"{owner_after['version']} from {owner['version']}"
    )


def test_utility_allowance_analysis_listing_paginates_with_total_count_and_has_more():
    """"`total_count` is the number of rows matching the filter before the window is
    applied, and `has_more` is true exactly when rows remain beyond the current window";
    an omitted `limit` defaults to 10 and an omitted `offset` to 0.

    Design: Corner/entities/utility_allowance_analysis_listing_paginates_with_total_count_and_has_more
    """
    ctx = setup_portfolio()
    prop_id = ctx["property"]["id"]
    owner_headers = ctx["owner_headers"]

    first = create_ua_analysis(
        prop_id, owner_headers, effective_date="2026-09-01", utility_rate_change_pct=0.09
    )
    second = create_ua_analysis(
        prop_id, owner_headers, effective_date="2026-10-01", utility_rate_change_pct=0.05
    )
    third = create_ua_analysis(
        prop_id,
        owner_headers,
        method="ENGINEERING_BASED",
        effective_date="2026-11-01",
        engineering_estimate_cents=12000,
    )

    page1_response = api_client.list_property_utility_allowance_analyses(
        prop_id, CA_HEADERS, limit=2, offset=0
    )
    page1, meta1 = validate_paginated(page1_response)
    assert_pagination_meta(meta1, limit=2, offset=0, total_count=3, has_more=True)
    assert len(page1) == 2, f"limit 2 returns two rows, got {len(page1)}"
    assert [row["id"] for row in page1] == [first["id"], second["id"]], (
        "list results are sorted by created_at ascending"
    )
    assert page1_response.json()["response_type"] == "array"

    page2, meta2 = validate_paginated(
        api_client.list_property_utility_allowance_analyses(
            prop_id, CA_HEADERS, limit=2, offset=2
        )
    )
    assert_pagination_meta(meta2, limit=2, offset=2, total_count=3, has_more=False)
    assert [row["id"] for row in page2] == [third["id"]]

    all_rows, meta_default = validate_paginated(
        api_client.list_property_utility_allowance_analyses(prop_id, CA_HEADERS, state="DRAFT")
    )
    assert_pagination_meta(meta_default, limit=10, offset=0, total_count=3, has_more=False)
    assert len(all_rows) == 3, f"all three DRAFT analyses come back, got {len(all_rows)}"


def test_unknown_path_ids_report_the_entity_specific_not_found_code():
    """"Path identifiers are resolved left to right, and the first unresolvable segment
    determines the error. Each resource kind has its own dedicated not-found code".

    Design: Corner/entities/unknown_path_ids_report_the_entity_specific_not_found_code
    """
    probes = [
        (api_client.get_owner(UNKNOWN_IDS["owner"], CA_HEADERS), ApiErrorId.ERR_OWNER_NOT_FOUND),
        (
            api_client.get_property(UNKNOWN_IDS["property"], CA_HEADERS),
            ApiErrorId.ERR_PROPERTY_NOT_FOUND,
        ),
        (
            api_client.get_hap_contract(UNKNOWN_IDS["contract"], CA_HEADERS),
            ApiErrorId.ERR_CONTRACT_NOT_FOUND,
        ),
        (
            api_client.get_renewal_case(UNKNOWN_IDS["case"], CA_HEADERS),
            ApiErrorId.ERR_RENEWAL_CASE_NOT_FOUND,
        ),
        (
            api_client.get_study(UNKNOWN_IDS["study"], CA_HEADERS),
            ApiErrorId.ERR_STUDY_NOT_FOUND,
        ),
        (
            api_client.get_utility_allowance_analysis(UNKNOWN_IDS["analysis"], CA_HEADERS),
            ApiErrorId.ERR_UA_ANALYSIS_NOT_FOUND,
        ),
        (
            api_client.get_tenant_household(UNKNOWN_IDS["tenant"], CA_HEADERS),
            ApiErrorId.ERR_TENANT_NOT_FOUND,
        ),
        (
            api_client.get_tenant_certification(UNKNOWN_IDS["certification"], CA_HEADERS),
            ApiErrorId.ERR_CERTIFICATION_NOT_FOUND,
        ),
        (
            api_client.get_tenant_notice(UNKNOWN_IDS["notice"], CA_HEADERS),
            ApiErrorId.ERR_NOTICE_NOT_FOUND,
        ),
        (
            api_client.get_restructuring_determination(
                UNKNOWN_IDS["determination"], CA_HEADERS
            ),
            ApiErrorId.ERR_DETERMINATION_NOT_FOUND,
        ),
        (
            api_client.get_enhanced_voucher(UNKNOWN_IDS["enhanced_voucher"], CA_HEADERS),
            ApiErrorId.ERR_ENHANCED_VOUCHER_NOT_FOUND,
        ),
        (
            api_client.get_voucher_submission(UNKNOWN_IDS["voucher"], CA_HEADERS),
            ApiErrorId.ERR_VOUCHER_SUBMISSION_NOT_FOUND,
        ),
        (
            api_client.get_special_claim(UNKNOWN_IDS["claim"], CA_HEADERS),
            ApiErrorId.ERR_CLAIM_NOT_FOUND,
        ),
    ]
    for response, expected in probes:
        error = validate_error(response, expected.value, expected_status=404)
        assert "message" in error, f"{expected.value} body must carry data.message"
        assert response.json()["response_type"] == "error"


def test_body_foreign_keys_are_resolved_before_any_business_rule_runs():
    """"Every foreign key supplied in a request body must resolve before any business rule
    is evaluated", and the body-reference check is ordered ahead of the household version
    match, so an unknown `tenant_id` reports the 404 and not the stale-version 412.

    Design: Corner/entities/body_foreign_keys_are_resolved_before_any_business_rule_runs
    """
    ctx = setup_adjustment_elected()
    owner_headers = ctx["owner_headers"]
    bundle = setup_submitted_study(
        ctx["case"]["id"],
        owner_headers,
        comparables=[
            {
                "address_label": "88 Alder Court",
                "raw_rent_cents": 125000,
                "adjustment_total_cents": 4650,
                "utility_adjustment_cents": 1500,
                "weight": 3,
            }
        ],
    )

    # The ownership test of the rejection ladder is ordered ahead of body-reference
    # existence, so this probe acts as the ghost owner itself: `X-User-ID` equals the
    # unresolvable `owner_id`, leaving the body-reference check as the first rule the
    # request can break.
    ghost_owner_id = "00000000-0000-4000-8000-0000000000f1"
    validate_error(
        api_client.create_property(
            create_property_payload(
                ghost_owner_id,
                project_name="Ghost Owner Apartments",
                total_units=10,
                assisted_unit_count=8,
            ),
            make_owner_agent_headers(ghost_owner_id),
        ),
        ApiErrorId.ERR_OWNER_NOT_FOUND.value,
        expected_status=404,
    )
    validate_error(
        api_client.create_hap_contract(
            create_hap_contract_payload("00000000-0000-4000-8000-0000000000f2"), CA_HEADERS
        ),
        ApiErrorId.ERR_PROPERTY_NOT_FOUND.value,
        expected_status=404,
    )
    validate_error(
        api_client.create_renewal_case(
            create_renewal_case_payload("00000000-0000-4000-8000-0000000000f3"), owner_headers
        ),
        ApiErrorId.ERR_CONTRACT_NOT_FOUND.value,
        expected_status=404,
    )
    validate_error(
        api_client.create_study(
            create_study_payload("00000000-0000-4000-8000-0000000000f4"), owner_headers
        ),
        ApiErrorId.ERR_RENEWAL_CASE_NOT_FOUND.value,
        expected_status=404,
    )
    validate_error(
        api_client.create_study(
            create_study_payload(
                ctx["case"]["id"], supersedes_study_id="00000000-0000-4000-8000-0000000000f5"
            ),
            owner_headers,
        ),
        ApiErrorId.ERR_STUDY_NOT_FOUND.value,
        expected_status=404,
    )
    validate_error(
        api_client.create_comparable(
            create_comparable_payload(
                "00000000-0000-4000-8000-0000000000f6",
                address_label="Nowhere",
                raw_rent_cents=100000,
                adjustment_total_cents=0,
                utility_adjustment_cents=0,
                weight=1,
            ),
            owner_headers,
        ),
        ApiErrorId.ERR_STUDY_NOT_FOUND.value,
        expected_status=404,
    )
    validate_error(
        api_client.create_tenant_certification(
            create_tenant_certification_payload(
                "00000000-0000-4000-8000-0000000000f7", 1, effective_date="2026-07-01"
            ),
            owner_headers,
        ),
        ApiErrorId.ERR_TENANT_NOT_FOUND.value,
        expected_status=404,
    )
    validate_error(
        api_client.challenge_study(
            bundle["study"]["id"],
            challenge_study_payload(
                "Comparable 1 is not comparable", ["00000000-0000-4000-8000-0000000000f8"]
            ),
            CA_HEADERS,
        ),
        ApiErrorId.ERR_COMPARABLE_NOT_FOUND.value,
        expected_status=404,
    )

    study_after = validate_success(api_client.get_study(bundle["study"]["id"], CA_HEADERS))
    assert study_after["state"] == "SUBMITTED", (
        f"a refused challenge fires no side effect, got state {study_after['state']}"
    )
    assert study_after["challenge_round"] == 0, (
        f"a refused challenge strikes nothing, got round {study_after['challenge_round']}"
    )


def test_a_required_body_field_supplied_as_null_is_rejected_as_an_invalid_request():
    """The request-shape check demands "Required body fields present, types correct, enum
    members legal, constrained integers non-negative", so a null `assisted_unit_count` on
    a property registration is `ERR_INVALID_REQUEST`.

    Design: Corner/entities/a_required_body_field_supplied_as_null_is_rejected_as_an_invalid_request
    """
    owner, owner_headers = create_owner_with_headers()
    payload = create_property_payload(owner["id"])
    payload["assisted_unit_count"] = None

    validate_error(
        api_client.create_property(payload, owner_headers),
        ApiErrorId.ERR_INVALID_REQUEST.value,
        expected_status=400,
    )

    owner_after = validate_success(api_client.get_owner(owner["id"], owner_headers))
    assert owner_after["portfolio_property_count"] == 0, (
        "a rejected registration creates no property, so the counter stays at 0, got "
        f"{owner_after['portfolio_property_count']}"
    )
    rows, meta = validate_paginated(
        api_client.list_owner_properties(owner["id"], owner_headers)
    )
    assert meta["total_count"] == 0 and rows == []


def test_omitted_optional_input_and_derived_openings_take_their_declared_defaults():
    """A property payload carries "an optional `has_fha_insured_mortgage` flag that
    defaults to false", and "At creation the property's `current_utility_allowance_cents`
    equals `baseline_utility_allowance_cents`, its `units_under_hap_count` equals
    `assisted_unit_count`, its `enhanced_voucher_unit_count` and `released_unit_count` are
    both 0, and its `last_applied_ua_effective_date` is null".

    Design: Corner/entities/omitted_optional_input_and_all_derived_openings_take_their_declared_defaults
    """
    owner, owner_headers = create_owner_with_headers()
    payload = create_property_payload(owner["id"])
    payload.pop("has_fha_insured_mortgage")

    prop = validate_success(
        api_client.create_property(payload, owner_headers), expected_status=201
    )
    assert_property(prop)
    assert prop["has_fha_insured_mortgage"] is False, (
        "an omitted has_fha_insured_mortgage defaults to false, got "
        f"{prop['has_fha_insured_mortgage']}"
    )
    assert prop["current_utility_allowance_cents"] == 11500
    assert prop["units_under_hap_count"] == 20
    assert prop["enhanced_voucher_unit_count"] == 0
    assert prop["released_unit_count"] == 0
    assert prop["last_applied_ua_effective_date"] is None

    contract = validate_success(
        api_client.create_hap_contract(
            create_hap_contract_payload(prop["id"]), CA_HEADERS
        ),
        expected_status=201,
    )
    assert_hap_contract(contract)
    assert contract["lifecycle_status"] == "ACTIVE"
    assert contract["paid_hap_total_cents"] == 0
    assert contract["paid_claims_total_cents"] == 0
    assert contract["hap_ledger_balance_cents"] == 30000000, (
        "a new contract's ledger equals the full authorization, got "
        f"{contract['hap_ledger_balance_cents']}"
    )
    assert contract["renewed_rent_per_unit_cents"] is None
    assert contract["renewed_expiration_date"] is None
    assert contract["renewed_option"] is None


def test_certification_money_fields_are_computed_from_the_snapshots():
    """"The `ttp_cents` is the greatest of those two rounded products and the minimum rent
    of 2,500 cents — a three-way maximum", and from it the tenant rent, the mirror utility
    reimbursement and the HAP term all follow.

    Design: Corner/entities/certification_money_fields_are_computed_from_the_snapshots_not_from_the_request
    """
    ctx = setup_portfolio()
    prop_id = ctx["property"]["id"]
    owner_headers = ctx["owner_headers"]
    first = create_household(prop_id, owner_headers, **REFERENCE_HOUSEHOLD_ONE)
    second = create_household(prop_id, owner_headers, **REFERENCE_HOUSEHOLD_TWO)

    cert_one = validate_success(
        api_client.create_tenant_certification(
            create_tenant_certification_payload(
                first["id"], first["version"], effective_date="2026-07-01"
            ),
            owner_headers,
        ),
        expected_status=201,
    )
    assert_tenant_certification(cert_one)
    assert cert_one["utility_allowance_cents"] == 11500
    assert cert_one["contract_rent_per_unit_cents"] == 118000
    assert cert_one["gross_rent_cents"] == 129500
    assert cert_one["ttp_cents"] == 45000
    assert cert_one["tenant_rent_cents"] == 33500
    assert cert_one["utility_reimbursement_cents"] == 0
    assert cert_one["hap_cents"] == 84500
    assert cert_one["status"] == "ACTIVE"

    cert_two = validate_success(
        api_client.create_tenant_certification(
            create_tenant_certification_payload(
                second["id"], second["version"], effective_date="2026-07-01"
            ),
            owner_headers,
        ),
        expected_status=201,
    )
    assert cert_two["ttp_cents"] == 2500, (
        f"the minimum rent floor applies, got {cert_two['ttp_cents']}"
    )
    assert cert_two["tenant_rent_cents"] == 0
    assert cert_two["utility_reimbursement_cents"] == 9000, (
        "the allowance exceeds the tenant payment, so the mirror figure is paid to the "
        f"tenant, got {cert_two['utility_reimbursement_cents']}"
    )
    assert cert_two["hap_cents"] == 127000

    household = validate_success(api_client.get_tenant_household(first["id"], owner_headers))
    assert household["current_ttp_cents"] == 45000
    assert household["current_hap_cents"] == 84500


def test_system_fields_are_server_minted_and_version_advances_on_a_sibling_write():
    """"The `version` of a freshly created resource is 1; every subsequent mutation of that
    resource increments its `version` by exactly one and refreshes its `updated_at`" — and
    that includes a mutation caused by a sibling write, since creating a certification
    "increments the household's `version` by 1".

    Design: Corner/entities/system_fields_are_server_minted_and_version_advances_on_every_write
    """
    ctx = setup_portfolio()
    household = validate_success(
        api_client.create_tenant_household(
            create_tenant_household_payload(ctx["property"]["id"], **REFERENCE_HOUSEHOLD_ONE),
            ctx["owner_headers"],
        ),
        expected_status=201,
    )
    assert_tenant_household(household)
    assert is_valid_uuid(household["id"]) and "_" not in household["id"], (
        f"id is a bare UUID with no type prefix, got {household['id']}"
    )
    assert is_iso8601_timestamp(household["created_at"])
    assert household["version"] == 1
    assert household["status"] == "ACTIVE"
    assert household["move_out_date"] is None
    assert household["ev_eligible"] is False

    cert = validate_success(
        api_client.create_tenant_certification(
            create_tenant_certification_payload(
                household["id"], household["version"], effective_date="2026-07-01"
            ),
            ctx["owner_headers"],
        ),
        expected_status=201,
    )
    assert_common_fields(cert, "certification")
    assert is_valid_uuid(cert["id"]) and "_" not in cert["id"]
    assert cert["version"] == 1

    household_after = validate_success(
        api_client.get_tenant_household(household["id"], ctx["owner_headers"])
    )
    assert household_after["version"] == 2, (
        "the certification write bumped the household's own version, got "
        f"{household_after['version']}"
    )
    assert household_after["updated_at"] >= household["updated_at"], (
        "the cascaded mutation refreshes updated_at"
    )


def test_enum_date_and_conditional_type_constraints_are_all_invalid_request():
    """The shape check covers enum members, "dates in `YYYY-MM-DD` form, billing months in
    `YYYY-MM` form, `cert_type` not `UA_ADJUSTMENT` on a client write,
    `utility_rate_change_pct` present exactly when the analysis method is `FACTOR_BASED`".

    Design: Corner/entities/enum_date_and_conditional_type_constraints_are_all_reported_as_invalid_request
    """
    ctx = setup_portfolio()
    prop_id = ctx["property"]["id"]
    owner_headers = ctx["owner_headers"]
    household = create_household(prop_id, owner_headers, **REFERENCE_HOUSEHOLD_ONE)

    bad_enum = create_hap_contract_payload(prop_id, contract_type="SECTION_811")
    validate_error(
        api_client.create_hap_contract(bad_enum, CA_HEADERS),
        ApiErrorId.ERR_INVALID_REQUEST.value,
        expected_status=400,
    )

    bad_date = create_hap_contract_payload(prop_id, expiration_date="12/31/2027")
    validate_error(
        api_client.create_hap_contract(bad_date, CA_HEADERS),
        ApiErrorId.ERR_INVALID_REQUEST.value,
        expected_status=400,
    )

    bad_month = create_voucher_submission_payload(
        ctx["contract"]["id"], ctx["contract"]["version"], period_month="2026-07-01"
    )
    validate_error(
        api_client.create_voucher_submission(bad_month, owner_headers),
        ApiErrorId.ERR_INVALID_REQUEST.value,
        expected_status=400,
    )

    mismatched_method = {
        "property_id": prop_id,
        "method": "FACTOR_BASED",
        "effective_date": "2026-09-01",
        "engineering_estimate_cents": 12000,
    }
    validate_error(
        api_client.create_utility_allowance_analysis(mismatched_method, owner_headers),
        ApiErrorId.ERR_INVALID_REQUEST.value,
        expected_status=400,
    )

    reserved_cert_type = create_tenant_certification_payload(
        household["id"],
        household["version"],
        cert_type="UA_ADJUSTMENT",
        effective_date="2026-07-01",
    )
    validate_error(
        api_client.create_tenant_certification(reserved_cert_type, owner_headers),
        ApiErrorId.ERR_INVALID_REQUEST.value,
        expected_status=400,
    )

    household_after = validate_success(
        api_client.get_tenant_household(household["id"], owner_headers)
    )
    assert household_after["version"] == household["version"], (
        "no rejected call mutated the household, got version "
        f"{household_after['version']}"
    )
    rows, meta = validate_paginated(
        api_client.list_property_utility_allowance_analyses(prop_id, CA_HEADERS)
    )
    assert meta["total_count"] == 0, (
        f"the rejected analysis was never created, got {meta['total_count']} rows"
    )
