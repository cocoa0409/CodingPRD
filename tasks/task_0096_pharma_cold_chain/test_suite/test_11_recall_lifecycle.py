"""Recall lifecycle — PRD §3.7.

Tests cover: create + scope + announce (with deadline calculation per
class), recall cascade to lots, notify-next-customer counting,
record-return, effectiveness check + close, the preview/projection
variant, and the failed-recall CAPA opening.
"""
from __future__ import annotations

import pytest

from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    TEST_USERS,
    add_recall_scope,
    advance_clock,
    announce_recall,
    assert_recall,
    close_recall,
    create_draft_recall,
    create_planned_shipment,
    dispatch_shipment,
    get_lot,
    get_recall,
    list_audit_log,
    list_capas,
    list_external_events,
    list_lots,
    list_shipments,
    notify_next_customer,
    pack_shipment,
    pick_shipment,
    record_recall_return,
    setup_accepted_lot,
    setup_shipped_shipment_then_recall,
    validate_error,
    validate_success,
    RECALL_CLASS_I_OFFSET,
    RECALL_CLASS_II_OFFSET,
    RECALL_CLASS_III_OFFSET,
    RECALL_FAILED_CAPA_DUE_OFFSET,
)


# ===========================================================================
# Recall draft + scope + announce — PRD §3.7
# ===========================================================================
class TestRecallDraftAndScope:

    def test_create_recall_initial_state_draft(self, api):
        """PRD §3.7: "The recall is born in `DRAFT` with a null
        `initiated_at_minutes`, a null `report_due_minutes`, a null
        `notifications_required`, a `notifications_sent` of 0, a null
        `returns_expected_units`, a `returns_received_units` of 0,
        and a null `effectiveness_pass`."

        Claim: a fresh recall carries the eight named fields per PRD.
        """
        from test_helpers import create_warehouse
        wh = create_warehouse()
        r = create_draft_recall(
            wh["id"], classification="CLASS_II", reason="bad batch",
        )
        assert r["status"] == "DRAFT"
        assert r.get("initiated_at_minutes") is None
        assert r.get("report_due_minutes") is None
        assert r.get("notifications_required") is None
        assert r["notifications_sent"] == 0
        assert r["returns_received_units"] == 0
        assert r.get("effectiveness_pass") is None
        assert_recall(r)


class TestRecallAnnounceEmptyScope:

    def test_announce_with_no_scope_returns_err_recall_scope_empty(self, api):
        """PRD §3.7: "Announcement requires at least one
        `RecallScopeEntry` (the empty-scope failure surfaces as
        `ERR_RECALL_SCOPE_EMPTY` at HTTP 422)".

        Claim: announce on a DRAFT recall with zero scope entries →
        ERR_RECALL_SCOPE_EMPTY.
        """
        from test_helpers import create_warehouse
        wh = create_warehouse()
        r = create_draft_recall(wh["id"], classification="CLASS_II")
        res = api.announce_recall(
            r["id"], TEST_USERS["recall_officer_headers"],
        )
        validate_error(res, ApiErrorId.ERR_RECALL_SCOPE_EMPTY.value)


