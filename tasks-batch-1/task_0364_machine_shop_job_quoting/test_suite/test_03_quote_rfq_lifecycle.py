"""Quote revision loop, RFQ lifecycle transitions, and the RFQ-cancel cascade.

Translates queue A non_linear_state_machine (quote reject/reopen cycle),
transitive_cascade (rfq_cancel_cascade_depth2), and queue B state_machines
instances for RFQ submit/cancel/close/reopen guards.
"""
import pytest
from test_helpers import (
    api_client, validate_success, validate_error, get_success_data,
    create_draft_rfq, create_rfq_with_part_line, create_submitted_rfq_with_part_line,
    create_draft_quote, add_routing_op, create_approved_quote,
    create_part_line_payload, create_quote_payload,
    TEST_USERS,
)

ADMIN = TEST_USERS["shop_admin_headers"]
EST = TEST_USERS["estimator_headers"]


def _priced_then_rejected_quote(customer_id, quantity=2, mat=1000):
    """SUBMITTED RFQ + PartLine + Quote priced then rejected. Returns (rfq, pl, quote)."""
    rfq, pl, quote = create_draft_quote(
        part_line_overrides={"material_spec": "AL_6061", "quantity": quantity},
        quote_overrides={"material_unit_cost_cents": mat, "scrap_allowance_pct": 0},
        customer_id=customer_id,
    )
    add_routing_op(quote["id"], seq=1, machine_class="MILL_3AX",
                   estimated_cycle_min=5.0, setup_fee_cents=2000)
    api_client.price_quote(quote["id"], EST)
    api_client.reject_quote(quote["id"], {"rejection_reason": "price too high"}, EST)
    return rfq, pl, quote


def test_quote_reopen_returns_to_priced_after_reprice(api):
    """PRD §3.2: "A REJECTED quote can be reopened by the Estimator, returning it
    REJECTED -> DRAFT for revision".
    PRD §3.2: "Pricing a quote drives it DRAFT -> PRICED".

    Reject -> reopen (DRAFT) -> price again returns the quote to PRICED.

    Design: Difficulty/non_linear_state_machine/quote_reject_reopen_revision_cycle
    """
    rfq, pl, quote = _priced_then_rejected_quote("CUST-5")
    reopened = validate_success(api.reopen_quote(quote["id"], EST), 200)
    assert reopened["status"] == "DRAFT"
    repriced = validate_success(api.price_quote(quote["id"], EST), 200)
    assert repriced["status"] == "PRICED"


def test_quote_reopen_clears_then_reprice_rederives_fields(api):
    """PRD §3.2: "Reopening clears the revision slate: margin_pct,
    extended_cost_cents, quoted_price_cents, and quoted_unit_price_cents are all
    reset to 0 and rejection_reason is cleared."
    PRD §3.2: "The estimated total cost, recorded in extended_cost_cents, is
    labor total plus material total."

    On reopen the computed figure clears to 0; re-pricing re-derives 5800 / 7830.

    Design: Difficulty/non_linear_state_machine/quote_reject_reopen_revision_cycle
    """
    rfq, pl, quote = _priced_then_rejected_quote("CUST-5b")
    reopened = validate_success(api.reopen_quote(quote["id"], EST), 200)
    assert reopened["extended_cost_cents"] == 0
    repriced = validate_success(api.price_quote(quote["id"], EST), 200)
    assert repriced["extended_cost_cents"] == 5800
    assert repriced["quoted_price_cents"] == 7830


def test_rfq_cancel_cascade_sets_rfq_cancelled(api):
    """PRD §3.1: "A SUBMITTED RFQ cancels too, transitioning SUBMITTED ->
    CANCELLED, but only when none of its quotes has been approved".

    Design: Difficulty/transitive_cascade/rfq_cancel_cascade_depth2_rejects_quotes
    """
    rfq, pl, quote = create_draft_quote(
        part_line_overrides={"material_spec": "AL_6061", "quantity": 3},
        quote_overrides={"material_unit_cost_cents": 1000, "scrap_allowance_pct": 0},
        customer_id="CUST-8",
    )
    add_routing_op(quote["id"], seq=1, machine_class="MILL_3AX",
                   estimated_cycle_min=5.0, setup_fee_cents=2000)
    api.price_quote(quote["id"], EST)
    validate_success(api.cancel_rfq(rfq["id"], ADMIN), 200)
    rfq_after = validate_success(api.get_rfq(rfq["id"], ADMIN), 200)
    assert rfq_after["status"] == "CANCELLED"


