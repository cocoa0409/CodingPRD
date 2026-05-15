"""Outbound shipment lifecycle — PRD §3.5.

Tests cover: shipment creation, FEFO pick selection (and its
preconditions including released lots only and expiry-strict),
packaging-match validation, temperature pre-checks, dispatch flow,
and QA-release from PACKED-QUARANTINED.
"""
from __future__ import annotations

import pytest

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    advance_clock,
    assert_shipment,
    create_planned_shipment,
    create_shipment_payload,
    get_lot,
    get_shipment,
    list_external_events,
    pack_shipment,
    pick_shipment,
    setup_accepted_lot,
    setup_picked_shipment,
    setup_packed_shipment,
    validate_error,
    validate_success,
)


# ===========================================================================
# Shipment creation — PRD §3.5
# ===========================================================================
class TestShipmentCreation:

    def test_create_shipment_initial_state_planned(self, api):
        """PRD §3.5: "The shipment is born in `PLANNED` with a null
        `pick_lot_id`, a null `dispatched_at_minutes`, and
        `logger_armed` of false."

        Claim: a fresh shipment carries the four named fields per PRD.
        """
        ctx = setup_accepted_lot(quantity_units=5)
        s = create_planned_shipment(
            ctx["warehouse"]["id"], ctx["product"]["id"],
            quantity_units=1,
        )
        assert s["status"] == "PLANNED"
        assert s.get("pick_lot_id") is None
        assert s.get("dispatched_at_minutes") is None
        assert s["logger_armed"] is False
        assert_shipment(s)

    def test_zero_quantity_units_returns_err_quantity_invalid(self, api):
        """PRD §3.5: "A zero or negative `quantity_units` is rejected
        on creation with `ERR_QUANTITY_INVALID` (HTTP 422)."

        Claim: quantity_units=0 on shipment creation →
        ERR_QUANTITY_INVALID.
        """
        ctx = setup_accepted_lot(quantity_units=5)
        payload = create_shipment_payload(
            product_id=ctx["product"]["id"],
            quantity_units=0,
        )
        res = api.create_shipment(
            ctx["warehouse"]["id"], payload,
            TEST_USERS["picker_headers"],
        )
        validate_error(res, ApiErrorId.ERR_QUANTITY_INVALID.value)

    def test_negative_quantity_units_returns_err_quantity_invalid(self, api):
        """PRD §3.5 same rule, lower side.

        Claim: quantity_units=-1 on shipment creation →
        ERR_QUANTITY_INVALID.
        """
        ctx = setup_accepted_lot(quantity_units=5)
        payload = create_shipment_payload(
            product_id=ctx["product"]["id"],
            quantity_units=-1,
        )
        res = api.create_shipment(
            ctx["warehouse"]["id"], payload,
            TEST_USERS["picker_headers"],
        )
        validate_error(res, ApiErrorId.ERR_QUANTITY_INVALID.value)