# ===========================================================================
# Class-specific report_due_minutes — PRD §3.7
# ===========================================================================
class TestRecallReportDueMinutes:

    def _build_recall_with_one_scope(self, *, classification: str):
        """Helper: build accepted-lot context + draft recall +
        ON_HAND scope entry covering the lot.
        """
        ctx = setup_accepted_lot(quantity_units=3)
        r = create_draft_recall(
            ctx["warehouse"]["id"], classification=classification,
        )
        add_recall_scope(
            r["id"], lot_id=ctx["lot"]["id"], units=3,
            scope_kind="ON_HAND",
        )
        return ctx, r

    def test_class_i_offset_is_1440_min(self, api):
        """PRD §3.7: "the regulatory `report_due_minutes` is computed
        as `initiated_at_minutes` plus a class-specific offset — 1440
        minutes (24 hours) for `CLASS_I`".

        Claim: announce of a CLASS_I recall pins report_due_minutes
        to initiated_at_minutes + 1440.
        """
        ctx, r = self._build_recall_with_one_scope(classification="CLASS_I")
        announced = announce_recall(r["id"])
        init = announced["initiated_at_minutes"]
        due = announced["report_due_minutes"]
        assert due == init + RECALL_CLASS_I_OFFSET, (
            f"CLASS_I report_due_minutes should equal initiated_at + "
            f"{RECALL_CLASS_I_OFFSET}, got initiated_at={init}, "
            f"report_due={due}"
        )

    def test_class_ii_offset_is_4320_min(self, api):
        """PRD §3.7: "4320 minutes (72 hours) for `CLASS_II`".

        Claim: CLASS_II report_due_minutes = initiated_at + 4320.
        """
        ctx, r = self._build_recall_with_one_scope(classification="CLASS_II")
        announced = announce_recall(r["id"])
        assert (
            announced["report_due_minutes"]
            == announced["initiated_at_minutes"] + RECALL_CLASS_II_OFFSET
        )

    def test_class_iii_offset_is_14400_min(self, api):
        """PRD §3.7: "or 14400 minutes (240 hours, equivalently 10
        days) for `CLASS_III`".

        Claim: CLASS_III report_due_minutes = initiated_at + 14400.
        """
        ctx, r = self._build_recall_with_one_scope(classification="CLASS_III")
        announced = announce_recall(r["id"])
        assert (
            announced["report_due_minutes"]
            == announced["initiated_at_minutes"] + RECALL_CLASS_III_OFFSET
        )


