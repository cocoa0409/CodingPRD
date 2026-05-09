"""Putaway selection: zone match, capacity boundaries, distance vs capacity strategies."""
import pytest
from test_helpers import (
    api_client, validate_success, validate_error,
    create_inbound_shipment_payload, create_complete_inspection_payload,
    create_warehouse, create_bin, create_lot,
    setup_two_bins_distinct_distance_capacity,
    TEST_USERS, get_inventory_row,
)


class TestPutawaySelectionStrategy:
    def test_distance_optimized_picks_closer_bin(self, api, staff_headers, manager_headers):
        """PRD §3.3: "Under the DISTANCE_OPTIMIZED strategy the candidate set
        is sorted by distance_from_dock in ascending order — the bin closest
        to the dock wins; ties on distance_from_dock are broken by bin_code
        in lexicographic ascending order. Two candidate bins of identical
        zone and capacity will resolve to the one with smaller distance_from_dock
        even if the other is emptier."

        # difficulty: dual_variant_calc/bin_putaway_distance_vs_capacity
        Claim: putaway under DISTANCE_OPTIMIZED selects the closer bin
        even when the other has more remaining capacity.
        """
        wh, bin_c, bin_d, lot = setup_two_bins_distinct_distance_capacity(
            putaway_strategy="DISTANCE_OPTIMIZED")
        sh = validate_success(api.create_inbound_shipment(
            wh["id"], create_inbound_shipment_payload(lot["id"], 1),
            staff_headers), 201)
        validate_success(api.start_inspection(wh["id"], sh["id"], staff_headers), 200)
        validate_success(api.complete_inspection(
            wh["id"], sh["id"],
            create_complete_inspection_payload(lot["id"], 1, 0),
            staff_headers), 200)
        validate_success(api.putaway_inbound_shipment(
            wh["id"], sh["id"], staff_headers), 200)
        # Check the line.bin_id matches BIN_C (closer)
        retrieved = validate_success(api.get_inbound_shipment(
            wh["id"], sh["id"], staff_headers), 200)
        line = retrieved["lines"][0]
        assert line["bin_id"] == bin_c["id"], \
            f"DISTANCE_OPTIMIZED should pick closer bin BIN_C, got {line['bin_id']}"

    def test_capacity_optimized_picks_emptier_bin(self, api, staff_headers, manager_headers):
        """PRD §3.3: "Under the CAPACITY_OPTIMIZED strategy the candidate set
        is sorted by remaining_volume_cm3 in descending order — the emptiest
        bin wins; ties on remaining_volume_cm3 are broken by bin_code in
        lexicographic ascending order. Two candidate bins of identical zone
        and reachable capacity will resolve to the one with greater
        remaining_volume_cm3 even if the other is closer to the dock."

        # difficulty: dual_variant_calc/bin_putaway_distance_vs_capacity
        Claim: putaway under CAPACITY_OPTIMIZED selects the emptier bin
        (BIN_D, 10000 cm3 capacity) even though BIN_C (2000 cm3) is closer.
        """
        wh, bin_c, bin_d, lot = setup_two_bins_distinct_distance_capacity(
            putaway_strategy="CAPACITY_OPTIMIZED")
        sh = validate_success(api.create_inbound_shipment(
            wh["id"], create_inbound_shipment_payload(lot["id"], 1),
            staff_headers), 201)
        validate_success(api.start_inspection(wh["id"], sh["id"], staff_headers), 200)
        validate_success(api.complete_inspection(
            wh["id"], sh["id"],
            create_complete_inspection_payload(lot["id"], 1, 0),
            staff_headers), 200)
        validate_success(api.putaway_inbound_shipment(
            wh["id"], sh["id"], staff_headers), 200)
        retrieved = validate_success(api.get_inbound_shipment(
            wh["id"], sh["id"], staff_headers), 200)
        line = retrieved["lines"][0]
        assert line["bin_id"] == bin_d["id"], \
            f"CAPACITY_OPTIMIZED should pick larger bin BIN_D, got {line['bin_id']}"


