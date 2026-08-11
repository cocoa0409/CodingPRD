"""Sale/void revert loops and the compensating invariants of PRD §2.10."""
import pytest

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    book_and_check_in,
    checkout_transaction,
    close_intake,
    create_event,
    create_item_for,
    create_slot,
    drop_off_item,
    get_consignor,
    get_event,
    get_item,
    get_transaction,
    inspect_pass,
    open_intake,
    open_transaction,
    register_consignor,
    register_volunteer,
    scan_barcode,
    setup_item_on_floor,
    start_presale,
    start_sale,
    validate_paginated,
    validate_success,
)

ORGANIZER = TEST_USERS["organizer_headers"]
CASHIER = TEST_USERS["cashier_headers"]


class TestItemBranchingWithSaleVoidRevert:

    def test_sold_item_reverts_to_on_floor_on_void(self, api, organizer_headers):
        """PRD §3.8: "Voiding a `COMPLETED` transaction is an organizer-only compensation — a cashier attempting it is rejected with `ERR_FORBIDDEN` — and is permitted only in `PRESALE_DAY` or `SALE_ACTIVE`."
        PRD §3.8: "The stronger void returns every line item `SOLD` → `ON_FLOOR`, decrements the consignors' sold counters and gross back down, recomputes the affected `DRAFT` settlements' provisional fields, recomputes the event's `sold_gross_cents`, and retains the line rows for audit."

        Design: Difficulty/non_linear_state_machine/item_branching_with_sale_void_revert
        """
        ctx = setup_item_on_floor(price_cents=1000, consignor_name="Eve",
                                  item_overrides={"title": "Doll"})
        tx = open_transaction(ctx["event"]["id"])
        scan_barcode(tx["id"], ctx["barcode"])
        checkout_transaction(tx["id"], 1000)
        assert get_item(ctx["item"]["id"])["status"] == "SOLD"
        assert get_consignor(ctx["consignor"]["id"])["sold_gross_cents"] == 1000

        voided = validate_success(api.void_transaction(tx["id"], organizer_headers))
        assert voided["status"] == "VOIDED"
        assert get_item(ctx["item"]["id"])["status"] == "ON_FLOOR", (
            "The void revert branch must return the item to ON_FLOOR"
        )
        assert get_consignor(ctx["consignor"]["id"])["sold_gross_cents"] == 0, (
            "The compensation must decrement the consignor's gross back to 0"
        )

    def test_item_rescannable_and_resold_after_void(self, api, organizer_headers):
        """PRD §3.8: "The barcode must resolve to an item of the transaction's own event, or the scan is rejected with `ERR_BARCODE_NOT_FOUND`, and the item must currently be `ON_FLOOR`, or the scan fails with `ERR_ITEM_NOT_ON_FLOOR`."
        PRD §3.8: "Checkout and completed-void form the compensating pair that conserves event gross."

        Design: Difficulty/non_linear_state_machine/item_branching_with_sale_void_revert
        """
        ctx = setup_item_on_floor(price_cents=1000, consignor_name="Eve",
                                  item_overrides={"title": "Doll"})
        tx1 = open_transaction(ctx["event"]["id"])
        scan_barcode(tx1["id"], ctx["barcode"])
        checkout_transaction(tx1["id"], 1000)
        validate_success(api.void_transaction(tx1["id"], organizer_headers))

        # The revert loop closes: the same barcode can be scanned and sold again.
        tx2 = open_transaction(ctx["event"]["id"])
        scan_barcode(tx2["id"], ctx["barcode"])
        completed2 = checkout_transaction(tx2["id"], 1000)

        assert get_transaction(tx1["id"])["status"] == "VOIDED"
        assert completed2["status"] == "COMPLETED"
        assert get_item(ctx["item"]["id"])["status"] == "SOLD"
        assert get_consignor(ctx["consignor"]["id"])["sold_gross_cents"] == 1000


