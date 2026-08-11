"""Recalls, quarantine, and the expiry sweep: lot quality cycles, the
four-hop recall cascade, recall-gated release, and clock-driven expiry."""
from test_helpers import (
    ApiErrorId,
    get_lot,
    get_order,
    get_order_lines,
    get_line_reservations,
    get_success_data,
    make_agreement,
    make_customer,
    make_lot,
    make_product,
    make_recall,
    make_warehouse,
    make_zone,
    setup_cold_chain_order,
    validate_error,
    validate_success,
)
from test_helpers import TEST_USERS

OPS = TEST_USERS["ops_admin_headers"]
CATALOG = TEST_USERS["catalog_manager_headers"]
CLERK = TEST_USERS["inventory_clerk_headers"]
QUALITY = TEST_USERS["quality_manager_headers"]
ACCOUNTS = TEST_USERS["account_manager_headers"]


class TestQuarantineCycle:
    def _setup_lot(self, api):
        warehouse = make_warehouse(api)
        zone = make_zone(api, warehouse["id"], zone_class="AMBIENT", capacity_units=500)
        product = make_product(api, sku="CH-105", name="Buffer Salt", unit_price_cents=105)
        lot = make_lot(api, product["id"], warehouse["id"], zone["id"], quantity_received=20)
        return lot

    def test_lot_quarantine_release_cycle_states(self, api):
        """PRD §3.2: "Quarantining moves a lot from `AVAILABLE` to `QUARANTINED` (a lot in any other state yields `ERR_LOT_NOT_AVAILABLE`) and fires the release cascade:"
        PRD §3.2: "Releasing quarantine returns the lot from `QUARANTINED` to `AVAILABLE`, but only while no `ISSUED` recall covers it — otherwise the attempt is rejected with `ERR_RECALL_ACTIVE_FOR_LOT` — and only from `QUARANTINED` (`ERR_LOT_NOT_QUARANTINED`)."

        Design: Difficulty/non_linear_state_machine/lot_quarantine_release_cycle
        """
        lot = self._setup_lot(api)
        quarantined = validate_success(api.quarantine_lot(lot["id"], QUALITY), 200)
        assert quarantined["status"] == "QUARANTINED"

        released = validate_success(api.release_lot_quarantine(lot["id"], QUALITY), 200)
        assert released["status"] == "AVAILABLE", (
            "with no ISSUED recall covering the lot the full cycle is legal"
        )

    def test_lot_quarantine_release_cycle_versions_and_quantities(self, api):
        """PRD §2.4: "`version` (integer): a system-managed integer that increments by exactly 1 on every mutation of the resource, including system-driven state transitions applied by cascades."
        PRD §2.11: "Each reconciliation independently mutates every resource it touches: the resource's own state fields change, its `updated_at` refreshes, and its `version` increments by 1."

        Design: Difficulty/non_linear_state_machine/lot_quarantine_release_cycle
        """
        lot = self._setup_lot(api)
        assert lot["version"] == 1

        quarantined = validate_success(api.quarantine_lot(lot["id"], QUALITY), 200)
        assert quarantined["version"] == 2
        released = validate_success(api.release_lot_quarantine(lot["id"], QUALITY), 200)
        assert released["version"] == 3

        # With no HELD reservations the cascade moves no units.
        assert quarantined["quantity_on_hand"] == 20
        assert released["quantity_on_hand"] == 20
        assert released["quantity_reserved"] == 0

    def test_lot_release_quarantine_from_available_rejected(self, api):
        """PRD §3.2: "Releasing quarantine returns the lot from `QUARANTINED` to `AVAILABLE`, but only while no `ISSUED` recall covers it — otherwise the attempt is rejected with `ERR_RECALL_ACTIVE_FOR_LOT` — and only from `QUARANTINED` (`ERR_LOT_NOT_QUARANTINED`)."

        Design: Corner/state_machines/lot_release_quarantine_from_available_rejected
        """
        lot = self._setup_lot(api)
        resp = api.release_lot_quarantine(lot["id"], QUALITY)
        validate_error(resp, ApiErrorId.ERR_LOT_NOT_QUARANTINED)
        after = get_lot(api, lot["id"])
        assert after["status"] == "AVAILABLE"
        assert after["quantity_on_hand"] == 20, "the rejected release touches no quantities"


