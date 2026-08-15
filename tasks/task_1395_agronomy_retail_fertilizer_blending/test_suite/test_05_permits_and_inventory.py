"""Environmental permits, price sheet windows, and inventory management."""
import pytest

from test_helpers import (
    validate_success, validate_error, validate_paginated, get_success_data,
    ApiErrorId, AGRON, COMPLIANCE, CREDIT, PLANT, ADMIN,
    grower_headers, create_batch_payload,
    create_product, published_price_sheet, active_permit, create_permit_payload,
    receive_lot, create_blend_order, book_order,
    setup_order_pipeline, setup_booked_order)

UREA_SPEC = {"name": "UREA 46-0-0", "analysis_n_pct": 46, "analysis_p2o5_pct": 0, "analysis_k2o_pct": 0}
UREA_LINE = [{"product_id": "UREA 46-0-0", "target_rate_lbs_per_acre": 348.1}]


class TestPermitLifecycle:
    def test_permit_expiry_renewal_cycle(self, api):
        """PRD 3.3: "An `ACTIVE` permit whose `expires_at` the clock has passed is
        treated as `EXPIRED` lazily on read and on every permit-gated operation; from
        `EXPIRED` a renewal moves it to `RENEWAL` (a re-inspection waiver), and
        activation completes the renewal."

        Design: Difficulty/non_linear_state_machine/permit_expiry_renewal_cycle
        """
        permit = active_permit("BLENDER_SITE", expires_at="2026-08-10T00:00:00Z")
        assert permit["status"] == "ACTIVE"

        get_success_data(api.set_clock({"to_iso8601": "2026-08-11T00:00:00Z"}, ADMIN))
        readback = get_success_data(api.get_permit(permit["id"], COMPLIANCE))
        assert readback["status"] == "EXPIRED", "lazy transition fired by the clock move"

        renewal = get_success_data(api.renew_permit(permit["id"], COMPLIANCE))
        assert renewal["status"] == "RENEWAL"

        reactivated = get_success_data(api.activate_permit(permit["id"], {"expires_at": "2027-01-31T00:00:00Z"}, COMPLIANCE))
        assert reactivated["status"] == "ACTIVE", "cycle closed: ACTIVE -> EXPIRED -> RENEWAL -> ACTIVE"

    def test_expired_permit_observable_on_read(self, api):
        """PRD 3.3: "An `ACTIVE` permit whose `expires_at` the clock has passed is
        treated as `EXPIRED` lazily on read and on every permit-gated operation."

        Design: Difficulty/non_linear_state_machine/permit_expiry_renewal_cycle
        """
        permit = active_permit("FERTILIZER_STORAGE", expires_at="2026-08-10T00:00:00Z")
        get_success_data(api.set_clock({"to_iso8601": "2026-08-10T00:00:01Z"}, ADMIN))
        readback = get_success_data(api.get_permit(permit["id"], COMPLIANCE))
        assert readback["status"] == "EXPIRED"