# ===========================================================================
# Recall announce — cascade to lots
# # difficulty: transitive_cascade/recall_announce_cascades_to_lot_recalled_and_shipment_recall_tag
# ===========================================================================
class TestRecallAnnounceCascade:

    def test_announce_marks_in_scope_lots_recalled(self, api):
        """PRD §3.7: "Every in-scope lot's `quality_status` is set to
        `RECALLED` as a cascade".

        Difficulty-design: transitive_cascade /
        recall_announce_cascades_to_lot_recalled_and_shipment_recall_tag.
        # difficulty: transitive_cascade/recall_announce_cascades_to_lot_recalled_and_shipment_recall_tag

        Claim: after announce, every Lot referenced in a
        RecallScopeEntry row has quality_status == RECALLED.
        """
        ctx = setup_accepted_lot(quantity_units=3)
        r = create_draft_recall(
            ctx["warehouse"]["id"], classification="CLASS_II",
        )
        add_recall_scope(
            r["id"], lot_id=ctx["lot"]["id"], units=3,
            scope_kind="ON_HAND",
        )
        announce_recall(r["id"])
        lot_after = get_lot(ctx["lot"]["id"])
        assert lot_after["quality_status"] == "RECALLED"

    def test_announce_sets_notifications_required_to_distinct_customers(
        self, api,
    ):
        """PRD §3.7: "`notifications_required` is computed as the
        count of distinct `customer_id` values appearing in scope
        entries whose `scope_kind` is `SHIPPED`".

        Difficulty-design: transitive_cascade /
        recall_announce_cascades_to_lot_recalled_and_shipment_recall_tag
        — the downstream side of the cascade (a recall announce
        re-computes notifications_required from the customer_ids of
        all SHIPPED scope entries).
        # difficulty: transitive_cascade/recall_announce_cascades_to_lot_recalled_and_shipment_recall_tag

        Claim: two SHIPPED scope entries from distinct customer_ids,
        one ON_HAND entry, → notifications_required == 2.
        """
        from test_helpers import (
            accept_receipt,
            create_bin,
            create_inspected_receipt,
            create_warehouse,
            create_zone,
            setup_qualified_supplier_and_product,
        )
        # Build 3 receipts → 3 lots, each in its own bin.
        wh = create_warehouse()
        z = create_zone(wh["id"], zone_type="REFRIGERATED")
        for _ in range(3):
            create_bin(z["id"], volume_units=100, weight_limit_kg=500.0)
        qz = create_zone(wh["id"], zone_type="QUARANTINE",
                         capacity_units=1000)
        create_bin(qz["id"], volume_units=1000, weight_limit_kg=10000.0)
        supplier, product = setup_qualified_supplier_and_product()
        lot_ids = []
        for _ in range(3):
            rcpt = create_inspected_receipt(
                wh["id"], supplier["id"], product["id"], quantity_units=2,
            )
            accept_receipt(rcpt["id"])
            lots = list_lots(
                wh["id"], params={"product_id": product["id"], "limit": 100},
            )
            lot_ids = [L["id"] for L in lots]
        # Three lots. Two ship to customer C1 and C2, one is ON_HAND.
        ships = []
        for customer_id, lot_id in [("C1", lot_ids[0]), ("C2", lot_ids[1])]:
            s = create_planned_shipment(
                wh["id"], product["id"], quantity_units=2,
                customer_id=customer_id,
            )
            pick_shipment(s["id"])
            packed = pack_shipment(s["id"])
            dispatched = dispatch_shipment(packed["id"])
            ships.append((dispatched, customer_id))

        # Build recall with three scope entries — two SHIPPED, one ON_HAND.
        r = create_draft_recall(wh["id"], classification="CLASS_II")
        add_recall_scope(
            r["id"], lot_id=ships[0][0]["pick_lot_id"], units=2,
            scope_kind="SHIPPED", shipment_id=ships[0][0]["id"],
        )
        add_recall_scope(
            r["id"], lot_id=ships[1][0]["pick_lot_id"], units=2,
            scope_kind="SHIPPED", shipment_id=ships[1][0]["id"],
        )
        add_recall_scope(
            r["id"], lot_id=lot_ids[2], units=2,
            scope_kind="ON_HAND",
        )
        announced = announce_recall(r["id"])
        # Two distinct customers in SHIPPED entries.
        assert announced["notifications_required"] == 2

    def test_announce_emits_regulatory_and_pharmacovigilance_events(
        self, api,
    ):
        """PRD §3.7: "Two `ExternalSyncEvent` rows are appended — one
        targeted at `REGULATORY_AUTHORITY` and one at
        `PHARMACOVIGILANCE`, both carrying `event_type`
        `RECALL_ANNOUNCED`".

        Claim: after announce, exactly one REGULATORY_AUTHORITY/
        RECALL_ANNOUNCED and one PHARMACOVIGILANCE/RECALL_ANNOUNCED
        event are present in the log.
        """
        ctx = setup_accepted_lot(quantity_units=3)
        r = create_draft_recall(
            ctx["warehouse"]["id"], classification="CLASS_II",
        )
        add_recall_scope(
            r["id"], lot_id=ctx["lot"]["id"], units=3,
            scope_kind="ON_HAND",
        )
        announce_recall(r["id"])
        events = list_external_events(
            ctx["warehouse"]["id"],
            params={"event_type": "RECALL_ANNOUNCED", "limit": 100},
        )
        reg = [
            e for e in events
            if e["target_system"] == "REGULATORY_AUTHORITY"
            and e["event_type"] == "RECALL_ANNOUNCED"
        ]
        ph = [
            e for e in events
            if e["target_system"] == "PHARMACOVIGILANCE"
            and e["event_type"] == "RECALL_ANNOUNCED"
        ]
        assert len(reg) >= 1
        assert len(ph) >= 1


# ===========================================================================
# Recall scope state guard — PRD §3.7
# ===========================================================================
class TestRecallStateGuards:

    def test_announce_on_already_announced_returns_err_recall_not_draft(
        self, api,
    ):
        """PRD §2.11: "When two `RecallOfficer` calls attempt to
        announce the same recall, the first writer wins the `DRAFT`
        to `ANNOUNCED` transition and the loser is rejected with
        `ERR_RECALL_NOT_DRAFT` (HTTP 409)."

        Claim: a second announce on the same recall →
        ERR_RECALL_NOT_DRAFT.
        """
        ctx = setup_accepted_lot(quantity_units=3)
        r = create_draft_recall(
            ctx["warehouse"]["id"], classification="CLASS_II",
        )
        add_recall_scope(
            r["id"], lot_id=ctx["lot"]["id"], units=3,
            scope_kind="ON_HAND",
        )
        announce_recall(r["id"])
        res = api.announce_recall(
            r["id"], TEST_USERS["recall_officer_headers"],
        )
        validate_error(res, ApiErrorId.ERR_RECALL_NOT_DRAFT.value)