def test_rfq_cancel_cascade_rejects_priced_quote_with_reason(api):
    """PRD §3.1: "When a SUBMITTED RFQ is successfully cancelled, the system
    cascades downward: every quote of that RFQ currently in DRAFT or PRICED is
    driven to REJECTED, and each such quote records the rejection reason
    'RFQ cancelled'."

    Design: Difficulty/transitive_cascade/rfq_cancel_cascade_depth2_rejects_quotes
    """
    rfq, pl, quote = create_draft_quote(
        part_line_overrides={"material_spec": "AL_6061", "quantity": 3},
        quote_overrides={"material_unit_cost_cents": 1000, "scrap_allowance_pct": 0},
        customer_id="CUST-8b",
    )
    add_routing_op(quote["id"], seq=1, machine_class="MILL_3AX",
                   estimated_cycle_min=5.0, setup_fee_cents=2000)
    api.price_quote(quote["id"], EST)
    api.cancel_rfq(rfq["id"], ADMIN)
    q_after = validate_success(api.get_quote(quote["id"], EST), 200)
    assert q_after["status"] == "REJECTED"
    assert q_after["rejection_reason"] == "RFQ cancelled"


def test_submit_rfq_with_zero_part_lines_rejected(api):
    """PRD §3.1: "Submission is refused with ERR_RFQ_NO_PART_LINES if the RFQ has
    no part lines (that is, if part_line_count is below 1)."

    Design: Corner/state_machines/submit_rfq_with_zero_part_lines_rejected
    """
    rfq = create_draft_rfq(customer_id="C-8")
    res = api.submit_rfq(rfq["id"], ADMIN)
    validate_error(res, "ERR_RFQ_NO_PART_LINES")
    after = validate_success(api.get_rfq(rfq["id"], ADMIN), 200)
    assert after["status"] == "DRAFT"


def test_cancel_terminal_rfq_invalid_state(api):
    """PRD §2.9: "State legality — the target resource must currently be in a
    state from which the requested transition is defined; otherwise
    ERR_INVALID_STATE (409)."
    PRD §3.1: "Both CLOSED and CANCELLED are terminal RFQ states."

    Design: Corner/state_machines/cancel_terminal_rfq_invalid_state
    """
    rfq = create_draft_rfq(customer_id="C-12")
    validate_success(api.cancel_rfq(rfq["id"], ADMIN), 200)
    res = api.cancel_rfq(rfq["id"], ADMIN)
    validate_error(res, "ERR_INVALID_STATE")


