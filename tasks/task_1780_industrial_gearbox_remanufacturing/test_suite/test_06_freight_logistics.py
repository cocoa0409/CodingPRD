"""Freight pricing tiers, rigging bay occupancy conflicts, and the shipment
state pipeline."""
from test_helpers import (
    ApiErrorId,
    add_shipment,
    assert_freight_shipment,
    TEST_USERS,
    setup_unit_with_order,
    validate_error,
    validate_success,
)

IC = TEST_USERS["intake_coordinator_headers"]


class TestFreightPricing:
    def test_freight_overweight_tier_uses_ceil(self, api):
        """PRD §3.5: "the base is 45,000 cents for a gross weight up to and
        including 500 kg; 120,000 cents for anything heavier up to and
        including 2,000 kg; and above 2,000 kg, 120,000 cents plus 18,000
        cents for each started 500-kg block beyond 2,000 kg, partial blocks
        rounding up. On top of the weight-tiered base, each booked rigging
        hour is charged at 9,500 cents."

        Design: Corner/calculations/freight_overweight_tier_uses_ceil
        """
        ctx = setup_unit_with_order(serial_number="GBX-HV")
        resp = api.create_shipment(
            ctx["order"]["id"],
            {"direction": "OUTBOUND", "weight_kg": 2_600,
             "rigging_bay_date": "2026-08-21", "rigging_bay_hours": 6},
            IC)
        data = validate_success(resp, expected_status=201)
        # ceil(600/500) = 2 blocks: 120000 + 2*18000 = 156000; + 6*9500.
        assert data["freight_charge_cents"] == 213_000
        assert_freight_shipment(data)
        assert data["status"] == "BOOKED"

    def test_freight_tier_boundary_2000kg_vs_2001kg(self, api):
        """PRD §3.5: "120,000 cents for anything heavier up to and including
        2,000 kg; and above 2,000 kg, 120,000 cents plus 18,000 cents for
        each started 500-kg block beyond 2,000 kg, partial blocks rounding
        up."

        Design: Corner/calculations/freight_tier_boundary_2000kg_vs_2001kg
        """
        ctx = setup_unit_with_order(serial_number="GBX-TB")
        ship_a = add_shipment(ctx["order"]["id"], direction="INBOUND",
                              weight_kg=2_000, rigging_bay_date="2026-08-22",
                              rigging_bay_hours=2)
        ship_b = add_shipment(ctx["order"]["id"], direction="OUTBOUND",
                              weight_kg=2_001, rigging_bay_date="2026-08-25",
                              rigging_bay_hours=2)
        # 2000 kg is still the flat tier: 120000 + 2*9500 = 139000.
        assert ship_a["freight_charge_cents"] == 139_000
        # 2001 kg enters overweight: ceil(1/500) = 1 block → 138000 + 19000.
        assert ship_b["freight_charge_cents"] == 157_000


class TestRiggingBayConflicts:
    def test_same_day_second_booking_conflicts(self, api):
        """PRD §3.5: "A booking occupies the bay for a half-open interval
        beginning at its `rigging_bay_date` and spanning its booked hours
        plus a two-hour turnaround buffer; if that occupancy intersects the
        occupancy of any other non-cancelled shipment, the booking is
        rejected with `ERR_RIGGING_BAY_CONFLICT`."

        Design: Difficulty/resource_temporal_overlap/rigging_bay_back_to_back_conflicts_due_to_buffer_tail
        """
        ctx1 = setup_unit_with_order(serial_number="GBX-RB1")
        ctx2 = setup_unit_with_order(serial_number="GBX-RB2",
                                     legal_name="Bay Co Two")
        first = add_shipment(ctx1["order"]["id"], direction="OUTBOUND",
                             weight_kg=400, rigging_bay_date="2026-08-12",
                             rigging_bay_hours=4)
        # First booking occupies [2026-08-12, +4h +2h buffer): a same-day
        # second booking intersects the buffer tail.
        resp = api.create_shipment(
            ctx2["order"]["id"],
            {"direction": "OUTBOUND", "weight_kg": 300,
             "rigging_bay_date": "2026-08-12", "rigging_bay_hours": 2},
            IC)
        validate_error(resp, ApiErrorId.ERR_RIGGING_BAY_CONFLICT.value)
        # The existing booking is untouched: 45000 + 4*9500 = 83000.
        unchanged = validate_success(
            api.get_shipment(first["id"], IC))
        assert unchanged["status"] == "BOOKED"
        assert unchanged["freight_charge_cents"] == 83_000

    def test_booking_beyond_buffer_tail_accepted(self, api):
        """PRD §3.5: "A booking occupies the bay for a half-open interval
        beginning at its `rigging_bay_date` and spanning its booked hours
        plus a two-hour turnaround buffer; if that occupancy intersects the
        occupancy of any other non-cancelled shipment, the booking is
        rejected with `ERR_RIGGING_BAY_CONFLICT`. Because the intervals are
        half-open, one booking ending exactly when another begins is
        permitted."

        Design: Difficulty/resource_temporal_overlap/rigging_bay_back_to_back_conflicts_due_to_buffer_tail
        """
        ctx1 = setup_unit_with_order(serial_number="GBX-RB3")
        ctx2 = setup_unit_with_order(serial_number="GBX-RB4",
                                     legal_name="Bay Co Four")
        add_shipment(ctx1["order"]["id"], direction="OUTBOUND", weight_kg=400,
                     rigging_bay_date="2026-08-12", rigging_bay_hours=4)
        # The next day's occupancy begins after the first booking's
        # date + 4h + 2h buffer, so no intersection.
        second = add_shipment(ctx2["order"]["id"], direction="OUTBOUND",
                              weight_kg=300, rigging_bay_date="2026-08-13",
                              rigging_bay_hours=2)
        assert second["status"] == "BOOKED"
        assert second["freight_charge_cents"] == 64_000  # 45000 + 2*9500


class TestShipmentPipeline:
    def test_deliver_before_dispatch_rejected(self, api,
                                              intake_coordinator_headers):
        """PRD §3.5: "From `BOOKED`, the coordinator dispatches the shipment
        (moving it to `IN_TRANSIT`), later marks it delivered (`IN_TRANSIT →
        DELIVERED`), or cancels it while still `BOOKED` (`→ CANCELLED`)."
        PRD §2.6: "Every action in this API exists only from specific states
        of its target resource; invoking an action from any other state is
        rejected with `ERR_INVALID_STATE` (HTTP 409)."

        Design: Corner/state_machines/freight_shipment_linear_pipeline_enforced
        """
        ctx = setup_unit_with_order(serial_number="GBX-SL")
        shipment = add_shipment(ctx["order"]["id"], direction="INBOUND",
                                weight_kg=400, rigging_bay_date="2026-08-20",
                                rigging_bay_hours=2)
        resp = api.deliver_shipment(shipment["id"], intake_coordinator_headers)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)
        assert validate_success(
            api.get_shipment(shipment["id"], intake_coordinator_headers)
        )["status"] == "BOOKED"
