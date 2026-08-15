"""Priority-pair conflicts: when a request would fail two checks, the earlier
pipeline category must surface. PRD 2.8 fixes the category order."""
from test_helpers import (
    ApiErrorId,
    UTILITY_ONLY_DEPARTMENTS,
    create_jurisdiction,
    create_search_order,
    create_search_order_payload,
    create_statute,
    create_department,
    identify_order,
    make_qa_reviewer_headers,
    make_title_agent_headers,
    set_clock,
    setup_config_a,
    setup_identified_order,
    validate_error,
)

AGENT = make_title_agent_headers("agent_1")
AGENT2 = make_title_agent_headers("agent_2")
QA = make_qa_reviewer_headers("qa_1")


def test_verify_in_research_state_surfaces_state_error(api):
    """PRD 2.8: "fourth, whether the target resource sits in a state that
    permits the requested transition, including the blanket refusal of any
    transition out of a terminal state and the deliverability gate on delivery
    (`ERR_INVALID_STATE_TRANSITION` or `ERR_ORDER_NOT_DELIVERABLE` as
    applicable); ... tenth, fiscal checks on payoff totals and claim amounts
    (`ERR_PAYOFF_MISMATCH`, `ERR_CLAIM_AMOUNT_INVALID`)."
    PRD 2.8: "Inbound requests pass through an ordered pipeline of validation
    categories, and the ordering matters because a request that would fail
    several checks must surface the earliest one."

    Design: Difficulty/priority_pair_validation_conflict/verify_payoff_state_error_beats_payoff_mismatch
    """
    ctx = setup_identified_order(
        "P-P1", departments=UTILITY_ONLY_DEPARTMENTS, with_association=False
    )
    # Order is RESEARCH_IN_PROGRESS (state failure) AND the verifier total
    # 999999 disagrees with the computed 0 (fiscal failure): state wins.
    response = api.verify_payoff(
        ctx["order"]["id"], {"verified_payoff_total_cents": 999999}, QA
    )
    validate_error(response, ApiErrorId.ERR_INVALID_STATE_TRANSITION.value)
    assert response.status_code == 409


def test_verify_in_intake_state_surfaces_state_error(api):
    """PRD 2.8: "fourth, whether the target resource sits in a state that
    permits the requested transition, including the blanket refusal of any
    transition out of a terminal state and the deliverability gate on delivery
    (`ERR_INVALID_STATE_TRANSITION` or `ERR_ORDER_NOT_DELIVERABLE` as
    applicable); ... tenth, fiscal checks on payoff totals and claim amounts
    (`ERR_PAYOFF_MISMATCH`, `ERR_CLAIM_AMOUNT_INVALID`)."

    Design: Difficulty/priority_pair_validation_conflict/verify_payoff_state_error_beats_payoff_mismatch
    """
    set_clock()
    order = create_search_order("P-P2")
    # INTAKE (state failure) with a mismatching total (fiscal failure).
    response = api.verify_payoff(
        order["id"], {"verified_payoff_total_cents": 12345}, QA
    )
    validate_error(response, ApiErrorId.ERR_INVALID_STATE_TRANSITION.value)
    assert response.status_code == 409


def _jurisdiction_at_capacity_with_occupant():
    """Capacity-1 jurisdiction; one RUSH order occupies service_date 2026-07-01
    (created on 2026-06-15 while that date was still in the future)."""
    set_clock("2026-06-15T00:00:00Z")
    jurisdiction = create_jurisdiction(rush_daily_capacity=1)
    create_statute(jurisdiction["id"])
    create_department(
        jurisdiction["id"], dept_type="UTILITY", name="Water & Sewer",
        research_fee_cents=5000, rush_surcharge_cents=2500, supports_rush=True,
    )
    occupant = create_search_order(
        "P-Q1",
        property_address="1 Q St",
        closing_date="2026-08-01",
        order_class="RUSH",
        service_date="2026-07-01",
        jurisdiction_id=jurisdiction["id"],
    )
    return jurisdiction, occupant


def test_rush_create_with_past_date_at_capacity_surfaces_temporal_error(api):
    """PRD 2.8: "eighth, temporal validity (`ERR_SERVICE_DATE_PAST`,
    `ERR_CLOSING_DATE_PASSED`, `ERR_STATUTE_WINDOW_OVERLAP`,
    `ERR_ESTOPPEL_STALE_FOR_CLOSING`); ninth, structural business constraints
    such as rush support, rush capacity, duplicate service windows, outstanding
    tasks, and estoppel currency"
    PRD 2.8: "Inbound requests pass through an ordered pipeline of validation
    categories, and the ordering matters because a request that would fail
    several checks must surface the earliest one."

    Design: Difficulty/priority_pair_validation_conflict/rush_create_temporal_error_beats_capacity_error
    """
    jurisdiction, _ = _jurisdiction_at_capacity_with_occupant()
    set_clock("2026-08-01T00:00:00Z")
    # service_date 2026-07-01 is now in the past (temporal failure) AND the
    # occupant already fills the capacity of 1 for that date (constraint
    # failure): the temporal error surfaces first.
    response = api.create_search_order(
        create_search_order_payload(
            "P-Q2",
            property_address="2 Q St",
            closing_date="2026-08-30",
            order_class="RUSH",
            service_date="2026-07-01",
            jurisdiction_id=jurisdiction["id"],
        ),
        AGENT2,
    )
    validate_error(response, ApiErrorId.ERR_SERVICE_DATE_PAST.value)
    assert response.status_code == 422


def test_rush_create_at_capacity_with_valid_date_surfaces_capacity_error(api):
    """PRD 3.2: "Finally, the jurisdiction's daily rush capacity is enforced by
    counting existing non-`CANCELLED` rush orders whose
    `rush_candidate_jurisdiction_id` equals the requested jurisdiction and whose
    `service_date` equals the requested date: if that occupant count already
    equals or exceeds the jurisdiction's `rush_daily_capacity`, creation is
    rejected with `ERR_RUSH_CAPACITY_FULL`, while a count exactly one below
    capacity is still accepted."

    Design: Difficulty/priority_pair_validation_conflict/rush_create_temporal_error_beats_capacity_error
    """
    # Same fixture as the sibling test, but evaluated while the service date is
    # still in the future, so the capacity constraint is the one that fires.
    jurisdiction, _ = _jurisdiction_at_capacity_with_occupant()
    response = api.create_search_order(
        create_search_order_payload(
            "P-Q3",
            property_address="3 Q St",
            closing_date="2026-08-01",
            order_class="RUSH",
            service_date="2026-07-01",
            jurisdiction_id=jurisdiction["id"],
        ),
        AGENT2,
    )
    validate_error(response, ApiErrorId.ERR_RUSH_CAPACITY_FULL.value)
    assert response.status_code == 409
