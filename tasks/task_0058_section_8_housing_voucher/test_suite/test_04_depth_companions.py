"""Queue A (depth) — companion tests giving every difficulty instance its
second covering test. Each asserts the same PRD rule via a distinct observable
or the adjacent boundary, and carries the same Design tag as its sibling.
"""
from test_helpers import (
    api_client, validate_success, validate_error, set_clock,
    setup_leaseup_ready, setup_active_hap_contract, setup_abated_contract,
    schedule_annual_inspection, create_region, make_eligible_household,
    issue_voucher, create_landlord, create_unit, create_payment_standard,
    create_hap_contract_payload, create_rent_reasonableness_payload,
    create_voucher_payload, create_household, request_portability_move,
    grant_special_mobility,
    CASEWORKER, INSPECTOR, ADMIN, COORDINATOR,
)


def _lease_up(scenario, contract_rent_cents):
    return api_client.create_hap_contract(
        create_hap_contract_payload(
            scenario["voucher"]["id"], scenario["unit"]["id"],
            contract_rent_cents, scenario["voucher_version"],
        ),
        CASEWORKER,
    )


# ── dual_variant_calc companions ───────────────────────────


def test_ttp_floor_also_sets_tenant_burden_equal_to_ttp():
    """PRD §3.5: "Finally the contract's tenant_rent_burden_cents is the
    contract_rent_cents minus the hap_subsidy_cents — the tenant's full
    out-of-pocket share." With contract 90,000 and subsidy 47,400 the burden is
    42,600, equal to the TTP for a gross subsidy.

    Design: Difficulty/dual_variant_calc/ttp_max_floor_30pct_vs_10pct_gross
    """
    scenario = setup_leaseup_ready(
        region_code="MN_COMP", family_size=3, annual_income_cents=1800000,
        dependents_count=2, bedroom_size=2, amount_cents=95000, fmr_cents=100000,
        asking_rent_cents=90000, comparable_rent_cents=90000,
    )
    contract = validate_success(_lease_up(scenario, 90000), 201)
    assert contract["tenant_rent_burden_cents"] == 42600


def test_gross_subsidy_when_contract_at_or_below_standard():
    """PRD §3.5: "when the contract rent is at or below the payment standard the
    capped rent equals the contract rent (a gross subsidy)". Family of 4 with
    contract 95,000 == ps 95,000: capped rent is the contract rent, subsidy
    20,000 (95,000 - 75,000 TTP).

    Design: Difficulty/dual_variant_calc/subsidy_capped_by_payment_standard_vs_gross
    """
    scenario = setup_leaseup_ready(
        region_code="OPP_COMP", family_size=4, annual_income_cents=3000000,
        bedroom_size=2, amount_cents=95000, fmr_cents=100000,
        asking_rent_cents=95000, comparable_rent_cents=95000,
    )
    contract = validate_success(_lease_up(scenario, 95000), 201)
    assert contract["total_tenant_payment_cents"] == 75000
    assert contract["hap_subsidy_cents"] == 20000


# ── combinatorial_formula companions ───────────────────────


def test_ten_pct_gross_floor_also_drives_burden():
    """PRD §3.5: "Finally the contract's tenant_rent_burden_cents is the
    contract_rent_cents minus the hap_subsidy_cents." With contract 60,000 and
    subsidy 35,000 the burden is 25,000, equal to the 10%-of-gross TTP.

    Design: Difficulty/combinatorial_formula/ttp_three_input_nonlinear_max_floor
    """
    scenario = setup_leaseup_ready(
        region_code="WE_COMP", family_size=2, annual_income_cents=3000000,
        childcare_expense_cents=2250000, bedroom_size=1,
        amount_cents=60000, fmr_cents=60000,
        asking_rent_cents=60000, comparable_rent_cents=60000,
    )
    contract = validate_success(_lease_up(scenario, 60000), 201)
    assert contract["tenant_rent_burden_cents"] == 25000


def test_subsidy_floor_when_contract_below_standard_uses_contract():
    """PRD §3.5: "when the contract rent is at or below the payment standard the
    capped rent equals the contract rent (a gross subsidy)". Studio contract
    39,000 below ps 40,000 -> capped rent equals the contract, total tenant
    payment 15,000 stored unchanged.

    Design: Difficulty/combinatorial_formula/subsidy_pinned_eval_order_cap_then_subtract_then_floor
    """
    scenario = setup_leaseup_ready(
        region_code="ES_COMP", family_size=1, annual_income_cents=600000,
        bedroom_size=0, amount_cents=40000, fmr_cents=40000,
        asking_rent_cents=39000, comparable_rent_cents=39000,
    )
    contract = validate_success(_lease_up(scenario, 39000), 201)
    assert contract["total_tenant_payment_cents"] == 15000


