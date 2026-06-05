"""Business-rule violations -> errors: card limit, budget, OOP chain, return
reason, no active policy, duplicate activation, policy in use, card open holds.

Queue B (Corner) — section validations.
"""
from test_helpers import (
    validate_error,
    get_success_data,
    ApiErrorId,
    setup_base_env,
    create_pending_trip,
    create_approved_trip,
    create_report,
    add_flight_line,
    add_flight_line_with_receipt,
    add_mileage_line,
    add_approval_step,
    submit_report,
    issue_card,
    create_draft_policy,
    create_active_policy,
    create_per_diem_rate,
    create_approver,
    create_traveler,
    make_traveler_headers,
    make_finance_admin_headers,
)

ADMIN = make_finance_admin_headers()


def test_card_limit_exceeded_on_charge(api):
    """PRD §3.4: "the line's reimbursable_amount_cents may not exceed the card's current
    available_balance_cents, otherwise it is refused with ERR_CARD_LIMIT_EXCEEDED."

    Design: Corner/validations/card_limit_exceeded_on_charge
    """
    env = setup_base_env()
    trip = create_approved_trip(env, budget_total_cents=100000)
    card = issue_card(env, trip, load_limit_cents=20000)
    report = create_report(env, trip, title="Limit Rpt")
    resp = api.create_expense_line(
        {
            "report_id": report["id"], "line_type": "FLIGHT",
            "claimed_amount_cents": 30000, "virtual_card_id": card["id"],
            "cabin_class": "ECONOMY", "scheduled_hours": 4, "advance_days": 20,
        },
        env["traveler_headers"],
    )
    validate_error(resp, ApiErrorId.ERR_CARD_LIMIT_EXCEEDED.value)


def test_budget_exceeded_on_report_approve(api):
    """PRD §3.8: "the trip's remaining_budget_cents must be at least the report's
    total_reimbursable_cents; an approve that would overcommit the trip is rejected with
    ERR_BUDGET_EXCEEDED."

    Design: Corner/validations/budget_exceeded_on_report_approve
    """
    env = setup_base_env(max_economy_fare_cents=50000)
    trip = create_approved_trip(env, budget_total_cents=30000)
    report = create_report(env, trip, title="Over Budget Rpt")
    add_flight_line_with_receipt(env, report, claimed_amount_cents=40000,
                                 cabin_class="ECONOMY", scheduled_hours=4, advance_days=20)
    submit_report(env, report)
    resp = api.decide_expense_report(report["id"], {"decision": "APPROVE"}, env["approver_headers"])
    validate_error(resp, ApiErrorId.ERR_BUDGET_EXCEEDED.value)


def test_oop_chain_incomplete_blocks_approve(api):
    """PRD §3.8: "if the report has any out-of-policy line, every approval step in its
    out-of-policy chain must already have a decision of APPROVED; an approve attempt
    while the chain is incomplete is rejected with ERR_OOP_CHAIN_INCOMPLETE."

    Design: Corner/validations/oop_chain_incomplete_blocks_approve
    """
    env = setup_base_env(max_economy_fare_cents=50000, advance_purchase_days=14)
    trip = create_approved_trip(env, budget_total_cents=100000)
    report = create_report(env, trip, title="OOP Rpt")
    # late-booked economy claimed 50000 > floor(50000*0.8)=40000 -> out of policy line.
    # reimbursable 40000 >= threshold 7500, so substantiate with a VERIFIED receipt
    # (ocr_amount must equal the claimed 50000) before submit (PRD §3.7).
    add_flight_line_with_receipt(env, report, claimed_amount_cents=50000,
                                 cabin_class="ECONOMY", scheduled_hours=4, advance_days=5)
    add_approval_step(env, report, env["approver"]["id"], step_order=1)
    submit_report(env, report)
    resp = api.decide_expense_report(report["id"], {"decision": "APPROVE"}, env["approver_headers"])
    validate_error(resp, ApiErrorId.ERR_OOP_CHAIN_INCOMPLETE.value)