class TestInventoryPermitGate:
    def test_receipt_requires_active_storage_permit(self, api):
        """PRD 3.3: "Permit expiry has the inverse flavor: while a required permit is
        not `ACTIVE`, the gated operation fails with `ERR_PERMIT_NOT_ACTIVE`
        (HTTP 422) — inventory receipts require an `ACTIVE` `FERTILIZER_STORAGE`
        permit (plus `ANHYDROUS_STORAGE` when the received product's `regulated_flag`
        is true), and batch creation and batch start require an `ACTIVE`
        `BLENDER_SITE` permit for the blender's `site_code`."

        Design: Difficulty/cross_entity_state_dependency/inventory_receipt_requires_active_storage_permit
        """
        urea = create_product("UREA 46-0-0", 46, 0, 0)
        # permit exists but is only in APPLICATION
        permit = get_success_data(api.create_permit(create_permit_payload(), COMPLIANCE))
        assert permit["status"] == "APPLICATION"

        resp = api.receive_inventory_lot(
            {"product_id": urea["id"], "warehouse_code": "WH-A", "received_tons": 20, "lot_cost_cents_per_ton": 40000},
            PLANT)
        validate_error(resp, ApiErrorId.ERR_PERMIT_NOT_ACTIVE)

        get_success_data(api.begin_inspection(permit["id"], COMPLIANCE))
        get_success_data(api.activate_permit(permit["id"], {"expires_at": "2027-12-31T00:00:00Z"}, COMPLIANCE))
        lot = get_success_data(api.receive_inventory_lot(
            {"product_id": urea["id"], "warehouse_code": "WH-A", "received_tons": 20, "lot_cost_cents_per_ton": 40000},
            PLANT))
        assert lot["on_hand_tons"] == pytest.approx(20.0), \
            "same payload, gate flipped by permit state"

    def test_receipt_blocked_without_any_permit(self, api):
        """PRD 3.3: "while a required permit is not `ACTIVE`, the gated operation
        fails with `ERR_PERMIT_NOT_ACTIVE` (HTTP 422) — inventory receipts require an
        `ACTIVE` `FERTILIZER_STORAGE` permit."

        Design: Difficulty/cross_entity_state_dependency/inventory_receipt_requires_active_storage_permit
        """
        urea = create_product("UREA 46-0-0", 46, 0, 0)
        resp = api.receive_inventory_lot(
            {"product_id": urea["id"], "warehouse_code": "WH-A", "received_tons": 20, "lot_cost_cents_per_ton": 40000},
            PLANT)
        validate_error(resp, ApiErrorId.ERR_PERMIT_NOT_ACTIVE)


class TestStorageCapacity:
    def test_storage_capacity_aggregate_boundary(self, api):
        """PRD 3.3: "Storage capacity is enforced at receipt: after the receipt, the
        sum of `on_hand_tons` across all lots must not exceed the `ACTIVE`
        `FERTILIZER_STORAGE` permit's `max_storage_tons` — exact equality is
        admitted, any excess is rejected with `ERR_STORAGE_CAPACITY_EXCEEDED`
        (HTTP 422)."

        Design: Corner/validations/storage_capacity_aggregate_boundary
        """
        urea = create_product("UREA 46-0-0", 46, 0, 0)
        active_permit("FERTILIZER_STORAGE", max_storage_tons=25)

        lot1 = receive_lot(urea["id"], 20, warehouse_code="WH-A")
        lot2 = receive_lot(urea["id"], 5, warehouse_code="WH-B")
        assert lot1["id"] and lot2["id"], "aggregate 25.000 == cap: equality ADMITTED"

        resp = api.receive_inventory_lot(
            {"product_id": urea["id"], "warehouse_code": "WH-C", "received_tons": 0.001, "lot_cost_cents_per_ton": 40000},
            PLANT)
        validate_error(resp, ApiErrorId.ERR_STORAGE_CAPACITY_EXCEEDED)


