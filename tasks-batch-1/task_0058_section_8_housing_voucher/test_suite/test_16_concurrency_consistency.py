"""Queue B (breadth) — optimistic-concurrency rejections, version increments,
and immediate-consistency of lease-up effects.
"""
from test_helpers import (
    api_client, validate_success, validate_error, validate_error_is_one_of, set_clock,
    create_region, create_landlord, create_unit, create_passed_initial_inspection,
    make_eligible_household, issue_voucher, create_payment_standard,
    setup_active_hap_contract, schedule_annual_inspection, draft_annual_review,
    request_portability_move,
    create_hap_contract_payload, finalize_annual_review_payload,
    CASEWORKER, INSPECTOR, COORDINATOR,
)


def test_occ_stale_voucher_blocks_leaseup():
    """PRD §2.7: "Creating a HAP contract requires the field
    expected_voucher_version, carrying the version of the target voucher as the
    client last read it. If that value does not match the voucher's current
    version — for example, because an approved portability move has since flipped
    the voucher to PORTING_OUT or ABSORBED and bumped its version — the lease-up
    is rejected with ERR_STALE_VERSION (HTTP 412)."

    Design: Corner/cross_cutting_complexity_layers/occ_stale_voucher_blocks_leaseup
    """
    set_clock("2026-06-01T00:00:00Z")
    home = create_region(code="OCC_HOME")
    opp = create_region(code="OCC_OPP")
    create_payment_standard(home["id"], bedroom_size=2, amount_cents=95000, fmr_cents=100000)
    household = make_eligible_household(
        home["id"], family_size=3, annual_income_cents=1800000, dependents_count=2
    )
    voucher = issue_voucher(household["id"])
    stale_version = voucher["version"]
    landlord = create_landlord()
    unit = create_unit(
        landlord["id"], home["id"], bedroom_size=2,
        asking_rent_cents=90000, comparable_rent_cents=90000,
    )
    create_passed_initial_inspection(unit["id"])
    move = request_portability_move(voucher["id"], opp["id"])
    validate_success(api_client.approve_portability_move(move["id"], COORDINATOR), 200)
    resp = api_client.create_hap_contract(
        create_hap_contract_payload(voucher["id"], unit["id"], 90000, stale_version),
        CASEWORKER,
    )
    validate_error(resp, "ERR_STALE_VERSION", 412)


def test_occ_stale_contract_blocks_review_finalize():
    """PRD §2.7: "Finalizing an annual review requires the field
    expected_hap_contract_version ... If that value does not match the contract's
    current version — for example, because a failed annual inspection has since
    abated the contract and bumped its version — the finalization is rejected
    with ERR_STALE_VERSION (HTTP 412)."

    Design: Corner/cross_cutting_complexity_layers/occ_stale_contract_blocks_review_finalize
    """
    scenario, contract = setup_active_hap_contract(
        contract_rent_cents=90000, region_code="OCCB_REG", family_size=3,
        annual_income_cents=1800000, dependents_count=2,
        amount_cents=95000, fmr_cents=100000,
        asking_rent_cents=90000, comparable_rent_cents=90000,
    )
    stale_contract_version = contract["version"]
    review = draft_annual_review(
        contract["id"], new_annual_income_cents=2400000,
        effective_date="2026-07-01T00:00:00Z",
    )
    annual = schedule_annual_inspection(scenario["unit"]["id"], contract["id"])
    validate_success(api_client.fail_inspection(annual["id"], INSPECTOR), 200)
    resp = api_client.finalize_annual_review(
        review["id"], finalize_annual_review_payload(stale_contract_version), CASEWORKER
    )
    # PRD §2.7 names ERR_STALE_VERSION for a finalize against a contract a failed
    # annual inspection has abated, but §2.6's fixed priority order evaluates
    # state-validity (ERR_INVALID_STATE) before the OCC check, and §3.8 requires
    # the linked contract to be ACTIVE — an ABATED contract trips the state gate
    # first. Both readings are PRD-faithful, so accept either.
    validate_error_is_one_of(resp, ["ERR_STALE_VERSION", "ERR_INVALID_STATE"])


def test_voucher_version_increments_on_portability_absorption():
    """PRD §3.7: "Either approval bumps the voucher's version as part of the
    cascade, which is the very advance that can later strand a stale lease-up
    writer under the optimistic-concurrency rule of Section 2.7." An ABSORPTION
    approval advances the version and sets the voucher ABSORBED.

    Design: Corner/cross_cutting_complexity_layers/voucher_version_increments_on_portability_approve
    """
    home = create_region(code="VV_HOME")
    opp = create_region(code="VV_OPP", is_special_mobility_area=True)
    household = make_eligible_household(home["id"], family_size=2, annual_income_cents=1500000)
    voucher = issue_voucher(household["id"])
    move = request_portability_move(voucher["id"], opp["id"])
    validate_success(api_client.approve_portability_move(move["id"], COORDINATOR), 200)
    v = validate_success(api_client.get_voucher(voucher["id"], COORDINATOR), 200)
    assert v["version"] == 2
    assert v["status"] == "ABSORBED"


def test_leaseup_effects_visible_in_same_request():
    """PRD §3.5: "On success the contract is created in ACTIVE status, the
    voucher advances to LEASED, the household advances to LEASED". The computed
    subsidy and the LEASED states are visible immediately. Family 3 gross
    1,800,000 with 2 dependents -> subsidy 47,400.

    Design: Corner/consistency_model/leaseup_all_effects_visible_in_same_request
    """
    from test_helpers import setup_leaseup_ready
    scenario = setup_leaseup_ready(
        region_code="CM_REG", family_size=3, annual_income_cents=1800000,
        dependents_count=2, bedroom_size=2, amount_cents=95000, fmr_cents=100000,
        asking_rent_cents=90000, comparable_rent_cents=90000,
    )
    contract = validate_success(
        api_client.create_hap_contract(
            create_hap_contract_payload(
                scenario["voucher"]["id"], scenario["unit"]["id"], 90000,
                scenario["voucher_version"],
            ),
            CASEWORKER,
        ),
        201,
    )
    assert contract["hap_subsidy_cents"] == 47400
    voucher = validate_success(api_client.get_voucher(scenario["voucher"]["id"], CASEWORKER), 200)
    household = validate_success(api_client.get_household(scenario["household"]["id"], CASEWORKER), 200)
    assert voucher["status"] == "LEASED"
    assert household["status"] == "LEASED"