def test_return_reason_required(api):
    """PRD §3.8: "A return decision sends the report from SUBMITTED back to RETURNED for
    revision; it requires a return_reason in the payload, and a return decision without
    one is rejected with ERR_RETURN_REASON_REQUIRED."

    Design: Corner/validations/return_reason_required
    """
    env = setup_base_env()
    trip = create_approved_trip(env, budget_total_cents=100000)
    report = create_report(env, trip, title="Return Rpt")
    add_mileage_line(env, report, miles=100)
    submit_report(env, report)
    resp = api.decide_expense_report(report["id"], {"decision": "RETURN"}, env["approver_headers"])
    validate_error(resp, ApiErrorId.ERR_RETURN_REASON_REQUIRED.value)


def test_trip_create_no_active_policy(api):
    """PRD §3.2: "If no policy is ACTIVE at the moment of creation, the request is
    rejected with ERR_NO_ACTIVE_POLICY."

    Design: Corner/validations/trip_create_no_active_policy
    """
    approver = create_approver(approval_limit_cents=500000)
    traveler = create_traveler(manager_id=approver["id"])
    create_draft_policy()  # DRAFT, never activated
    create_per_diem_rate(state_code="CA", lodging_cap_cents=20000, mie_cents=8000)
    resp = api.create_trip_request(
        {
            "traveler_id": traveler["id"], "destination_state": "CA",
            "start_date": "2026-06-01", "end_date": "2026-06-03",
            "budget_total_cents": 50000,
        },
        make_traveler_headers(traveler["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_NO_ACTIVE_POLICY.value)


def test_policy_already_active_on_second_activate(api):
    """PRD §3.1: "A policy moves from DRAFT to ACTIVE only when no other policy is
    already ACTIVE; activating a second policy while one is already active is rejected
    with ERR_POLICY_ALREADY_ACTIVE."

    Design: Corner/validations/policy_already_active_on_second_activate
    """
    create_active_policy(name="P1")
    p2 = create_draft_policy(name="P2", max_economy_fare_cents=60000,
                             business_class_min_hours=5, advance_purchase_days=10,
                             cdw_daily_cap_cents=4000, mileage_rate_milli_cents=70000,
                             receipt_required_threshold_cents=5000)
    resp = api.activate_travel_policy(p2["id"], ADMIN)
    validate_error(resp, ApiErrorId.ERR_POLICY_ALREADY_ACTIVE.value)


def test_policy_in_use_on_retire(api):
    """PRD §3.1: "Retiring an ACTIVE policy moves it to the terminal RETIRED state, but
    only when no trip request that still references it is in PENDING or
    PENDING_OOP_APPROVAL; an attempt to retire a policy still referenced by such a trip
    is rejected with ERR_POLICY_IN_USE."

    Design: Corner/validations/policy_in_use_on_retire
    """
    env = setup_base_env()
    create_pending_trip(env, budget_total_cents=50000)  # PENDING trip pinned to active policy
    resp = api.retire_travel_policy(env["policy"]["id"], env["admin_headers"])
    validate_error(resp, ApiErrorId.ERR_POLICY_IN_USE.value)


def test_card_close_with_open_holds(api):
    """PRD §3.3: "Closing moves a card to the terminal CLOSED state from either ACTIVE
    or FROZEN, but only when it has no outstanding provisional reservations — that is,
    when authorized_holds_cents equals zero; closing a card that still carries open
    holds is rejected with ERR_CARD_HAS_OPEN_HOLDS."

    Design: Corner/validations/card_close_with_open_holds
    """
    env = setup_base_env()
    trip = create_approved_trip(env, budget_total_cents=100000)
    card = issue_card(env, trip, load_limit_cents=100000)
    report = create_report(env, trip, title="Hold Rpt")
    add_flight_line(env, report, claimed_amount_cents=30000,
                    cabin_class="ECONOMY", scheduled_hours=4, advance_days=20,
                    virtual_card_id=card["id"])
    resp = api.close_virtual_card(card["id"], env["admin_headers"])
    validate_error(resp, ApiErrorId.ERR_CARD_HAS_OPEN_HOLDS.value)
