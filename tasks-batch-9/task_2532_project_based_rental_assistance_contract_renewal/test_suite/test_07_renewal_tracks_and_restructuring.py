"""The two independent case tracks joining at execution, and the restructuring branches."""
from test_helpers import (
    ApiErrorId,
    RENEWAL_WINDOW_CLOCK_DATE,
    TEST_USERS,
    api_client,
    approve_rents,
    create_contract,
    create_property,
    create_restructuring_determination_payload,
    create_tenant_notice_payload,
    current_contract_version,
    execute_renewal_payload,
    setup_adjustment_elected,
    setup_case_with_accepted_study,
    setup_portfolio,
    validate_error,
    validate_success,
)

CA_HEADERS = TEST_USERS["contract_administrator_headers"]
CA_APPROVER_HEADERS = TEST_USERS["contract_administrator_approver_headers"]
HUD_HEADERS = TEST_USERS["hud_field_office_headers"]
HUD_SECOND_HEADERS = TEST_USERS["hud_field_office_second_headers"]
HUD_SECOND_USER_ID = TEST_USERS["hud_field_office_second_user_id"]

ALDER_COURT_SINGLE = {
    "address_label": "88 Alder Court",
    "raw_rent_cents": 128649,
    "adjustment_total_cents": 55,
    "utility_adjustment_cents": 1500,
    "weight": 1,
}
ELM_TERRACE_AT_RENT = {
    "address_label": "9 Elm Terrace",
    "raw_rent_cents": 116500,
    "adjustment_total_cents": 0,
    "utility_adjustment_cents": 1500,
    "weight": 1,
}
ELM_TERRACE_ONE_DOLLAR_UP = {
    "address_label": "11 Elm Terrace",
    "raw_rent_cents": 116600,
    "adjustment_total_cents": 0,
    "utility_adjustment_cents": 1500,
    "weight": 1,
}


def _accepted_case_on(base: dict, contract: dict, renewal_option: str, comparable: dict) -> dict:
    """A case on `contract` carrying one ACCEPTED single-comparable study."""
    return setup_case_with_accepted_study(
        renewal_option=renewal_option,
        adjustment_method="OCAF",
        comparables=[comparable],
        clock_date=RENEWAL_WINDOW_CLOCK_DATE,
        base={
            "owner": base["owner"],
            "owner_headers": base["owner_headers"],
            "property": base["property"],
            "contract": contract,
        },
    )


def test_the_rent_track_reaches_approval_while_the_notice_track_blocks_execution():
    """"the request requires the case's `notice_track_status` to be exactly
    `RENEWAL_NOTICED` — a case whose notice track sits anywhere else, including a case on the
    opt-out path, is refused with `ERR_TRANSITION_NOT_ALLOWED`".

    Design: Difficulty/non_linear_state_machine/renewal_case_rent_track_and_notice_track_advance_independently_and_join_at_execution
    """
    ctx = setup_adjustment_elected(
        renewal_option="OPTION_2_OCAF", adjustment_method="OCAF"
    )
    case_id = ctx["case"]["id"]
    contract_id = ctx["contract"]["id"]

    approved = approve_rents(case_id, CA_APPROVER_HEADERS)
    assert approved["rent_track_status"] == "RENTS_APPROVED"
    assert approved["notice_track_status"] == "NOTICES_PENDING", (
        "the rent dimension advanced alone, got " f"{approved['notice_track_status']}"
    )
    assert approved["approved_rent_per_unit_cents"] == 120752

    blocked_version = current_contract_version(contract_id)
    validate_error(
        api_client.execute_renewal(
            case_id, execute_renewal_payload(blocked_version), CA_APPROVER_HEADERS
        ),
        ApiErrorId.ERR_TRANSITION_NOT_ALLOWED.value,
        expected_status=409,
    )

    after = validate_success(api_client.get_renewal_case(case_id, CA_HEADERS))
    assert after["rent_track_status"] == "RENTS_APPROVED", (
        "the guard reads the notice dimension, not the rent dimension's own from-state, "
        f"got {after['rent_track_status']}"
    )
    assert after["approved_rent_per_unit_cents"] == 120752
    contract_after = validate_success(api_client.get_hap_contract(contract_id, CA_HEADERS))
    assert contract_after["lifecycle_status"] == "RENEWAL_PENDING"
    assert contract_after["renewed_rent_per_unit_cents"] is None
    assert contract_after["version"] == blocked_version, (
        f"the refused execution bumped nothing, got {contract_after['version']}"
    )


