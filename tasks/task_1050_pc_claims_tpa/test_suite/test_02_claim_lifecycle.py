"""Claim state machine: illegal transitions and the CLOSED->REOPENED->CLOSED cycle.

Translates the non_linear_state_machine (claim cycle) difficulty instance and the
claim invalid-transition corner instance.
"""
from test_helpers import (
    validate_success, validate_error,
    create_claim_payload, TEST_USERS,
    create_account, create_policy, setup_closed_claim, get_claim,
)

CM = TEST_USERS["claims_manager_headers"]
ADJ = TEST_USERS["adjuster_headers"]


def test_intake_to_evaluated_is_invalid_state(api):
    """PRD §3.2: "Any transition requested from a state that does not permit it is rejected
    with `ERR_INVALID_STATE`."

    Design: Corner/state_machines/claim_invalid_transition_intake_to_evaluated
    """
    account = create_account(api, account_code="C-IV")
    policy = create_policy(api, account["id"], policy_number="P-IV")
    claim = validate_success(api.create_claim(create_claim_payload(policy["id"]), ADJ), 201)
    resp = api.transition_claim(claim["id"], "EVALUATED", ADJ)
    validate_error(resp, "ERR_INVALID_STATE")
    assert get_claim(api, claim["id"], ADJ)["status"] == "INTAKE"


def test_reopen_cycle_returns_claim_to_closed(api):
    """PRD §3.2: "A `ClaimsManager` may take a `CLOSED` claim to `REOPENED`, from which an
    adjuster may go `REOPENED → EVALUATED` or `REOPENED → CLOSED`."
    PRD §3.9: "An `Adjuster` closes a claim from `EVALUATED` (or from `REOPENED`, which
    follows the identical rules)."

    Design: Difficulty/non_linear_state_machine/claim_reopen_cycle_closed_reopened_closed
    """
    env = setup_closed_claim(api, account_overrides={"account_code": "NL1"})
    claim_id, adj = env["claim"]["id"], env["adj_headers"]
    validate_success(api.transition_claim(claim_id, "REOPENED", CM), 200)
    validate_success(api.transition_claim(claim_id, "CLOSED", adj), 200)
    assert get_claim(api, claim_id, adj)["status"] == "CLOSED"


def test_reopened_claim_passes_through_reopened_before_reclosing(api):
    """PRD §3.2: "A `ClaimsManager` may take a `CLOSED` claim to `REOPENED`, from which an
    adjuster may go `REOPENED → EVALUATED` or `REOPENED → CLOSED`."

    Design: Difficulty/non_linear_state_machine/claim_reopen_cycle_closed_reopened_closed
    """
    env = setup_closed_claim(api, account_overrides={"account_code": "NL1b"})
    claim_id, adj = env["claim"]["id"], env["adj_headers"]
    reopened = validate_success(api.transition_claim(claim_id, "REOPENED", CM), 200)
    assert reopened["status"] == "REOPENED"
    reclosed = validate_success(api.transition_claim(claim_id, "CLOSED", adj), 200)
    assert reclosed["status"] == "CLOSED"