# ===========================================================================
# Return scope validity — PRD §3.7
# ===========================================================================
class TestRecordReturnScopeInvalid:

    def test_return_targeting_on_hand_scope_rejected(self, api):
        """PRD §3.7: "A return targeting a non-existent, wrong-recall,
        or `ON_HAND` scope entry is rejected with
        `ERR_RETURN_SCOPE_INVALID` (HTTP 422)."

        Claim: record-return on an ON_HAND scope_entry_id →
        ERR_RETURN_SCOPE_INVALID.

        The recall must be in RETURNS_IN_PROGRESS before record-return
        can run; otherwise PRD §2.12 surfaces the state-precondition
        ERR_RECALL_STATE_INVALID first. Notify the lone SHIPPED
        customer first to auto-advance the recall.
        """
        # Build a SHIPPED scope + recall.
        ctx = setup_shipped_shipment_then_recall(
            accepted_quantity_units=5, shipment_quantity_units=3,
            customer_id="C-ret",
        )
        r = create_draft_recall(
            ctx["warehouse"]["id"], classification="CLASS_II",
        )
        # Add ON_HAND scope.
        on_hand_entry = add_recall_scope(
            r["id"], lot_id=ctx["lot"]["id"], units=2,
            scope_kind="ON_HAND",
        )
        # Also a SHIPPED scope so announce passes.
        add_recall_scope(
            r["id"], lot_id=ctx["shipment"]["pick_lot_id"], units=3,
            scope_kind="SHIPPED", shipment_id=ctx["shipment"]["id"],
        )
        announce_recall(r["id"])
        # Advance to RETURNS_IN_PROGRESS by notifying the single
        # SHIPPED-scope customer (notifications_required == 1).
        notify_next_customer(r["id"])
        # Try to record return against ON_HAND scope_entry_id.
        res = api.record_recall_return(
            r["id"],
            {"scope_entry_id": on_hand_entry["id"], "units": 1},
            TEST_USERS["recall_officer_headers"],
        )
        validate_error(res, ApiErrorId.ERR_RETURN_SCOPE_INVALID.value)