def test_the_two_tracks_join_once_the_notice_is_issued_and_execution_renews_the_contract():
    """"Execution then moves `rent_track_status` from `RENTS_APPROVED` to the terminal
    `EXECUTED` and, on the contract, moves `lifecycle_status` from `RENEWAL_PENDING` to the
    terminal `RENEWED` while writing four things: `renewed_rent_per_unit_cents` and
    `contract_rent_per_unit_cents` both take the case's `approved_rent_per_unit_cents`".

    Design: Difficulty/non_linear_state_machine/renewal_case_rent_track_and_notice_track_advance_independently_and_join_at_execution
    """
    ctx = setup_adjustment_elected(
        renewal_option="OPTION_2_OCAF", adjustment_method="OCAF"
    )
    case_id = ctx["case"]["id"]
    contract_id = ctx["contract"]["id"]
    approve_rents(case_id, CA_APPROVER_HEADERS)

    notice = validate_success(
        api_client.create_tenant_notice(
            create_tenant_notice_payload(
                case_id, notice_type="RENEWAL_INTENT", effective_date="2027-12-31"
            ),
            ctx["owner_headers"],
        ),
        expected_status=201,
    )
    assert notice["lead_days"] == 395, (
        f"2026-12-01 to 2027-12-31 is 395 whole days, got {notice['lead_days']}"
    )
    assert notice["required_lead_days"] == 120
    noticed = validate_success(api_client.get_renewal_case(case_id, CA_HEADERS))
    assert noticed["notice_track_status"] == "RENEWAL_NOTICED"
    assert noticed["rent_track_status"] == "RENTS_APPROVED", (
        "issuing the notice left the rent dimension where it stood, got "
        f"{noticed['rent_track_status']}"
    )

    ready_version = current_contract_version(contract_id)
    executed = validate_success(
        api_client.execute_renewal(
            case_id, execute_renewal_payload(ready_version), CA_APPROVER_HEADERS
        )
    )
    assert executed["rent_track_status"] == "EXECUTED"
    assert executed["notice_track_status"] == "RENEWAL_NOTICED"

    contract_after = validate_success(api_client.get_hap_contract(contract_id, CA_HEADERS))
    assert contract_after["lifecycle_status"] == "RENEWED"
    assert contract_after["renewed_rent_per_unit_cents"] == 120752
    assert contract_after["contract_rent_per_unit_cents"] == 120752, (
        "the renewed rent becomes the in-force rent, got "
        f"{contract_after['contract_rent_per_unit_cents']}"
    )
    assert contract_after["renewed_option"] == "OPTION_2_OCAF"
    assert contract_after["renewed_expiration_date"] == "2028-12-31", (
        "2027-12-31 advanced by 12 whole months, got "
        f"{contract_after['renewed_expiration_date']}"
    )
    assert contract_after["expiration_date"] == "2028-12-31"
    assert contract_after["version"] == ready_version + 1


def test_a_market_rent_equal_to_the_contract_rent_is_not_mark_up_to_market_eligible():
    """"the market-versus-contract test is strict, so a market rent exactly equal to the
    contract rent is not mark-up-to-market eligible", and "In every remaining situation the
    determination is `INELIGIBLE` with reason `MARKET_NOT_ABOVE_CONTRACT`".

    Design: Difficulty/boundary_precision_check/mutm_eligibility_requires_market_strictly_above_contract_rent
    """
    base = setup_portfolio(property_overrides={"published_fmr_cents": 110000})
    ctx = _accepted_case_on(
        base, base["contract"], "OPTION_1_MARK_UP_TO_MARKET", ELM_TERRACE_AT_RENT
    )
    assert ctx["case"]["comparable_market_rent_cents"] == 118000, (
        "116500 + 0 + 1500 is a whole dollar already, got "
        f"{ctx['case']['comparable_market_rent_cents']}"
    )

    determination = validate_success(
        api_client.create_restructuring_determination(
            create_restructuring_determination_payload(ctx["case"]["id"]), CA_HEADERS
        ),
        expected_status=201,
    )
    assert determination["determination_state"] == "DRAFT"
    assert determination["eligibility_reason_code"] is None
    assert determination["post_restructure_rent_per_unit_cents"] is None
    assert determination["market_rent_per_unit_cents"] == 118000
    assert determination["current_rent_per_unit_cents"] == 118000
    assert determination["fmr_per_unit_cents"] == 110000

    evaluated = validate_success(
        api_client.evaluate_restructuring_determination(determination["id"], CA_HEADERS)
    )
    assert evaluated["determination_state"] == "INELIGIBLE", (
        "equality does not clear a strictly-greater test, got "
        f"{evaluated['determination_state']}"
    )
    assert evaluated["eligibility_reason_code"] == "MARKET_NOT_ABOVE_CONTRACT"
    assert evaluated["post_restructure_rent_per_unit_cents"] is None
    assert evaluated["approved_by_user_id"] is None