# ── non_linear_state_machine companions ────────────────────


def test_cure_cascades_unit_back_to_under_contract():
    """PRD §3.6: "the contract is restored from ABATED to ACTIVE ... and the
    linked unit is cascaded back to UNDER_CONTRACT." The cure half of the
    ACTIVE->ABATED->ACTIVE cycle restores the unit.

    Design: Difficulty/non_linear_state_machine/inspection_fail_then_cure_cycle_on_hap_contract
    """
    scenario = setup_abated_contract(
        family_size=3, annual_income_cents=1800000, dependents_count=2,
        amount_cents=95000, fmr_cents=100000,
        asking_rent_cents=90000, comparable_rent_cents=90000,
    )
    set_clock("2026-06-20T00:00:00Z")
    validate_success(api_client.cure_inspection(scenario["annual_inspection"]["id"], INSPECTOR), 200)
    unit = validate_success(api_client.get_unit(scenario["unit"]["id"], INSPECTOR), 200)
    assert unit["status"] == "UNDER_CONTRACT"


def test_billing_branch_leaves_issuing_region_unchanged():
    """PRD §3.7: "When the mode is BILLING, the move's billing_mode is set to
    BILLING, the move advances from REQUESTED -> APPROVED, and the voucher
    cascades from ISSUED -> PORTING_OUT; the voucher's issuing_region_id is left
    unchanged". The BILLING fork is the divergent counterpart to ABSORPTION.

    Design: Difficulty/non_linear_state_machine/portability_branch_billing_vs_absorption_on_voucher
    """
    home = create_region(code="HOME_BIL")
    dest = create_region(code="DEST_BIL", is_special_mobility_area=False)
    household = make_eligible_household(home["id"], family_size=2, annual_income_cents=1500000)
    voucher = issue_voucher(household["id"])
    move = request_portability_move(voucher["id"], dest["id"])
    pm = validate_success(api_client.approve_portability_move(move["id"], COORDINATOR), 200)
    assert pm["billing_mode"] == "BILLING"
    assert pm["status"] == "APPROVED"
    v = validate_success(api_client.get_voucher(voucher["id"], COORDINATOR), 200)
    assert v["status"] == "PORTING_OUT"
    assert v["issuing_region_id"] == home["id"]


# ── transitive_cascade companions ──────────────────────────


def test_fail_cure_also_marks_inspection_abated():
    """PRD §3.4: "this system operation ... moves the inspection from FAILED to
    ABATED and triggers the contract's termination cascade." The terminal
    inspection state is the head of the depth-3 chain.

    Design: Difficulty/transitive_cascade/failcure_terminates_contract_voucher_household_depth3
    """
    scenario = setup_abated_contract(
        family_size=3, annual_income_cents=1800000, dependents_count=2,
        amount_cents=95000, fmr_cents=100000,
        asking_rent_cents=90000, comparable_rent_cents=90000,
    )
    annual = scenario["annual_inspection"]
    set_clock("2026-07-01T00:00:00Z")
    validate_success(api_client.fail_cure_inspection(annual["id"], ADMIN), 200)
    insp = validate_success(api_client.get_inspection(annual["id"], ADMIN), 200)
    assert insp["status"] == "ABATED"


def test_annual_fail_also_zeros_subsidy_on_abatement():
    """PRD §3.6: "it moves from ACTIVE to ABATED, its hap_subsidy_cents is set to
    zero so no subsidy is paid while the deficiency stands". The depth-2 chain's
    money side effect on the contract.

    Design: Difficulty/transitive_cascade/annual_fail_abates_contract_and_flips_unit_depth2
    """
    scenario, contract = setup_active_hap_contract(
        contract_rent_cents=90000, family_size=3, annual_income_cents=1800000,
        dependents_count=2, amount_cents=95000, fmr_cents=100000,
        asking_rent_cents=90000, comparable_rent_cents=90000,
    )
    annual = schedule_annual_inspection(scenario["unit"]["id"], contract["id"])
    validate_success(api_client.fail_inspection(annual["id"], INSPECTOR), 200)
    c = validate_success(api_client.get_hap_contract(contract["id"], CASEWORKER), 200)
    assert c["status"] == "ABATED"
    assert c["hap_subsidy_cents"] == 0


# ── compensating_invariant companions ──────────────────────


