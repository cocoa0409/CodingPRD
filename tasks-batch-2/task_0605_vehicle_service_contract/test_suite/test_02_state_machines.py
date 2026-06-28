"""Contract / claim / plan / cancellation state machine transitions and guards.

Translates corner-design state_machines instances plus the difficulty-design
non_linear_state_machine cyclic-loop instance.
"""
from test_helpers import (
    TEST_USERS,
    validate_success,
    validate_error,
    validate_paginated,
    ApiErrorId,
    create_contract_payload,
)
from test_helpers.fixtures import (
    create_pool,
    create_active_plan,
    create_facility,
    create_contract,
    setup_active_contract,
    setup_submitted_claim,
    setup_under_review_claim,
    setup_approved_cancellation,
    set_clock,
)

ADMIN = TEST_USERS["admin_underwriter_headers"]
CONTRACT_ADMIN = TEST_USERS["contract_admin_headers"]
ADJUSTER = TEST_USERS["claims_adjuster_headers"]


def test_contract_initial_state_pending(api):
    """PRD §3.2: "A freshly sold contract is in `PENDING` status."

    Design: Corner/state_machines/contract_initial_state_pending
    """
    pool = create_pool("Pool IS")
    plan = create_active_plan()
    resp = api.create_contract(create_contract_payload(plan["id"], pool["id"], vin="VINIS00001"), CONTRACT_ADMIN)
    data = validate_success(resp, expected_status=201)
    assert data["status"] == "PENDING", f"expected PENDING, got {data['status']}"


def test_approve_claim_from_submitted_invalid_state(api):
    """PRD §2.8: "If it is not, the request is rejected with `ERR_INVALID_STATE`
    (HTTP 409). This guard ... catches, for example, an attempt to approve a claim
    that is not under review".

    Design: Corner/state_machines/approve_claim_from_submitted_invalid_state
    """
    base = setup_submitted_claim(claim_overrides={"complaint": "engine"})
    resp = api.approve_claim(base["claim"]["id"], ADJUSTER)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)


def test_retire_plan_in_use_rejected(api):
    """PRD §3.1: "retirement is refused with `ERR_PLAN_IN_USE` (HTTP 409) if any
    contract in `PENDING` or `ACTIVE` status still references the plan."

    Design: Corner/state_machines/retire_plan_in_use_rejected
    """
    base = setup_active_contract(pool_name="Pool PIU", contract_overrides={"vin": "VINPIU0001"})
    resp = api.retire_coverage_plan(base["plan"]["id"], ADMIN)
    validate_error(resp, ApiErrorId.ERR_PLAN_IN_USE)


def test_lapse_blocked_by_open_claim(api):
    """PRD §3.2: "Lapsing moves an `ACTIVE` contract to `LAPSED` and increments its
    `version`, but is refused with `ERR_OPEN_CLAIM_BLOCKS` (HTTP 409) if any claim
    under the contract is in adjudication status `UNDER_REVIEW`, or is `APPROVED`
    with a payment status other than `PAID`."

    Design: Corner/state_machines/lapse_blocked_by_open_claim
    """
    base = setup_under_review_claim(
        claim_overrides={"complaint": "engine"},
        claim_lines=[{"line_type": "PART", "part_number": "EN-4", "requested_amount_cents": 50000, "covered": True}],
        pool_name="Pool OCB",
        contract_overrides={"vin": "VINOCB0001"},
    )
    resp = api.lapse_contract(base["contract"]["id"], CONTRACT_ADMIN)
    validate_error(resp, ApiErrorId.ERR_OPEN_CLAIM_BLOCKS)


def test_deny_claim_releases_reserve(api):
    """PRD §3.4: "Denying a claim instead advances its adjudication dimension from
    `UNDER_REVIEW` to `DENIED`; denial releases the case reserve by posting a
    `RESERVE_RELEASE` entry equal to the negative of the claim's `reserve_cents` —
    decreasing the pool's `reserve_held_cents` and recomputing surplus — and then
    setting the claim's `reserve_cents` to 0."

    Design: Corner/state_machines/deny_claim_releases_reserve
    """
    base = setup_under_review_claim(
        claim_overrides={"complaint": "engine"},
        claim_lines=[{"line_type": "PART", "part_number": "EN-5", "requested_amount_cents": 50000, "covered": True}],
        pool_name="Pool DEN",
        contract_overrides={"vin": "VINDEN0001"},
    )
    deny = validate_success(api.deny_claim(base["claim"]["id"], ADJUSTER))
    assert deny["adjudication_status"] == "DENIED", f"expected DENIED, got {deny['adjudication_status']}"
    pool = validate_success(api.get_reinsurance_pool(base["pool"]["id"], ADMIN))
    assert pool["reserve_held_cents"] == 0, f"expected reserve 0 after deny, got {pool['reserve_held_cents']}"


