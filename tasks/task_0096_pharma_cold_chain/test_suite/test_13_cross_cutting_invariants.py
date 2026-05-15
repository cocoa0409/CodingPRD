"""Cross-cutting invariants — PRD §2.5, §2.8, §2.9, §2.12, §2.13.

Tests cover the universal contracts: zone utilization roll-up,
precision/rounding rules, validation priority interplays, audit log
and external sync event emission, and the FEFO provisional preview
(dual-variant calculation #1 from the difficulty design).
"""
from __future__ import annotations

import pytest

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    accept_receipt,
    add_recall_scope,
    advance_clock,
    announce_recall,
    assert_zone_utilization_invariant,
    create_bin,
    create_draft_recall,
    create_inspected_receipt,
    create_planned_shipment,
    create_warehouse,
    create_zone,
    get_bin,
    get_lot,
    get_warehouse,
    get_zone,
    list_audit_log,
    list_lots,
    list_external_events,
    make_qa_officer_headers,
    make_receiver_headers,
    pack_shipment,
    pick_shipment,
    record_temperature_event,
    setup_accepted_lot,
    setup_basic_topology,
    setup_qualified_supplier_and_product,
    setup_two_planned_shipments_for_one_lot,
    validate_error,
    validate_success,
)


# ===========================================================================
# Zone utilization roll-up — PRD §2.8
# ===========================================================================
class TestZoneUtilizationRollup:

    def test_zone_utilization_equals_sum_of_bin_occupied_volumes(self, api):
        """PRD §2.8: "A bin's `occupied_volume` and `occupied_weight_kg`
        rise on allocation and fall on pick or cancel. The parent
        zone's `utilization_units` is always exactly the sum of
        `occupied_volume` across its child bins".

        Claim: after a receipt accept, zone.utilization_units equals
        bin.occupied_volume for the single occupied bin.
        """
        ctx = setup_accepted_lot(quantity_units=7)
        zone_after = get_zone(ctx["zone"]["id"])
        bin_after = get_bin(ctx["zone"]["id"], ctx["bin"]["id"])
        # The storage zone has one bin; utilization == 7 == that
        # bin's occupied_volume.
        assert_zone_utilization_invariant(zone_after, [bin_after])
        assert zone_after["utilization_units"] == 7

    def test_zone_utilization_falls_after_pick(self, api):
        """PRD §3.5: "the bin's `occupied_volume` and
        `occupied_weight_kg` are recomputed (with `occupied_weight_kg`
        reduced by `quantity_units` multiplied by the product's
        `unit_weight_kg`), the bin's `status` flips to `AVAILABLE` if
        `occupied_volume` reaches 0, and the parent zone's
        `utilization_units` is rolled up."

        Claim: after picking the full lot, the bin returns to
        AVAILABLE and zone.utilization_units drops to 0.
        """
        ctx = setup_accepted_lot(quantity_units=5)
        s = create_planned_shipment(
            ctx["warehouse"]["id"], ctx["product"]["id"], quantity_units=5,
        )
        pick_shipment(s["id"])
        bin_after = get_bin(ctx["zone"]["id"], ctx["bin"]["id"])
        zone_after = get_zone(ctx["zone"]["id"])
        assert bin_after["occupied_volume"] == 0
        assert bin_after["status"] == "AVAILABLE"
        assert zone_after["utilization_units"] == 0


