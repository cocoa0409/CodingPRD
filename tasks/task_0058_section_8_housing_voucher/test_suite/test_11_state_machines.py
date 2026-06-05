"""Queue B (breadth) — state-machine transitions, terminal lockdown, initial
states, valid branches, and precondition enforcement.
"""
from test_helpers import (
    api_client, validate_success, validate_error, set_clock,
    create_region, create_landlord, create_unit, create_passed_initial_inspection,
    make_eligible_household, issue_voucher, request_portability_move,
    setup_active_hap_contract, setup_abated_contract,
    create_inspection_payload, create_voucher_payload,
    CASEWORKER, INSPECTOR, COORDINATOR, ADMIN,
)


def test_pass_already_passed_inspection_invalid_state():
    """PRD §3.4: "Passing a scheduled inspection moves it to PASSED". PRD §2.8:
    "the target's state validity comes fourth, yielding ERR_INVALID_STATE
    (HTTP 409) when the resource is not in a state from which the requested
    transition is legal." A second pass on a PASSED inspection is rejected.

    Design: Corner/state_machines/pass_inspection_from_passed_invalid_transition
    """
    region = create_region(code="SMA")
    landlord = create_landlord(name="LLs", payee_account="acct-s")
    unit = create_unit(
        landlord["id"], region["id"], bedroom_size=1,
        asking_rent_cents=80000, comparable_rent_cents=80000,
    )
    insp = create_passed_initial_inspection(unit["id"])
    validate_error(
        api_client.pass_inspection(insp["id"], INSPECTOR), "ERR_INVALID_STATE", 409
    )


def test_terminate_already_terminated_contract_invalid_state():
    """PRD §3.5: "A standing contract can be terminated by a Caseworker.
    Terminating an ACTIVE contract moves it to TERMINATED". PRD §2.8: a
    transition from an illegal state yields ERR_INVALID_STATE (HTTP 409).

    Design: Corner/state_machines/terminal_terminated_contract_no_further_transition
    """
    scenario, contract = setup_active_hap_contract(
        contract_rent_cents=90000, family_size=3, annual_income_cents=1800000,
        dependents_count=2, amount_cents=95000, fmr_cents=100000,
        asking_rent_cents=90000, comparable_rent_cents=90000,
    )
    validate_success(api_client.terminate_hap_contract(contract["id"], CASEWORKER), 200)
    validate_error(
        api_client.terminate_hap_contract(contract["id"], CASEWORKER),
        "ERR_INVALID_STATE", 409,
    )


def test_voucher_initial_state_is_issued():
    """PRD §3.3: "On success the voucher is created in ISSUED status and the
    household advances from ELIGIBLE to VOUCHER_ISSUED."

    Design: Corner/state_machines/voucher_initial_state_issued
    """
    region = create_region(code="SMC")
    household = make_eligible_household(region["id"], family_size=2, annual_income_cents=1500000)
    voucher = validate_success(
        api_client.create_voucher(create_voucher_payload(household["id"]), CASEWORKER), 201
    )
    assert voucher["status"] == "ISSUED"


def test_portability_deny_branch_marks_denied():
    """PRD §3.7: "Denial, permitted whenever the move is REQUESTED, simply moves
    it REQUESTED -> DENIED." The voucher remains ISSUED.

    Design: Corner/state_machines/portability_deny_branch_marks_denied
    """
    home = create_region(code="SMD_HOME")
    dest = create_region(code="SMD_DEST")
    household = make_eligible_household(home["id"], family_size=2, annual_income_cents=1500000)
    voucher = issue_voucher(household["id"])
    move = request_portability_move(voucher["id"], dest["id"])
    pm = validate_success(api_client.deny_portability_move(move["id"], COORDINATOR), 200)
    assert pm["status"] == "DENIED"
    v = validate_success(api_client.get_voucher(voucher["id"], COORDINATOR), 200)
    assert v["status"] == "ISSUED"


def test_portability_billing_branch_marks_porting_out():
    """PRD §3.7: "When the mode is BILLING, the move's billing_mode is set to
    BILLING, the move advances from REQUESTED -> APPROVED, and the voucher
    cascades from ISSUED -> PORTING_OUT; the voucher's issuing_region_id is left
    unchanged".

    Design: Corner/state_machines/portability_billing_branch_marks_porting_out
    """
    home = create_region(code="BIL_HOME")
    dest = create_region(code="BIL_DEST", is_special_mobility_area=False)
    household = make_eligible_household(home["id"], family_size=2, annual_income_cents=1500000)
    voucher = issue_voucher(household["id"])
    move = request_portability_move(voucher["id"], dest["id"])
    pm = validate_success(api_client.approve_portability_move(move["id"], COORDINATOR), 200)
    assert pm["billing_mode"] == "BILLING"
    assert pm["status"] == "APPROVED"
    v = validate_success(api_client.get_voucher(voucher["id"], COORDINATOR), 200)
    assert v["status"] == "PORTING_OUT"
    assert v["issuing_region_id"] == home["id"]


def test_initial_inspection_pass_marks_unit_under_contract():
    """PRD §3.4: "Passing a scheduled inspection moves it to PASSED; if the
    inspection was of type INITIAL, passing also marks the linked unit
    UNDER_CONTRACT."

    Design: Corner/state_machines/initial_inspection_pass_marks_unit_under_contract
    """
    region = create_region(code="SEA")
    landlord = create_landlord(name="LLse", payee_account="acct-se")
    unit = create_unit(
        landlord["id"], region["id"], bedroom_size=1,
        asking_rent_cents=80000, comparable_rent_cents=80000,
    )
    insp = validate_success(
        api_client.create_inspection(
            create_inspection_payload(unit["id"], inspection_type="INITIAL"), INSPECTOR
        ),
        201,
    )
    passed = validate_success(api_client.pass_inspection(insp["id"], INSPECTOR), 200)
    assert passed["status"] == "PASSED"
    u = validate_success(api_client.get_unit(unit["id"], INSPECTOR), 200)
    assert u["status"] == "UNDER_CONTRACT"


def test_cure_after_deadline_returns_error():
    """PRD §3.4: "a cure attempted after the deadline is rejected with
    ERR_CURE_DEADLINE_PASSED (HTTP 422)." Curing strictly after the 2026-06-29
    deadline is rejected.

    Design: Corner/state_machines/cure_after_deadline_invalid_returns_error
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
