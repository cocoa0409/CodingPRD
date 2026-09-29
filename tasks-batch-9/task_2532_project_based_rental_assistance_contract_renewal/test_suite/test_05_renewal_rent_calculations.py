"""The two renewal-rent variants, the weighted-mean market rent and the election gates."""
from test_helpers import (
    ApiErrorId,
    REFERENCE_COMPARABLES,
    TEST_USERS,
    api_client,
    approve_rents,
    create_comparable_payload,
    create_contract,
    create_study_payload,
    elect_adjustment_payload,
    select_option_payload,
    setup_accepted_study,
    setup_adjustment_elected,
    setup_case_with_accepted_study,
    setup_evaluated_determination,
    setup_option_selected,
    setup_portfolio,
    setup_renewal_case,
    setup_study,
    validate_error,
    validate_paginated,
    validate_success,
)

CA_HEADERS = TEST_USERS["contract_administrator_headers"]
CA_APPROVER_HEADERS = TEST_USERS["contract_administrator_approver_headers"]
HUD_HEADERS = TEST_USERS["hud_field_office_headers"]

MAPLE_COURT = {
    "address_label": "418 Maple Court",
    "raw_rent_cents": 128649,
    "adjustment_total_cents": 55,
    "utility_adjustment_cents": 1500,
    "weight": 1,
}


def test_identical_contracts_carry_both_candidate_rents_and_diverge_only_by_election():
    """"The election also recomputes both candidate rents on the case from the contract's
    current per-unit components", so two contracts carrying byte-identical figures both
    report `ocaf_rent_per_unit_cents` 120752 and `budget_rent_per_unit_cents` 105300 while
    "`rcs_required` as true when `adjustment_method` is `BUDGET_BASED`".

    Design: Difficulty/dual_variant_calc/renewal_rent_ocaf_track_versus_budget_based_track_on_identical_contract_data
    """
    base = setup_portfolio()
    contract_b = create_contract(base["property"]["id"])
    assert contract_b["contract_rent_per_unit_cents"] == 118000
    assert contract_b["monthly_debt_service_per_unit_cents"] == 32000
    assert contract_b["operating_expense_per_unit_cents"] == 61000
    assert contract_b["reserve_deposit_per_unit_cents"] == 4500

    ctx_a = setup_adjustment_elected(
        renewal_option="OPTION_2_OCAF", adjustment_method="OCAF", base=base
    )
    case_a = ctx_a["case"]
    assert case_a["ocaf_rent_per_unit_cents"] == 120752, (
        "round_half_up((118000 - 32000) * 1.032) is 88752, then the 32000 debt service is "
        f"added back, got {case_a['ocaf_rent_per_unit_cents']}"
    )
    assert case_a["budget_rent_per_unit_cents"] == 105300, (
        "the budget candidate is computed too even though OCAF was elected, got "
        f"{case_a['budget_rent_per_unit_cents']}"
    )
    assert case_a["adjustment_method"] == "OCAF"
    assert case_a["rcs_required"] is False

    ctx_b = setup_adjustment_elected(
        renewal_option="OPTION_2_OCAF",
        adjustment_method="BUDGET_BASED",
        clock_date=None,
        base={
            "owner": base["owner"],
            "owner_headers": base["owner_headers"],
            "property": base["property"],
            "contract": contract_b,
        },
    )
    case_b = ctx_b["case"]
    assert case_b["ocaf_rent_per_unit_cents"] == 120752, (
        "the same stored columns give the same operating-cost candidate, got "
        f"{case_b['ocaf_rent_per_unit_cents']}"
    )
    assert case_b["budget_rent_per_unit_cents"] == 105300
    assert case_b["adjustment_method"] == "BUDGET_BASED"
    assert case_b["rcs_required"] is True, (
        f"a budget-based election makes a study mandatory, got {case_b['rcs_required']}"
    )

    study_b = setup_accepted_study(case_b["id"], ctx_b["owner_headers"])
    assert study_b["study"]["estimated_market_rent_cents"] == 130200
    case_b_after = validate_success(api_client.get_renewal_case(case_b["id"], CA_HEADERS))
    assert case_b_after["comparable_market_rent_cents"] == 130200
    assert case_b_after["ocaf_rent_per_unit_cents"] == 120752, (
        "accepting the study does not disturb either candidate rent, got "
        f"{case_b_after['ocaf_rent_per_unit_cents']}"
    )
    assert case_b_after["budget_rent_per_unit_cents"] == 105300