class TestReleaseBlockedByRecall:
    def _setup_recalled_lot(self, api):
        warehouse = make_warehouse(api)
        zone = make_zone(api, warehouse["id"], zone_class="AMBIENT", capacity_units=500)
        product = make_product(api, sku="CH-105", name="Buffer Salt", unit_price_cents=105)
        lot = make_lot(api, product["id"], warehouse["id"], zone["id"], quantity_received=10)
        assert lot["lot_sequence_number"] == 1
        recall = make_recall(
            api,
            product_id=product["id"],
            scope_type="LOT_RANGE",
            scope_lot_seq_min=1,
            scope_lot_seq_max=1,
            severity_class="CLASS_III",
            reason="Label defect",
        )
        get_success_data(api.issue_recall(recall["id"], QUALITY))
        return lot, recall

    def test_lot_release_blocked_by_issued_recall_error(self, api):
        """PRD §3.2: "Releasing quarantine returns the lot from `QUARANTINED` to `AVAILABLE`, but only while no `ISSUED` recall covers it — otherwise the attempt is rejected with `ERR_RECALL_ACTIVE_FOR_LOT` — and only from `QUARANTINED` (`ERR_LOT_NOT_QUARANTINED`)."
        PRD §3.7: "While a recall is `ISSUED`, its covered products are poison to new business: order submission, kit activation, and consignment consumption referencing such a product are rejected with `ERR_PRODUCT_UNDER_RECALL`, and releasing quarantine on a covered lot is rejected with `ERR_RECALL_ACTIVE_FOR_LOT`."

        Design: Difficulty/cross_entity_state_dependency/lot_release_blocked_by_issued_recall
        """
        lot, _recall = self._setup_recalled_lot(api)
        assert get_lot(api, lot["id"])["status"] == "QUARANTINED"
        resp = api.release_lot_quarantine(lot["id"], QUALITY)
        validate_error(resp, ApiErrorId.ERR_RECALL_ACTIVE_FOR_LOT)

    def test_lot_release_blocked_by_issued_recall_lot_unchanged(self, api):
        """PRD §3.7: "First, every lot of the product matching the scope (sequence number between the bounds inclusive for `LOT_RANGE`; all lots for `PRODUCT_ALL`) whose status is `AVAILABLE` or `QUARANTINED` is forced into `QUARANTINED` — available lots transition, quarantined lots remain — and stamped with the recall's id in `recall_id`."
        PRD §3.2: "A lot carries the `recall_id` of an issued recall that covers it from issuance until that recall closes and clears the reference."

        Design: Difficulty/cross_entity_state_dependency/lot_release_blocked_by_issued_recall
        """
        lot, recall = self._setup_recalled_lot(api)
        resp = api.release_lot_quarantine(lot["id"], QUALITY)
        validate_error(resp, ApiErrorId.ERR_RECALL_ACTIVE_FOR_LOT)
        after = get_lot(api, lot["id"])
        assert after["status"] == "QUARANTINED"
        assert after["recall_id"] == recall["id"], (
            "the covering recall reference persists while the recall is ISSUED"
        )