def test_mobility_grant_extends_expiration_before_revoke():
    """PRD §3.8: "The grant is created in GRANTED status and, as a side effect,
    extends the linked voucher's expiration_date by the granted
    term_extension_days." The forward leg of the conserved-time invariant must
    actually move the expiration before the revoke restores it.

    Design: Difficulty/compensating_invariant/mobility_grant_revoke_restores_voucher_expiration
    """
    set_clock("2026-06-01T00:00:00Z")
    home = create_region(code="SM_HOMEB")
    opp = create_region(code="SM_OPPB", is_special_mobility_area=True)
    household = make_eligible_household(
        home["id"], family_size=3, annual_income_cents=1800000, dependents_count=2
    )
    voucher = issue_voucher(household["id"], term_days=60)
    exp0 = voucher["expiration_date"]
    grant_special_mobility(voucher["id"], opp["id"], term_extension_days=30)
    v = validate_success(api_client.get_voucher(voucher["id"], COORDINATOR), 200)
    assert v["expiration_date"] != exp0


def test_abate_zeros_subsidy_before_cure_restores_it():
    """PRD §3.6: "its hap_subsidy_cents is set to zero so no subsidy is paid
    while the deficiency stands". The conserved-money invariant requires the
    subsidy to be 0 during abatement before the cure restores 47,400.

    Design: Difficulty/compensating_invariant/abate_then_cure_restores_subsidy_money_invariant
    """
    scenario = setup_abated_contract(
        family_size=3, annual_income_cents=1800000, dependents_count=2,
        amount_cents=95000, fmr_cents=100000,
        asking_rent_cents=90000, comparable_rent_cents=90000,
    )
    c = validate_success(
        api_client.get_hap_contract(scenario["contract"]["id"], CASEWORKER), 200
    )
    assert c["status"] == "ABATED"
    assert c["hap_subsidy_cents"] == 0


# ── priority_pair_validation_conflict companions ───────────


def test_expired_voucher_error_is_422_status():
    """PRD §3.5: "a voucher whose expiration date is at or before the current UTC
    is rejected with ERR_VOUCHER_EXPIRED (HTTP 422)." The temporal gate wins the
    priority conflict and returns HTTP 422.

    Design: Difficulty/priority_pair_validation_conflict/expired_voucher_vs_rent_not_reasonable_temporal_beats_constraint
    """
    scenario = setup_leaseup_ready(
        region_code="PRI_REGAB", family_size=3, annual_income_cents=1800000,
        dependents_count=2, bedroom_size=2, amount_cents=95000, fmr_cents=100000,
        asking_rent_cents=200000, comparable_rent_cents=90000, term_days=60,
        clock="2026-06-01T00:00:00Z",
    )
    set_clock("2026-09-01T00:00:00Z")
    resp = api_client.create_hap_contract(
        create_hap_contract_payload(
            scenario["voucher"]["id"], scenario["unit"]["id"], 200000,
            scenario["voucher_version"],
        ),
        CASEWORKER,
    )
    assert resp.status_code == 422, resp.text


def test_inspection_gate_returns_422_over_fiscal():
    """PRD §3.5: "lease-up without one is rejected with ERR_INSPECTION_NOT_PASSED
    (HTTP 422)." The safety gate (priority earlier than the fiscal burden gate)
    returns HTTP 422.

    Design: Difficulty/priority_pair_validation_conflict/inspection_not_passed_vs_rent_burden_safety_beats_fiscal
    """
    set_clock("2026-06-01T00:00:00Z")
    region = create_region(code="PRI_REGBB")
    create_payment_standard(region["id"], bedroom_size=0, amount_cents=40000, fmr_cents=40000)
    household = make_eligible_household(region["id"], family_size=1, annual_income_cents=600000)
    voucher = issue_voucher(household["id"])
    landlord = create_landlord()
    unit = create_unit(
        landlord["id"], region["id"], bedroom_size=0,
        asking_rent_cents=70000, comparable_rent_cents=70000,
    )
    resp = api_client.create_hap_contract(
        create_hap_contract_payload(voucher["id"], unit["id"], 70000, voucher["version"]),
        CASEWORKER,
    )
    assert resp.status_code == 422, resp.text


# ── boundary_precision_check companions ────────────────────


def test_rent_reasonableness_above_comparable_is_not_reasonable():
    """PRD §3.1: "the outcome is REASONABLE when the requested_rent_cents is less
    than or equal to that snapshotted comparable rent, with the boundary
    inclusive, and NOT_REASONABLE otherwise." Requested 90,001 > comparable
    90,000 -> NOT_REASONABLE (the X+1 boundary companion).

    Design: Difficulty/boundary_precision_check/rent_reasonableness_inclusive_equal_passes
    """
    region = create_region(code="BND_REGAB")
    landlord = create_landlord()
    unit = create_unit(
        landlord["id"], region["id"], bedroom_size=2,
        asking_rent_cents=90000, comparable_rent_cents=90000,
    )
    det = validate_success(
        api_client.create_rent_reasonableness(
            create_rent_reasonableness_payload(unit["id"], requested_rent_cents=90001),
            CASEWORKER,
        ),
        201,
    )
    assert det["outcome"] == "NOT_REASONABLE"


