"""Negotiation cases: rounds, the propose/counter cycle, accept/abandon, capacity."""
from test_helpers import (
    validate_success, validate_error,
    make_member_headers, make_agent_headers,
    setup_open_case, setup_proposed_case, setup_confirmed_charge,
    setup_detected_charge, create_agent,
    create_negotiation_case_payload,
    ApiErrorId,
)


def test_open_negotiation_requires_charge_confirmed(api):
    """PRD §3.2: "A subscription, negotiation case, or refund claim may be opened against a charge only when that charge is `CONFIRMED`; opening any of them against a charge that is not `CONFIRMED` is rejected with `ERR_LINKED_RESOURCE_STATE`."

    Design: Difficulty/cross_entity_state_dependency/open_negotiation_requires_charge_confirmed
    """
    member, la, charge = setup_detected_charge(amount_cents=5000)  # DETECTED, not confirmed
    agent = create_agent()
    resp = api.create_negotiation_case(
        create_negotiation_case_payload(member["id"], charge["id"], agent["id"]),
        headers=make_member_headers(member["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_LINKED_RESOURCE_STATE.value)


def test_open_negotiation_against_detected_blocked(api):
    """PRD §3.2: "opening any of them against a charge that is not `CONFIRMED` is rejected with `ERR_LINKED_RESOURCE_STATE`."

    Design: Difficulty/cross_entity_state_dependency/open_negotiation_requires_charge_confirmed
    """
    member, la, charge = setup_detected_charge(amount_cents=3000)
    agent = create_agent()
    resp = api.create_negotiation_case(
        create_negotiation_case_payload(member["id"], charge["id"], agent["id"]),
        headers=make_member_headers(member["id"]),
    )
    assert resp.status_code == 409
    validate_error(resp, ApiErrorId.ERR_LINKED_RESOURCE_STATE.value)


def test_propose_counter_propose_cycle(api):
    """PRD §3.5: "From `COUNTERED`, the agent may propose again by supplying `offered_annual_cost_cents` (at least zero), returning the case to `PROPOSED`, updating `current_offer_annual_cost_cents`, incrementing `round_count`, and bumping the `version`."

    Design: Difficulty/non_linear_state_machine/negotiation_case_proposed_countered_cycle
    """
    member, agent, charge, case = setup_open_case(charge_amount_cents=5000)
    ah = make_agent_headers(agent["id"])
    api.propose_negotiation(case["id"], {"offered_annual_cost_cents": 55000}, headers=ah)
    api.counter_negotiation(case["id"], {"counter_annual_cost_cents": 52000}, headers=ah)
    resp = api.propose_negotiation(case["id"], {"offered_annual_cost_cents": 50000}, headers=ah)
    data = validate_success(resp)
    assert data["status"] == "PROPOSED"
    assert data["round_count"] == 2
    assert data["current_offer_annual_cost_cents"] == 50000


def test_round_count_increments_only_on_propose(api):
    """PRD §3.5: "the agent **proposes** an offer ... increments `round_count` by one".
    PRD §3.5: "the agent may record a provider **counter ... advances the case to `COUNTERED`, sets `current_offer_annual_cost_cents` to the countered amount, and bumps the `version`." (no round_count increment on counter)

    Design: Difficulty/non_linear_state_machine/negotiation_case_proposed_countered_cycle
    """
    member, agent, charge, case = setup_open_case(charge_amount_cents=5000)
    ah = make_agent_headers(agent["id"])
    p1 = validate_success(api.propose_negotiation(case["id"], {"offered_annual_cost_cents": 55000}, headers=ah))
    assert p1["round_count"] == 1
    c1 = validate_success(api.counter_negotiation(case["id"], {"counter_annual_cost_cents": 52000}, headers=ah))
    assert c1["round_count"] == 1  # counter does not bump round_count
    assert c1["status"] == "COUNTERED"


def test_abandon_open_case_decrements_agent_count(api):
    """PRD §3.5: "Abandoning** the case advances it to `LOST` and is permitted from `OPEN`, `PROPOSED`, or `COUNTERED`; it decrements the assigned agent's `open_case_count` and bumps the `version`."

    Design: Corner/state_machines/abandon_case_bubble_up_agent_count
    """
    member, agent, charge, case = setup_open_case(charge_amount_cents=5000)
    resp = api.abandon_negotiation(case["id"], headers=make_agent_headers(agent["id"]))
    data = validate_success(resp)
    assert data["status"] == "LOST"
    prof = validate_success(api.get_concierge_agent(agent["id"], headers=make_agent_headers(agent["id"])))
    assert prof["open_case_count"] == 0


def test_agent_capacity_exceeded_on_open(api):
    """PRD §3.4: "an attempt to open a case for an agent already at capacity is rejected with `ERR_AGENT_CAPACITY_EXCEEDED`."

    Design: Corner/validations/agent_capacity_exceeded_on_open_case
    """
    member, la, charge1 = setup_confirmed_charge(amount_cents=5000, merchant_name="A")
    # second confirmed charge for same member
    resp2 = api.create_recurring_charge(
        {"linked_account_id": la["id"], "merchant_name": "B", "amount_cents": 6000,
         "cadence": "MONTHLY", "first_seen_utc": "2026-01-01T00:00:00Z"},
        headers=make_member_headers(member["id"]),
    )
    charge2 = validate_success(resp2, 201)
    api.confirm_recurring_charge(charge2["id"], headers=make_member_headers(member["id"]))
    agent = create_agent(max_open_cases=1)
    api.create_negotiation_case(
        create_negotiation_case_payload(member["id"], charge1["id"], agent["id"]),
        headers=make_member_headers(member["id"]),
    )
    resp = api.create_negotiation_case(
        create_negotiation_case_payload(member["id"], charge2["id"], agent["id"]),
        headers=make_member_headers(member["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_AGENT_CAPACITY_EXCEEDED.value)


def test_accept_offer_exactly_at_baseline_allowed(api):
    """PRD §3.5: "only when `current_offer_annual_cost_cents` is at most `baseline_annual_cost_cents` — accepting an offer whose annual cost exceeds the baseline is rejected with `ERR_OFFER_ABOVE_BASELINE`."
    PRD §3.6: "gross_annual_savings_cents` is computed as the baseline annual cost minus the agreed annual cost ... taken as zero if that difference would be negative."

    Design: Difficulty/boundary_precision_check/accept_offer_exactly_at_baseline_allowed
    """
    # MONTHLY 5000 -> baseline 60000; offer exactly 60000
    member, agent, charge, case = setup_proposed_case(60000, charge_amount_cents=5000)
    resp = api.accept_negotiation(case["id"], headers=make_agent_headers(agent["id"]))
    data = validate_success(resp)
    assert data["status"] == "WON"
    assert data["gross_annual_savings_cents"] == 0
    assert data["success_fee_cents"] == 0
    assert data["member_net_savings_cents"] == 0


def test_accept_at_baseline_books_zero_ledger(api):
    """PRD §3.6: "First, `gross_annual_savings_cents` is computed as the baseline annual cost minus the agreed annual cost ... and is taken as zero if that difference would be negative."
    PRD §3.6: "the platform's `success_fee_cents` is computed from this gross by the success-fee split."

    Design: Difficulty/boundary_precision_check/accept_offer_exactly_at_baseline_allowed
    """
    member, agent, charge, case = setup_proposed_case(60000, charge_amount_cents=5000)
    won = validate_success(api.accept_negotiation(case["id"], headers=make_agent_headers(agent["id"])))
    assert won["agreed_annual_cost_cents"] == 60000
    assert won["gross_annual_savings_cents"] == 0
    assert won["member_net_savings_cents"] == 0


def test_accept_on_open_case_state_check_wins(api):
    """PRD §2.9: "then the state-transition check that the resource is in an allowed source state (`ERR_INVALID_STATE`); then cross-entity referential preconditions".
    PRD §3.5: "Accepting** the current offer wins the case: it is permitted from either `PROPOSED` or `COUNTERED".

    Design: Difficulty/priority_pair_validation_conflict/state_vs_fiscal_on_accept_above_baseline
    """
    # OPEN case (no proposal): accept is not allowed from OPEN -> state check fires.
    member, agent, charge, case = setup_open_case(charge_amount_cents=5000)
    resp = api.accept_negotiation(case["id"], headers=make_agent_headers(agent["id"]))
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)
    after = validate_success(api.get_negotiation_case(case["id"],
                                                      headers=make_member_headers(member["id"])))
    assert after["status"] == "OPEN"


def test_accept_from_open_returns_409_not_fiscal(api):
    """PRD §2.6: "an attempt from a disallowed state is rejected with `ERR_INVALID_STATE` (HTTP 409)."
    PRD §3.5: "Accepting** the current offer wins the case: it is permitted from either `PROPOSED` or `COUNTERED".

    Design: Difficulty/priority_pair_validation_conflict/state_vs_fiscal_on_accept_above_baseline
    """
    member, agent, charge, case = setup_open_case(charge_amount_cents=5000)
    resp = api.accept_negotiation(case["id"], headers=make_agent_headers(agent["id"]))
    assert resp.status_code == 409
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)


def test_member_cannot_propose_forbidden_role(api):
    """PRD §2.1: "When the headers are present and recognized but the role is not permitted to perform the requested operation, the request is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403)."

    Design: Corner/rbac/member_cannot_run_propose
    """
    member, agent, charge, case = setup_open_case(charge_amount_cents=5000)
    resp = api.propose_negotiation(
        case["id"], {"offered_annual_cost_cents": 50000},
        headers=make_member_headers(member["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE.value)