def test_approved_rent_selects_the_elected_variant_and_the_tracks_differ_by_15452():
    """"The approved rent is selected, never recomputed. When `adjustment_method` is `OCAF`,
    the candidate is the case's stored `ocaf_rent_per_unit_cents` ... When `adjustment_method`
    is `BUDGET_BASED`, the candidate is the case's stored `budget_rent_per_unit_cents`".

    Design: Difficulty/dual_variant_calc/renewal_rent_ocaf_track_versus_budget_based_track_on_identical_contract_data
    """
    base = setup_portfolio()
    contract_b = create_contract(base["property"]["id"])

    ctx_a = setup_adjustment_elected(
        renewal_option="OPTION_2_OCAF", adjustment_method="OCAF", base=base
    )
    ctx_b = setup_case_with_accepted_study(
        renewal_option="OPTION_2_OCAF",
        adjustment_method="BUDGET_BASED",
        clock_date=None,
        base={
            "owner": base["owner"],
            "owner_headers": base["owner_headers"],
            "property": base["property"],
            "contract": contract_b,
        },
    )

    approved_a = approve_rents(ctx_a["case"]["id"], CA_APPROVER_HEADERS)
    assert approved_a["rent_track_status"] == "RENTS_APPROVED", (
        "the fork path from OPTION_SELECTED is open because rcs_required is false and the "
        f"method is OCAF, got {approved_a['rent_track_status']}"
    )
    assert approved_a["approved_rent_per_unit_cents"] == 120752

    approved_b = approve_rents(ctx_b["case"]["id"], CA_APPROVER_HEADERS)
    assert approved_b["rent_track_status"] == "RENTS_APPROVED"
    assert approved_b["approved_rent_per_unit_cents"] == 105300, (
        "the budget-based candidate 105300 sits under the 110-percent-of-market ceiling of "
        f"143220, so it is approved unchanged, got {approved_b['approved_rent_per_unit_cents']}"
    )

    divergence = (
        approved_a["approved_rent_per_unit_cents"]
        - approved_b["approved_rent_per_unit_cents"]
    )
    assert divergence == 15452, (
        "identical contract data diverges by exactly 15452 cents on the elected variant "
        f"alone, got {divergence}"
    )
    assert approved_a["ocaf_rent_per_unit_cents"] == 120752
    assert approved_b["budget_rent_per_unit_cents"] == 105300
    assert approved_b["ocaf_rent_per_unit_cents"] == 120752, (
        "the unselected candidate is left standing on the case, got "
        f"{approved_b['ocaf_rent_per_unit_cents']}"
    )


def test_each_comparable_is_rounded_to_whole_dollars_before_the_weighted_mean():
    """"sum its `raw_rent_cents`, its `adjustment_total_cents`, and its
    `utility_adjustment_cents`, and round that gross figure half up to the nearest whole
    dollar ... Computing the weighted mean over the unrounded gross figures and rounding
    only once at the end yields a different answer and is not permitted".

    Design: Difficulty/combinatorial_formula/comparable_market_rent_rounds_each_comparable_to_whole_dollars_before_the_weighted_mean
    """
    ctx = setup_adjustment_elected(
        renewal_option="OPTION_2_OCAF", adjustment_method="OCAF"
    )
    bundle = setup_study(ctx["case"]["id"], ctx["owner_headers"], REFERENCE_COMPARABLES)
    adjusted = [c["adjusted_rent_cents"] for c in bundle["comparables"]]
    assert adjusted[0] == 131200, (
        f"125000 + 4650 + 1500 is 131150, which rounds to 131200, got {adjusted[0]}"
    )
    assert adjusted[1] == 123600, (
        f"118000 + 4100 + 1500 is already a whole dollar, got {adjusted[1]}"
    )
    assert adjusted[2] == 140400, (
        f"133000 + 5925 + 1500 is 140425, which rounds down to 140400, got {adjusted[2]}"
    )

    submitted = validate_success(
        api_client.submit_study(bundle["study"]["id"], ctx["owner_headers"])
    )
    assert submitted["accepted_comparable_count"] == 3
    market = submitted["estimated_market_rent_cents"]
    assert market == 130200, (
        "(131200*3 + 123600*2 + 140400*1) / 6 is 130200, got " f"{market}"
    )
    assert market != 130179, (
        "130179 is the weighted mean of the unrounded gross figures rounded once at the "
        "end, which the pinned order forbids"
    )

    case_after = validate_success(
        api_client.get_renewal_case(ctx["case"]["id"], CA_HEADERS)
    )
    assert case_after["comparable_market_rent_cents"] == 130200
    assert case_after["rent_track_status"] == "RCS_IN_PROGRESS"


