"""Endpoint behaviour: a partial update, a void that moves no stock, a repair order
carrying a recovery reference, and the kit ledger read back between two writes.
"""

from __future__ import annotations

from typing import Any, Dict

from test_helpers import (
    BASIS_SURVEY_BASED,
    CARRIER_ACTIVE,
    CLAIM_FILED,
    DAMAGE_REPAIR_AUTHORIZED,
    DAMAGE_ZONE_BODY_PANEL,
    DAMAGE_ZONE_INTERIOR,
    MANAGER,
    MODEL_LINE_LX500,
    MODEL_LINE_TX300,
    PLANNER,
    PROC_ACCESSORY_IN_PROGRESS,
    PROC_SURVEYED,
    TECHNICIAN,
    TIER_AUTO,
    WO_INSTALLED,
    WO_KITTED,
    WO_VOIDED,
    Vpc,
    assert_kit_ledger,
    assert_pagination_meta,
    assert_slot_ledger,
    assert_subset,
    assert_vehicle_dimensions,
    assert_versioned_record,
    factories as f,
    ids_of,
    ok,
    open_port,
    validate_paginated,
)

CLEAN_LINE = f.damage_line(DAMAGE_ZONE_INTERIOR, 10, 0)


class TestCarrierPartialUpdate:
    def test_each_patch_touches_one_field_and_leaves_the_rest_standing(self, flow: Vpc):
        """Two successive partial updates, three versions, nothing else disturbed.

        PRD: "A carrier's `status`, `linehaul_rate_cents_per_mile` and
        `concurrent_load_capacity` may each be updated later; suspending a carrier
        removes it from future selection without disturbing any release order it
        already holds, and already-committed slots are retained."

        PRD: "Almost all resources additionally carry an `updated_at` timestamp in
        the same format, refreshed on every mutation, and a `version` integer that
        starts at 1 on creation and increments by one on every mutation of the
        record — including mutations the server performs on its own initiative, such
        as recomputing a center's occupancy counters or reverting a unit to a prior
        processing state as part of a cascade."

        Design: Corner/endpoints/corner_truck_carrier_patch_updates_only_the_supplied_fields
        """
        flow.set_clock("2026-08-01T00:00:00Z")
        carrier = flow.create_carrier(
            carrier_code="TC-ROAD",
            name="Roadway Auto Transport",
            served_route_zones=["A", "B"],
            linehaul_rate_cents_per_mile=412,
            slot_capacity=4,
            concurrent_load_capacity=2,
        )
        assert_versioned_record(carrier, expected_version=1)

        cheaper = ok(
            flow.api.patch_carrier(
                carrier["id"], {"linehaul_rate_cents_per_mile": 380}, MANAGER
            )
        )
        assert_subset(
            cheaper,
            {
                "linehaul_rate_cents_per_mile": 380,
                "status": CARRIER_ACTIVE,
                "slot_capacity": 4,
                "concurrent_load_capacity": 2,
                "version": 2,
            },
        )
        assert_slot_ledger(cheaper, committed_slots=0, available_slots=4)

        wider = ok(
            flow.api.patch_carrier(
                carrier["id"], {"concurrent_load_capacity": 3}, MANAGER
            )
        )
        assert_subset(
            wider,
            {
                "concurrent_load_capacity": 3,
                "linehaul_rate_cents_per_mile": 380,
                "version": 3,
            },
        )

        read_back = ok(flow.api.get_carrier(carrier["id"], PLANNER))
        assert_subset(
            read_back,
            {
                "linehaul_rate_cents_per_mile": 380,
                "concurrent_load_capacity": 3,
                "served_route_zones": ["A", "B"],
                "status": CARRIER_ACTIVE,
            },
        )


def _planned_work_order_on_a_five_unit_kit(flow: Vpc) -> Dict[str, Any]:
    """A surveyed unit and a qty-2 work order that has not reserved anything yet."""
    port = open_port(flow)
    unit = port.discharge(
        "000501", model_line=MODEL_LINE_LX500, pio_program_code="PIO-ALLOY"
    )
    port.surveyed(unit["id"], [CLEAN_LINE])
    kit = port.create_kit(
        kit_code="K-ALLOY",
        program_code="PIO-ALLOY",
        received_qty_total=5,
        unit_cost_cents=24_000,
        install_minutes_per_unit=45,
    )
    work_order = port.plan_work_order(unit["id"], kit["id"], 2)
    return {
        "port": port,
        "vehicle_id": unit["id"],
        "kit_id": kit["id"],
        "order_id": work_order["id"],
    }