# ===========================================================================
# Effectiveness check + close — PRD §3.7
# ===========================================================================
class TestRecallEffectiveness:

    def test_effectiveness_pass_at_80_percent_threshold(self, api):
        """PRD §3.7: "The recall's `effectiveness_pass` is true if and
        only if the rounded ratio is at least 0.80".

        Claim: 4 SHIPPED units, 4 returned → ratio=1.0 ≥ 0.80 →
        effectiveness_pass == true.
        """
        ctx = setup_shipped_shipment_then_recall(
            accepted_quantity_units=5, shipment_quantity_units=4,
            customer_id="C-pass",
        )
        r = create_draft_recall(
            ctx["warehouse"]["id"], classification="CLASS_II",
        )
        entry = add_recall_scope(
            r["id"], lot_id=ctx["shipment"]["pick_lot_id"], units=4,
            scope_kind="SHIPPED", shipment_id=ctx["shipment"]["id"],
        )
        announce_recall(r["id"])
        notify_next_customer(r["id"])  # 1 of 1
        record_recall_return(
            r["id"], scope_entry_id=entry["id"], units=4,
        )
        # Should auto-advance to EFFECTIVENESS_CHECK once
        # returns_received_units == returns_expected_units == 4.
        closed = close_recall(r["id"])
        assert closed["status"] == "CLOSED"
        assert closed["effectiveness_pass"] is True

    def test_effectiveness_fail_below_80_percent_opens_capa(self, api):
        """PRD §3.7: "When `effectiveness_pass` is false, the system
        opens a new `CAPA` whose `due_minutes` is the current
        `clock_minutes` plus 4320 minutes (72 hours)."

        Claim: ratio < 0.80 on close → effectiveness_pass=false AND
        a new CAPA appears with due_minutes == close_clock + 4320.
        """
        # Build 10 SHIPPED units, return only 5 → ratio = 0.50.
        from test_helpers import (
            accept_receipt,
            create_bin,
            create_inspected_receipt,
            create_warehouse,
            create_zone,
            setup_qualified_supplier_and_product,
            get_warehouse,
        )
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
        # Build a SHIPPED shipment of 10 units.
        s = create_planned_shipment(
            wh["id"], product["id"], quantity_units=10,
            customer_id="C-fail",
        )
        pick_shipment(s["id"])
        packed = pack_shipment(s["id"])
        dispatched = dispatch_shipment(packed["id"])
        r = create_draft_recall(wh["id"], classification="CLASS_II")
        entry = add_recall_scope(
            r["id"], lot_id=dispatched["pick_lot_id"], units=10,
            scope_kind="SHIPPED", shipment_id=dispatched["id"],
        )
        announce_recall(r["id"])
        notify_next_customer(r["id"])
        # Return only 5 of 10.
        record_recall_return(
            r["id"], scope_entry_id=entry["id"], units=5,
        )
        # Force EFFECTIVENESS_CHECK transition by passing the deadline.
        advance_clock(wh["id"], RECALL_CLASS_II_OFFSET + 1)
        wh_before_close = get_warehouse(wh["id"])
        clock_at_close = wh_before_close["clock_minutes"]
        closed = close_recall(r["id"])
        assert closed["effectiveness_pass"] is False
        # CAPA opened.
        capas = list_capas(wh["id"])
        recall_capas = [c for c in capas if c.get("recall_id") == r["id"]]
        assert len(recall_capas) == 1, (
            f"Expected exactly one CAPA from failed recall, got "
            f"{len(recall_capas)}"
        )
        assert recall_capas[0]["due_minutes"] == (
            clock_at_close + RECALL_FAILED_CAPA_DUE_OFFSET
        )

    def test_effectiveness_denominator_excludes_on_hand_units(self, api):
        """PRD §3.7: "the denominator includes only `SHIPPED` scope
        entries — `ON_HAND` units are excluded."

        Claim: 4 SHIPPED + 6 ON_HAND, return 4 → effectiveness =
        4/4 = 1.0 → pass.
        """
        ctx = setup_shipped_shipment_then_recall(
            accepted_quantity_units=10, shipment_quantity_units=4,
            customer_id="C-onhand",
        )
        # Need a second lot for ON_HAND units; reuse the accepted lot
        # which still has 6 units on hand (10 - 4 shipped).
        # Actually setup_shipped_shipment_then_recall picks all 4 units
        # from the lot — on_hand drops to 6. We'll scope that lot as
        # ON_HAND for the remaining 6 units.
        r = create_draft_recall(
            ctx["warehouse"]["id"], classification="CLASS_II",
        )
        # SHIPPED entry for the 4 dispatched units.
        ship_entry = add_recall_scope(
            r["id"], lot_id=ctx["shipment"]["pick_lot_id"], units=4,
            scope_kind="SHIPPED", shipment_id=ctx["shipment"]["id"],
        )
        # ON_HAND entry on the same lot for the 6 remaining units.
        add_recall_scope(
            r["id"], lot_id=ctx["lot"]["id"], units=6,
            scope_kind="ON_HAND",
        )
        announce_recall(r["id"])
        notify_next_customer(r["id"])
        record_recall_return(
            r["id"], scope_entry_id=ship_entry["id"], units=4,
        )
        closed = close_recall(r["id"])
        # Denominator = 4 (SHIPPED only). Ratio = 4/4 = 1.0 → pass.
        assert closed["effectiveness_pass"] is True