def test_list_vouchers_empty_set_has_more_false():
    """PRD §2.3: "Every list response includes the following fields in the meta
    object: limit, offset, total_count, and has_more." An empty filtered voucher
    list reports has_more false alongside total_count 0.

    Design: Difficulty/boundary_precision_check/list_vouchers_empty_set_for_unused_region
    """
    region = create_region(code="BND_REGBB")
    resp = api_client.list_vouchers(CASEWORKER, params={"issuing_region_id": region["id"]})
    assert resp.status_code == 200, resp.text
    meta = resp.json()["meta"]
    assert meta["total_count"] == 0
    assert meta["has_more"] is False


# ── cross_entity_state_dependency companions ───────────────


def test_leaseup_succeeds_once_initial_inspection_passed():
    """PRD §3.5: "Fourth, the unit must have a passed initial inspection: there
    must exist a PASSED inspection of type INITIAL for the unit". With the
    INITIAL inspection passed, the Voucher ISSUED->LEASED transition succeeds.

    Design: Difficulty/cross_entity_state_dependency/leaseup_requires_unit_initial_inspection_passed
    """
    scenario = setup_leaseup_ready(
        region_code="CESD_REGAB", family_size=3, annual_income_cents=1800000,
        dependents_count=2, bedroom_size=2, amount_cents=95000, fmr_cents=100000,
        asking_rent_cents=90000, comparable_rent_cents=90000,
    )
    contract = validate_success(_lease_up(scenario, 90000), 201)
    voucher = validate_success(api_client.get_voucher(scenario["voucher"]["id"], CASEWORKER), 200)
    assert contract["status"] == "ACTIVE"
    assert voucher["status"] == "LEASED"


def test_voucher_issuance_succeeds_for_eligible_household():
    """PRD §3.3: "A Caseworker issues a voucher to a household that has reached
    ELIGIBLE status ... On success the voucher is created in ISSUED status and
    the household advances from ELIGIBLE to VOUCHER_ISSUED." The positive
    counterpart to the not-eligible rejection.

    Design: Difficulty/cross_entity_state_dependency/voucher_issuance_requires_household_eligible
    """
    region = create_region(code="CESD_REGBB")
    household = make_eligible_household(region["id"], family_size=3, annual_income_cents=1800000)
    voucher = validate_success(
        api_client.create_voucher(create_voucher_payload(household["id"]), CASEWORKER), 201
    )
    assert voucher["status"] == "ISSUED"
    hh = validate_success(api_client.get_household(household["id"], CASEWORKER), 200)
    assert hh["status"] == "VOUCHER_ISSUED"


# ── resource_temporal_overlap companions ───────────────────


def test_cure_one_day_after_deadline_is_rejected():
    """PRD §3.4: "a cure attempted after the deadline is rejected with
    ERR_CURE_DEADLINE_PASSED (HTTP 422)." One day past the 2026-06-29 deadline
    (the open-right adjacency) is rejected — companion to the inclusive boundary.

    Design: Difficulty/resource_temporal_overlap/cure_within_deadline_inclusive_boundary
    """
    scenario = setup_abated_contract(
        family_size=3, annual_income_cents=1800000, dependents_count=2,
        amount_cents=95000, fmr_cents=100000,
        asking_rent_cents=90000, comparable_rent_cents=90000,
        annual_scheduled_date="2026-06-15T00:00:00Z",
    )
    set_clock("2026-06-30T00:00:00Z")
    validate_error(
        api_client.cure_inspection(scenario["annual_inspection"]["id"], INSPECTOR),
        "ERR_CURE_DEADLINE_PASSED", 422,
    )


def test_leaseup_one_second_before_expiration_succeeds():
    """PRD §3.5: "the server's current UTC must be strictly before the voucher's
    expiration_date". At one day before the 2026-07-31 expiration the lease-up
    succeeds — the inside-the-window companion to the at-instant rejection.

    Design: Difficulty/resource_temporal_overlap/voucher_expiration_open_right_boundary_blocks_leaseup
    """
    scenario = setup_leaseup_ready(
        region_code="OVL_REGBB", family_size=3, annual_income_cents=1800000,
        dependents_count=2, bedroom_size=2, amount_cents=95000, fmr_cents=100000,
        asking_rent_cents=90000, comparable_rent_cents=90000, term_days=60,
        clock="2026-06-01T00:00:00Z",
    )
    set_clock("2026-07-30T00:00:00Z")
    contract = validate_success(_lease_up(scenario, 90000), 201)
    assert contract["status"] == "ACTIVE"