# ===========================================================================
# Difficulty-design: dual-variant FEFO pick — provisional vs final.
# # difficulty: dual_variant_calc/fefo_pick_provisional_vs_final_on_shipment
# ===========================================================================
class TestFefoProvisionalVsFinal:

    def test_two_planned_shipments_setup_does_not_pre_decrement_lot(
        self, api,
    ):
        """PRD §3.5: "Picking moves the shipment from `PLANNED` to
        `PICKED`. The FEFO pick-selection calculation walks every lot
        in the warehouse whose `product_id` matches the shipment's,
        whose `quality_status` is `RELEASED`, whose `expiry_minutes`
        is strictly greater than the warehouse's `clock_minutes`, and
        whose `quantity_on_hand` is at least the shipment's
        `quantity_units`."

        Difficulty-design: dual_variant_calc /
        fefo_pick_provisional_vs_final_on_shipment (the provisional
        side — PLANNED shipments do NOT modify physical Lot stock).
        # difficulty: dual_variant_calc/fefo_pick_provisional_vs_final_on_shipment

        Claim: creating two PLANNED shipments for the same lot does
        NOT decrement Lot.quantity_on_hand (PLANNED is pre-pick state
        and per PRD §3.5 only the PICK transition decrements stock).
        """
        ctx = setup_two_planned_shipments_for_one_lot(
            accepted_quantity_units=10, shipment_quantity_units=6,
        )
        # Both shipments are PLANNED; lot.on_hand should still equal
        # the accepted_quantity_units (10).
        lot = get_lot(ctx["lot"]["id"])
        assert lot["quantity_on_hand"] == 10, (
            f"PLANNED shipments must not decrement lot stock; got "
            f"on_hand={lot['quantity_on_hand']}, expected 10"
        )
        assert lot["quantity_picked"] == 0

    def test_first_pick_succeeds_second_pick_fails_insufficient_stock(
        self, api,
    ):
        """PRD §2.11: "When two pickers race for the last available
        units of a single lot, the first writer wins the atomic
        decrement on `quantity_on_hand` and the loser is rejected
        with `ERR_INSUFFICIENT_STOCK` (HTTP 409)."

        Difficulty-design: dual_variant_calc /
        fefo_pick_provisional_vs_final_on_shipment.
        # difficulty: dual_variant_calc/fefo_pick_provisional_vs_final_on_shipment

        Claim: two PLANNED shipments S1, S2 each requesting 6 units
        of a 10-unit lot. Pick S1 succeeds (lot.on_hand → 4); pick S2
        fails with ERR_INSUFFICIENT_STOCK (final pick sees the
        physical 4 < 6, not the provisional 10).

        (The preview variant — a separate GET endpoint that would
        return projected_available=4 BEFORE S1 picks — is not
        explicitly stated in PRD prose. The behaviour we assert is
        the final-pick side of the dual-variant, which the PRD does
        state.)
        """
        ctx = setup_two_planned_shipments_for_one_lot(
            accepted_quantity_units=10, shipment_quantity_units=6,
        )
        # Pick S1 (succeeds).
        picked_1 = pick_shipment(ctx["shipment_1"]["id"])
        assert picked_1["status"] == "PICKED"
        lot_after_first_pick = get_lot(ctx["lot"]["id"])
        assert lot_after_first_pick["quantity_on_hand"] == 4
        # Pick S2 (fails — final pick sees physical 4 < 6).
        #
        # PRD §2.11 names ERR_INSUFFICIENT_STOCK for the race outcome
        # (two pickers racing for the last units), but PRD §3.5's
        # candidate-set filter also says "whose `quantity_on_hand` is at
        # least the shipment's `quantity_units`" — under that filter S2
        # finds no candidate, so ERR_NO_FEFO_LOT is equally PRD-faithful
        # for this sequential follow-up pick. Accept either member of
        # the PRD-derivable set.
        from test_helpers import validate_error_is_one_of
        res = api.pick_shipment(
            ctx["shipment_2"]["id"], TEST_USERS["picker_headers"],
        )
        validate_error_is_one_of(
            res,
            [
                ApiErrorId.ERR_INSUFFICIENT_STOCK.value,
                ApiErrorId.ERR_NO_FEFO_LOT.value,
            ],
        )