class TestVoidFromPlanned:
    def test_voiding_before_kitting_moves_no_quantity_at_all(self, flow: Vpc):
        """There was never a reservation to release.

        PRD: "From `PLANNED` the work order simply becomes `VOIDED`; no quantity
        moves, because none was ever reserved."

        PRD: "A voided work order is terminal and contributes to no kit quantity
        thereafter."

        Design: Corner/endpoints/corner_void_on_a_planned_work_order_reaches_the_terminal_state_untouched_inventory
        """
        scenario = _planned_work_order_on_a_five_unit_kit(flow)
        port = scenario["port"]

        voided = port.void_work_order(scenario["order_id"])

        assert_subset(voided, {"status": WO_VOIDED, "billed_cents": 0})
        assert_kit_ledger(
            port.get_kit(scenario["kit_id"]),
            on_hand_qty=5,
            reserved_qty=0,
            available_qty=5,
            consumed_qty=0,
            received_qty_total=5,
        )

        unit = port.get_vehicle(scenario["vehicle_id"])
        assert_vehicle_dimensions(unit, processing_status=PROC_SURVEYED)
        assert unit["accessory_billed_cents"] == 0

        rows, meta = validate_paginated(
            port.api.list_work_orders(
                TECHNICIAN,
                params={"vehicle_id": scenario["vehicle_id"], "status": WO_VOIDED},
            )
        )
        assert_pagination_meta(meta, total_count=1)
        assert ids_of(rows) == [scenario["order_id"]]


class TestRepairOrderRecoveryReference:
    def test_the_link_is_stored_and_queryable_without_latching_the_basis(self, flow: Vpc):
        """Naming the claim is not the same as completing the repair against it.

        PRD: "A `DamageSurveyor` creates a repair estimate against a unit with a
        `description` of the scope, an `estimate_cents` figure of 0 or more, and
        optionally a `carrier_claim_id` naming the claim this repair is to be
        recovered against — omitted for own-account repairs."

        PRD: "The basis latches to `REPAIR_ACTUAL` the moment a repair order
        carrying this claim's identifier reaches completion while the claim is still
        non-terminal, and once latched it never reverts."

        Design: Corner/endpoints/corner_repair_order_links_to_an_existing_carrier_claim
        """
        port = open_port(flow)
        unit = port.discharge("000502", model_line=MODEL_LINE_TX300)
        survey = port.surveyed(
            unit["id"], [f.damage_line(DAMAGE_ZONE_BODY_PANEL, 25, 60_000)]
        )
        claim = port.file_claim(survey["id"], survey["version"])
        assert_subset(
            claim,
            {
                "recoverable_amount_cents": 35_000,
                "recoverable_basis": BASIS_SURVEY_BASED,
            },
        )

        order = port.repair_order(unit["id"], 60_000, carrier_claim_id=claim["id"])

        assert_subset(
            order,
            {"carrier_claim_id": claim["id"], "authorization_tier": TIER_AUTO},
        )
        rows, meta = validate_paginated(
            port.api.list_repair_orders(MANAGER, params={"carrier_claim_id": claim["id"]})
        )
        assert_pagination_meta(meta, total_count=1)
        assert ids_of(rows) == [order["id"]]

        assert_subset(
            port.get_claim(claim["id"]),
            {"status": CLAIM_FILED, "recoverable_basis": BASIS_SURVEY_BASED},
        )
        assert_vehicle_dimensions(
            port.get_vehicle(unit["id"]), damage_status=DAMAGE_REPAIR_AUTHORIZED
        )


class TestKitLedgerReads:
    def test_the_read_shows_the_reservation_then_the_consumption(self, flow: Vpc):
        """Same kit, two reads, and the billing stamped between them.

        PRD: "The four derived quantities on the record — `on_hand_qty`,
        `reserved_qty`, `consumed_qty` and `available_qty` — are maintained exactly
        as §2.9 specifies, and the read for a kit record always shows the live
        ledger."

        PRD: "Add the two rounded per-unit components together and multiply the sum
        by the work order's `qty`; that product is `billed_cents`, and it is not
        rounded again."

        PRD: "Whenever `billed_cents` changes, the unit's `accessory_billed_cents` is
        recomputed as the sum of `billed_cents` across that unit's work orders
        currently in `INSTALLED`."

        Design: Corner/endpoints/corner_kit_counters_are_derived_reads_after_reservation_and_consumption
        """
        scenario = _planned_work_order_on_a_five_unit_kit(flow)
        port = scenario["port"]

        kitted = port.kit_work_order(scenario["order_id"])
        assert kitted["status"] == WO_KITTED
        assert_kit_ledger(
            port.get_kit(scenario["kit_id"]),
            on_hand_qty=5,
            reserved_qty=2,
            available_qty=3,
            consumed_qty=0,
            received_qty_total=5,
        )

        installed = port.install_work_order(scenario["order_id"])

        assert_subset(
            installed,
            {
                "status": WO_INSTALLED,
                "billed_cents": 67_500,
                "installed_by_user_id": TECHNICIAN.user_id,
            },
        )
        assert_kit_ledger(
            port.get_kit(scenario["kit_id"]),
            on_hand_qty=3,
            reserved_qty=0,
            available_qty=3,
            consumed_qty=2,
            received_qty_total=5,
        )

        unit = port.get_vehicle(scenario["vehicle_id"])
        assert unit["accessory_billed_cents"] == 67_500
        assert_vehicle_dimensions(unit, processing_status=PROC_ACCESSORY_IN_PROGRESS)