def test_one_whole_dollar_above_the_contract_rent_clears_the_mark_up_to_market_test():
    """"if the snapshot market rent is strictly greater than the snapshot current rent, the
    project is in the mark-up-to-market family ... the determination becomes `MUTM_ELIGIBLE`
    with reason `MARKET_ABOVE_CONTRACT_AND_FMR`", and on approval
    "`post_restructure_rent_per_unit_cents` is set to the snapshot
    `market_rent_per_unit_cents` unchanged".

    Design: Difficulty/boundary_precision_check/mutm_eligibility_requires_market_strictly_above_contract_rent
    """
    base = setup_portfolio(property_overrides={"published_fmr_cents": 110000})
    ctx = _accepted_case_on(
        base, base["contract"], "OPTION_1_MARK_UP_TO_MARKET", ELM_TERRACE_ONE_DOLLAR_UP
    )
    case_id = ctx["case"]["id"]
    assert ctx["case"]["comparable_market_rent_cents"] == 118100, (
        "116600 + 0 + 1500 is 118100, one whole dollar above the contract rent, got "
        f"{ctx['case']['comparable_market_rent_cents']}"
    )

    determination = validate_success(
        api_client.create_restructuring_determination(
            create_restructuring_determination_payload(case_id), CA_HEADERS
        ),
        expected_status=201,
    )
    evaluated = validate_success(
        api_client.evaluate_restructuring_determination(determination["id"], CA_HEADERS)
    )
    assert evaluated["determination_state"] == "MUTM_ELIGIBLE"
    assert evaluated["eligibility_reason_code"] == "MARKET_ABOVE_CONTRACT_AND_FMR"
    assert evaluated["market_rent_per_unit_cents"] == 118100
    assert evaluated["current_rent_per_unit_cents"] == 118000

    approved = validate_success(
        api_client.approve_restructuring_determination(determination["id"], HUD_HEADERS)
    )
    assert approved["determination_state"] == "APPROVED"
    assert approved["post_restructure_rent_per_unit_cents"] == 118100, (
        "the mark-up-to-market branch stamps the market rent unchanged, got "
        f"{approved['post_restructure_rent_per_unit_cents']}"
    )
    case_after = validate_success(api_client.get_renewal_case(case_id, CA_HEADERS))
    assert case_after["ocaf_rent_per_unit_cents"] == 118100, (
        "the approval re-points the case's candidate rent at the restructured rent, got "
        f"{case_after['ocaf_rent_per_unit_cents']}"
    )