def test_cancel_submitted_rfq_with_approved_quote_rejected(api):
    """PRD §3.1: "A SUBMITTED RFQ cancels too, transitioning SUBMITTED ->
    CANCELLED, but only when none of its quotes has been approved; if any quote
    of the RFQ is already APPROVED, the cancel is refused with
    ERR_RFQ_HAS_APPROVED_QUOTE."

    The RFQ must stay SUBMITTED while one of its quotes is APPROVED — per PRD
    §3.2 the RFQ only bubbles SUBMITTED -> QUOTED once *every* part line has an
    approved quote. So the RFQ here carries two part lines; only the first part
    line's quote is approved, leaving the RFQ in SUBMITTED with an APPROVED quote
    present. Cancelling it is then refused with ERR_RFQ_HAS_APPROVED_QUOTE.

    Design: Corner/state_machines/cancel_submitted_rfq_with_approved_quote_rejected
    """
    # DRAFT RFQ with TWO part lines, then submit -> SUBMITTED.
    rfq = create_draft_rfq(customer_id="C-13")
    pl1 = get_success_data(api.create_part_line(
        rfq["id"], create_part_line_payload(part_number="P-1",
                                            material_spec="AL_6061", quantity=3), ADMIN))
    pl2 = get_success_data(api.create_part_line(
        rfq["id"], create_part_line_payload(part_number="P-2",
                                            material_spec="AL_6061", quantity=3), ADMIN))
    get_success_data(api.submit_rfq(rfq["id"], ADMIN))
    # Price + approve a quote for ONLY the first part line. The second part line
    # has no approved quote, so the RFQ remains SUBMITTED (no QUOTED bubble-up).
    quote = get_success_data(api.create_quote(
        create_quote_payload(rfq["id"], pl1["id"],
                             material_unit_cost_cents=800, scrap_allowance_pct=0), EST))
    add_routing_op(quote["id"], seq=1, machine_class="MILL_3AX",
                   estimated_cycle_min=4.0, setup_fee_cents=1000)
    # Pricing bumps the quote's version (PRD §2.6); approve OCC must carry the
    # post-price version, so capture the priced quote before approving.
    priced = get_success_data(api.price_quote(quote["id"], EST))
    quote = get_success_data(api.approve_quote(
        priced["id"], {"expected_quote_version": priced["version"]}, EST))
    # Confirm the precondition the assertion depends on: RFQ still SUBMITTED.
    rfq_now = get_success_data(api.get_rfq(rfq["id"], ADMIN))
    assert rfq_now["status"] == "SUBMITTED"
    res = api.cancel_rfq(rfq["id"], ADMIN)
    validate_error(res, "ERR_RFQ_HAS_APPROVED_QUOTE")


def test_reopen_quote_on_non_submitted_rfq_rejected(api):
    """PRD §3.2: "reopening a quote whose RFQ has closed or been cancelled is
    refused with ERR_RFQ_NOT_SUBMITTED."

    The cancel from SUBMITTED rejects the PRICED quote and the RFQ becomes
    CANCELLED; reopening that quote is then blocked.

    Design: Corner/state_machines/reopen_quote_on_non_submitted_rfq_rejected
    """
    rfq, pl, quote = create_draft_quote(
        part_line_overrides={"material_spec": "AL_6061", "quantity": 3},
        quote_overrides={"material_unit_cost_cents": 800, "scrap_allowance_pct": 0},
        customer_id="C-14",
    )
    add_routing_op(quote["id"], seq=1, machine_class="MILL_3AX",
                   estimated_cycle_min=4.0, setup_fee_cents=1000)
    api.price_quote(quote["id"], EST)
    api.cancel_rfq(rfq["id"], ADMIN)  # cascade rejects the PRICED quote, RFQ -> CANCELLED
    res = api.reopen_quote(quote["id"], EST)
    validate_error(res, "ERR_RFQ_NOT_SUBMITTED")


def test_rfq_close_blocked_when_wo_not_shipped(api):
    """PRD §3.1: "a ShopAdmin may close a QUOTED RFQ, transitioning it QUOTED ->
    CLOSED, but only when every work order derived from that RFQ's quotes has
    reached SHIPPED or CLOSED."
    PRD §2.9: "the target resource must currently be in a state from which the
    requested transition is defined; otherwise ERR_INVALID_STATE (409)."

    Design: Corner/state_machines/rfq_close_blocked_when_wo_not_shipped
    """
    rfq, pl, quote, ops = create_approved_quote(
        routing_ops=[{"seq": 1, "machine_class": "MILL_3AX",
                      "estimated_cycle_min": 4.0, "setup_fee_cents": 1000}],
        part_line_overrides={"material_spec": "AL_6061", "quantity": 3},
        quote_overrides={"material_unit_cost_cents": 800, "scrap_allowance_pct": 0},
        customer_id="C-15",
    )
    # RFQ bubbled to QUOTED; create a PLANNED work order from the approved quote.
    validate_success(api.create_work_order(
        {"quote_id": quote["id"], "part_line_id": pl["id"],
         "qty_ordered": 3, "qty_started": 3}, ADMIN), 201)
    res = api.close_rfq(rfq["id"], ADMIN)
    validate_error(res, "ERR_INVALID_STATE")
