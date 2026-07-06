"""Warranty callbacks (inclusive window boundary) and protection-plan claim routing,
adjudication, and coverage computation.
"""
from test_helpers import (
    validate_success, validate_error,
    ApiErrorId, TEST_USERS,
    create_customer, create_device, create_ticket,
    setup_estimate_sent, setup_ticket_in_repair, setup_completed_ticket,
    set_clock, file_claim, route_claim, setup_claim_routed,
)

SA = TEST_USERS["service_advisor_headers"]
SM = TEST_USERS["store_manager_headers"]


# ---------------------------------------------------------------------------
# Difficulty: boundary_precision_check / warranty_callback_window_inclusive
# ---------------------------------------------------------------------------
def test_callback_at_exact_expiry_instant_is_eligible(api):
    """PRD §3.6: "the original ticket's `completed_at` plus 90 days defines an expiry
    instant, and the callback is eligible only if the current logical clock is at or
    before that expiry — the boundary is inclusive."
    PRD §3.6: "the system creates a new repair ticket whose `original_ticket_id` points
    at the completed ticket, with `is_callback` set to true, `is_under_warranty` set to
    true, `status` of `INTAKE`".

    Design: Difficulty/boundary_precision_check/warranty_callback_window_inclusive
    """
    scn = setup_completed_ticket(market_value_cents=60000, spend_cap_cents=100000,
                                 labor_hours=2, actual_labor_hours=2,
                                 completed_at="2026-05-10T00:00:00Z")
    set_clock("2026-08-08T00:00:00Z")  # exactly 90 days after completion
    resp = api.callback_ticket(scn["ticket"]["id"],
                               {"reported_issue": "same fault", "intake_channel": "WALK_IN"}, SA)
    cb = validate_success(resp, 201)
    assert cb["is_callback"] is True
    assert cb["original_ticket_id"] == scn["ticket"]["id"]
    assert cb["status"] == "INTAKE"


def test_callback_copies_warranty_flag_and_spend_cap(api):
    """PRD §3.6: "with `is_callback` set to true, `is_under_warranty` set to true,
    `status` of `INTAKE`, and `spend_cap_cents` copied from the original ticket."

    Design: Difficulty/boundary_precision_check/warranty_callback_window_inclusive
    """
    scn = setup_completed_ticket(market_value_cents=60000, spend_cap_cents=100000,
                                 labor_hours=2, actual_labor_hours=2,
                                 completed_at="2026-05-10T00:00:00Z")
    set_clock("2026-08-08T00:00:00Z")
    cb = validate_success(api.callback_ticket(
        scn["ticket"]["id"],
        {"reported_issue": "same fault", "intake_channel": "WALK_IN"}, SA), 201)
    assert cb["is_under_warranty"] is True
    assert cb["spend_cap_cents"] == 100000


# ---------------------------------------------------------------------------
# Corner: calculations / warranty_callback_after_expiry_returns_warranty_expired
# ---------------------------------------------------------------------------
def test_callback_one_second_past_expiry_returns_warranty_expired(api):
    """PRD §3.6: "A callback filed after the window has closed is rejected with
    `ERR_WARRANTY_EXPIRED`."

    Design: Corner/calculations/warranty_callback_after_expiry_returns_warranty_expired
    """
    scn = setup_completed_ticket(market_value_cents=60000, spend_cap_cents=100000,
                                 labor_hours=2, actual_labor_hours=2,
                                 completed_at="2026-05-10T00:00:00Z")
    set_clock("2026-08-08T00:00:01Z")  # one second past the inclusive expiry
    resp = api.callback_ticket(scn["ticket"]["id"],
                               {"reported_issue": "same fault", "intake_channel": "WALK_IN"}, SA)
    validate_error(resp, ApiErrorId.ERR_WARRANTY_EXPIRED.value, 422)


# ---------------------------------------------------------------------------
# Difficulty: cross_entity_state_dependency / claim_approve_requires_approved_estimate
# ---------------------------------------------------------------------------
def test_claim_approve_blocked_when_estimate_only_sent(api):
    """PRD §3.8: "Approval moves it `ROUTED → APPROVED` but only if the claim's ticket
    has an estimate in `APPROVED` or `FINALIZED` status, otherwise `ERR_ESTIMATE_NOT_APPROVED`."

    Design: Difficulty/cross_entity_state_dependency/claim_approve_requires_approved_estimate
    """
    scn = setup_estimate_sent(market_value_cents=60000, spend_cap_cents=100000, labor_hours=2)
    claim = setup_claim_routed(scn["ticket"]["id"], scn["customer"]["id"], "ADH")
    resp = api.approve_claim(claim["id"], SM)
    validate_error(resp, ApiErrorId.ERR_ESTIMATE_NOT_APPROVED.value, 409)