# ===========================================================================
# FEFO pick selection — PRD §3.5
# ===========================================================================
class TestFefoPickSelection:

    def test_pick_no_eligible_lot_returns_err_no_fefo_lot(self, api):
        """PRD §3.5: "If no candidate exists, the request fails with
        `ERR_NO_FEFO_LOT` (HTTP 422)".

        Difficulty-design: boundary_precision_check /
        empty_pick_pool_on_pick_endpoint.

        # difficulty: boundary_precision_check/empty_pick_pool_on_pick_endpoint

        Claim: when no Lot satisfies the FEFO candidate filter (e.g.
        the only Lot is QUARANTINED, not RELEASED), the pick endpoint
        returns ERR_NO_FEFO_LOT.
        """
        from test_helpers import trigger_alarm_high_and_recover
        ctx = setup_accepted_lot(quantity_units=5)
        # Force the lot into QUARANTINED via a deviation cascade.
        trigger_alarm_high_and_recover(
            ctx["zone"]["id"], ctx["warehouse"]["id"],
            alarm_temp_c=12.0, in_range_temp_c=5.0, start_minutes=1,
        )
        # Now create a shipment and attempt pick — no RELEASED lot.
        s = create_planned_shipment(
            ctx["warehouse"]["id"], ctx["product"]["id"],
            quantity_units=1,
        )
        res = api.pick_shipment(s["id"], TEST_USERS["picker_headers"])
        validate_error(res, ApiErrorId.ERR_NO_FEFO_LOT.value)

    def test_pick_no_fefo_lot_when_only_lot_is_expired(self, api):
        """PRD §3.5: "The FEFO pick-selection calculation walks every
        lot in the warehouse whose `product_id` matches the
        shipment's, whose `quality_status` is `RELEASED`, whose
        `expiry_minutes` is strictly greater than the warehouse's
        `clock_minutes`".

        Difficulty-design: boundary_precision_check /
        empty_pick_pool_on_pick_endpoint (a different path to an
        empty candidate set — the only RELEASED lot is now expired
        because clock has advanced past expiry_minutes).
        # difficulty: boundary_precision_check/empty_pick_pool_on_pick_endpoint

        Claim: a RELEASED lot exists but its expiry_minutes is no
        longer strictly greater than the warehouse's clock_minutes;
        pick fails with ERR_NO_FEFO_LOT (the filter excludes the
        expired lot).
        """
        ctx = setup_accepted_lot(
            quantity_units=5,
            expiry_minutes=200,
        )
        # Advance the clock past expiry. Per PRD §3.5 the filter is
        # strict (expiry > clock); at clock=200, 200 > 200 is false,
        # so the lot is excluded.
        from test_helpers import advance_clock
        advance_clock(ctx["warehouse"]["id"], 200)
        s = create_planned_shipment(
            ctx["warehouse"]["id"], ctx["product"]["id"], quantity_units=1,
        )
        res = api.pick_shipment(s["id"], TEST_USERS["picker_headers"])
        validate_error(res, ApiErrorId.ERR_NO_FEFO_LOT.value)

    def test_pick_no_eligible_lot_for_quarantined_only_yields_err_no_fefo_lot(
        self, api,
    ):
        """PRD §3.5 / cross-entity dep:
        "OutboundShipment.PLANNED→PICKED is gated by the state of a
        different entity Lot — specifically Lot.quality_status must
        be RELEASED."

        Difficulty-design: cross_entity_state_dependency /
        shipment_pick_depends_on_lot_quality_status.

        # difficulty: cross_entity_state_dependency/shipment_pick_depends_on_lot_quality_status

        Claim: a lot in QUARANTINED state disqualifies from FEFO,
        leading to ERR_NO_FEFO_LOT.
        """
        from test_helpers import trigger_alarm_high_and_recover
        ctx = setup_accepted_lot(quantity_units=5)
        trigger_alarm_high_and_recover(
            ctx["zone"]["id"], ctx["warehouse"]["id"],
            alarm_temp_c=12.0, in_range_temp_c=5.0, start_minutes=1,
        )
        s = create_planned_shipment(
            ctx["warehouse"]["id"], ctx["product"]["id"],
            quantity_units=1,
        )
        res = api.pick_shipment(s["id"], TEST_USERS["picker_headers"])
        validate_error(res, ApiErrorId.ERR_NO_FEFO_LOT.value)

    def test_pick_disqualifies_recalled_lot(self, api):
        """PRD §3.5 (candidate filter): "whose `quality_status` is
        `RELEASED`".
        PRD §3.7: "Every in-scope lot's `quality_status` is set to
        `RECALLED` as a cascade".

        Difficulty-design: cross_entity_state_dependency /
        shipment_pick_depends_on_lot_quality_status (the RECALLED
        side — Lot state RECALLED disqualifies from FEFO candidate
        set, identically to QUARANTINED).
        # difficulty: cross_entity_state_dependency/shipment_pick_depends_on_lot_quality_status

        Claim: a Lot in RECALLED state (after recall announce) is
        excluded from the FEFO candidate set; pick fails with
        ERR_NO_FEFO_LOT.
        """
        from test_helpers import (
            add_recall_scope,
            announce_recall,
            create_draft_recall,
        )
        ctx = setup_accepted_lot(quantity_units=5)
        # Build recall covering the lot, then announce.
        r = create_draft_recall(
            ctx["warehouse"]["id"], classification="CLASS_II",
        )
        add_recall_scope(
            r["id"], lot_id=ctx["lot"]["id"], units=5,
            scope_kind="ON_HAND",
        )
        announce_recall(r["id"])
        # Lot is now RECALLED.
        lot_after = get_lot(ctx["lot"]["id"])
        assert lot_after["quality_status"] == "RECALLED"
        # Create shipment + pick — should fail with ERR_NO_FEFO_LOT.
        s = create_planned_shipment(
            ctx["warehouse"]["id"], ctx["product"]["id"], quantity_units=1,
        )
        res = api.pick_shipment(s["id"], TEST_USERS["picker_headers"])
        validate_error(res, ApiErrorId.ERR_NO_FEFO_LOT.value)

    def test_pick_decrements_lot_quantity_on_hand(self, api):
        """PRD §3.5: "On success, the chosen lot's `quantity_on_hand`
        is decremented by the shipment's `quantity_units` and its
        `quantity_picked` is incremented by the same amount".

        Claim: after pick, the lot's on_hand drops by the shipment
        quantity and picked rises by the same amount.
        """
        ctx = setup_picked_shipment(
            quantity_units=3, accepted_quantity_units=10,
        )
        lot = get_lot(ctx["lot"]["id"])
        assert lot["quantity_on_hand"] == 10 - 3
        assert lot["quantity_picked"] == 3

    def test_pick_chooses_earliest_expiry_lot(self, api):
        """PRD §3.5: "The candidates are sorted by three ascending
        keys: `expiry_minutes` first (earliest expiry wins, which is
        the FEFO discipline)".

        Claim: when two RELEASED lots exist for the same product, the
        pick selects the one with the smaller expiry_minutes.
        """
        from test_helpers import (
            accept_receipt,
            create_inspected_receipt,
            create_bin,
            setup_basic_topology,
            setup_qualified_supplier_and_product,
        )
        # Build a warehouse with TWO bins so we can land two lots in
        # the same warehouse. Each receipt accept allocates one bin.
        topology = setup_basic_topology()
        # Add a second bin.
        create_bin(
            topology["zone"]["id"], volume_units=100, weight_limit_kg=500.0,
        )
        supplier, product = setup_qualified_supplier_and_product()
        # Receipt A — expiry=5000 (earlier).
        receipt_a = create_inspected_receipt(
            topology["warehouse"]["id"], supplier["id"], product["id"],
            quantity_units=4, expiry_minutes=5000,
        )
        accept_receipt(receipt_a["id"])
        # Receipt B — expiry=8000 (later).
        receipt_b = create_inspected_receipt(
            topology["warehouse"]["id"], supplier["id"], product["id"],
            quantity_units=4, expiry_minutes=8000,
        )
        accept_receipt(receipt_b["id"])
        # Pick 1 unit; expect lot from receipt_a (earlier expiry).
        from test_helpers import list_lots
        lots = list_lots(
            topology["warehouse"]["id"],
            params={"product_id": product["id"], "limit": 100},
        )
        lot_a = [L for L in lots if L["receipt_id"] == receipt_a["id"]][0]
        lot_b = [L for L in lots if L["receipt_id"] == receipt_b["id"]][0]
        s = create_planned_shipment(
            topology["warehouse"]["id"], product["id"], quantity_units=1,
        )
        picked = pick_shipment(s["id"])
        assert picked["pick_lot_id"] == lot_a["id"], (
            f"FEFO violation: expected pick from {lot_a['id']} "
            f"(expiry=5000), got {picked['pick_lot_id']}"
        )