class TestPermitRevokeCascade:
    def _scheduled_ctx(self, api):
        ctx = setup_booked_order(
            legal_name="Revoke Test Farms",
            products=[UREA_SPEC], prices={"UREA 46-0-0": 52000},
            lots={"UREA 46-0-0": 20}, with_blender=True,
            lines=UREA_LINE)
        batch = get_success_data(api.create_batch(
            ctx["order"]["id"],
            create_batch_payload(blender_id=ctx["blender"]["id"],
                                 scheduled_start="2026-08-05T08:00:00Z",
                                 scheduled_end="2026-08-05T09:00:00Z"),
            PLANT))
        ctx["batch"] = batch
        return ctx

    def test_revoke_cascades_blender_batch_order(self, api):
        """PRD 3.3: "Revocation cascades three hops. First, every `Blender` whose
        `site_code` matches the revoked permit's `site_code` and whose `status` is
        `ACTIVE` goes `OUT_OF_SERVICE`. Second, every `BlendBatch` assigned to one of
        those blenders and still `SCHEDULED` is `VOIDED` with `void_reason` set to
        `PERMIT_REVOKED`. Third, each blend order whose batch was just voided reverts
        its `fulfillment_status` from `SCHEDULED` to `BOOKED`, releasing the blender
        window."

        Design: Difficulty/transitive_cascade/permit_revoke_blender_batch_cascade
        """
        ctx = self._scheduled_ctx(api)
        get_success_data(api.revoke_permit(ctx["blender_permit"]["id"], COMPLIANCE,
                                           payload={"reason": "setback violation found"}))

        blender = get_success_data(api.get_blender(ctx["blender"]["id"], PLANT))
        assert blender["status"] == "OUT_OF_SERVICE", "hop 1: site blender taken down"

        batch = get_success_data(api.get_batch(ctx["batch"]["id"], PLANT))
        assert batch["status"] == "VOIDED", "hop 2: scheduled batch voided"
        assert batch["void_reason"] == "PERMIT_REVOKED"

        order = get_success_data(api.get_blend_order(ctx["order"]["id"], CREDIT))
        assert order["fulfillment_status"] == "BOOKED", "hop 3: order reverted"
        assert order["payment_status"] == "CREDIT_APPROVED", "payment dim untouched"

        pos = validate_success(api.get_inventory_position(ctx["products"]["UREA 46-0-0"]["id"], PLANT))
        assert pos["reserved_tons"] == pytest.approx(8.703, abs=1e-9), \
            "reservation survives the cascade; only the schedule unwound"
        assert pos["available_tons"] == pytest.approx(11.297, abs=1e-9)

    def test_revoke_void_reason_is_permit_revoked(self, api):
        """PRD 3.3: "Second, every `BlendBatch` assigned to one of those blenders and
        still `SCHEDULED` is `VOIDED` with `void_reason` set to `PERMIT_REVOKED`."

        Design: Difficulty/transitive_cascade/permit_revoke_blender_batch_cascade
        """
        ctx = self._scheduled_ctx(api)
        get_success_data(api.revoke_permit(ctx["blender_permit"]["id"], COMPLIANCE))
        batch = get_success_data(api.get_batch(ctx["batch"]["id"], PLANT))
        assert batch["status"] == "VOIDED"
        assert batch["void_reason"] == "PERMIT_REVOKED"


class TestPermitSafetyVsTemporalPriority:
    def test_permit_not_active_beats_window_conflict(self, api):
        """PRD 2.7: "and then the business rules in their own documented order: the
        grower-orderable gate, equipment-availability gates, nutrient-plan presence,
        nitrogen cap, phosphorus restriction, permit gates, storage capacity,
        price-window overlap, blender-window conflicts, funding deadlines,
        current-price availability, recommendation expiry, formulation feasibility,
        batch variance, truck capacity, duplicate routes, inventory sufficiency,
        blender form coverage, and finally the referential and fiscal checks."
        PRD 3.5: "an `ACTIVE` `BLENDER_SITE` permit must exist for the blender's
        `site_code` — otherwise `ERR_PERMIT_NOT_ACTIVE`."

        Design: Difficulty/priority_pair_validation_conflict/permit_safety_beats_blender_temporal_on_schedule
        """
        # Blender permit expires 2026-08-10; batch1 scheduled while permit ACTIVE
        ctx = setup_booked_order(
            legal_name="Dual Fail Farms",
            products=[UREA_SPEC], prices={"UREA 46-0-0": 52000},
            lots={"UREA 46-0-0": 20}, with_blender=True,
            blender_permit_expires="2026-08-10T00:00:00Z",
            lines=UREA_LINE)
        get_success_data(api.create_batch(
            ctx["order"]["id"],
            create_batch_payload(blender_id=ctx["blender"]["id"],
                                 scheduled_start="2026-08-05T08:00:00Z",
                                 scheduled_end="2026-08-05T10:00:00Z"),
            PLANT))
        # Move the clock past the permit expiry (lazy EXPIRED)
        get_success_data(api.set_clock({"to_iso8601": "2026-08-20T00:00:00Z"}, ADMIN))

        order2 = create_blend_order(
            ctx["grower"], ctx["field"]["id"], ctx["recommendation"]["id"], 50,
            [{"product_id": ctx["products"]["UREA 46-0-0"]["id"], "target_rate_lbs_per_acre": 100.0}])
        book_order(order2["id"], ctx["grower"])

        # Window 08:30-09:30 collides with batch1's buffered window AND permit is expired
        resp = api.create_batch(
            order2["id"],
            create_batch_payload(blender_id=ctx["blender"]["id"],
                                 scheduled_start="2026-08-05T08:30:00Z",
                                 scheduled_end="2026-08-05T09:30:00Z"),
            PLANT)
        validate_error(resp, ApiErrorId.ERR_PERMIT_NOT_ACTIVE)
        readback = get_success_data(api.get_blend_order(order2["id"], CREDIT))
        assert readback["fulfillment_status"] == "BOOKED", "no batch created"

    def test_expired_permit_blocks_batch_create_even_with_free_window(self, api):
        """PRD 3.3: "while a required permit is not `ACTIVE`, the gated operation
        fails with `ERR_PERMIT_NOT_ACTIVE` (HTTP 422) — ... and batch creation and
        batch start require an `ACTIVE` `BLENDER_SITE` permit for the blender's
        `site_code`."

        Design: Difficulty/priority_pair_validation_conflict/permit_safety_beats_blender_temporal_on_schedule
        """
        ctx = setup_booked_order(
            legal_name="Expired Permit Farms",
            products=[UREA_SPEC], prices={"UREA 46-0-0": 52000},
            lots={"UREA 46-0-0": 20}, with_blender=True,
            blender_permit_expires="2026-08-10T00:00:00Z",
            lines=UREA_LINE)
        get_success_data(api.set_clock({"to_iso8601": "2026-08-20T00:00:00Z"}, ADMIN))
        resp = api.create_batch(
            ctx["order"]["id"],
            create_batch_payload(blender_id=ctx["blender"]["id"],
                                 scheduled_start="2026-09-05T08:00:00Z",
                                 scheduled_end="2026-09-05T09:00:00Z"),
            PLANT)
        validate_error(resp, ApiErrorId.ERR_PERMIT_NOT_ACTIVE)


