"""Queue A (depth) — non-linear state machines, transitive cascades, and
conserved-quantity invariants around the annual inspection lifecycle.
"""
from test_helpers import (
    api_client, validate_success, set_clock,
    setup_active_hap_contract, setup_abated_contract, schedule_annual_inspection,
    setup_leaseup_ready, grant_special_mobility, lease_up,
    CASEWORKER, INSPECTOR, ADMIN, COORDINATOR,
)


# ── rule: non_linear_state_machine ─────────────────────────


def test_annual_fail_then_cure_cycles_contract_active_again():
    """PRD §3.6: "When a timely cure is recorded against the failed inspection
    (the inspection moving FAILED -> CURED) and the contract is currently
    ABATED, the contract is restored from ABATED to ACTIVE, its hap_subsidy_cents
    is recomputed by re-running the subsidy calculation of Section 3.5 ... and
    the linked unit is cascaded back to UNDER_CONTRACT."

    Design: Difficulty/non_linear_state_machine/inspection_fail_then_cure_cycle_on_hap_contract
    """
    scenario = setup_abated_contract(
        family_size=3, annual_income_cents=1800000, dependents_count=2,
        amount_cents=95000, fmr_cents=100000,
        asking_rent_cents=90000, comparable_rent_cents=90000,
        annual_scheduled_date="2026-06-15T00:00:00Z",
    )
    annual = scenario["annual_inspection"]
    set_clock("2026-06-20T00:00:00Z")
    validate_success(api_client.cure_inspection(annual["id"], INSPECTOR), 200)
    contract = validate_success(
        api_client.get_hap_contract(scenario["contract"]["id"], CASEWORKER), 200
    )
    assert contract["status"] == "ACTIVE"
    assert contract["hap_subsidy_cents"] == 47400
    insp = validate_success(api_client.get_inspection(annual["id"], INSPECTOR), 200)
    assert insp["status"] == "CURED"


def test_portability_approval_branches_to_absorption_on_mobility_region():
    """PRD §3.7: "When the mode is ABSORPTION, the move's billing_mode is set to
    ABSORPTION, the move advances from REQUESTED -> ABSORBED, and the voucher
    cascades from ISSUED -> ABSORBED with its issuing_region_id reset to the
    move's receiving_region_id."

    Design: Difficulty/non_linear_state_machine/portability_branch_billing_vs_absorption_on_voucher
    """
    from test_helpers import create_region, make_eligible_household, issue_voucher, \
        request_portability_move
    home = create_region(code="HOME_REG")
    opp = create_region(code="OPP_REG", is_special_mobility_area=True)
    household = make_eligible_household(
        home["id"], family_size=3, annual_income_cents=1800000, dependents_count=2
    )
    voucher = issue_voucher(household["id"])
    move = request_portability_move(voucher["id"], opp["id"])
    pm = validate_success(api_client.approve_portability_move(move["id"], COORDINATOR), 200)
    assert pm["billing_mode"] == "ABSORPTION"
    assert pm["status"] == "ABSORBED"
    v = validate_success(api_client.get_voucher(voucher["id"], COORDINATOR), 200)
    assert v["status"] == "ABSORBED"
    assert v["issuing_region_id"] == opp["id"]


# ── rule: transitive_cascade ───────────────────────────────


def test_fail_cure_terminates_contract_voucher_household():
    """PRD §3.6: "When a ProgramAdmin records the post-deadline failure on an
    ABATED contract ... the contract moves from ABATED to TERMINATED, the linked
    voucher is set to TERMINATED, and the linked household is set to TERMINATED
    as a cascade of that cascade."

    Design: Difficulty/transitive_cascade/failcure_terminates_contract_voucher_household_depth3
    """
    scenario = setup_abated_contract(
        family_size=3, annual_income_cents=1800000, dependents_count=2,
        amount_cents=95000, fmr_cents=100000,
        asking_rent_cents=90000, comparable_rent_cents=90000,
        annual_scheduled_date="2026-06-15T00:00:00Z",
    )
    annual = scenario["annual_inspection"]
    set_clock("2026-07-01T00:00:00Z")
    validate_success(api_client.fail_cure_inspection(annual["id"], ADMIN), 200)
    contract = validate_success(
        api_client.get_hap_contract(scenario["contract"]["id"], ADMIN), 200
    )
    voucher = validate_success(api_client.get_voucher(scenario["voucher"]["id"], ADMIN), 200)
    household = validate_success(
        api_client.get_household(scenario["household"]["id"], ADMIN), 200
    )
    assert contract["status"] == "TERMINATED"
    assert voucher["status"] == "TERMINATED"
    assert household["status"] == "TERMINATED"