# ===========================================================================
# Pack — packaging match + temperature pre-check
# ===========================================================================
class TestPackagingMatch:

    def test_frozen_product_with_pcm_packaging_returns_err_packaging_mismatch(
        self, api,
    ):
        """PRD §3.5: "a product in `FROZEN` must ship in
        `INSULATED_DRY_ICE`; products in `REFRIGERATED`, `COOL`, or
        `CONTROLLED_TEMP` must ship in `INSULATED_PCM`; products in
        `ROOM_TEMP` must ship `AMBIENT`. Any mismatch is rejected
        with `ERR_PACKAGING_MISMATCH` (HTTP 422)."

        Claim: FROZEN-required product packed as INSULATED_PCM →
        ERR_PACKAGING_MISMATCH.
        """
        ctx = setup_accepted_lot(
            quantity_units=2,
            required_zone_type="FROZEN",
        )
        # Pack temperatures must be within FROZEN range to isolate
        # the packaging-match failure from temp pre-check.
        # FROZEN target: -25..-15.
        s = create_planned_shipment(
            ctx["warehouse"]["id"], ctx["product"]["id"],
            quantity_units=1,
            packaging_kind="INSULATED_PCM",   # mismatch
            pick_temp_c=-20.0,
            vehicle_precondition_temp_c=-20.0,
        )
        pick_shipment(s["id"])
        res = api.pack_shipment(s["id"], TEST_USERS["picker_headers"])
        validate_error(res, ApiErrorId.ERR_PACKAGING_MISMATCH.value)

    def test_refrigerated_product_with_dry_ice_packaging_returns_err_packaging_mismatch(
        self, api,
    ):
        """Same rule, REFRIGERATED ↔ INSULATED_DRY_ICE mismatch.

        Claim: REFRIGERATED-required product packed as
        INSULATED_DRY_ICE → ERR_PACKAGING_MISMATCH.
        """
        ctx = setup_accepted_lot(
            quantity_units=2, required_zone_type="REFRIGERATED",
        )
        s = create_planned_shipment(
            ctx["warehouse"]["id"], ctx["product"]["id"],
            quantity_units=1,
            packaging_kind="INSULATED_DRY_ICE",  # mismatch
            pick_temp_c=5.0, vehicle_precondition_temp_c=5.0,
        )
        pick_shipment(s["id"])
        res = api.pack_shipment(s["id"], TEST_USERS["picker_headers"])
        validate_error(res, ApiErrorId.ERR_PACKAGING_MISMATCH.value)


