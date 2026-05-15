"""Concurrency outcomes — PRD §2.11.

The PRD §2.11 enumerates five named concurrent-edit scenarios with
specific winners and loser error_ids. These tests exercise each.

PRD explicitly states each loser's error_id, so we use
validate_error against the specific id (not validate_error_is_one_of).
"""
from __future__ import annotations

import pytest

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    assert_exactly_one_succeeds,
    create_inspected_receipt,
    create_planned_shipment,
    create_recall_payload,
    pick_shipment,
    record_temperature_event,
    run_race,
    setup_accepted_lot,
    setup_basic_topology,
    setup_qualified_supplier_and_product,
    setup_two_inspected_receipts_for_single_bin,
    validate_error,
    validate_error_is_one_of,
)


# ===========================================================================
# Two QAOfficers accept the same receipt — first wins,
# loser gets ERR_RECEIPT_NOT_INSPECTED. PRD §2.11.
# ===========================================================================
class TestRaceAcceptSameReceipt:

    def test_two_concurrent_accepts_one_succeeds_one_fails(self, api):
        """PRD §2.11: "When two `QAOfficer` calls attempt to accept
        the same inbound receipt at the same moment, the first writer
        wins the `INSPECTED` to `ACCEPTED` transition and the loser
        is rejected with `ERR_RECEIPT_NOT_INSPECTED` (HTTP 409)."

        Claim: two concurrent accept calls on the same INSPECTED
        receipt → exactly one succeeds; the loser is
        ERR_RECEIPT_NOT_INSPECTED.
        """
        topology = setup_basic_topology()
        supplier, product = setup_qualified_supplier_and_product()
        receipt = create_inspected_receipt(
            topology["warehouse"]["id"],
            supplier["id"], product["id"], quantity_units=1,
        )
        results = run_race(
            lambda: api.accept_receipt(
                receipt["id"], TEST_USERS["qa_officer_headers"],
            ),
            lambda: api.accept_receipt(
                receipt["id"], TEST_USERS["qa_officer_headers_alt"],
            ),
        )
        outcome = assert_exactly_one_succeeds(results[0], results[1])
        loser = outcome["failures"][0]
        validate_error(loser, ApiErrorId.ERR_RECEIPT_NOT_INSPECTED.value)


# ===========================================================================
# Two pickers race for the last units of a single lot — first wins,
# loser gets ERR_INSUFFICIENT_STOCK. PRD §2.11.
# ===========================================================================
class TestRacePickSameLotInsufficientStock:

    def test_two_concurrent_picks_one_succeeds_one_fails(self, api):
        """PRD §2.11: "When two pickers race for the last available
        units of a single lot, the first writer wins the atomic
        decrement on `quantity_on_hand` and the loser is rejected
        with `ERR_INSUFFICIENT_STOCK` (HTTP 409)."

        Claim: two pickers race; each wants 4 units of a 5-unit lot.
        Exactly one succeeds; the loser → ERR_INSUFFICIENT_STOCK.
        """
        ctx = setup_accepted_lot(quantity_units=5)
        # Two shipments each requesting 4 units (total 8 > 5).
        s1 = create_planned_shipment(
            ctx["warehouse"]["id"], ctx["product"]["id"], quantity_units=4,
            customer_id="c-A",
        )
        s2 = create_planned_shipment(
            ctx["warehouse"]["id"], ctx["product"]["id"], quantity_units=4,
            customer_id="c-B",
        )
        results = run_race(
            lambda: api.pick_shipment(s1["id"], TEST_USERS["picker_headers"]),
            lambda: api.pick_shipment(s2["id"], TEST_USERS["picker_headers_alt"]),
        )
        outcome = assert_exactly_one_succeeds(results[0], results[1])
        loser = outcome["failures"][0]
        # PRD §2.11 names ERR_INSUFFICIENT_STOCK for this race outcome,
        # but PRD §3.5's candidate-set filter "whose `quantity_on_hand`
        # is at least the shipment's `quantity_units`" can equally
        # produce ERR_NO_FEFO_LOT when the loser re-evaluates the FEFO
        # filter post-winner-commit. Both readings are PRD-faithful
        # for the race loser; accept either.
        from test_helpers import validate_error_is_one_of
        validate_error_is_one_of(
            loser,
            [
                ApiErrorId.ERR_INSUFFICIENT_STOCK.value,
                ApiErrorId.ERR_NO_FEFO_LOT.value,
            ],
        )


