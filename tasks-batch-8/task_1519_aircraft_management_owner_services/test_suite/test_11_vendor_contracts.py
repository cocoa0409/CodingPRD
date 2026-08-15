"""Vendor contract negotiation cycle and terminal-state lockdown (PRD §3.7)."""
from test_helpers import (
    validate_success, validate_error,
    setup_owner_and_aircraft, create_contract, create_contract_payload,
    TEST_USERS,
)

AE = TEST_USERS["account_executive_headers"]
CM = TEST_USERS["contracts_manager_headers"]


def test_contract_counter_after_execute_rejected(api):
    """PRD §3.7: "Recording a vendor counter-offer moves a `PROPOSED` contract
    to `COUNTERED` and replaces `rate_cents_per_unit` with the countered value,
    which is required on the counter action."
    PRD §3.7: "Any of these transitions attempted from the wrong status is
    `ERR_CONTRACT_INVALID_STATE`."

    Design: Corner/state_machines/contract_counter_after_execute_rejected
    """
    _owner, aircraft = setup_owner_and_aircraft(tail_number="N270JX")
    contract = create_contract(aircraft["id"], vendor_kind="HANGAR",
                               vendor_name="Teterboro Hangars", unit="MONTH",
                               rate_cents_per_unit=4500000)
    validate_success(api.propose_contract(contract["id"], {}, CM), 200)
    executed = validate_success(api.execute_contract(contract["id"], AE), 200)
    assert executed["status"] == "EXECUTED"

    res = api.counter_contract(
        contract["id"], {"rate_cents_per_unit": 4300000}, CM
    )
    validate_error(res, "ERR_CONTRACT_INVALID_STATE", expected_status=409)

    current = validate_success(api.get_contract(contract["id"], CM), 200)
    assert current["status"] == "EXECUTED"
    assert current["rate_cents_per_unit"] == 4500000


def _setup_draft_fuel_contract(api):
    """Owner + aircraft + DRAFT FUEL contract at rate 500."""
    _owner, aircraft = setup_owner_and_aircraft(tail_number="N700JX")
    contract = create_contract(
        aircraft["id"], vendor_kind="FUEL", vendor_name="JetFuel Co",
        unit="GALLON", rate_cents_per_unit=500,
        term_start="2026-09-01", term_end="2027-08-31",
    )
    return contract


def test_contract_negotiation_cycle_executes_reproposed_rate(api):
    """PRD §3.7: "Proposing moves a `DRAFT` contract to `PROPOSED`; the same
    propose action re-proposes revised terms from `COUNTERED` back to
    `PROPOSED`. On either flavor of propose, `rate_cents_per_unit` is replaced
    by the request value when supplied."
    PRD §3.7: "Execution — an `AccountExecutive` privilege — moves a contract
    from `PROPOSED` or `COUNTERED` to `EXECUTED` at the currently proposed
    terms."

    Design: Difficulty/non_linear_state_machine/vendor_contract_counter_reproposal_cycle
    """
    contract = _setup_draft_fuel_contract(api)

    validate_success(api.propose_contract(contract["id"], {}, CM), 200)
    validate_success(
        api.counter_contract(contract["id"], {"rate_cents_per_unit": 450}, CM), 200
    )
    validate_success(
        api.propose_contract(contract["id"], {"rate_cents_per_unit": 470}, CM), 200
    )
    executed = validate_success(api.execute_contract(contract["id"], AE), 200)
    assert executed["status"] == "EXECUTED"
    assert executed["rate_cents_per_unit"] == 470, (
        f"execution lands at the re-proposed rate, got "
        f"{executed['rate_cents_per_unit']}"
    )


def test_contract_counter_and_reproposal_intermediate_terms(api):
    """PRD §3.7: "Recording a vendor counter-offer moves a `PROPOSED` contract
    to `COUNTERED` and replaces `rate_cents_per_unit` with the countered value,
    which is required on the counter action."
    PRD §3.7: "Proposing moves a `DRAFT` contract to `PROPOSED`; the same
    propose action re-proposes revised terms from `COUNTERED` back to
    `PROPOSED`. On either flavor of propose, `rate_cents_per_unit` is replaced
    by the request value when supplied."

    Design: Difficulty/non_linear_state_machine/vendor_contract_counter_reproposal_cycle
    """
    contract = _setup_draft_fuel_contract(api)

    proposed = validate_success(api.propose_contract(contract["id"], {}, CM), 200)
    assert proposed["status"] == "PROPOSED"
    assert proposed["rate_cents_per_unit"] == 500, (
        "propose without a rate keeps the drafted rate"
    )

    countered = validate_success(
        api.counter_contract(contract["id"], {"rate_cents_per_unit": 450}, CM), 200
    )
    assert countered["status"] == "COUNTERED"
    assert countered["rate_cents_per_unit"] == 450

    reproposed = validate_success(
        api.propose_contract(contract["id"], {"rate_cents_per_unit": 470}, CM), 200
    )
    assert reproposed["status"] == "PROPOSED"
    assert reproposed["rate_cents_per_unit"] == 470