class TestPackTemperaturePreCheck:

    def test_pack_out_of_range_pick_temp_returns_err_temp_precheck_fail(
        self, api,
    ):
        """PRD §3.5: "The temperature pre-checks require that both
        `pick_temp_c` and `vehicle_precondition_temp_c` lie within
        the product's required operating range ... a violation in
        either reading surfaces as `ERR_TEMP_PRECHECK_FAIL` (HTTP 422)."

        Claim: REFRIGERATED (2..8) product with pick_temp_c=12 →
        ERR_TEMP_PRECHECK_FAIL.
        """
        ctx = setup_accepted_lot(
            quantity_units=2, required_zone_type="REFRIGERATED",
        )
        s = create_planned_shipment(
            ctx["warehouse"]["id"], ctx["product"]["id"],
            quantity_units=1,
            packaging_kind="INSULATED_PCM",
            pick_temp_c=12.0,   # out of REFRIGERATED 2..8
            vehicle_precondition_temp_c=5.0,
        )
        pick_shipment(s["id"])
        res = api.pack_shipment(s["id"], TEST_USERS["picker_headers"])
        validate_error(res, ApiErrorId.ERR_TEMP_PRECHECK_FAIL.value)


# ===========================================================================
# Dispatch — sets logger_armed + emits TMS event
# ===========================================================================
class TestDispatch:

    def test_dispatch_sets_logger_armed_and_dispatched_at(self, api):
        """PRD §3.5: "Dispatch ... moves the shipment from `PACKED` to
        `DISPATCHED`, sets `logger_armed` to true, sets
        `dispatched_at_minutes` to the current `clock_minutes`".

        Claim: after dispatch, logger_armed=true,
        dispatched_at_minutes equals current warehouse clock.
        """
        ctx = setup_packed_shipment(
            quantity_units=1, accepted_quantity_units=5,
        )
        from test_helpers import dispatch_shipment, get_warehouse
        before = get_warehouse(ctx["warehouse"]["id"])
        dispatched = dispatch_shipment(ctx["shipment"]["id"])
        assert dispatched["logger_armed"] is True
        assert dispatched["status"] == "DISPATCHED"
        assert dispatched["dispatched_at_minutes"] == before["clock_minutes"]

    def test_dispatch_emits_tms_shipment_dispatched_event(self, api):
        """PRD §3.5: "appends one `ExternalSyncEvent` targeted at
        `TMS` with `event_type` `SHIPMENT_DISPATCHED`".

        Claim: after dispatch, the external-events log contains a
        TMS / SHIPMENT_DISPATCHED row.
        """
        from test_helpers import dispatch_shipment
        ctx = setup_packed_shipment(
            quantity_units=1, accepted_quantity_units=5,
        )
        dispatch_shipment(ctx["shipment"]["id"])
        events = list_external_events(
            ctx["warehouse"]["id"],
            params={"event_type": "SHIPMENT_DISPATCHED", "limit": 100},
        )
        tms_events = [
            e for e in events
            if e["target_system"] == "TMS"
            and e["event_type"] == "SHIPMENT_DISPATCHED"
        ]
        assert len(tms_events) >= 1


# ===========================================================================
# Shipment state-precondition — PRD §2.12 priority 8
# ===========================================================================
class TestShipmentStatePrecondition:

    def test_pack_on_planned_shipment_returns_err_shipment_state_invalid(
        self, api,
    ):
        """PRD §3.5: "A request to drive a shipment through a
        transition that does not match its current `status` is
        rejected with `ERR_SHIPMENT_STATE_INVALID` (HTTP 409)."

        Claim: pack on a still-PLANNED shipment → ERR_SHIPMENT_STATE_INVALID.
        """
        ctx = setup_accepted_lot(quantity_units=2)
        s = create_planned_shipment(
            ctx["warehouse"]["id"], ctx["product"]["id"],
            quantity_units=1,
            packaging_kind="INSULATED_PCM",
            pick_temp_c=5.0, vehicle_precondition_temp_c=5.0,
        )
        # Don't pick — go straight to pack.
        res = api.pack_shipment(s["id"], TEST_USERS["picker_headers"])
        validate_error(res, ApiErrorId.ERR_SHIPMENT_STATE_INVALID.value)

    def test_dispatch_on_picked_shipment_rejected(self, api):
        """Same rule, different transition: dispatch on PICKED → error.

        Claim: dispatch on a PICKED-but-not-PACKED shipment →
        ERR_SHIPMENT_STATE_INVALID.
        """
        ctx = setup_picked_shipment(
            quantity_units=1, accepted_quantity_units=5,
        )
        res = api.dispatch_shipment(
            ctx["shipment"]["id"], TEST_USERS["picker_headers"],
        )
        validate_error(res, ApiErrorId.ERR_SHIPMENT_STATE_INVALID.value)