def test_restructuring_eligibility_reports_the_reason_code_of_every_non_mutm_branch():
    """"If the contract's `contract_type` is `LOAN_MANAGEMENT_SET_ASIDE`, the determination is
    `INELIGIBLE` with `eligibility_reason_code` `CONTRACT_TYPE_EXCLUDED`, and no rent
    comparison is made at all", "if the snapshot current rent is strictly greater than the
    snapshot market rent **and** the property's `has_fha_insured_mortgage` is true, the
    determination becomes `M2M_REFERRED`", and on that branch
    "`post_restructure_rent_per_unit_cents` is set to 90 percent of the snapshot
    `market_rent_per_unit_cents`, rounded half up to whole cents".

    Design: Corner/calculations/restructuring_eligibility_reports_the_reason_code_of_every_non_mutm_branch
    """
    base = setup_portfolio(
        contract_overrides={"contract_type": "LOAN_MANAGEMENT_SET_ASIDE"}
    )
    excluded = _accepted_case_on(
        base, base["contract"], "OPTION_2_OCAF", ALDER_COURT_SINGLE
    )
    assert excluded["comparables"][0]["adjusted_rent_cents"] == 130200, (
        "128649 + 55 + 1500 is 130204, which rounds to the whole dollar 130200, got "
        f"{excluded['comparables'][0]['adjusted_rent_cents']}"
    )
    assert excluded["case"]["comparable_market_rent_cents"] == 130200

    above_market_uninsured_contract = create_contract(
        base["property"]["id"],
        contract_rent_per_unit_cents=145000,
        expiration_date="2027-11-30",
    )
    uninsured = _accepted_case_on(
        base, above_market_uninsured_contract, "OPTION_2_OCAF", ALDER_COURT_SINGLE
    )

    insured_property = create_property(
        base["owner"]["id"],
        base["owner_headers"],
        project_name="Birch Hollow Apartments",
        total_units=18,
        assisted_unit_count=16,
        has_fha_insured_mortgage=True,
    )
    insured_contract = create_contract(
        insured_property["id"],
        contract_rent_per_unit_cents=145000,
        expiration_date="2027-10-31",
    )
    referred = setup_case_with_accepted_study(
        renewal_option="OPTION_3_MARK_TO_MARKET",
        adjustment_method="OCAF",
        comparables=[ALDER_COURT_SINGLE],
        clock_date=RENEWAL_WINDOW_CLOCK_DATE,
        base={
            "owner": base["owner"],
            "owner_headers": base["owner_headers"],
            "property": insured_property,
            "contract": insured_contract,
        },
    )

    d_excluded = validate_success(
        api_client.create_restructuring_determination(
            create_restructuring_determination_payload(excluded["case"]["id"]), CA_HEADERS
        ),
        expected_status=201,
    )
    assert d_excluded["determination_state"] == "DRAFT"
    assert d_excluded["eligibility_reason_code"] is None
    assert d_excluded["market_rent_per_unit_cents"] == 130200
    assert d_excluded["current_rent_per_unit_cents"] == 118000
    assert d_excluded["fmr_per_unit_cents"] == 126000
    evaluated_excluded = validate_success(
        api_client.evaluate_restructuring_determination(d_excluded["id"], CA_HEADERS)
    )
    assert evaluated_excluded["determination_state"] == "INELIGIBLE"
    assert evaluated_excluded["eligibility_reason_code"] == "CONTRACT_TYPE_EXCLUDED", (
        "the contract-type test runs first, even though 130200 > 118000 and 130200 >= "
        f"126000 would otherwise qualify, got {evaluated_excluded['eligibility_reason_code']}"
    )
    assert evaluated_excluded["post_restructure_rent_per_unit_cents"] is None

    d_uninsured = validate_success(
        api_client.create_restructuring_determination(
            create_restructuring_determination_payload(uninsured["case"]["id"]), CA_HEADERS
        ),
        expected_status=201,
    )
    evaluated_uninsured = validate_success(
        api_client.evaluate_restructuring_determination(d_uninsured["id"], CA_HEADERS)
    )
    assert evaluated_uninsured["current_rent_per_unit_cents"] == 145000
    assert evaluated_uninsured["determination_state"] == "INELIGIBLE"
    assert evaluated_uninsured["eligibility_reason_code"] == "MARKET_NOT_ABOVE_CONTRACT", (
        "an above-market contract on an uninsured property falls through to the residual "
        f"branch, got {evaluated_uninsured['eligibility_reason_code']}"
    )
    assert evaluated_uninsured["post_restructure_rent_per_unit_cents"] is None

    d_referred = validate_success(
        api_client.create_restructuring_determination(
            create_restructuring_determination_payload(referred["case"]["id"]), CA_HEADERS
        ),
        expected_status=201,
    )
    evaluated_referred = validate_success(
        api_client.evaluate_restructuring_determination(d_referred["id"], CA_HEADERS)
    )
    assert evaluated_referred["determination_state"] == "M2M_REFERRED"
    assert evaluated_referred["eligibility_reason_code"] == (
        "CONTRACT_ABOVE_MARKET_FHA_INSURED"
    )

    approved = validate_success(
        api_client.approve_restructuring_determination(
            d_referred["id"], HUD_SECOND_HEADERS
        )
    )
    assert approved["determination_state"] == "APPROVED"
    assert approved["approved_by_user_id"] == HUD_SECOND_USER_ID
    assert approved["post_restructure_rent_per_unit_cents"] == 117180, (
        "the mark-to-market branch stamps round_half_up(0.9 * 130200), not the market rent "
        f"itself, got {approved['post_restructure_rent_per_unit_cents']}"
    )
    case_after = validate_success(
        api_client.get_renewal_case(referred["case"]["id"], CA_HEADERS)
    )
    assert case_after["ocaf_rent_per_unit_cents"] == 117180, (
        "the approval re-points the candidate rent at the restructured rent, got "
        f"{case_after['ocaf_rent_per_unit_cents']}"
    )