class TestPriceWindowOverlap:
    def test_half_open_window_semantics(self, api):
        """PRD 3.4: "the new window must not intersect any other `PUBLISHED` sheet of
        the same product under half-open intersection — that is, the new window's
        start earlier than the existing window's end while the new window's end is
        later than the existing window's start. Touching windows, where one sheet's
        `effective_to` equals the other's `effective_from`, are admitted; anything
        overlapping is rejected with `ERR_PRICE_WINDOW_OVERLAP` (HTTP 409)."

        Design: Difficulty/resource_temporal_overlap/price_sheet_half_open_window_semantics
        """
        urea = create_product("UREA 46-0-0", 46, 0, 0)
        # Windows sit after the default logical clock (2026-08-01) so lazy expiry
        # cannot retire them mid-test.
        published_price_sheet(urea["id"], 52000, season="IN_SEASON",
                              effective_from="2026-09-01T00:00:00Z",
                              effective_to="2026-11-01T00:00:00Z")

        # touching: 2026-11-01 == sheet1.effective_to -> admitted
        sheet2 = published_price_sheet(urea["id"], 53000, season="SPRING",
                                       effective_from="2026-11-01T00:00:00Z",
                                       effective_to="2027-02-01T00:00:00Z")
        assert sheet2["status"] == "PUBLISHED"

        # interior overlap 2026-10-15..12-01 intersects both published windows
        sheet3 = get_success_data(api.create_price_sheet(urea["id"], {
            "season": "SPRING", "price_per_ton_cents": 54000,
            "effective_from": "2026-10-15T00:00:00Z", "effective_to": "2026-12-01T00:00:00Z",
        }, ADMIN))
        resp = api.publish_price_sheet(sheet3["id"], ADMIN)
        validate_error(resp, ApiErrorId.ERR_PRICE_WINDOW_OVERLAP)
        readback = get_success_data(api.get_price_sheet(sheet3["id"], ADMIN))
        assert readback["status"] == "DRAFT", "rejected publish left no state change"

    def test_touching_window_admitted(self, api):
        """PRD 3.4: "Touching windows, where one sheet's `effective_to` equals the
        other's `effective_from`, are admitted."

        Design: Difficulty/resource_temporal_overlap/price_sheet_half_open_window_semantics
        """
        urea = create_product("UREA 46-0-0", 46, 0, 0)
        published_price_sheet(urea["id"], 52000, season="FALL",
                              effective_from="2026-01-01T00:00:00Z",
                              effective_to="2026-03-01T00:00:00Z")
        sheet2 = published_price_sheet(urea["id"], 53000, season="SPRING",
                                       effective_from="2026-03-01T00:00:00Z",
                                       effective_to="2026-06-01T00:00:00Z")
        assert sheet2["status"] == "PUBLISHED"

    def test_expired_sheet_terminal_lockdown(self, api):
        """PRD 3.4: "A `PUBLISHED` sheet may be manually expired (`→ EXPIRED`) by a
        branch admin."
        PRD 3.5: "Any transition fired from an ineligible state is
        `ERR_INVALID_TRANSITION`."

        Design: Corner/state_machines/price_sheet_expired_terminal_lockdown
        """
        urea = create_product("UREA 46-0-0", 46, 0, 0)
        sheet = published_price_sheet(urea["id"], 52000)
        get_success_data(api.expire_price_sheet(sheet["id"], ADMIN))
        resp = api.publish_price_sheet(sheet["id"], ADMIN)
        validate_error(resp, ApiErrorId.ERR_INVALID_TRANSITION)


