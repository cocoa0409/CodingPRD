"""Which failure a request reports when it violates more than one rule.

The order of the checks is fixed, so a request that breaks two rules must always
name the earlier one. Two pairings prove it: a state guard against the fiscal gate
on the clearance endpoint, and a safety rule against a temporal rule on the
start-pumping endpoint.
"""

from test_helpers import (
    ApiErrorId,
    EARLY_QUOTE,
    OPS,
    add_confirmed_nomination,
    api_client,
    build_cleared_order,
    build_issued_invoice,
    build_two_asset_context,
    clear_order,
    clear_payload,
    force_credit_hold,
    make_barge_master_headers,
    read_customer,
    read_order,
    schedule_order,
    validate_error,
)

STEM_B_WINDOW_START = "2026-08-15T06:00:00Z"
STEM_B_WINDOW_END = "2026-08-16T06:00:00Z"
STEM_B_SLOT_END = "2026-08-15T12:00:00Z"

BRAVO_SLOT_START = "2026-08-10T13:31:00Z"
BRAVO_SLOT_END = "2026-08-10T17:00:00Z"


def _held_buyer_with_a_delivered_and_a_scheduled_order():
    """One delivered, invoiced stem and one freshly scheduled stem on a held buyer.

    The credit limit is only shrunk to the settled receivable after both orders
    exist, so the scheduling itself is never blocked and the hold is left as the
    only fiscal defect at clearance time.
    """
    ctx = build_issued_invoice()
    nomination_b = add_confirmed_nomination(
        ctx,
        store_as="nomination_b",
        nominated_quantity_mt=900.000,
        vessel_imo="9654321",
        vessel_name="MV Boreas",
        window_start=STEM_B_WINDOW_START,
        window_end=STEM_B_WINDOW_END,
        eca_documentation_ref="CHG-2026-0002",
    )
    schedule_order(
        ctx,
        nomination_id=nomination_b["id"],
        store_as="order_b",
        planned_quantity_mt=900.000,
        slot_start=STEM_B_WINDOW_START,
        slot_end=STEM_B_SLOT_END,
    )
    force_credit_hold(ctx)
    return ctx


class TestStateLegalityOutranksTheFiscalGate:
    """`ERR_INVALID_ORDER_STATE` at step 8 against the credit hold at step 14."""

    def test_a_delivered_order_reports_the_state_failure_not_the_hold(self):
        """PRD §2.8: "When a single request could fail several checks, the system
        evaluates them in a fixed precedence and returns the first failure."
        PRD §2.8: "Placing the fiscal gates last matters commercially: a customer on
        credit hold whose nomination is also badly documented sees the documentation
        failure first, because that is the defect the operator can actually fix."
        PRD §2.8: "The delivery order's `logistics_status` legality check guards eight
        operations, each rejecting with `ERR_INVALID_ORDER_STATE`: recording clearance,
        starting pumping, completing pumping, filing a joint survey, cancelling the
        order, issuing a bunker delivery note, raising an invoice, and reporting a spill
        incident."
        PRD §3.2: "A customer whose standing is `HOLD` cannot have a stem confirmed and
        cannot have a delivery slot cleared: both attempts are rejected with
        `ERR_CUSTOMER_CREDIT_HOLD` (HTTP 402)."

        Design: Difficulty/priority_pair_validation_conflict/order_state_precondition_precedes_credit_check
        """
        ctx = _held_buyer_with_a_delivered_and_a_scheduled_order()
        assert read_customer(ctx)["credit_status"] == "HOLD", (
            "The buyer must be on hold for both defects to be live"
        )
        assert ctx["order"]["logistics_status"] == "DELIVERED", (
            f"Expected the first order delivered, got "
            f"{ctx['order']['logistics_status']}"
        )

        response = api_client.clear_delivery_order(
            ctx["order"]["id"], clear_payload("PA-RTM-0009"), OPS
        )

        validate_error(response, ApiErrorId.ERR_INVALID_ORDER_STATE)

    def test_a_scheduled_order_for_the_same_buyer_reaches_the_credit_gate(self):
        """PRD §2.8: "Fiscal gates last: credit hold, then credit limit."
        PRD §3.5: "Clearance is gated by four substantive conditions beyond the state
        check: the nomination's `compliance_status` must be `APPROVED`, else
        `ERR_COMPLIANCE_NOT_APPROVED`; the asset's `status` must be `AVAILABLE`, else
        `ERR_ASSET_QUARANTINED`; no spill incident on that asset may still be `OPEN`,
        else `ERR_OPEN_SPILL_INCIDENT`; and the customer's `credit_status` must not be
        `HOLD`, else `ERR_CUSTOMER_CREDIT_HOLD`."

        Satisfying only the state guard isolates the fiscal gate, proving it is
        reachable rather than dead.

        Design: Difficulty/priority_pair_validation_conflict/order_state_precondition_precedes_credit_check
        """
        ctx = _held_buyer_with_a_delivered_and_a_scheduled_order()
        assert ctx["order_b"]["logistics_status"] == "SCHEDULED", (
            f"Expected the second order scheduled, got "
            f"{ctx['order_b']['logistics_status']}"
        )

        response = api_client.clear_delivery_order(
            ctx["order_b"]["id"], clear_payload("PA-RTM-0010"), OPS
        )

        validate_error(response, ApiErrorId.ERR_CUSTOMER_CREDIT_HOLD)

    def test_neither_refused_clearance_alters_its_order(self):
        """PRD §3.5: "The operations desk supplies a `port_clearance_ref`, and the
        order advances `SCHEDULED → CLEARED`, storing that reference and stamping
        `cleared_at` with the current logical clock."

        Design: Difficulty/priority_pair_validation_conflict/order_state_precondition_precedes_credit_check
        """
        ctx = _held_buyer_with_a_delivered_and_a_scheduled_order()

        api_client.clear_delivery_order(
            ctx["order"]["id"], clear_payload("PA-RTM-0009"), OPS
        )
        api_client.clear_delivery_order(
            ctx["order_b"]["id"], clear_payload("PA-RTM-0010"), OPS
        )

        delivered = read_order(ctx)
        assert delivered["port_clearance_ref"] == "PA-RTM-0001", (
            "The refused re-clearance must not overwrite the stored reference, got "
            f"{delivered['port_clearance_ref']}"
        )
        scheduled = read_order(order_id=ctx["order_b"]["id"])
        assert scheduled["logistics_status"] == "SCHEDULED", (
            f"The held order must stay scheduled, got "
            f"{scheduled['logistics_status']}"
        )
        assert scheduled["port_clearance_ref"] is None, (
            "No clearance reference may be stored on a refused clearance, got "
            f"{scheduled['port_clearance_ref']}"
        )
        assert scheduled["cleared_at"] is None, (
            f"cleared_at must stay null, got {scheduled['cleared_at']}"
        )