def test_cancellation_reject_clears_link(api):
    """PRD §3.6: "Rejecting a cancellation advances it from `REQUESTED` to the
    terminal `REJECTED` status and clears the contract's `cancellation_id`
    back-reference."

    Design: Corner/state_machines/cancellation_reject_clears_link
    """
    base = setup_active_contract(pool_name="Pool REJ", contract_overrides={"vin": "VINREJ0001"})
    canc = validate_success(api.create_cancellation(
        {"contract_id": base["contract"]["id"], "reason": "CUSTOMER_REQUEST", "request_date": "2026-03-01T00:00:00Z"},
        CONTRACT_ADMIN,
    ), expected_status=201)
    api.reject_cancellation(canc["id"], CONTRACT_ADMIN)
    contract = validate_success(api.get_contract(base["contract"]["id"], CONTRACT_ADMIN))
    assert contract["cancellation_id"] is None, f"expected null cancellation_id, got {contract['cancellation_id']}"
    assert contract["status"] == "ACTIVE", f"expected ACTIVE, got {contract['status']}"


def test_terminal_refunded_cancellation_no_further_transition(api):
    """PRD §2.8: "an attempt to ... [transition from a state where the requested
    transition is not defined] is rejected with `ERR_INVALID_STATE` (HTTP 409)."
    PRD §3.6: "Refunding an approved cancellation advances it from `APPROVED` to the
    terminal `REFUNDED` status".

    Design: Corner/state_machines/terminal_refunded_cancellation_no_further_transition
    """
    base = setup_approved_cancellation(
        reason="CUSTOMER_REQUEST", request_date="2026-01-20T00:00:00Z",
        clock="2026-01-20T00:00:00Z", pool_name="Pool TRM",
        contract_overrides={"vin": "VINTRM0001"},
    )
    api.refund_cancellation(base["cancellation"]["id"], CONTRACT_ADMIN)
    resp = api.refund_cancellation(base["cancellation"]["id"], CONTRACT_ADMIN)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)


def test_contract_cyclic_lapse_reinstate_loop(api):
    """PRD §3.2: "The contract runs a cyclic active/lapsed loop. Lapsing moves an
    `ACTIVE` contract to `LAPSED` and increments its `version` ... Reinstating moves
    a `LAPSED` contract back to `ACTIVE` and increments its `version`, but only if
    the referenced plan is still in `ACTIVE` status".

    Design: Difficulty/non_linear_state_machine/contract_cyclic_lapse_reinstate_loop
    """
    base = setup_active_contract(pool_name="Pool C", contract_overrides={"vin": "VINCYC00001"})
    lapsed = validate_success(api.lapse_contract(base["contract"]["id"], CONTRACT_ADMIN))
    assert lapsed["status"] == "LAPSED", f"expected LAPSED, got {lapsed['status']}"
    reinstated = validate_success(api.reinstate_contract(base["contract"]["id"], CONTRACT_ADMIN))
    assert reinstated["status"] == "ACTIVE", f"expected ACTIVE after reinstate, got {reinstated['status']}"


def test_contract_lapse_reinstate_returns_to_active_again(api):
    """PRD §3.2: "Reinstating moves a `LAPSED` contract back to `ACTIVE` and
    increments its `version`, but only if the referenced plan is still in `ACTIVE`
    status (otherwise `ERR_PLAN_NOT_ACTIVE`)."

    Design: Difficulty/non_linear_state_machine/contract_cyclic_lapse_reinstate_loop
    """
    base = setup_active_contract(pool_name="Pool C2", contract_overrides={"vin": "VINCYC00002"})
    cid = base["contract"]["id"]
    validate_success(api.lapse_contract(cid, CONTRACT_ADMIN))
    again_active = validate_success(api.reinstate_contract(cid, CONTRACT_ADMIN))
    assert again_active["status"] == "ACTIVE", f"expected ACTIVE, got {again_active['status']}"
    # The cycle is repeatable: lapse once more is legal from ACTIVE.
    lapsed_again = validate_success(api.lapse_contract(cid, CONTRACT_ADMIN))
    assert lapsed_again["status"] == "LAPSED", f"expected LAPSED, got {lapsed_again['status']}"