class TestInventoryPositionAndFIFO:
    def test_position_computed_after_receipt(self, api):
        """PRD 3.4: "The lot's `on_hand_tons` initializes to `received_tons`,
        `reserved_tons` and `shipped_tons` start at zero."
        PRD 3.4: "A product-level inventory position read aggregates each product's
        lots into `product_id`, `on_hand_tons`, `reserved_tons`, `available_tons`,
        and `shipped_tons`, where per-lot available tonnage is `on_hand_tons` minus
        `reserved_tons` and the product figures are the sums across its lots."

        Design: Corner/entities/inventory_position_computed_after_receipt
        """
        urea = create_product("UREA 46-0-0", 46, 0, 0)
        active_permit("FERTILIZER_STORAGE")
        receive_lot(urea["id"], 20)

        pos = validate_success(api.get_inventory_position(urea["id"], PLANT))
        assert pos["on_hand_tons"] == pytest.approx(20.0)
        assert pos["reserved_tons"] == pytest.approx(0.0)
        assert pos["available_tons"] == pytest.approx(20.0)
        assert pos["shipped_tons"] == pytest.approx(0.0)

    def test_fifo_lot_reservation_chronological(self, api):
        """PRD 3.5: "A successful booking reserves inventory FIFO: for each line, the
        system walks the product's lots ordered by `received_at` ascending with
        `created_at` ascending as tie-break, taking from each lot the lesser of the
        remaining need and the lot's available tonnage until the line's
        `quantity_tons` is fully allocated, adding each allocation to that lot's
        `reserved_tons`."

        Design: Corner/calculations/fifo_lot_reservation_chronological
        """
        ctx = setup_order_pipeline(
            legal_name="FIFO Farms",
            products=[UREA_SPEC], prices={"UREA 46-0-0": 52000},
            lots={"UREA 46-0-0": [5]},  # older 5 t lot at the default clock
        )
        # Advance the clock, then receive the newer 30 t lot
        get_success_data(api.set_clock({"to_iso8601": "2026-08-02T00:00:00Z"}, ADMIN))
        lot_b = receive_lot(ctx["products"]["UREA 46-0-0"]["id"], 30, warehouse_code="WH-B")
        lot_a_data, _ = validate_paginated(api.list_inventory_lots(PLANT, params={"product_id": ctx["products"]["UREA 46-0-0"]["id"]}))
        lot_a = next(l for l in lot_a_data if l["received_tons"] == pytest.approx(5.0))

        order = create_blend_order(
            ctx["grower"], ctx["field"]["id"], ctx["recommendation"]["id"], 50,
            [{"product_id": ctx["products"]["UREA 46-0-0"]["id"], "target_rate_lbs_per_acre": 348.1}])
        book_order(order["id"], ctx["grower"])

        lot_a_read = get_success_data(api.get_inventory_lot(lot_a["id"], PLANT))
        lot_b_read = get_success_data(api.get_inventory_lot(lot_b["id"], PLANT))
        assert lot_a_read["reserved_tons"] == pytest.approx(5.0), "oldest lot exhausted first"
        assert lot_b_read["reserved_tons"] == pytest.approx(3.703, abs=1e-9), \
            "remainder spills to the newer lot"