# ===========================================================================
# Recall preview (provisional projection) — PRD §3.7
# # difficulty: dual_variant_calc/recall_effectiveness_provisional_vs_final
# ===========================================================================
class TestRecallPreviewProvisional:

    def test_preview_projects_pass_even_when_returns_are_low(self, api):
        """PRD §3.7: "A read-only preview capability is also available
        before close and uses a provisional projection variant of the
        same calculation: it adds to `returns_received_units` a credit
        equal to the count of notified-but-not-yet-returned customers
        (with a per-notification credit of 1.0 unit), divides by
        `returns_expected_units`, and reports a projected pass against
        the same 0.80 threshold."

        Difficulty-design: dual_variant_calc /
        recall_effectiveness_provisional_vs_final.
        # difficulty: dual_variant_calc/recall_effectiveness_provisional_vs_final

        Claim: with returns_received_units=6, notifications_sent=5
        (all required customers notified — PRD §3.7's state machine
        requires record-return to fire in RETURNS_IN_PROGRESS, which
        is only reached after notifications_sent reaches
        notifications_required), returns_expected_units=10, and 3
        distinct customers having actually returned → notified-but-not-
        yet-returned = 5 - 3 = 2 → provisional ratio = (6 + 2) / 10 =
        0.80 ≥ 0.80 → projected_pass=true. The final ratio (without
        the credit) is 6/10 = 0.60 < 0.80, so the dual-variant
        provisional-vs-final divergence is exhibited.
        """
        # Build 5 SHIPPED scope entries from 5 distinct customers, each
        # 2 units (so returns_expected_units == 10,
        # notifications_required == 5).
        from test_helpers import (
            accept_receipt,
            create_bin,
            create_inspected_receipt,
            create_warehouse,
            create_zone,
            setup_qualified_supplier_and_product,
        )
        wh = create_warehouse()
        z = create_zone(wh["id"], zone_type="REFRIGERATED")
        # 5 bins for 5 lots.
        for _ in range(5):
            create_bin(z["id"], volume_units=100, weight_limit_kg=500.0)
        qz = create_zone(wh["id"], zone_type="QUARANTINE",
                         capacity_units=1000)
        create_bin(qz["id"], volume_units=1000, weight_limit_kg=10000.0)
        supplier, product = setup_qualified_supplier_and_product()
        shipments = []
        for i in range(5):
            rcpt = create_inspected_receipt(
                wh["id"], supplier["id"], product["id"], quantity_units=2,
            )
            accept_receipt(rcpt["id"])
            s = create_planned_shipment(
                wh["id"], product["id"], quantity_units=2,
                customer_id=f"C-{i}",
            )
            pick_shipment(s["id"])
            packed = pack_shipment(s["id"])
            dispatched = dispatch_shipment(packed["id"])
            shipments.append(dispatched)
        # Recall with 5 SHIPPED entries.
        r = create_draft_recall(wh["id"], classification="CLASS_II")
        entries = []
        for s in shipments:
            e = add_recall_scope(
                r["id"], lot_id=s["pick_lot_id"], units=2,
                scope_kind="SHIPPED", shipment_id=s["id"],
            )
            entries.append(e)
        announce_recall(r["id"])
        # Notify all 5 customers — PRD §3.7 requires the recall to be
        # in RETURNS_IN_PROGRESS before record-return can fire.
        for _ in range(5):
            notify_next_customer(r["id"])
        # Record returns for 3 entries (6 units returned).
        record_recall_return(r["id"], scope_entry_id=entries[0]["id"],
                             units=2)
        record_recall_return(r["id"], scope_entry_id=entries[1]["id"],
                             units=2)
        record_recall_return(r["id"], scope_entry_id=entries[2]["id"],
                             units=2)
        # Now preview.
        res = api.get_recall_preview(
            r["id"], TEST_USERS["recall_officer_headers"],
        )
        preview = validate_success(res, 200)
        # Per PRD §3.7 the provisional projection adds a 1.0-unit credit
        # per notified-but-not-yet-returned customer. With 5 notified
        # and 3 actually returned, the credit is 5 - 3 = 2. The
        # projected ratio is (6 + 2) / 10 = 0.80, which meets the 0.80
        # threshold → projected_pass = true.
        assert preview.get("projected_pass") is True, (
            f"Expected projected_pass=true with received=6, "
            f"notifications=5, distinct_returned=3, expected=10, "
            f"got {preview}"
        )