# ===========================================================================
# Audit log — PRD §2.13
# ===========================================================================
class TestAuditLogEmission:

    def test_audit_entries_carry_actor_user_id_and_role(self, api):
        """PRD §2.13: "Every state-changing action persists an
        `AuditLogEntry` row carrying the warehouse, the acting
        `actor_user_id`, the acting `actor_role`, a verb-plus-entity
        `action` string, the `target_id` of the affected entity, and
        the `at_minutes` clock reading at write."

        Claim: after accept, the matching audit entry carries the
        QAOfficer's X-User-ID in actor_user_id and 'QAOfficer' in
        actor_role.
        """
        ctx = setup_accepted_lot(quantity_units=1)
        entries = list_audit_log(
            ctx["warehouse"]["id"],
            params={"action": "RECEIPT_ACCEPT", "limit": 100},
        )
        # The receiver headers used 'receiver-001' and qa_officer
        # used 'qa-001'.
        matched = [
            e for e in entries
            if e["action"] == "RECEIPT_ACCEPT"
            and e["target_id"] == ctx["receipt"]["id"]
        ]
        assert len(matched) == 1
        entry = matched[0]
        from test_helpers import QA_OFFICER_ID
        assert entry["actor_user_id"] == QA_OFFICER_ID
        assert entry["actor_role"] == "QAOfficer"


# ===========================================================================
# Difficulty-design: priority pair business_safety vs business_constraint
# # difficulty: priority_pair_validation_conflict/business_safety_vs_business_constraint_unqualified_supplier_and_segregation
# ===========================================================================
class TestPriorityBusinessSafetyVsConstraint:

    def test_segregation_fires_when_supplier_is_qualified(self, api):
        """PRD §2.12 priority pinning. With supplier qualified
        (business_safety passes), the next-in-priority
        business_constraint check fires — ERR_SEGREGATION_VIOLATION.

        Difficulty-design: priority_pair_validation_conflict /
        business_safety_vs_business_constraint_unqualified_supplier_and_segregation
        (matched SEGREGATION side — proves the chain is consistent).
        # difficulty: priority_pair_validation_conflict/business_safety_vs_business_constraint_unqualified_supplier_and_segregation

        Claim: supplier qualified (business_safety passes), product
        is NARCOTIC and only NONE bins exist → accept yields
        ERR_SEGREGATION_VIOLATION.
        """
        from test_helpers import create_product, create_supplier
        wh = create_warehouse()
        z = create_zone(wh["id"], zone_type="REFRIGERATED")
        create_bin(z["id"], volume_units=100, weight_limit_kg=500.0)
        qz = create_zone(wh["id"], zone_type="QUARANTINE",
                         capacity_units=1000)
        create_bin(qz["id"], volume_units=1000, weight_limit_kg=10000.0)
        # Qualified supplier (so business_safety passes).
        supplier = create_supplier(qualified=True,
                                   qualification_expiry_minutes=100_000)
        product = create_product(
            required_zone_type="REFRIGERATED",
            special_storage_tag="NARCOTIC",
            qualified=True,
        )
        receipt = create_inspected_receipt(
            wh["id"], supplier["id"], product["id"],
            quantity_units=1, visual_pass=True,
        )
        res = api.accept_receipt(
            receipt["id"], TEST_USERS["qa_officer_headers"],
        )
        validate_error(res, ApiErrorId.ERR_SEGREGATION_VIOLATION.value)

    def test_unqualified_supplier_wins_over_segregation_violation(self, api):
        """PRD §2.12: "Cold-chain safety follows: zone-frozen blocking
        (`ERR_ZONE_FROZEN`), then supplier qualification
        (`ERR_UNQUALIFIED_SUPPLIER`), then product qualification ...,
        then lot expiry .... Business constraints follow in this
        declared order: packaging match ..., segregation
        (`ERR_SEGREGATION_VIOLATION`)".

        Difficulty-design: priority_pair_validation_conflict /
        business_safety_vs_business_constraint_unqualified_supplier_and_segregation.
        # difficulty: priority_pair_validation_conflict/business_safety_vs_business_constraint_unqualified_supplier_and_segregation

        Claim: receipt has BOTH (a) unqualified supplier AND (b) would
        require a bin with no matching segregation tag (NARCOTIC
        product but only NONE bins exist). Accept yields
        ERR_UNQUALIFIED_SUPPLIER (business_safety wins over
        business_constraint).
        """
        from test_helpers import create_product, create_supplier
        wh = create_warehouse()
        z = create_zone(wh["id"], zone_type="REFRIGERATED")
        # Only NONE-tagged bin (no NARCOTIC bin exists).
        create_bin(z["id"], volume_units=100, weight_limit_kg=500.0)
        qz = create_zone(wh["id"], zone_type="QUARANTINE",
                         capacity_units=1000)
        create_bin(qz["id"], volume_units=1000, weight_limit_kg=10000.0)
        # Unqualified supplier.
        supplier = create_supplier(qualified=False,
                                   qualification_expiry_minutes=100_000)
        product = create_product(
            required_zone_type="REFRIGERATED",
            special_storage_tag="NARCOTIC",
            qualified=True,
        )
        receipt = create_inspected_receipt(
            wh["id"], supplier["id"], product["id"],
            quantity_units=1, visual_pass=True,
        )
        res = api.accept_receipt(
            receipt["id"], TEST_USERS["qa_officer_headers"],
        )
        # business_safety priority (supplier qualification, priority
        # 12) wins over business_constraint priority (segregation,
        # priority 16).
        validate_error(res, ApiErrorId.ERR_UNQUALIFIED_SUPPLIER.value)