class TestRecallIssueCascade:
    def _setup_allocated_with_recall(self, api):
        # quantity 5 of a 10-unit lot: the lot keeps 5 on hand and stays
        # AVAILABLE, so the PRD §3.7 hop-1 filter (AVAILABLE or QUARANTINED
        # lots) covers it when the recall issues.
        ctx = setup_cold_chain_order(api, quantity=5, lot_quantity=10)
        line = get_order_lines(api, ctx["order"]["id"])[0]
        reservation = get_line_reservations(api, line["id"])[0]
        assert reservation["quantity"] == 5
        recall = make_recall(
            api,
            product_id=ctx["product"]["id"],
            scope_type="LOT_RANGE",
            scope_lot_seq_min=1,
            scope_lot_seq_max=1,
            severity_class="CLASS_II",
            reason="Impurity detected",
        )
        return ctx, line, reservation, recall

    def test_recall_issue_cascade_lot_and_reservation(self, api):
        """PRD §3.7: "Issuance — permitted only from `DRAFT` (`ERR_RECALL_NOT_DRAFT`) — fires a four-hop cascade. First, every lot of the product matching the scope (sequence number between the bounds inclusive for `LOT_RANGE`; all lots for `PRODUCT_ALL`) whose status is `AVAILABLE` or `QUARANTINED` is forced into `QUARANTINED` — available lots transition, quarantined lots remain — and stamped with the recall's id in `recall_id`. Second, every `HELD` reservation on those lots transitions to `RELEASED` with quantity compensation back to its lot."

        Design: Difficulty/transitive_cascade/recall_issue_cascade_depth4
        """
        ctx, _line, reservation, recall = self._setup_allocated_with_recall(api)
        get_success_data(api.issue_recall(recall["id"], QUALITY))

        lot = get_lot(api, ctx["lot"]["id"])
        assert lot["status"] == "QUARANTINED", "hop 1: the covered lot quarantines"
        assert lot["recall_id"] == recall["id"]
        res = validate_success(api.get_reservation(reservation["id"], OPS), 200)
        assert res["status"] == "RELEASED", "hop 2: the HELD reservation releases"
        assert lot["quantity_on_hand"] == 10 and lot["quantity_reserved"] == 0, (
            "quantity compensation returns the 5 reserved units, restoring the lot to 10"
        )

    def test_recall_issue_cascade_line_order_and_product(self, api):
        """PRD §3.7: "Third, each affected order line recomputes its `allocated_quantity` and demotes to `PENDING` when the recomputed amount reaches zero. Fourth, each affected order in `ALLOCATED` demotes to `BACKORDERED`. When the scope is `PRODUCT_ALL`, the product itself additionally moves from `LISTED` to `UNDER_RECALL`."

        Design: Difficulty/transitive_cascade/recall_issue_cascade_depth4
        """
        ctx, line, _reservation, recall = self._setup_allocated_with_recall(api)
        get_success_data(api.issue_recall(recall["id"], QUALITY))

        line_after = get_order_lines(api, ctx["order"]["id"])[0]
        assert line_after["id"] == line["id"]
        assert line_after["status"] == "PENDING", "hop 3: the line demotes at zero"
        assert line_after["allocated_quantity"] == 0
        assert get_order(api, ctx["order"]["id"])["status"] == "BACKORDERED", "hop 4"
        product = validate_success(api.get_product(ctx["product"]["id"], OPS), 200)
        assert product["status"] == "LISTED", (
            "a LOT_RANGE scope does not flip the product to UNDER_RECALL"
        )


class TestRecallCloseGuard:
    def test_recall_close_from_draft_rejected(self, api):
        """PRD §3.7: "Closing the recall performs the lot pull. It is permitted only from `ISSUED` (`ERR_RECALL_NOT_CLOSABLE`), and only once every covered lot sits `QUARANTINED` with `quantity_reserved` at exactly zero — a lot still holding reserved quantity blocks the close with `ERR_RECALL_LOTS_PENDING`."

        Design: Corner/state_machines/recall_close_from_draft_rejected
        """
        product = make_product(api, sku="CH-105", name="Buffer Salt", unit_price_cents=105)
        recall = make_recall(api, product_id=product["id"], scope_type="PRODUCT_ALL")
        resp = api.close_recall(recall["id"], QUALITY)
        validate_error(resp, ApiErrorId.ERR_RECALL_NOT_CLOSABLE)
        after = validate_success(api.get_recall(recall["id"], QUALITY), 200)
        assert after["status"] == "DRAFT"