class TestPutawayCapacityBoundary:
    def test_putaway_at_exact_volume_capacity_succeeds(self, api, staff_headers, manager_headers):
        """PRD §3.3: "the bin's remaining_volume_cm3 is at least received_units
        multiplied by the lot's unit_volume_cm3 AND its remaining_weight_g
        is at least received_units multiplied by the lot's unit_weight_g."

        # difficulty: boundary_precision_check/bin_volume_capacity_inclusive_boundary
        Claim: when received_units * unit_volume == bin remaining_volume_cm3
        exactly, the putaway succeeds (≥ inclusive boundary).
        """
        wh = create_warehouse()
        # Bin: 1000 cm3 volume, ample weight; Lot: 200 cm3/unit; 5 units = exactly 1000
        b = create_bin(wh["id"], bin_code="BIN_BOUND", zone="AMBIENT",
                      capacity_volume_cm3=1000, capacity_weight_g=100000)
        lot = create_lot(wh["id"], sku="PEN", category="AMBIENT",
                        unit_volume_cm3=200, unit_weight_g=10, unit_value_cents=100)
        sh = validate_success(api.create_inbound_shipment(
            wh["id"], create_inbound_shipment_payload(lot["id"], 5),
            staff_headers), 201)
        validate_success(api.start_inspection(wh["id"], sh["id"], staff_headers), 200)
        validate_success(api.complete_inspection(
            wh["id"], sh["id"],
            create_complete_inspection_payload(lot["id"], 5, 0),
            staff_headers), 200)
        result = validate_success(api.putaway_inbound_shipment(
            wh["id"], sh["id"], staff_headers), 200)
        assert result["status"] == "PUTAWAY"
        bin_after = validate_success(api.get_bin(wh["id"], b["id"], staff_headers), 200)
        assert bin_after["used_volume_cm3"] == 1000

    def test_putaway_one_above_volume_capacity_fails(self, api, staff_headers, manager_headers):
        """PRD §3.3: "If no bin satisfies all three filters, the operation
        fails with ERR_NO_BIN_AVAILABLE."

        # difficulty: boundary_precision_check/bin_volume_capacity_inclusive_boundary
        Claim: when received_units * unit_volume > bin capacity by 1 unit's
        worth, putaway fails ERR_NO_BIN_AVAILABLE.
        """
        wh = create_warehouse()
        b = create_bin(wh["id"], bin_code="BIN_TIGHT", zone="AMBIENT",
                      capacity_volume_cm3=1000, capacity_weight_g=100000)
        lot = create_lot(wh["id"], sku="PEN", category="AMBIENT",
                        unit_volume_cm3=200, unit_weight_g=10, unit_value_cents=100)
        sh = validate_success(api.create_inbound_shipment(
            wh["id"], create_inbound_shipment_payload(lot["id"], 6),
            staff_headers), 201)
        validate_success(api.start_inspection(wh["id"], sh["id"], staff_headers), 200)
        validate_success(api.complete_inspection(
            wh["id"], sh["id"],
            create_complete_inspection_payload(lot["id"], 6, 0),
            staff_headers), 200)
        validate_error(api.putaway_inbound_shipment(
            wh["id"], sh["id"], staff_headers), "ERR_NO_BIN_AVAILABLE")


class TestPutawayZoneMatch:
    def test_putaway_no_zone_matching_bin_zone_mismatch(self, api, staff_headers, manager_headers):
        """PRD §3.3: "If a candidate bin satisfies the volume and weight test
        but its `zone` does not match `category` (or, for quarantine, is not
        `RETURNS`), the response is `ERR_ZONE_MISMATCH`."

        Claim: when the only bin (AMBIENT) has plenty of capacity but its zone
        does not match the COLD lot's category, putaway fails ERR_ZONE_MISMATCH
        (priority 8 in §2.6 — Zone match wins over Bin capacity at priority 12).
        """
        wh = create_warehouse()
        # Only AMBIENT bin, with ample capacity
        create_bin(wh["id"], bin_code="ONLY_AMB", zone="AMBIENT",
                  capacity_volume_cm3=100000, capacity_weight_g=100000)
        # Lot is COLD — no zone match, but bin capacity easily fits 5 units × 100 cm³
        lot = create_lot(wh["id"], sku="ICE", category="COLD",
                        unit_volume_cm3=100, unit_weight_g=10, unit_value_cents=100)
        sh = validate_success(api.create_inbound_shipment(
            wh["id"], create_inbound_shipment_payload(lot["id"], 5),
            staff_headers), 201)
        validate_success(api.start_inspection(wh["id"], sh["id"], staff_headers), 200)
        validate_success(api.complete_inspection(
            wh["id"], sh["id"],
            create_complete_inspection_payload(lot["id"], 5, 0),
            staff_headers), 200)
        validate_error(api.putaway_inbound_shipment(
            wh["id"], sh["id"], staff_headers), "ERR_ZONE_MISMATCH")