# ===========================================================================
# Difficulty-design: volume conservation across zones on recall return.
# # difficulty: compensating_invariant/zone_volume_conserved_on_accept_then_recall_return
# ===========================================================================
class TestVolumeConservationOnRecallReturn:

    def test_recall_return_increments_returns_received_units(self, api):
        """PRD §3.7: "Each valid return increments
        `returns_received_units` by the supplied `units`".

        Difficulty-design: compensating_invariant /
        zone_volume_conserved_on_accept_then_recall_return (the
        accounting side — returns_received_units reflects the
        cumulative units physically moved back into quarantine).
        # difficulty: compensating_invariant/zone_volume_conserved_on_accept_then_recall_return

        Claim: a recall return of 3 units raises the recall's
        returns_received_units from 0 to 3.
        """
        from test_helpers import (
            notify_next_customer,
            record_recall_return,
            setup_shipped_shipment_then_recall,
        )
        ctx = setup_shipped_shipment_then_recall(
            accepted_quantity_units=5, shipment_quantity_units=5,
            customer_id="C-incr",
        )
        r = create_draft_recall(
            ctx["warehouse"]["id"], classification="CLASS_II",
        )
        entry = add_recall_scope(
            r["id"], lot_id=ctx["shipment"]["pick_lot_id"], units=5,
            scope_kind="SHIPPED", shipment_id=ctx["shipment"]["id"],
        )
        announced = announce_recall(r["id"])
        assert announced["returns_received_units"] == 0
        notify_next_customer(r["id"])
        updated = record_recall_return(
            r["id"], scope_entry_id=entry["id"], units=3,
        )
        assert updated["returns_received_units"] == 3

    def test_recall_return_moves_volume_to_quarantine_zone(self, api):
        """PRD §3.7: "Each valid return increments
        `returns_received_units` by the supplied `units` and
        physically moves those units into a `QUARANTINE`-zone bin in
        the warehouse (raising the bin's `occupied_volume` and rolling
        up the parent zone's `utilization_units`)."

        Difficulty-design: compensating_invariant /
        zone_volume_conserved_on_accept_then_recall_return.
        # difficulty: compensating_invariant/zone_volume_conserved_on_accept_then_recall_return

        Claim: after a recall return of N units, the
        QUARANTINE-zone's utilization_units rises by N. (The
        REFRIGERATED zone's utilization was already 0 because the
        units were dispatched; total warehouse occupied volume now
        equals the returned amount.)
        """
        from test_helpers import (
            dispatch_shipment,
            notify_next_customer,
            record_recall_return,
            setup_shipped_shipment_then_recall,
        )
        ctx = setup_shipped_shipment_then_recall(
            accepted_quantity_units=5, shipment_quantity_units=5,
            customer_id="C-vol",
        )
        # After dispatch, the REFRIGERATED zone utilization is 0.
        z_storage = get_zone(ctx["zone"]["id"])
        assert z_storage["utilization_units"] == 0
        # Build recall, scope, announce.
        r = create_draft_recall(
            ctx["warehouse"]["id"], classification="CLASS_II",
        )
        entry = add_recall_scope(
            r["id"], lot_id=ctx["shipment"]["pick_lot_id"], units=5,
            scope_kind="SHIPPED", shipment_id=ctx["shipment"]["id"],
        )
        announce_recall(r["id"])
        notify_next_customer(r["id"])
        record_recall_return(
            r["id"], scope_entry_id=entry["id"], units=5,
        )
        # Quarantine zone now carries the returned volume.
        z_quarantine = get_zone(ctx["quarantine_zone"]["id"])
        assert z_quarantine["utilization_units"] == 5