def test_annual_fail_abates_contract_and_flips_unit_off_market():
    """PRD §3.6: "When an annual inspection of an ACTIVE contract is failed, the
    contract enters abatement: it moves from ACTIVE to ABATED, its
    hap_subsidy_cents is set to zero so no subsidy is paid while the deficiency
    stands, and the linked unit is cascaded to OFF_MARKET."

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
    unit = validate_success(api_client.get_unit(scenario["unit"]["id"], INSPECTOR), 200)
    assert c["status"] == "ABATED"
    assert c["hap_subsidy_cents"] == 0
    assert unit["status"] == "OFF_MARKET"


# ── rule: compensating_invariant ───────────────────────────


def test_mobility_grant_revoke_restores_expiration_date():
    """PRD §3.8: "A PortabilityCoordinator may instead revoke a GRANTED grant,
    moving it GRANTED -> REVOKED and rolling back the incentive by subtracting
    the term_extension_days back off the linked voucher's expiration_date."
    A 30-day grant then revoke leaves the expiration at its pre-grant value.

    Design: Difficulty/compensating_invariant/mobility_grant_revoke_restores_voucher_expiration
    """
    from test_helpers import create_region, make_eligible_household, issue_voucher
    set_clock("2026-06-01T00:00:00Z")
    home = create_region(code="SM_HOME")
    opp = create_region(code="SM_OPP", is_special_mobility_area=True)
    household = make_eligible_household(
        home["id"], family_size=3, annual_income_cents=1800000, dependents_count=2
    )
    voucher = issue_voucher(household["id"], term_days=60)
    exp0 = voucher["expiration_date"]
    grant = grant_special_mobility(voucher["id"], opp["id"], term_extension_days=30)
    g = validate_success(
        api_client.revoke_special_mobility_grant(grant["id"], COORDINATOR), 200
    )
    assert g["status"] == "REVOKED"
    v = validate_success(api_client.get_voucher(voucher["id"], COORDINATOR), 200)
    assert v["expiration_date"] == exp0


def test_abate_then_cure_restores_subsidy_money_invariant():
    """PRD §3.6: "When a timely cure is recorded against the failed inspection
    (the inspection moving FAILED -> CURED) and the contract is currently
    ABATED, the contract is restored from ABATED to ACTIVE, its hap_subsidy_cents
    is recomputed by re-running the subsidy calculation of Section 3.5." The
    cure restores the subsidy to its exact pre-abatement value 47,400.

    Design: Difficulty/compensating_invariant/abate_then_cure_restores_subsidy_money_invariant
    """
    scenario = setup_abated_contract(
        family_size=3, annual_income_cents=1800000, dependents_count=2,
        amount_cents=95000, fmr_cents=100000,
        asking_rent_cents=90000, comparable_rent_cents=90000,
        annual_scheduled_date="2026-06-15T00:00:00Z",
    )
    annual = scenario["annual_inspection"]
    set_clock("2026-06-20T00:00:00Z")
    validate_success(api_client.cure_inspection(annual["id"], INSPECTOR), 200)
    contract = validate_success(
        api_client.get_hap_contract(scenario["contract"]["id"], CASEWORKER), 200
    )
    assert contract["hap_subsidy_cents"] == 47400
    assert contract["status"] == "ACTIVE"