class TestPutawayInventoryAndReceivedAt:
    def test_putaway_creates_inventory_and_sets_received_at(self, api, staff_headers, manager_headers):
        """PRD §3.2: "A PASSED shipment is putaway by floor staff, which moves
        the shipment from PASSED to PUTAWAY, sets each line's bin_id and
        transitions the line's status from INSPECTED_PASS to PUTAWAY,
        upserts inventory for the chosen (bin_id, lot_id) pair by adding
        received_units, recomputes the affected bins' used and remaining
        capacity, and writes received_at on each lot for which this is
        the first putaway"

        Claim: after putaway, an Inventory row exists with qty_units = received_units,
        the bin's used capacity reflects the goods, and Lot.received_at is set.
        """
        wh = create_warehouse(advance_clock_to="2025-03-15T00:00:00.000Z")
        b = create_bin(wh["id"], bin_code="BIN_X", zone="AMBIENT",
                      capacity_volume_cm3=10000, capacity_weight_g=10000)
        lot = create_lot(wh["id"], sku="PEN", category="AMBIENT",
                        unit_volume_cm3=20, unit_weight_g=5, unit_value_cents=100)
        sh = validate_success(api.create_inbound_shipment(
            wh["id"], create_inbound_shipment_payload(lot["id"], 50),
            staff_headers), 201)
        validate_success(api.start_inspection(wh["id"], sh["id"], staff_headers), 200)
        validate_success(api.complete_inspection(
            wh["id"], sh["id"],
            create_complete_inspection_payload(lot["id"], 50, 0),
            staff_headers), 200)
        result = validate_success(api.putaway_inbound_shipment(
            wh["id"], sh["id"], staff_headers), 200)
        assert result["status"] == "PUTAWAY"
        # Inventory row exists
        inv = get_inventory_row(wh["id"], b["id"], lot["id"])
        assert inv is not None
        assert inv["qty_units"] == 50
        # Bin used recomputed
        bin_after = validate_success(api.get_bin(wh["id"], b["id"], staff_headers), 200)
        assert bin_after["used_volume_cm3"] == 50 * 20
        assert bin_after["used_weight_g"] == 50 * 5
        # Lot.received_at set
        lot_after = validate_success(api.get_lot(wh["id"], lot["id"], staff_headers), 200)
        assert lot_after["received_at"] is not None

    def test_received_at_only_set_on_first_putaway(self, api, staff_headers, manager_headers):
        """PRD §3.1: "The received_at timestamp on the lot is left empty at
        creation and is filled by the system the very first time the lot is
        putaway from an inbound shipment — once written, received_at is
        never overwritten by later putaways."
        PRD §3.2: "writes received_at on each lot for which this is the first
        putaway (subsequent putaways of the same lot do not overwrite an
        existing received_at)."

        Claim: a second putaway of the same lot does not overwrite received_at.
        """
        wh = create_warehouse(advance_clock_to="2025-01-01T00:00:00.000Z")
        b = create_bin(wh["id"], bin_code="BIN_RA", zone="AMBIENT",
                      capacity_volume_cm3=100000, capacity_weight_g=100000)
        lot = create_lot(wh["id"], sku="PEN", category="AMBIENT",
                        unit_volume_cm3=20, unit_weight_g=5, unit_value_cents=100)
        # First putaway via the helper
        from test_helpers import putaway_lot_units, create_clock_advance_payload
        putaway_lot_units(wh["id"], lot["id"], 30)
        first = validate_success(api.get_lot(wh["id"], lot["id"], staff_headers), 200)
        first_received_at = first["received_at"]
        assert first_received_at is not None
        # Advance clock so a "second received_at" would differ if overwritten
        validate_success(api.advance_clock(
            create_clock_advance_payload(wh["id"], "2025-06-15T00:00:00.000Z"),
            TEST_USERS["manager_headers"]), 200)
        # Second putaway
        putaway_lot_units(wh["id"], lot["id"], 20, asn_number="ASN_SECOND")
        second = validate_success(api.get_lot(wh["id"], lot["id"], staff_headers), 200)
        assert second["received_at"] == first_received_at, \
            "received_at must not be overwritten by subsequent putaways"


class TestPutawayBinFrozen:
    def test_putaway_rejected_when_only_bin_is_frozen(self, api, staff_headers, manager_headers):
        """PRD §2.6 rule 10: "A bin whose status is FROZEN (held by an open
        cycle count) cannot host putaway nor be the source of a pick task
        start, yielding ERR_BIN_FROZEN."

        Claim: putaway against a warehouse whose only candidate bin is FROZEN
        → ERR_BIN_FROZEN. Note: PRD §3.3 says no candidate bin satisfying
        ALL three filters (status ACTIVE, zone match, capacity) yields
        ERR_NO_BIN_AVAILABLE; both interpretations are PRD-faithful, so we
        accept either.
        """
        wh = create_warehouse()
        b = create_bin(wh["id"], bin_code="FROZ", zone="AMBIENT",
                      capacity_volume_cm3=100000, capacity_weight_g=100000)
        lot = create_lot(wh["id"], sku="PEN", category="AMBIENT",
                        unit_volume_cm3=20, unit_weight_g=5, unit_value_cents=100)
        # Put an initial 10 units in so that a cycle count can be scheduled meaningfully
        from test_helpers import putaway_lot_units, create_cycle_count_payload
        putaway_lot_units(wh["id"], lot["id"], 10)
        # Schedule a cycle count to freeze the bin
        validate_success(api.create_cycle_count(
            wh["id"], create_cycle_count_payload(b["id"], lot["id"]),
            staff_headers), 201)
        # Now another shipment for the same lot
        sh2 = validate_success(api.create_inbound_shipment(
            wh["id"],
            create_inbound_shipment_payload(lot["id"], 5, asn_number="ASN_2"),
            staff_headers), 201)
        validate_success(api.start_inspection(wh["id"], sh2["id"], staff_headers), 200)
        validate_success(api.complete_inspection(
            wh["id"], sh2["id"],
            create_complete_inspection_payload(lot["id"], 5, 0),
            staff_headers), 200)
        from test_helpers import validate_error_is_one_of
        validate_error_is_one_of(
            api.putaway_inbound_shipment(wh["id"], sh2["id"], staff_headers),
            ["ERR_BIN_FROZEN", "ERR_NO_BIN_AVAILABLE"])