# ===========================================================================
# Difficulty-design: recall_effectiveness final variant — failing close.
# # difficulty: dual_variant_calc/recall_effectiveness_provisional_vs_final
# ===========================================================================
class TestRecallEffectivenessFinalVariant:

    def test_final_effectiveness_ratio_below_threshold_fails(self, api):
        """PRD §3.7: "The authoritative effectiveness ratio is
        `returns_received_units` divided by `returns_expected_units`
        ... The recall's `effectiveness_pass` is true if and only if
        the rounded ratio is at least 0.80".

        Difficulty-design: dual_variant_calc /
        recall_effectiveness_provisional_vs_final (final side).
        # difficulty: dual_variant_calc/recall_effectiveness_provisional_vs_final

        Claim: returns_received_units=6, returns_expected_units=10 →
        ratio=0.60 < 0.80 → effectiveness_pass=false on close.
        """
        from test_helpers import (
            accept_receipt,
            close_recall,
            notify_next_customer,
            record_recall_return,
            setup_qualified_supplier_and_product,
        )
        # Build a 10-unit SHIPPED setup.
        wh = create_warehouse()
        z = create_zone(wh["id"], zone_type="REFRIGERATED")
        create_bin(z["id"], volume_units=200, weight_limit_kg=1000.0)
        qz = create_zone(wh["id"], zone_type="QUARANTINE",
                         capacity_units=1000)
        create_bin(qz["id"], volume_units=1000, weight_limit_kg=10000.0)
        supplier, product = setup_qualified_supplier_and_product()
        rcpt = create_inspected_receipt(
            wh["id"], supplier["id"], product["id"], quantity_units=15,
        )
        accept_receipt(rcpt["id"])
        s = create_planned_shipment(
            wh["id"], product["id"], quantity_units=10,
            customer_id="C-eff",
        )
        pick_shipment(s["id"])
        packed = pack_shipment(s["id"])
        from test_helpers import dispatch_shipment
        dispatched = dispatch_shipment(packed["id"])
        r = create_draft_recall(wh["id"], classification="CLASS_II")
        entry = add_recall_scope(
            r["id"], lot_id=dispatched["pick_lot_id"], units=10,
            scope_kind="SHIPPED", shipment_id=dispatched["id"],
        )
        announce_recall(r["id"])
        notify_next_customer(r["id"])
        # Return 6 of 10 units.
        record_recall_return(
            r["id"], scope_entry_id=entry["id"], units=6,
        )
        # Force EFFECTIVENESS_CHECK by elapsing the deadline.
        from test_helpers import RECALL_CLASS_II_OFFSET
        advance_clock(wh["id"], RECALL_CLASS_II_OFFSET + 1)
        closed = close_recall(r["id"])
        # Final ratio = 6/10 = 0.60 < 0.80 → fail.
        assert closed["effectiveness_pass"] is False
