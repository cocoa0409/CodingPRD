"""Transitive cascade chains (PRD §3.11 settlement cascade, §3.8 dispatch)."""
from test_helpers import (
    validate_success, validate_paginated,
    setup_financing_active, setup_case_active_step1_booked_ground,
    open_refund, list_steps,
    api_client, TEST_USERS,
)

BILLING = TEST_USERS["billing_headers"]
MFG = TEST_USERS["manufacturing_headers"]


def _installment_by_seq(api, fin_id, seq):
    # Request a full page: a 12-month schedule exceeds the default page limit
    # of 10, so seq 12 would be off the first page without an explicit limit.
    data, _meta = validate_paginated(
        api.list_installments(fin_id, BILLING, params={"limit": 100})
    )
    for inst in data:
        if inst["sequence_no"] == seq:
            return inst
    raise AssertionError(f"installment seq {seq} not found")


def test_refund_settle_cascades_case_to_refunded_and_cancels_financing(api):
    """PRD §3.11 Settlement cascade: "If a financing plan exists for the case,
    its `billing_state` is set to `CANCELLED` and all of its `SCHEDULED` (and
    `LATE`) installments are marked `WAIVED`. The full chain is: settle -> case
    `REFUNDED` -> financing `CANCELLED` -> installments `WAIVED`".

    A depth-3 chain: settling drives the ACTIVE case to REFUNDED, which cancels
    the ACTIVE financing plan.

    Design: Difficulty/transitive_cascade/refund_settle_depth3_case_financing_installments
    """
    ctx = setup_financing_active(
        proposed_step_count=10, term_months=12, down_payment_cents=0, apr_bps=0,
        list_price_cents=375000,
    )
    assert ctx["case"]["total_contracted_cents"] == 300000
    fin_id = ctx["financing"]["id"]
    # Financing is ACTIVE, so the case may activate (money side settled).
    validate_success(api.activate_case(ctx["case"]["id"], MFG), 200)
    refund = open_refund(ctx["case"]["id"], reason="PATIENT_CANCEL")
    validate_success(api.approve_refund(refund["id"], BILLING), 200)
    validate_success(api.settle_refund(refund["id"], BILLING), 200)

    case = validate_success(api.get_case(ctx["case"]["id"], BILLING), 200)
    assert case["status"] == "REFUNDED", case["status"]
    fin = validate_success(api.get_financing_plan(fin_id, BILLING), 200)
    assert fin["billing_state"] == "CANCELLED", fin["billing_state"]


def test_refund_settle_waives_scheduled_installments(api):
    """PRD §3.11 Settlement cascade: "all of its `SCHEDULED` (and `LATE`)
    installments are marked `WAIVED`."

    The third link of the chain: after financing is cancelled by the settle, its
    SCHEDULED installments (first and last) are WAIVED.

    Design: Difficulty/transitive_cascade/refund_settle_depth3_case_financing_installments
    """
    ctx = setup_financing_active(
        proposed_step_count=10, term_months=12, down_payment_cents=0, apr_bps=0,
        list_price_cents=375000,
    )
    fin_id = ctx["financing"]["id"]
    validate_success(api.activate_case(ctx["case"]["id"], MFG), 200)
    refund = open_refund(ctx["case"]["id"], reason="PATIENT_CANCEL")
    validate_success(api.approve_refund(refund["id"], BILLING), 200)
    validate_success(api.settle_refund(refund["id"], BILLING), 200)

    assert _installment_by_seq(api, fin_id, 1)["status"] == "WAIVED"
    assert _installment_by_seq(api, fin_id, 12)["status"] == "WAIVED"


def test_dispatch_ships_step_then_next_step_becomes_eligible(api):
    """PRD §3.8: "Dispatching a booked shipment moves it from `BOOKED` to
    `IN_TRANSIT` and, across the aggregate boundary, moves the referenced step
    from `MANUFACTURED` to `SHIPPED`".
    PRD §3.8: "When a step ships, the next `PLANNED` step (if any) becomes
    eligible to start production."

    A depth-2 chain from a different trigger: dispatch -> shipment IN_TRANSIT ->
    step1 SHIPPED -> step2 can start production (PLANNED -> IN_PRODUCTION).

    Design: Difficulty/transitive_cascade/shipment_dispatch_depth2_step_then_next_eligible
    """
    ctx = setup_case_active_step1_booked_ground(
        proposed_step_count=10,
        window_start="2026-05-02T00:00:00Z", window_end="2026-05-03T00:00:00Z",
    )
    s1, s2 = ctx["steps"][0], ctx["steps"][1]
    dispatched = validate_success(api.dispatch_shipment(ctx["shipment"]["id"], MFG), 200)
    assert dispatched["status"] == "IN_TRANSIT", dispatched["status"]
    step1 = validate_success(api.get_aligner_step(s1["id"], MFG), 200)
    assert step1["status"] == "SHIPPED", step1["status"]
    started = validate_success(api.start_production(s2["id"], MFG), 200)
    assert started["status"] == "IN_PRODUCTION", started["status"]


def test_dispatch_marks_shipment_in_transit_and_step_shipped(api):
    """PRD §3.8: "Dispatching a booked shipment moves it from `BOOKED` to
    `IN_TRANSIT` and, across the aggregate boundary, moves the referenced step
    from `MANUFACTURED` to `SHIPPED`; the dispatch requires the referenced step
    to be `MANUFACTURED`."

    The first two links of the chain, asserted in isolation: the BOOKED shipment
    becomes IN_TRANSIT and its MANUFACTURED step becomes SHIPPED.

    Design: Difficulty/transitive_cascade/shipment_dispatch_depth2_step_then_next_eligible
    """
    ctx = setup_case_active_step1_booked_ground(
        proposed_step_count=10,
    )
    s1 = ctx["steps"][0]
    step_before = validate_success(api.get_aligner_step(s1["id"], MFG), 200)
    assert step_before["status"] == "MANUFACTURED"
    dispatched = validate_success(api.dispatch_shipment(ctx["shipment"]["id"], MFG), 200)
    assert dispatched["status"] == "IN_TRANSIT"
    step1 = validate_success(api.get_aligner_step(s1["id"], MFG), 200)
    assert step1["status"] == "SHIPPED", step1["status"]
