"""State-machine transitions, initial states, terminal-state lockdown.

Each test translates exactly one corner-design instance (queue B).
"""
import pytest
from test_helpers import (
    validate_success, validate_error,
    create_product_payload, create_contract_payload,
    setup_active_fixed_contract, setup_death_claim_verifying,
    set_clock,
    TEST_USERS,
)

ADMIN = TEST_USERS["contract_admin_headers"]
COMPLIANCE = TEST_USERS["compliance_officer_headers"]


def test_clear_already_cleared_premium_invalid_state(api):
    """PRD §3.2: "A clear may be requested only while the premium is `SUBMITTED`
    and only while the contract is in the matching state ... otherwise it is
    rejected with `ERR_INVALID_STATE`."

    Design: Corner/state_machines/clear_already_cleared_premium_invalid_state
    """
    product, contract, premium = setup_active_fixed_contract(gross_premium_cents=2_000_000)
    res = api.clear_premium(premium["id"], ADMIN)
    validate_error(res, "ERR_INVALID_STATE", expected_status=409)
    contract_after = validate_success(api.get_contract(contract["id"], ADMIN), 200)
    assert contract_after["accumulation_value_cents"] == 2000000, "no double credit"


def test_new_contract_starts_in_pending(api):
    """PRD §3.2: "The contract is born in `PENDING` status with an accumulation
    value of zero".

    Design: Corner/state_machines/new_contract_starts_in_pending
    """
    product = validate_success(api.create_product(create_product_payload(), ADMIN), 201)
    res = api.create_contract(create_contract_payload(product["id"]), ADMIN)
    contract = validate_success(res, 201)
    assert contract["status"] == "PENDING"
    assert contract["accumulation_value_cents"] == 0


def test_withdraw_on_pending_contract_invalid_state(api):
    """PRD §3.5: "A `ContractAdmin` requests a **Withdrawal** against an `ACTIVE`
    contract".
    PRD §2.9: "the state-machine check confirming the target is in a state from
    which the requested transition is defined (`ERR_INVALID_STATE`, 409)".

    Design: Corner/state_machines/withdraw_on_pending_contract_invalid_state
    """
    product = validate_success(api.create_product(create_product_payload(), ADMIN), 201)
    contract = validate_success(api.create_contract(create_contract_payload(product["id"]), ADMIN), 201)
    res = api.create_withdrawal({
        "contract_id": contract["id"],
        "requested_amount_cents": 100000,
        "expected_contract_version": contract["version"],
    }, ADMIN)
    validate_error(res, "ERR_INVALID_STATE", expected_status=409)


def test_terminal_surrendered_contract_rejects_annuitization(api):
    """PRD §3.2: "the latter three of those — `SURRENDERED`, `ANNUITIZED`, and
    `TERMINATED` — are terminal."
    PRD §3.8: "A `ContractAdmin` elects an **Annuitization** against an `ACTIVE`
    contract".

    Design: Corner/state_machines/terminal_surrendered_contract_rejects_annuitization
    """
    set_clock("2026-01-01T00:00:00Z")
    product = validate_success(api.create_product(create_product_payload(
        free_withdrawal_corridor_bps=10000), ADMIN), 201)
    contract = validate_success(api.create_contract(create_contract_payload(product["id"]), ADMIN), 201)
    premium = validate_success(api.create_premium({
        "contract_id": contract["id"], "gross_premium_cents": 2_000_000,
        "expected_contract_version": contract["version"]}, ADMIN), 201)
    validate_success(api.clear_premium(premium["id"], ADMIN), 200)
    fresh = validate_success(api.get_contract(contract["id"], ADMIN), 200)
    wd = validate_success(api.create_withdrawal({
        "contract_id": contract["id"], "requested_amount_cents": 2_000_000,
        "is_full_surrender": True, "expected_contract_version": fresh["version"]}, ADMIN), 201)
    validate_success(api.settle_withdrawal(wd["id"], COMPLIANCE), 200)
    surrendered = validate_success(api.get_contract(contract["id"], ADMIN), 200)
    assert surrendered["status"] == "SURRENDERED"
    res = api.create_annuitization({"contract_id": contract["id"], "payout_option": "LIFE_ONLY"}, ADMIN)
    validate_error(res, "ERR_INVALID_STATE", expected_status=409)


def test_reverify_identity_from_verifying_invalid_state(api):
    """PRD §3.9: "The first branch, verify-identity, moves the claim from
    `FILED` to `VERIFYING` and sets `identity_verified` to true."
    PRD §3.9: "Each transition is rejected with `ERR_INVALID_STATE` if the claim
    is not in the state from which that transition is defined."

    Design: Corner/state_machines/deny_then_reverify_identity_loops_back_invalid
    """
    product, contract, claim, _ = setup_death_claim_verifying(gross_premium_cents=2_000_000)
    res = api.verify_identity(claim["id"], COMPLIANCE)
    validate_error(res, "ERR_INVALID_STATE", expected_status=409)


def test_retire_product_blocks_new_contracts(api):
    """PRD §3.1: "a `RETIRED` product rejects any attempt to open a new contract
    against it."
    PRD §3.1: "A product's `status` is `ACTIVE` when created and may be moved to
    `RETIRED` by a `ContractAdmin`".

    Design: Corner/endpoints/retire_product_blocks_new_contracts
    """
    product = validate_success(api.create_product(create_product_payload(), ADMIN), 201)
    retired = validate_success(api.retire_product(product["id"], ADMIN), 200)
    assert retired["status"] == "RETIRED"
    res = api.create_contract(create_contract_payload(product["id"]), ADMIN)
    validate_error(res, "ERR_INVALID_STATE", expected_status=409)
