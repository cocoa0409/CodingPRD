"""State machine tests: the FulfillmentJob cyclic loop (SHIPPED->FAILED->
REPRINT_REQUESTED->QUEUED) and the parallel payment/fulfillment dimensions
on Order."""
from test_helpers import (
    validate_success,
    get_success_data,
    api_client,
    make_creator_headers,
    make_platform_admin_headers,
    make_anonymous_headers,
    make_fulfillment_partner_headers,
    setup_basic_scenario,
    create_and_capture_order,
    advance_order_to_shipped,
    fail_shipped_job,
    open_reprint_on_failed_job,
)
from test_helpers.fixtures import _find_job_for_order


# =============================================================================
# Rule 3 — non_linear_state_machine: FulfillmentJob cyclic on approval
# =============================================================================

def test_reprint_approval_cycles_job_back_to_queued(api):
    """PRD §3.8: "On approval, `ReprintRequest.status` moves to `APPROVED`,
    `FulfillmentJob.status` cycles back to `QUEUED`, `FulfillmentJob.reprint_generation`
    increments by 1, and `FulfillmentJob.partner_charge_cents` is recomputed to
    reflect the reprint surcharge described below."

    A job that has traversed QUEUED->PRINTING->SHIPPED, been failed, and had a
    reprint approved now sits at QUEUED again with reprint_generation == 1.

    Design: Difficulty/non_linear_state_machine/fulfillment_job_cyclic_shipped_failed_reprint_queued
    """
    scenario = setup_basic_scenario(
        creator_email="sm1@example.com", display_name="SM1", slug="sm1-sf",
        sku="T-SM1", base_cost_cents=2000, markup_bps=5000,
        file_hash="hash_sm1", clock_iso="2026-06-01T00:00:00Z",
    )
    order, job = create_and_capture_order(scenario, item_count=1)
    order, job = advance_order_to_shipped(scenario, order)
    fail_shipped_job(scenario, job)
    job = _find_job_for_order(order["id"])
    reprint = open_reprint_on_failed_job(
        job, fault_category="PARTNER_FAULT", reason_code="MISPRINT",
    )
    api.approve_reprint(reprint["id"], make_platform_admin_headers())

    job_after = get_success_data(
        api.get_fulfillment_job(job["id"], make_platform_admin_headers())
    )
    assert job_after["status"] == "QUEUED", \
        f"Expected job status=QUEUED after reprint approval, got {job_after['status']}"
    assert job_after["reprint_generation"] == 1, \
        f"Expected reprint_generation=1, got {job_after['reprint_generation']}"


def test_reprint_approval_drags_order_fulfillment_from_shipped_back_to_in_print(api):
    """PRD §3.8: "The linked order's `fulfillment_status` transitions from
    `SHIPPED` back to `IN_PRINT` — a legal retrograde permitted only on reprint
    approval — so that the reprint cycle then re-enters the print → ship → deliver
    sequence as if it were a fresh routing."

    An Order at fulfillment_status=SHIPPED whose linked job's reprint is approved
    moves back to IN_PRINT — a retrograde motion legal only on this trigger.

    Design: Difficulty/non_linear_state_machine/fulfillment_job_cyclic_shipped_failed_reprint_queued
    """
    scenario = setup_basic_scenario(
        creator_email="sm2@example.com", display_name="SM2", slug="sm2-sf",
        sku="T-SM2", base_cost_cents=2000, markup_bps=5000,
        file_hash="hash_sm2", clock_iso="2026-06-01T00:00:00Z",
    )
    order, job = create_and_capture_order(scenario, item_count=1)
    order, job = advance_order_to_shipped(scenario, order)
    fail_shipped_job(scenario, job)
    job = _find_job_for_order(order["id"])
    reprint = open_reprint_on_failed_job(
        job, fault_category="PARTNER_FAULT", reason_code="MISPRINT",
    )
    api.approve_reprint(reprint["id"], make_platform_admin_headers())

    order_after = get_success_data(
        api.get_order(order["id"], make_platform_admin_headers())
    )
    assert order_after["fulfillment_status"] == "IN_PRINT", \
        f"Expected fulfillment_status=IN_PRINT after reprint, got {order_after['fulfillment_status']}"


# =============================================================================
# Rule 3 — non_linear_state_machine: Order parallel dimensions
# =============================================================================

def test_capture_leaves_payment_and_fulfillment_on_independent_states(api):
    """PRD §3.7: "An `Order` runs on two independent state axes at once. The
    `payment_status` axis flows through `DRAFT`, `AUTHORIZED`, `CAPTURED`, and
    thence to `REFUND_PARTIAL`, `REFUND_FULL`, or `VOIDED`. The `fulfillment_status`
    axis flows through `PENDING`, `ROUTED`, `IN_PRINT`, `SHIPPED`, and either
    `DELIVERED` or `CANCELLED`."
    PRD §3.7: "Capturing the payment transitions `payment_status` from `AUTHORIZED`
    to `CAPTURED` and, if `fulfillment_status` is still `PENDING`, immediately
    fires the routing selector."

    After a capture, payment_status==CAPTURED and fulfillment_status==ROUTED sit
    on the same row.

    Design: Difficulty/non_linear_state_machine/order_parallel_payment_and_fulfillment_dimensions
    """
    scenario = setup_basic_scenario(
        creator_email="sm3@example.com", display_name="SM3", slug="sm3-sf",
        sku="T-SM3", base_cost_cents=2000, markup_bps=5000,
        file_hash="hash_sm3", clock_iso="2026-06-01T00:00:00Z",
    )
    order, _ = create_and_capture_order(scenario, item_count=1)
    assert order["payment_status"] == "CAPTURED", \
        f"Expected payment_status=CAPTURED, got {order['payment_status']}"
    assert order["fulfillment_status"] == "ROUTED", \
        f"Expected fulfillment_status=ROUTED, got {order['fulfillment_status']}"


def test_mark_in_print_advances_fulfillment_without_changing_payment(api):
    """PRD §3.7: "The two axes evolve independently — a fully captured order can
    still be pending routing, and a shipped order can still trigger a refund —
    with a small set of explicit coupling rules called out below."
    PRD §3.8: "The partner marks the job in print, transitioning the order's
    `fulfillment_status` from `ROUTED` to `IN_PRINT` and the linked
    `FulfillmentJob.status` from `QUEUED` to `PRINTING`."

    After mark-in-print: fulfillment_status advances ROUTED->IN_PRINT while
    payment_status stays CAPTURED.

    Design: Difficulty/non_linear_state_machine/order_parallel_payment_and_fulfillment_dimensions
    """
    scenario = setup_basic_scenario(
        creator_email="sm4@example.com", display_name="SM4", slug="sm4-sf",
        sku="T-SM4", base_cost_cents=2000, markup_bps=5000,
        file_hash="hash_sm4", clock_iso="2026-06-01T00:00:00Z",
    )
    order, _ = create_and_capture_order(scenario, item_count=1)
    partner_headers = make_fulfillment_partner_headers(scenario["partner"]["id"])
    resp = api.mark_in_print(order["id"], partner_headers)
    after = validate_success(resp)
    assert after["payment_status"] == "CAPTURED", \
        f"Expected payment_status still CAPTURED, got {after['payment_status']}"
    assert after["fulfillment_status"] == "IN_PRINT", \
        f"Expected fulfillment_status=IN_PRINT, got {after['fulfillment_status']}"