class TestSafetyBeatsFiscal:
    def _setup_recalled_agreement(self, api):
        warehouse = make_warehouse(api)
        product = make_product(api, sku="CS-500", name="Consigned Stain", unit_price_cents=500)
        customer = make_customer(api, name="Lab Kappa")
        agreement = make_agreement(
            api,
            customer_id=customer["id"],
            product_id=product["id"],
            ceiling_quantity=10,
            reorder_point=0,
            contract_unit_price_cents=500,
            replenishment_warehouse_id=warehouse["id"],
            initial_stocked_quantity=10,
            effective_from="2026-05-01",
            effective_until="2027-05-01",
        )
        get_success_data(api.record_consumption(agreement["id"], {"quantity": 6}, ACCOUNTS))
        recall = make_recall(
            api,
            product_id=product["id"],
            scope_type="PRODUCT_ALL",
            severity_class="CLASS_I",
            reason="Contamination",
        )
        get_success_data(api.issue_recall(recall["id"], QUALITY))
        return agreement

    def test_safety_beats_fiscal_on_recalled_consumption_error(self, api):
        """PRD §3.8: "Three business checks guard it in order after the generic chain: the product must not be covered by an `ISSUED` recall (`ERR_PRODUCT_UNDER_RECALL`); the record may not push `consumed_quantity` above the `ceiling_quantity` (`ERR_CONSIGNMENT_CEILING_EXCEEDED`); and the quantity may not exceed the on-hand at customer — `stocked_quantity` minus `consumed_quantity` (`ERR_CONSUMPTION_EXCEEDS_STOCK`)."

        Design: Difficulty/priority_pair_validation_conflict/safety_beats_fiscal_on_recalled_consumption
        """
        agreement = self._setup_recalled_agreement(api)
        # consumed 6 + quantity 5 = 11 would breach ceiling 10 — but the recall
        # check is stated first and must mask the fiscal one.
        resp = api.record_consumption(agreement["id"], {"quantity": 5}, ACCOUNTS)
        validate_error(resp, ApiErrorId.ERR_PRODUCT_UNDER_RECALL)

    def test_safety_beats_fiscal_on_recalled_consumption_no_partial_posting(self, api):
        """PRD §3.8: "Three business checks guard it in order after the generic chain: the product must not be covered by an `ISSUED` recall (`ERR_PRODUCT_UNDER_RECALL`);"
        PRD §3.8: "The charge posts to the customer's `outstanding_balance_cents` and the agreement's `consumed_quantity` grows by the quantity."

        Design: Difficulty/priority_pair_validation_conflict/safety_beats_fiscal_on_recalled_consumption
        """
        agreement = self._setup_recalled_agreement(api)
        resp = api.record_consumption(agreement["id"], {"quantity": 5}, ACCOUNTS)
        validate_error(resp, ApiErrorId.ERR_PRODUCT_UNDER_RECALL)
        after = validate_success(api.get_agreement(agreement["id"], ACCOUNTS), 200)
        assert after["consumed_quantity"] == 6, (
            "a rejected record posts nothing — consumed stays at its pre-call value"
        )


class TestExpirySweep:
    def test_lot_expiry_sweep_at_clock_boundary(self, api):
        """PRD §3.2: "A lot is expired when the logical clock's current date is strictly after its `expiry_date`; on the expiry date itself the lot remains usable."
        PRD §2.5: "Setting the clock performs two sweeps in its wake: every lot whose `expiry_date` falls before the new current date transitions to `EXPIRED` with the reservation-release cascade described in §3.2, and the standing-order run generation described in §3.8 executes. The capability responds with the new `current_utc` plus three counters: `lots_expired`, `standing_orders_run`, and `orders_generated`."

        Design: Corner/calculations/lot_expiry_sweep_at_clock_boundary
        """
        warehouse = make_warehouse(api)
        zone = make_zone(
            api, warehouse["id"], zone_class="REFRIGERATED_2_8", capacity_units=100
        )
        product = make_product(
            api, sku="RG-100", name="Enzyme Mix", storage_requirement="REFRIGERATED_2_8",
            unit_price_cents=20000, requires_cold_chain=True, shelf_life_days=60,
        )
        lot = make_lot(api, product["id"], warehouse["id"], zone["id"],
                       quantity_received=20, manufacture_date="2026-04-01")
        assert lot["expiry_date"] == "2026-05-31"

        on_the_day = validate_success(
            api.set_clock({"to_iso8601": "2026-05-31T12:00:00Z"}, OPS), 200
        )
        assert on_the_day["lots_expired"] == 0
        assert get_lot(api, lot["id"])["status"] == "AVAILABLE", (
            "the expiry date itself is still usable"
        )

        day_after = validate_success(
            api.set_clock({"to_iso8601": "2026-06-01T00:00:00Z"}, OPS), 200
        )
        assert day_after["lots_expired"] == 1
        assert get_lot(api, lot["id"])["status"] == "EXPIRED", (
            "strictly-after semantics: the day after expiry sweeps the lot"
        )
