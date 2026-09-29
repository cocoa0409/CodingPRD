"""Consistency breadth: one short receipt with a damaged split, whose own response body already
carries the post-cascade plan counters, and whose lot, listing, seller ledger and quota row are
already updated on the very next read — nothing deferred to a sweep or to a billing run."""
from test_helpers import (
    api_client,
    read_listing,
    read_lot,
    read_seller,
    setup_partially_received_plan,
    validate_paginated,
)


class TestReceiveResponseAlreadyCarriesTheCascade:
    """100 declared, 80 received of which 30 damaged: an 80/30 lot and a 20-unit shortfall."""

    def _short_receipt_with_a_damaged_split(self) -> dict:
        return setup_partially_received_plan(
            declared_units=100, received_units=80, unfulfillable_units=30
        )

    def test_the_receive_response_body_itself_shows_the_fork_and_the_shortfall(self):
        """No follow-up read is needed to learn the outcome: the mutating call returns the plan
        already sitting in PARTIALLY_RECEIVED with its counters settled.

        PRD 2.2: "Unless otherwise noted, operations that create or modify a resource will return
        the created or updated resource object in the data field."
        PRD 3.5: "**When the cumulative total is strictly below `declared_units`**, the plan lands
        in `PARTIALLY_RECEIVED` and a four-link cascade fires."

        Design: Corner/consistency_model/receive_response_already_reflects_the_whole_cascade
        """
        ctx = self._short_receipt_with_a_damaged_split()
        receipt = ctx["receipt"]
        assert receipt["status"] == "PARTIALLY_RECEIVED"
        assert receipt["received_units"] == 80
        assert receipt["missing_units"] == 20

    def test_the_lot_and_the_listing_are_already_updated_on_the_next_read(self):
        """The very next reads show both pools credited, the whole receipt in
        `units_received_total`, the shortfall recorded and the discrepancy already open.

        PRD 3.5: "Crediting a line adds its `received_units` to the lot's `fulfillable_units`,
        adds its `unfulfillable_units` to the lot's `unfulfillable_units`, and adds both
        quantities to the lot's `units_received_total`."
        PRD 2.7: "Derived fields are not caches that may lag. Whenever a lot pool changes, the
        owning listing's rollups and the owning seller's aggregate ledgers are recomputed inside
        the same request, and each such recomputation is a mutation of the affected resource: it
        refreshes that resource's `updated_at` and increments its `version`."

        Design: Corner/consistency_model/receive_response_already_reflects_the_whole_cascade
        """
        ctx = self._short_receipt_with_a_damaged_split()
        lot = read_lot(ctx["lot_id"], ctx["seller_id"])
        assert lot["fulfillable_units"] == 80
        assert lot["unfulfillable_units"] == 30
        assert lot["units_received_total"] == 110
        assert lot["missing_units"] == 20
        assert lot["reconciliation_status"] == "DISCREPANCY_OPEN"

        listing = read_listing(ctx["listing_id"], ctx["seller_id"])
        assert listing["fulfillable_units"] == 80
        assert listing["unfulfillable_units"] == 30
        assert listing["missing_units"] == 20
        assert listing["inventory_health"] == "HEALTHY"
        assert listing["lot_ever_created"] is True

    def test_the_seller_ledger_and_the_quota_row_need_no_second_call_and_no_sweep(self):
        """The seller's discrepancy ledger and the re-scored quota period are both already
        current, and repeating every read returns identical values.

        PRD 3.5: "The fourth link, caused by the second link's change to the seller's
        `open_discrepancy_units`, is quota re-scoring: the inventory performance score is re-run
        on the seller's active quota period, which may lower `iprs_score`, `base_capacity_tier`,
        `capacity_tier` and `restock_limit_units`, and may set `seller_status` to `SUSPENDED`."
        PRD 2.7: "Cascades propagate in the order given by the workflow that triggered them, and
        every link of a cascade is part of the same atomic request — either all of it lands or
        none of it does."

        Design: Corner/consistency_model/receive_response_already_reflects_the_whole_cascade
        """
        ctx = self._short_receipt_with_a_damaged_split()
        assert read_seller(ctx["seller_id"])["open_discrepancy_units"] == 20

        rows, meta = validate_paginated(
            api_client.list_restock_quotas(ctx["seller_id"], ctx["seller_headers"])
        )
        assert meta["total_count"] == 1
        assert rows[0]["id"] == ctx["quota_id"]
        assert rows[0]["iprs_score"] == 1000
        assert rows[0]["capacity_tier"] == "TIER_ELEVATED"
        assert rows[0]["restock_limit_units"] == 3000

        assert read_lot(ctx["lot_id"], ctx["seller_id"]) == read_lot(
            ctx["lot_id"], ctx["seller_id"]
        )
        assert read_listing(ctx["listing_id"], ctx["seller_id"]) == read_listing(
            ctx["listing_id"], ctx["seller_id"]
        )
        assert read_seller(ctx["seller_id"])["open_discrepancy_units"] == 20