class TestSafetyOutranksTheTemporalRule:
    """`ERR_BOOM_NOT_CERTIFIED` at step 10 against the slot rule at step 12."""

    def _two_cleared_orders_before_either_slot_opens(self):
        """Alpha certified on the 06:00 slot, Bravo uncertified on the 13:31 slot.

        The clock is held at 2026-08-05, before both slots, so neither transfer may
        legally begin on temporal grounds either.
        """
        ctx = build_cleared_order(
            build_two_asset_context(
                second_asset={"name": "Bunker Bravo", "boom_certified": False},
                quotes=[EARLY_QUOTE],
            ),
            clearance_clock=None,
        )
        nomination_b = add_confirmed_nomination(
            ctx,
            store_as="nomination_b",
            nominated_quantity_mt=800.000,
            vessel_imo="9654321",
            vessel_name="MV Boreas",
            eca_documentation_ref="CHG-2026-0002",
        )
        schedule_order(
            ctx,
            asset_id=ctx["second_asset"]["id"],
            nomination_id=nomination_b["id"],
            store_as="order_b",
            planned_quantity_mt=800.000,
            slot_start=BRAVO_SLOT_START,
            slot_end=BRAVO_SLOT_END,
        )
        clear_order(ctx, order_id=ctx["order_b"]["id"], clock=None,
                    port_clearance_ref="PA-RTM-0002")
        return ctx

    def test_boom_certification_is_reported_before_the_slot_window(self):
        """PRD §2.8: "Business-safety rules, in this internal order: emission-control
        sulfur, emission-control documentation, boom certification, grade
        compatibility, containment confirmation."
        PRD §2.8: "Temporal rules, in this internal order: nomination window length,
        slot inside the window, asset slot conflict, port capacity, notice period, claim
        window, sample retention."
        PRD §3.5: "The asset must be `boom_certified`, because the spill prevention
        plan cannot otherwise be satisfied — a non-certified asset is rejected with
        `ERR_BOOM_NOT_CERTIFIED`."

        The uncertified barge's slot has not opened either, so both rules are live and
        the safety rule must win.

        Design: Difficulty/priority_pair_validation_conflict/boom_safety_precedes_slot_window_temporal
        """
        ctx = self._two_cleared_orders_before_either_slot_opens()

        response = api_client.start_pumping(
            ctx["order_b"]["id"],
            make_barge_master_headers(ctx["second_asset"]["id"]),
        )

        validate_error(response, ApiErrorId.ERR_BOOM_NOT_CERTIFIED)

    def test_a_certified_barge_in_the_same_unopened_slot_hits_the_temporal_rule(self):
        """PRD §3.5: "And the slot must actually have begun: the logical clock must be
        at or after the order's `slot_start`, else the start is rejected with
        `ERR_SLOT_OUTSIDE_WINDOW`."
        PRD §3.5: "Three safety conditions are enforced at exactly this moment and
        nowhere else."

        Design: Difficulty/priority_pair_validation_conflict/boom_safety_precedes_slot_window_temporal
        """
        ctx = self._two_cleared_orders_before_either_slot_opens()

        response = api_client.start_pumping(
            ctx["order"]["id"], make_barge_master_headers(ctx["asset"]["id"])
        )

        validate_error(response, ApiErrorId.ERR_SLOT_OUTSIDE_WINDOW)

    def test_neither_start_attempt_reaches_pumping(self):
        """PRD §3.5: "The barge master then starts the transfer, advancing the order
        `CLEARED → PUMPING`."
        PRD §3.5: "A successful start writes the nomination's grade onto the asset as
        its `last_grade_id`, which is what makes the segregation rule bite on the
        asset's next stem."

        Design: Difficulty/priority_pair_validation_conflict/boom_safety_precedes_slot_window_temporal
        """
        ctx = self._two_cleared_orders_before_either_slot_opens()

        api_client.start_pumping(
            ctx["order_b"]["id"], make_barge_master_headers(ctx["second_asset"]["id"])
        )
        api_client.start_pumping(
            ctx["order"]["id"], make_barge_master_headers(ctx["asset"]["id"])
        )

        for label, order_id in (
            ("certified", ctx["order"]["id"]),
            ("uncertified", ctx["order_b"]["id"]),
        ):
            order = read_order(order_id=order_id)
            assert order["logistics_status"] == "CLEARED", (
                f"The {label} barge's order must stay CLEARED, got "
                f"{order['logistics_status']}"
            )
        assert ctx["asset"]["last_grade_id"] is None, (
            "No transfer began, so no grade may have been written onto a barge"
        )