class TestInventoryConservation:
    def test_reserve_release_conservation(self, api):
        """PRD 3.5: "A successful booking reserves inventory FIFO... adding each
        allocation to that lot's `reserved_tons`."
        PRD 3.5: "Cancellation is available from `QUOTED`, `BOOKED`, or `SCHEDULED`...
        from `BOOKED` it additionally releases all lot reservations."

        Design: Difficulty/compensating_invariant/inventory_reserve_release_conservation
        """
        ctx = setup_order_pipeline(
            legal_name="Conserve Tons Farms",
            products=[UREA_SPEC], prices={"UREA 46-0-0": 52000},
            lots={"UREA 46-0-0": 20},
            lines=UREA_LINE)
        pid = ctx["products"]["UREA 46-0-0"]["id"]
        pre = validate_success(api.get_inventory_position(pid, PLANT))
        assert pre["on_hand_tons"] == pytest.approx(20.0)
        assert pre["reserved_tons"] == pytest.approx(0.0)
        assert pre["shipped_tons"] == pytest.approx(0.0)

        book_order(ctx["order"]["id"], ctx["grower"])
        mid = validate_success(api.get_inventory_position(pid, PLANT))
        assert mid["on_hand_tons"] == pytest.approx(20.0), "forward action: reservation only"
        assert mid["reserved_tons"] == pytest.approx(8.703, abs=1e-9)
        assert mid["available_tons"] == pytest.approx(11.297, abs=1e-9)

        get_success_data(api.cancel_blend_order(ctx["order"]["id"], grower_headers(ctx["grower"]),
                                                payload={"reason": "grower postponed"}))
        post = validate_success(api.get_inventory_position(pid, PLANT))
        assert post["on_hand_tons"] == pytest.approx(20.0)
        assert post["reserved_tons"] == pytest.approx(0.0)
        assert post["available_tons"] == pytest.approx(20.0)
        assert post["shipped_tons"] == pytest.approx(0.0), \
            "compensating cancel restores exactly"

        for probe in (pre, mid, post):
            assert abs(20.0 - (probe["on_hand_tons"] + probe["shipped_tons"])) < 0.0005, \
                "received(20.000) == on_hand + shipped at every probe"

    def test_cancel_restores_available_exactly(self, api):
        """PRD 3.5: "from `BOOKED` it additionally releases all lot reservations."
        PRD 3.4: "per-lot available tonnage is `on_hand_tons` minus `reserved_tons`."

        Design: Difficulty/compensating_invariant/inventory_reserve_release_conservation
        """
        ctx = setup_booked_order(
            legal_name="Conserve Tons Farms 2",
            products=[UREA_SPEC], prices={"UREA 46-0-0": 52000},
            lots={"UREA 46-0-0": 20},
            lines=UREA_LINE)
        pid = ctx["products"]["UREA 46-0-0"]["id"]
        get_success_data(api.cancel_blend_order(ctx["order"]["id"], grower_headers(ctx["grower"])))
        pos = validate_success(api.get_inventory_position(pid, PLANT))
        assert pos["available_tons"] == pytest.approx(20.0)
        assert pos["reserved_tons"] == pytest.approx(0.0)


class TestInventoryLotFilter:
    def test_lots_filtered_by_product(self, api):
        """PRD 2.3: "Several list endpoints accept additional filter parameters (for
        example ..., `product_id`, ...); these are named alongside the relevant list
        endpoints in §4 and constrain the returned collection to matching records."

        Design: Corner/endpoints/inventory_lots_filtered_by_product
        """
        urea = create_product("UREA 46-0-0", 46, 0, 0)
        mop = create_product("MOP 0-0-60", 0, 0, 60)
        active_permit("FERTILIZER_STORAGE")
        receive_lot(urea["id"], 10)
        receive_lot(mop["id"], 10, lot_cost_cents_per_ton=36000)

        data, meta = validate_paginated(api.list_inventory_lots(PLANT, params={"product_id": urea["id"]}))
        assert meta["total_count"] == 1
        assert all(lot["product_id"] == urea["id"] for lot in data)