def test_the_market_rent_refreshes_on_every_add_always_rounding_each_comparable_first():
    """"Both `estimated_market_rent_cents` and `accepted_comparable_count` are refreshed,
    and the study's `version` incremented, every time a comparable is added", each refresh
    running the same rounded-first weighted mean.

    Design: Difficulty/combinatorial_formula/comparable_market_rent_rounds_each_comparable_to_whole_dollars_before_the_weighted_mean
    """
    ctx = setup_adjustment_elected(
        renewal_option="OPTION_2_OCAF", adjustment_method="OCAF"
    )
    study = validate_success(
        api_client.create_study(
            create_study_payload(
                ctx["case"]["id"], appraiser_name="Hollis Appraisal Group"
            ),
            ctx["owner_headers"],
        ),
        expected_status=201,
    )
    assert study["accepted_comparable_count"] == 0

    first = validate_success(
        api_client.create_comparable(
            create_comparable_payload(study["id"], **REFERENCE_COMPARABLES[0]),
            ctx["owner_headers"],
        ),
        expected_status=201,
    )
    assert first["adjusted_rent_cents"] == 131200
    after_one = validate_success(api_client.get_study(study["id"], CA_HEADERS))
    assert after_one["estimated_market_rent_cents"] == 131200, (
        "a single comparable of weight 3 is its own weighted mean, at its rounded value, "
        f"got {after_one['estimated_market_rent_cents']}"
    )
    assert after_one["accepted_comparable_count"] == 1
    assert after_one["version"] == 2

    validate_success(
        api_client.create_comparable(
            create_comparable_payload(study["id"], **REFERENCE_COMPARABLES[1]),
            ctx["owner_headers"],
        ),
        expected_status=201,
    )
    after_two = validate_success(api_client.get_study(study["id"], CA_HEADERS))
    assert after_two["estimated_market_rent_cents"] == 128160, (
        "(131200*3 + 123600*2) / 5 is 128160; the unrounded pipeline would give 128130, "
        f"got {after_two['estimated_market_rent_cents']}"
    )
    assert after_two["accepted_comparable_count"] == 2
    assert after_two["version"] == 3

    validate_success(
        api_client.create_comparable(
            create_comparable_payload(study["id"], **REFERENCE_COMPARABLES[2]),
            ctx["owner_headers"],
        ),
        expected_status=201,
    )
    after_three = validate_success(api_client.get_study(study["id"], CA_HEADERS))
    assert after_three["estimated_market_rent_cents"] == 130200
    assert after_three["accepted_comparable_count"] == 3
    assert after_three["version"] == 4

    rows, meta = validate_paginated(
        api_client.list_study_comparables(study["id"], CA_HEADERS)
    )
    assert meta["total_count"] == 3
    assert [row["adjusted_rent_cents"] for row in rows] == [131200, 123600, 140400], (
        "every stored comparable keeps its own whole-dollar figure, got "
        f"{[row['adjusted_rent_cents'] for row in rows]}"
    )