def test_the_fair_market_rent_floor_is_inclusive_and_one_cent_above_disqualifies():
    """"when the market rent is also at least the Fair Market Rent floor — that is, at least
    the snapshot Fair Market Rent multiplied by 1.00 and rounded half up to whole cents, an
    inclusive comparison — the determination becomes `MUTM_ELIGIBLE` ...; when the market rent
    falls below that floor, the determination is `INELIGIBLE` with reason
    `MARKET_BELOW_FMR_FLOOR`".

    Design: Corner/calculations/mutm_fmr_floor_is_inclusive_at_the_published_fmr_and_refuses_one_cent_above
    """
    base = setup_portfolio(
        property_overrides={
            "project_name": "Below Floor Apartments",
            "total_units": 12,
            "assisted_unit_count": 10,
            "published_fmr_cents": 130199,
        }
    )
    below = _accepted_case_on(
        base, base["contract"], "OPTION_1_MARK_UP_TO_MARKET", ALDER_COURT_SINGLE
    )
    assert below["case"]["rcs_required"] is True, (
        "mark-up-to-market forces the study requirement at option selection, got "
        f"{below['case']['rcs_required']}"
    )
    assert below["case"]["comparable_market_rent_cents"] == 130200

    at_property = create_property(
        base["owner"]["id"],
        base["owner_headers"],
        project_name="At Floor Apartments",
        total_units=12,
        assisted_unit_count=10,
        published_fmr_cents=130200,
    )
    at_contract = create_contract(at_property["id"])
    at_floor = setup_case_with_accepted_study(
        renewal_option="OPTION_1_MARK_UP_TO_MARKET",
        adjustment_method="OCAF",
        comparables=[ALDER_COURT_SINGLE],
        clock_date=RENEWAL_WINDOW_CLOCK_DATE,
        base={
            "owner": base["owner"],
            "owner_headers": base["owner_headers"],
            "property": at_property,
            "contract": at_contract,
        },
    )

    above_property = create_property(
        base["owner"]["id"],
        base["owner_headers"],
        project_name="Above Floor Apartments",
        total_units=12,
        assisted_unit_count=10,
        published_fmr_cents=130201,
    )
    above_contract = create_contract(above_property["id"])
    above_floor = setup_case_with_accepted_study(
        renewal_option="OPTION_1_MARK_UP_TO_MARKET",
        adjustment_method="OCAF",
        comparables=[ALDER_COURT_SINGLE],
        clock_date=RENEWAL_WINDOW_CLOCK_DATE,
        base={
            "owner": base["owner"],
            "owner_headers": base["owner_headers"],
            "property": above_property,
            "contract": above_contract,
        },
    )

    outcomes = {}
    for label, ctx in (
        ("below", below),
        ("at", at_floor),
        ("above", above_floor),
    ):
        determination = validate_success(
            api_client.create_restructuring_determination(
                create_restructuring_determination_payload(ctx["case"]["id"]), CA_HEADERS
            ),
            expected_status=201,
        )
        outcomes[label] = validate_success(
            api_client.evaluate_restructuring_determination(determination["id"], CA_HEADERS)
        )
        assert outcomes[label]["market_rent_per_unit_cents"] == 130200, (
            f"every probe holds the market rent still, got "
            f"{outcomes[label]['market_rent_per_unit_cents']}"
        )

    assert outcomes["below"]["fmr_per_unit_cents"] == 130199
    assert outcomes["below"]["determination_state"] == "MUTM_ELIGIBLE"
    assert outcomes["below"]["eligibility_reason_code"] == "MARKET_ABOVE_CONTRACT_AND_FMR"

    assert outcomes["at"]["fmr_per_unit_cents"] == 130200
    assert outcomes["at"]["determination_state"] == "MUTM_ELIGIBLE", (
        "a market rent exactly at the floor is eligible, got "
        f"{outcomes['at']['determination_state']}"
    )
    assert outcomes["at"]["eligibility_reason_code"] == "MARKET_ABOVE_CONTRACT_AND_FMR"

    assert outcomes["above"]["fmr_per_unit_cents"] == 130201
    assert outcomes["above"]["determination_state"] == "INELIGIBLE", (
        "one cent of Fair Market Rent above the market disqualifies, got "
        f"{outcomes['above']['determination_state']}"
    )
    assert outcomes["above"]["eligibility_reason_code"] == "MARKET_BELOW_FMR_FLOOR"
    assert outcomes["above"]["post_restructure_rent_per_unit_cents"] is None

    approved = validate_success(
        api_client.approve_restructuring_determination(
            outcomes["at"]["id"], HUD_SECOND_HEADERS
        )
    )
    assert approved["determination_state"] == "APPROVED"
    assert approved["post_restructure_rent_per_unit_cents"] == 130200, (
        "the mark-up-to-market branch stamps the market rent unchanged, not 0.9 times it, "
        f"got {approved['post_restructure_rent_per_unit_cents']}"
    )
    case_after = validate_success(
        api_client.get_renewal_case(at_floor["case"]["id"], CA_HEADERS)
    )
    assert case_after["ocaf_rent_per_unit_cents"] == 130200
    assert case_after["comparable_market_rent_cents"] == 130200