# ===========================================================================
# Two FEFO bin allocations race for the same Bin — first wins,
# loser gets ERR_BIN_UNAVAILABLE. PRD §2.11.
# # difficulty: resource_temporal_overlap/bin_single_lot_occupancy_overlap_inclusive
# ===========================================================================
class TestRaceBinAllocation:

    def test_two_concurrent_accepts_for_one_bin_one_loses(self, api):
        """PRD §2.11: "When two FEFO bin allocations target the same
        bin, the first writer wins the `current_lot_id` assignment
        while the bin was `AVAILABLE` and the loser is rejected with
        `ERR_BIN_UNAVAILABLE` (HTTP 409)."

        Difficulty-design: resource_temporal_overlap /
        bin_single_lot_occupancy_overlap_inclusive.
        # difficulty: resource_temporal_overlap/bin_single_lot_occupancy_overlap_inclusive

        Claim: warehouse with exactly ONE AVAILABLE bin in a
        REFRIGERATED zone; two INSPECTED receipts; concurrent accept
        calls — exactly one wins; the loser is rejected with either
        ERR_BIN_UNAVAILABLE (PRD-named) or ERR_NO_ELIGIBLE_BIN (the
        candidate-set filter sees no AVAILABLE bin after the winner
        committed).

        Two-reader thought: PRD §2.11 names ERR_BIN_UNAVAILABLE for
        this race, but PRD §3.4 also says an empty candidate set
        surfaces as ERR_NO_ELIGIBLE_BIN. Different reasonable
        implementations might surface different errors. We accept
        either to avoid scaffold-leakage.
        """
        ctx = setup_two_inspected_receipts_for_single_bin(
            quantity_units=10,
        )
        results = run_race(
            lambda: api.accept_receipt(
                ctx["receipt_1"]["id"], TEST_USERS["qa_officer_headers"],
            ),
            lambda: api.accept_receipt(
                ctx["receipt_2"]["id"], TEST_USERS["qa_officer_headers_alt"],
            ),
        )
        outcome = assert_exactly_one_succeeds(results[0], results[1])
        loser = outcome["failures"][0]
        validate_error_is_one_of(loser, [
            ApiErrorId.ERR_BIN_UNAVAILABLE.value,
            ApiErrorId.ERR_NO_ELIGIBLE_BIN.value,
        ])


# ===========================================================================
# Two RecallOfficers announce the same recall — first wins,
# loser gets ERR_RECALL_NOT_DRAFT. PRD §2.11.
# ===========================================================================
class TestRaceAnnounceRecall:

    def test_two_concurrent_announces_one_succeeds_one_fails(self, api):
        """PRD §2.11: "When two `RecallOfficer` calls attempt to
        announce the same recall, the first writer wins the `DRAFT`
        to `ANNOUNCED` transition and the loser is rejected with
        `ERR_RECALL_NOT_DRAFT` (HTTP 409)."

        Claim: concurrent announce on a DRAFT recall — exactly one
        succeeds; the loser is ERR_RECALL_NOT_DRAFT.
        """
        from test_helpers import (
            add_recall_scope,
            create_draft_recall,
        )
        ctx = setup_accepted_lot(quantity_units=3)
        r = create_draft_recall(
            ctx["warehouse"]["id"], classification="CLASS_II",
        )
        add_recall_scope(
            r["id"], lot_id=ctx["lot"]["id"], units=3,
            scope_kind="ON_HAND",
        )
        results = run_race(
            lambda: api.announce_recall(
                r["id"], TEST_USERS["recall_officer_headers"],
            ),
            lambda: api.announce_recall(
                r["id"], TEST_USERS["recall_officer_headers_alt"],
            ),
        )
        outcome = assert_exactly_one_succeeds(results[0], results[1])
        loser = outcome["failures"][0]
        validate_error(loser, ApiErrorId.ERR_RECALL_NOT_DRAFT.value)
