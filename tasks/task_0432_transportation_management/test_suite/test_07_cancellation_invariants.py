"""Shipment cancellation: the unwind cascade and the conserved-quantity
invariants it preserves (load weight, carrier-assignment bundle).
"""
from test_helpers import (
    TEST_USERS,
    validate_success,
    setup_tendered_shipment, setup_booked_shipment, setup_consolidated_shipment,
)

CARRIER = TEST_USERS["carrier_ops_headers"]
SHIPPER = TEST_USERS["shipper_ops_headers"]
DOCK = TEST_USERS["dock_ops_headers"]


class TestCancelCascadeDepth3:
    """Cancel -> OFFERED tender declines -> the decline reverts tender_status."""

    def test_cancel_declines_offered_tender_and_reverts_status(self, api):
        """PRD §3.9: "any `OFFERED` tender for this shipment fires its own
        `OFFERED → DECLINED` transition; that tender's decline side effect in turn
        reverts the shipment's `tender_status` from `TENDERED` back to
        `UNTENDERED`."

        Design: Difficulty/transitive_cascade/shipment_cancel_cascade_depth3_tender_decline_reverts_status
        """
        ctx = setup_tendered_shipment()  # Tender OFFERED, Shipment TENDERED/PENDING
        ship = validate_success(api.cancel_shipment(ctx["shipment"]["id"], SHIPPER), 200)
        assert ship["execution_status"] == "CANCELLED"
        tender = validate_success(api.get_tender(ctx["tender"]["id"], SHIPPER), 200)
        assert tender["status"] == "DECLINED"
        reread = validate_success(api.get_shipment(ctx["shipment"]["id"], SHIPPER), 200)
        assert reread["tender_status"] == "UNTENDERED"

    def test_cancel_sets_execution_status_cancelled(self, api):
        """PRD §3.9: "Cancellation sets the `execution_status` to `CANCELLED` and
        then unwinds everything the shipment had accumulated, in a defined cascade."

        Design: Difficulty/transitive_cascade/shipment_cancel_cascade_depth3_tender_decline_reverts_status
        """
        ctx = setup_tendered_shipment()
        ship = validate_success(api.cancel_shipment(ctx["shipment"]["id"], SHIPPER), 200)
        assert ship["execution_status"] == "CANCELLED"


class TestLoadWeightConservation:
    """Add then cancel-detach returns the load's consolidated weight to pre-add."""

    def test_cancel_detaches_and_recomputes_weight_to_zero(self, api):
        """PRD §3.9: "if the shipment was consolidated onto a load, it is detached:
        its `load_id` is set back to null and the load's `consolidated_weight_lbs`
        is recomputed accordingly."

        Design: Difficulty/compensating_invariant/load_weight_conservation_add_then_cancel_detach
        """
        ctx = setup_consolidated_shipment(planned_capacity_lbs=10000, ship_weight=6000)
        # Pre-cancel the load already carries the 6000-lb shipment.
        ship = validate_success(api.cancel_shipment(ctx["shipment"]["id"], SHIPPER), 200)
        assert ship["execution_status"] == "CANCELLED"
        assert ship["load_id"] is None
        load = validate_success(api.get_load(ctx["load_id"], DOCK), 200)
        assert load["consolidated_weight_lbs"] == 0

    def test_consolidated_weight_reflects_add_before_cancel(self, api):
        """PRD §3.6: "The conserved property is that the total non-cancelled weight
        assigned to a load always equals its consolidated weight, so adding a
        shipment and later cancelling it returns the load to its pre-add weight."

        Design: Difficulty/compensating_invariant/load_weight_conservation_add_then_cancel_detach
        """
        ctx = setup_consolidated_shipment(planned_capacity_lbs=10000, ship_weight=6000)
        load_before = validate_success(api.get_load(ctx["load_id"], DOCK), 200)
        assert load_before["consolidated_weight_lbs"] == 6000
        validate_success(api.cancel_shipment(ctx["shipment"]["id"], SHIPPER), 200)
        load_after = validate_success(api.get_load(ctx["load_id"], DOCK), 200)
        assert load_after["consolidated_weight_lbs"] == 0


class TestCarrierAssignmentConservation:
    """Book then cancel clears the entire carrier-assignment bundle."""

    def test_cancel_clears_assignment_bundle(self, api):
        """PRD §3.9: "Where the shipment was already booked — its tender accepted,
        so there is no `OFFERED` tender left to decline — the cancel instead clears
        `assigned_carrier_id`, `contract_rate_id`, and `quoted_cost_cents` directly
        and sets `tender_status` back to `UNTENDERED`."

        Design: Difficulty/compensating_invariant/carrier_assignment_conservation_book_then_cancel_clears
        """
        ctx = setup_booked_shipment()  # BOOKED, quoted_cost_cents locked, not on a load
        ship = validate_success(api.cancel_shipment(ctx["shipment"]["id"], SHIPPER), 200)
        assert ship["assigned_carrier_id"] is None
        assert ship["contract_rate_id"] is None
        assert ship["quoted_cost_cents"] is None
        assert ship["tender_status"] == "UNTENDERED"

    def test_booked_shipment_carries_assignment_before_cancel(self, api):
        """PRD §3.5: "Booking writes the accepted tender's carrier onto the
        shipment's `assigned_carrier_id` and the accepted tender's rate onto the
        shipment's `contract_rate_id`, and it locks the provisional freight cost
        into `quoted_cost_cents`."

        Design: Difficulty/compensating_invariant/carrier_assignment_conservation_book_then_cancel_clears
        """
        ctx = setup_booked_shipment()
        ship = validate_success(api.get_shipment(ctx["shipment"]["id"], SHIPPER), 200)
        assert ship["assigned_carrier_id"] == ctx["carrier"]["id"]
        assert ship["quoted_cost_cents"] == 91250
        assert ship["tender_status"] == "BOOKED"