class TestCheckoutVoidConservesEventGross:

    def test_checkout_sets_event_and_consignor_gross(self, api, organizer_headers):
        """PRD §2.10: "the event's `sold_gross_cents` always equals the sum of `total_cents` over the event's `COMPLETED` transactions, and always equals the sum of `sold_gross_cents` over the event's consignors — checkout adds a transaction's total and voiding a completed transaction subtracts it, a compensating pair that leaves the conserved quantity consistent."

        Design: Difficulty/compensating_invariant/checkout_void_conserves_event_gross
        """
        ctx = setup_item_on_floor(price_cents=2000, consignor_name="Val",
                                  item_overrides={"title": "Game"})
        tx = open_transaction(ctx["event"]["id"])
        scan_barcode(tx["id"], ctx["barcode"])
        checkout_transaction(tx["id"], 2000)

        event = get_event(ctx["event"]["id"])
        consignor = get_consignor(ctx["consignor"]["id"])
        assert event["sold_gross_cents"] == 2000, (
            "Checkout adds the transaction's total to the event's sold_gross_cents"
        )
        assert consignor["sold_gross_cents"] == 2000
        assert event["sold_gross_cents"] == consignor["sold_gross_cents"], (
            "Money invariant: event gross equals the sum of consignor grosses"
        )

    def test_void_of_completed_restores_zero_gross(self, api, organizer_headers):
        """PRD §2.10: "checkout adds a transaction's total and voiding a completed transaction subtracts it, a compensating pair that leaves the conserved quantity consistent."
        PRD §3.8: "The stronger void returns every line item `SOLD` → `ON_FLOOR`, decrements the consignors' sold counters and gross back down, recomputes the affected `DRAFT` settlements' provisional fields, recomputes the event's `sold_gross_cents`, and retains the line rows for audit."

        Design: Difficulty/compensating_invariant/checkout_void_conserves_event_gross
        """
        ctx = setup_item_on_floor(price_cents=2000, consignor_name="Val",
                                  item_overrides={"title": "Game"})
        tx = open_transaction(ctx["event"]["id"])
        scan_barcode(tx["id"], ctx["barcode"])
        checkout_transaction(tx["id"], 2000)
        validate_success(api.void_transaction(tx["id"], organizer_headers))

        event = get_event(ctx["event"]["id"])
        consignor = get_consignor(ctx["consignor"]["id"])
        assert event["sold_gross_cents"] == 0, (
            "The compensating pair must leave the event's gross unchanged (0 == 0)"
        )
        assert consignor["sold_gross_cents"] == 0
        assert get_item(ctx["item"]["id"])["status"] == "ON_FLOOR"


class TestScanRemoveConservesSellableCount:

    def _two_item_world(self, api):
        """Event in SALE_ACTIVE; consignor Wes has two items ON_FLOOR; an OPEN
        transaction exists."""
        event = create_event()
        open_intake(event["id"])
        wes = register_consignor(event["id"], "Wes")
        slot = create_slot(event["id"])
        book_and_check_in(slot["id"], wes["id"])
        it1 = create_item_for(wes["id"], price_cents=500, title="Toy A")
        it2 = create_item_for(wes["id"], price_cents=600, title="Toy B")
        drop_off_item(it1["id"], wes["id"])
        drop_off_item(it2["id"], wes["id"])
        inspector = register_volunteer(event["id"], "Insp Ira")
        inspect_pass(it1["id"], inspector["id"])
        inspect_pass(it2["id"], inspector["id"])
        close_intake(event["id"])
        start_presale(event["id"])
        start_sale(event["id"])
        tx = open_transaction(event["id"])
        return event, wes, it1, it2, tx

    def _sellable_counts(self, api, event_id):
        """Counts of the event's items in ON_FLOOR / IN_CART / SOLD."""
        counts = {}
        for status in ("ON_FLOOR", "IN_CART", "SOLD"):
            _rows, meta = validate_paginated(
                api.list_items(ORGANIZER, params={"sale_event_id": event_id,
                                                  "status": status})
            )
            counts[status] = meta["total_count"]
        return counts

    def test_scan_moves_item_to_in_cart_conserving_sellable_count(self, api):
        """PRD §2.10: "the sellable-inventory invariant: the count of the event's items in `ON_FLOOR`, `IN_CART`, or `SOLD` status changes only through real business events; scanning an item (`ON_FLOOR` → `IN_CART`) and removing the line (`IN_CART` → `ON_FLOOR`) leave the count unchanged, as do checkout and the void of a completed transaction."

        Design: Difficulty/compensating_invariant/scan_remove_conserves_sellable_count
        """
        event, _wes, it1, _it2, tx = self._two_item_world(api)
        scan_barcode(tx["id"], it1["barcode"])

        counts = self._sellable_counts(api, event["id"])
        assert counts["ON_FLOOR"] == 1
        assert counts["IN_CART"] == 1
        assert counts["ON_FLOOR"] + counts["IN_CART"] + counts["SOLD"] == 2, (
            "Scan (ON_FLOOR -> IN_CART) must leave the sellable count unchanged"
        )

    def test_line_removal_restores_on_floor_conserving_sellable_count(self, api, cashier_headers):
        """PRD §3.8: "Removing a line — addressed by its `lineId` within the transaction — is the compensating twin of a scan: permitted while the ticket is `OPEN`, it deletes the line row, returns the item from `IN_CART` to `ON_FLOOR`, and recomputes the totals, leaving the sellable-inventory count unchanged."
        PRD §2.10: "No item transition ever creates or destroys an item row: after creation, the total item count per event is constant."

        Design: Difficulty/compensating_invariant/scan_remove_conserves_sellable_count
        """
        event, _wes, it1, _it2, tx = self._two_item_world(api)
        line = scan_barcode(tx["id"], it1["barcode"])

        validate_success(api.delete_line(tx["id"], line["id"], cashier_headers))

        counts = self._sellable_counts(api, event["id"])
        assert counts["ON_FLOOR"] == 2
        assert counts["IN_CART"] == 0, (
            "Scan + line removal is a compensating pair with no count drift"
        )
        assert get_item(it1["id"])["status"] == "ON_FLOOR"