def test_budget_based_rent_levies_the_eight_percent_fee_once_on_the_subtotal():
    """"First form the pre-fee subtotal: `operating_expense_per_unit_cents` plus
    `monthly_debt_service_per_unit_cents` plus `reserve_deposit_per_unit_cents` ... Then levy
    the management fee of 8 percent **on that subtotal**, rounding the fee half up to whole
    cents", and "Exactly one rounding occurs, and it applies to the fee term alone".

    Design: Difficulty/combinatorial_formula/budget_based_rent_levies_the_management_fee_once_on_the_pre_fee_subtotal
    """
    ctx = setup_option_selected(renewal_option="OPTION_2_OCAF")
    after_option = ctx["case"]
    assert after_option["budget_rent_per_unit_cents"] == 105300, (
        "the subtotal 61000 + 32000 + 4500 is 97500 and the single 8-percent fee is 7800, "
        f"summing to 105300, got {after_option['budget_rent_per_unit_cents']}"
    )
    assert after_option["budget_rent_per_unit_cents"] != 105978, (
        "105978 is the algebraic fixed point 97500 / 0.92, which the pinned single forward "
        "pass forbids"
    )
    assert after_option["budget_rent_per_unit_cents"] != 105924, (
        "105924 re-levies the fee against the new total for a second iteration, which is "
        "not permitted"
    )

    elected = validate_success(
        api_client.elect_adjustment(
            after_option["id"],
            elect_adjustment_payload("BUDGET_BASED"),
            ctx["owner_headers"],
        )
    )
    assert elected["rent_track_status"] == "OPTION_SELECTED", (
        "recording the adjustment method is a self-transition on the rent track, got "
        f"{elected['rent_track_status']}"
    )
    assert elected["adjustment_method"] == "BUDGET_BASED"
    assert elected["rcs_required"] is True
    assert elected["budget_rent_per_unit_cents"] == 105300, (
        "the recomputation on election reproduces the same single forward pass, got "
        f"{elected['budget_rent_per_unit_cents']}"
    )


def test_the_budget_based_rent_reads_only_the_three_budget_components():
    """"The figure written to `budget_rent_per_unit_cents` reads only the three per-unit
    budget components on the contract and no property or tenant data at all", so a contract
    whose `contract_rent_per_unit_cents` differs but whose three components match reports the
    identical budget rent.

    Design: Difficulty/combinatorial_formula/budget_based_rent_levies_the_management_fee_once_on_the_pre_fee_subtotal
    """
    base = setup_portfolio()
    richer = create_contract(base["property"]["id"], contract_rent_per_unit_cents=130000)
    assert richer["operating_expense_per_unit_cents"] == 61000
    assert richer["monthly_debt_service_per_unit_cents"] == 32000
    assert richer["reserve_deposit_per_unit_cents"] == 4500

    ctx_baseline = setup_option_selected(renewal_option="OPTION_2_OCAF", base=base)
    ctx_richer = setup_option_selected(
        renewal_option="OPTION_2_OCAF",
        clock_date=None,
        base={
            "owner": base["owner"],
            "owner_headers": base["owner_headers"],
            "property": base["property"],
            "contract": richer,
        },
    )

    assert ctx_baseline["case"]["budget_rent_per_unit_cents"] == 105300
    assert ctx_richer["case"]["budget_rent_per_unit_cents"] == 105300, (
        "a 12000-cent higher contract rent moves nothing, because the budget pass never "
        f"reads it, got {ctx_richer['case']['budget_rent_per_unit_cents']}"
    )
    assert ctx_baseline["case"]["ocaf_rent_per_unit_cents"] == 120752
    assert ctx_richer["case"]["ocaf_rent_per_unit_cents"] == 133136, (
        "the operating-cost candidate does read the contract rent: round_half_up(98000 * "
        f"1.032) is 101136 plus 32000, got {ctx_richer['case']['ocaf_rent_per_unit_cents']}"
    )

    leaner = create_contract(
        base["property"]["id"],
        operating_expense_per_unit_cents=60000,
        reserve_deposit_per_unit_cents=4500,
        monthly_debt_service_per_unit_cents=32000,
    )
    ctx_leaner = setup_option_selected(
        renewal_option="OPTION_2_OCAF",
        clock_date=None,
        base={
            "owner": base["owner"],
            "owner_headers": base["owner_headers"],
            "property": base["property"],
            "contract": leaner,
        },
    )
    assert ctx_leaner["case"]["budget_rent_per_unit_cents"] == 104220, (
        "a subtotal of 96500 carries a fee of 7720, summing to 104220, got "
        f"{ctx_leaner['case']['budget_rent_per_unit_cents']}"
    )


