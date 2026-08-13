"""Recall events: activation cascade and disposition-gated completion."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    activate_recall,
    create_allocated_order,
    declare_recall,
    dispose_pallet,
    get_lot,
    get_order,
    get_recall,
    get_success_data,
    list_lot_pallets,
    list_order_allocations,
    setup_stocked_account,
    validate_error,
)

QUALITY = TEST_USERS["quality_manager_headers"]


class TestRecallActivateCascade:
    def _setup_recall_with_allocated_order(self):
        sc = setup_stocked_account(customer_name="Rec Co", zone_code="FZ-10",
                                   pallets=3)
        order = create_allocated_order(sc["customer"]["id"], 2)
        recall = declare_recall(sc["customer"]["id"], product_code="PEAS",
                                lot_code="L1", reason="listeria swab positive")
        return sc, order, recall

    def test_activate_recalls_every_present_pallet(self, api):
        """PRD §3.7: "Activation — `DECLARED` → `ACTIVE` — executes the recall
        cascade. Every pallet of the recalled lot standing at `STORED`,
        `ALLOCATED`, or `IN_BLAST_FREEZE` moves to quality `RECALLED`, and a
        pallet that was `ALLOCATED` first releases its allocation and returns to
        `STORED` before the recall mark lands."
        PRD §3.7: "Finally, the lot itself is marked `RECALLED`."

        Design: Difficulty/transitive_cascade/recall_activate_three_hop_cascade
        """
        sc, _order, recall = self._setup_recall_with_allocated_order()
        activated = activate_recall(recall["id"])
        assert activated["status"] == "ACTIVE"
        for pallet in list_lot_pallets(sc["lot_id"]):
            assert pallet["quality"] == "RECALLED", (
                "all 3 pallets recalled, including the 2 that were ALLOCATED")
            assert pallet["status"] == "STORED", (
                "allocated pallets return to STORED as the mark lands")
        assert get_lot(sc["lot_id"])["status"] == "RECALLED"

    def test_activate_releases_allocations_and_demotes_order(self, api):
        """PRD §3.7: "Released allocations move to `RELEASED`, and each order that
        owned one demotes from `ALLOCATED` to `SUBMITTED`."

        Design: Difficulty/transitive_cascade/recall_activate_three_hop_cascade
        """
        sc, order, recall = self._setup_recall_with_allocated_order()
        activate_recall(recall["id"])
        allocations = list_order_allocations(order["id"])
        assert len(allocations) == 2
        assert all(a["status"] == "RELEASED" for a in allocations)
        after = get_order(order["id"])
        assert after["status"] == "SUBMITTED", "demoted from ALLOCATED"
        assert after["allocated_pallets"] == 0


class TestRecallCompletion:
    def test_complete_blocked_until_recalled_stock_dispositioned(self, api):
        """PRD §3.7: "Completion — `ACTIVE` → `COMPLETED` — is allowed only once
        the recalled stock is gone: if any pallet of the lot is still present
        with quality `RECALLED`, completion is rejected with
        `ERR_RECALL_HAS_UNDISPOSITIONED_STOCK`."
        PRD §3.3: "Otherwise, if `on_hand_pallets` has fallen to zero and at least
        one pallet was ever created for the lot, the lot is `DEPLETED`."

        Design: Corner/validations/recall_complete_blocked_by_undispositioned_stock
        """
        sc = setup_stocked_account(customer_name="Rec2 Co", zone_code="FZ-R2",
                                   capacity_pallets=5, pallets=2)
        recall = declare_recall(sc["customer"]["id"], product_code="PEAS",
                                lot_code="L1", reason="salmonella")
        activate_recall(recall["id"])
        early = api.complete_recall(recall["id"], QUALITY)
        validate_error(early, ApiErrorId.ERR_RECALL_HAS_UNDISPOSITIONED_STOCK,
                       expected_status=409)
        assert get_recall(recall["id"])["status"] == "ACTIVE"

        for pallet in list_lot_pallets(sc["lot_id"]):
            dispose_pallet(pallet["id"])
        completed = get_success_data(api.complete_recall(recall["id"], QUALITY))
        assert completed["status"] == "COMPLETED"
        assert get_lot(sc["lot_id"])["status"] == "DEPLETED", (
            "all pallets disposed: on_hand 0 with pallets ever created")