def test_claim_stays_routed_after_blocked_approval(api):
    """PRD §3.8: "Approval moves it `ROUTED → APPROVED` but only if the claim's ticket
    has an estimate in `APPROVED` or `FINALIZED` status, otherwise `ERR_ESTIMATE_NOT_APPROVED`."

    Design: Difficulty/cross_entity_state_dependency/claim_approve_requires_approved_estimate
    """
    scn = setup_estimate_sent(market_value_cents=60000, spend_cap_cents=100000, labor_hours=2)
    claim = setup_claim_routed(scn["ticket"]["id"], scn["customer"]["id"], "ADH")
    api.approve_claim(claim["id"], SM)
    now = validate_success(api.get_claim(claim["id"], SM))
    assert now["status"] == "ROUTED"
    assert now["covered_amount_cents"] is None


# ---------------------------------------------------------------------------
# Corner: calculations / protection_covered_amount_min_of_estimate_and_cap
# ---------------------------------------------------------------------------
def test_protection_covered_amount_is_estimate_minus_deductible(api):
    """PRD §3.8: "Filing places the claim in `FILED` and sets its `deductible_cents`
    from the plan type: 7500 cents for `ADH`".
    PRD §3.8: "That difference is then capped at the coverage limit of 50000 cents by
    taking the smaller of the two, and the result is floored at 0 by taking the larger
    of it and 0."

    Design: Corner/calculations/protection_covered_amount_min_of_estimate_and_cap
    """
    # market 200000 keeps REPAIR; provisional total = 10000 labor + 6000 part + 4000 diag = 20000.
    scn = setup_ticket_in_repair(market_value_cents=200000, spend_cap_cents=100000,
                                 labor_hours=2, part_specs=[(6000, 10, 1)])
    claim = setup_claim_routed(scn["ticket"]["id"], scn["customer"]["id"], "ADH")
    approved = validate_success(api.approve_claim(claim["id"], SM))
    assert approved["status"] == "APPROVED"
    assert approved["covered_amount_cents"] == 12500


# ---------------------------------------------------------------------------
# Corner: state_machines / approve_claim_from_filed_returns_claim_invalid_state
# ---------------------------------------------------------------------------
def test_approve_claim_from_filed_returns_claim_invalid_state(api):
    """PRD §3.8: "Routing, approval, and denial each require the claim to be in the
    correct starting state, and a claim acted on from the wrong state is rejected with
    `ERR_CLAIM_INVALID_STATE`."

    Design: Corner/state_machines/approve_claim_from_filed_returns_claim_invalid_state
    """
    cust = create_customer()
    dev = create_device(cust["id"], market_value_cents=1000)
    tkt = create_ticket(dev["id"], cust["id"], spend_cap_cents=1000)
    claim = file_claim(tkt["id"], cust["id"], "ADH")
    resp = api.approve_claim(claim["id"], SM)
    validate_error(resp, ApiErrorId.ERR_CLAIM_INVALID_STATE.value, 409)


# ---------------------------------------------------------------------------
# Corner: state_machines / route_claim_sets_destination_from_plan_type
# ---------------------------------------------------------------------------
def test_route_extended_warranty_claim_sets_manufacturer_destination(api):
    """PRD §3.8: "Routing is the advisor's next move, taking the claim `FILED → ROUTED`
    and setting its `routing_destination` from the plan type: an `ADH` plan routes
    `IN_STORE`, an `EXTENDED_WARRANTY` plan routes to the `MANUFACTURER`, and an
    `ACCESSORY` plan routes to the `THIRD_PARTY_ADMIN`."
    PRD §3.8: "sets its `deductible_cents` from the plan type: 7500 cents for `ADH`,
    0 for `EXTENDED_WARRANTY`, and 2500 cents for `ACCESSORY`."

    Design: Corner/state_machines/route_claim_sets_destination_from_plan_type
    """
    cust = create_customer()
    dev = create_device(cust["id"], market_value_cents=1000)
    tkt = create_ticket(dev["id"], cust["id"], spend_cap_cents=1000)
    claim = file_claim(tkt["id"], cust["id"], "EXTENDED_WARRANTY")
    routed = route_claim(claim["id"])
    assert routed["status"] == "ROUTED"
    assert routed["routing_destination"] == "MANUFACTURER"
    assert routed["deductible_cents"] == 0