def test_option_and_adjustment_elections_are_gated_by_contract_type_and_by_each_other():
    """"A `LOAN_MANAGEMENT_SET_ASIDE` contract admits `OPTION_2_OCAF` and nothing else. ...
    Any other pairing is refused with `ERR_OPTION_NOT_PERMITTED_FOR_TYPE` (HTTP 422)",
    "electing `BUDGET_BASED` on a case whose `renewal_option` is
    `OPTION_1_MARK_UP_TO_MARKET` is refused with `ERR_ADJUSTMENT_METHOD_CONFLICT`", and
    "Approving a `MUTM_ELIGIBLE` determination requires the case's `renewal_option` to be
    `OPTION_1_MARK_UP_TO_MARKET`".

    Design: Corner/endpoints/option_and_adjustment_elections_are_gated_by_contract_type_and_by_each_other
    """
    lmsa = setup_renewal_case(
        contract_overrides={"contract_type": "LOAN_MANAGEMENT_SET_ASIDE"}
    )
    case_a = lmsa["case"]
    validate_error(
        api_client.select_option(
            case_a["id"],
            select_option_payload("OPTION_1_MARK_UP_TO_MARKET"),
            lmsa["owner_headers"],
        ),
        ApiErrorId.ERR_OPTION_NOT_PERMITTED_FOR_TYPE.value,
        expected_status=422,
    )
    still_open = validate_success(api_client.get_renewal_case(case_a["id"], CA_HEADERS))
    assert still_open["renewal_option"] is None, (
        f"the refused election wrote nothing, got {still_open['renewal_option']}"
    )
    assert still_open["rent_track_status"] == "TERMS_PENDING"

    permitted = validate_success(
        api_client.select_option(
            case_a["id"], select_option_payload("OPTION_2_OCAF"), lmsa["owner_headers"]
        )
    )
    assert permitted["renewal_option"] == "OPTION_2_OCAF", (
        "the operating-cost option is the single entry the table gives a loan-management "
        f"set-aside contract, got {permitted['renewal_option']}"
    )
    assert permitted["rent_track_status"] == "OPTION_SELECTED"

    mutm = setup_option_selected(
        renewal_option="OPTION_1_MARK_UP_TO_MARKET", clock_date=None
    )
    case_b = mutm["case"]
    assert case_b["rcs_required"] is True, (
        f"mark-up-to-market makes a study mandatory, got {case_b['rcs_required']}"
    )
    validate_error(
        api_client.elect_adjustment(
            case_b["id"], elect_adjustment_payload("BUDGET_BASED"), mutm["owner_headers"]
        ),
        ApiErrorId.ERR_ADJUSTMENT_METHOD_CONFLICT.value,
        expected_status=422,
    )
    unelected = validate_success(api_client.get_renewal_case(case_b["id"], CA_HEADERS))
    assert unelected["adjustment_method"] is None, (
        "the refused election must leave the one-shot decision available, got "
        f"{unelected['adjustment_method']}"
    )
    retried = validate_success(
        api_client.elect_adjustment(
            case_b["id"], elect_adjustment_payload("OCAF"), mutm["owner_headers"]
        )
    )
    assert retried["adjustment_method"] == "OCAF", (
        "mark-up-to-market admits the operating-cost adjustment factor only, and the "
        f"one-shot election was never consumed, got {retried['adjustment_method']}"
    )

    ocaf_case = setup_case_with_accepted_study(
        renewal_option="OPTION_2_OCAF",
        adjustment_method="OCAF",
        comparables=[MAPLE_COURT],
        clock_date=None,
    )
    assert ocaf_case["case"]["renewal_option"] == "OPTION_2_OCAF"
    assert ocaf_case["case"]["comparable_market_rent_cents"] == 130200
    determination = setup_evaluated_determination(ocaf_case["case"]["id"])
    assert determination["market_rent_per_unit_cents"] == 130200
    assert determination["determination_state"] == "MUTM_ELIGIBLE"
    assert determination["eligibility_reason_code"] == "MARKET_ABOVE_CONTRACT_AND_FMR"

    validate_error(
        api_client.approve_restructuring_determination(determination["id"], HUD_HEADERS),
        ApiErrorId.ERR_MUTM_OPTION_MISMATCH.value,
        expected_status=422,
    )
    unapproved = validate_success(
        api_client.get_restructuring_determination(determination["id"], CA_HEADERS)
    )
    assert unapproved["determination_state"] == "MUTM_ELIGIBLE"
    assert unapproved["post_restructure_rent_per_unit_cents"] is None
    assert unapproved["approved_by_user_id"] is None
