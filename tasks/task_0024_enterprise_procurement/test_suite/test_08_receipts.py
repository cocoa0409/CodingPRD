"""Goods receipt and acceptance (PRD §3.8)."""
from __future__ import annotations
import pytest

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    assert_receipt,
    create_receipt_payload,
    post_supplier_delivery,
    setup_executed_contract,
    setup_receipt_in_inspecting,
    setup_receipts_for_invoice,
    unique_delivery_note_no,
    validate_error,
    validate_success,
)


# ===========================================================================
# Inspect: delivery-note matching (PRD §3.8, §2.8 priority 12)
# ===========================================================================
class TestReceiptInspect:
    def test_inspect_with_unmatched_delivery_note_rejected(
        self, api, inspector_headers
    ):
        """PRD §3.8: "the receipt's delivery_note_no matches a delivery-note
        number recorded against the purchase order via the supplier-delivery
        synchronization — that is, an identical delivery_note_no was
        previously posted by the platform-admin supplier-delivery event
        for that same purchase_order_id. A mismatch — either no matching
        delivery-note record, or accepted_quantity greater than
        received_quantity — yields ERR_DELIVERY_NOTE_MISMATCH."

        Claim: inspecting a receipt whose delivery_note_no was never posted
        via /_events/supplier-delivery yields ERR_DELIVERY_NOTE_MISMATCH.
        """
        setup = setup_executed_contract(payment_terms_type="ON_DELIVERY")
        # Do NOT post a supplier-delivery event for this delivery_note_no.
        receipt = validate_success(
            api.create_receipt(
                setup["po"]["id"],
                create_receipt_payload(
                    delivery_note_no="UNRECORDED-DN",
                    received_quantity=10,
                    accepted_quantity=10,
                    quality_rating=90,
                ),
                inspector_headers,
            ),
            201,
        )
        res = api.inspect_receipt(receipt["id"], inspector_headers)
        validate_error(res, ApiErrorId.ERR_DELIVERY_NOTE_MISMATCH.value)

    def test_inspect_advances_to_inspecting(self, api, inspector_headers):
        """PRD §3.8: "The inspector advances the receipt to INSPECTING
        once it is being matched against a delivery-note record."

        Claim: with a matching delivery_note_no, /receipts/{id}/inspect
        moves the receipt to INSPECTING.
        """
        setup = setup_receipt_in_inspecting()
        assert setup["receipt"]["status"] == "INSPECTING"


# ===========================================================================
# Accept: full / partial / cumulative quantity check (PRD §3.8)
# ===========================================================================
class TestReceiptAccept:
    def test_full_acceptance_moves_to_accepted(self, api, inspector_headers):
        """PRD §3.8: "A full acceptance — accepted_quantity equal to
        received_quantity and quality_rating at least 60 — moves the
        receipt to ACCEPTED."

        Claim: accept on a fully-quantity-matching receipt with quality
        ≥ 60 yields status=ACCEPTED.
        """
        setup = setup_receipt_in_inspecting(
            received_quantity=10, accepted_quantity=10, quality_rating=90
        )
        accepted = validate_success(
            api.accept_receipt(setup["receipt"]["id"], inspector_headers), 200
        )
        assert accepted["status"] == "ACCEPTED"

    def test_partial_acceptance_moves_to_partially_accepted(
        self, api, inspector_headers
    ):
        """PRD §3.8: "A partial acceptance — accepted_quantity strictly
        greater than 0 and strictly less than received_quantity, with
        quality_rating at least 60 — moves the receipt to
        PARTIALLY_ACCEPTED."

        Claim: 0 < accepted < received with quality ≥ 60 yields
        status=PARTIALLY_ACCEPTED.
        """
        setup = setup_receipt_in_inspecting(
            received_quantity=10, accepted_quantity=4, quality_rating=85
        )
        partial = validate_success(
            api.accept_receipt(setup["receipt"]["id"], inspector_headers), 200
        )
        assert partial["status"] == "PARTIALLY_ACCEPTED"

    def test_quality_below_60_rejects(self, api, inspector_headers):
        """PRD §3.8: "The third outcome, rejection, applies when either
        accepted_quantity is 0 or the quality_rating is strictly less
        than 60; the receipt moves to REJECTED."

        Claim: quality_rating < 60 forces REJECTED via /reject.
        """
        setup = setup_receipt_in_inspecting(
            received_quantity=10, accepted_quantity=10, quality_rating=59
        )
        rejected = validate_success(
            api.reject_receipt(setup["receipt"]["id"], inspector_headers), 200
        )
        assert rejected["status"] == "REJECTED"

    def test_full_fulfilment_cascades_po_to_fulfilled(
        self, api, inspector_headers, buyer_headers
    ):
        """PRD §3.8: "When cumulative_accepted_after equals the
        requirement's quantity, the parent purchase order cascades from
        CONTRACTED to FULFILLED."

        Claim: a single full-acceptance receipt with quantity ==
        requirement.quantity flips PO from CONTRACTED to FULFILLED.
        """
        setup = setup_receipts_for_invoice(quantity=10, accepted_full=True)
        po = validate_success(
            api.get_purchase_order(setup["po"]["id"], buyer_headers), 200
        )
        assert po["status"] == "FULFILLED"

    def test_over_receipt_rejected(self, api, inspector_headers):
        """PRD §3.8: "if cumulative_accepted_after would exceed the
        requirement's quantity, the accept call is rejected with
        ERR_OVER_RECEIPT."

        Claim: a second receipt that would push the cumulative beyond
        Requirement.quantity yields ERR_OVER_RECEIPT.

        Setup: keep PO in CONTRACTED while staging the over-accept.
        First receipt is partial (5 of 10 accepted) so the PO does not
        cascade to FULFILLED. Then a second receipt of 6 more units —
        cumulative would be 11, exceeding requirement.quantity=10.
        """
        # Build CONTRACTED PO with quantity=10. First receipt accepts 5
        # partially → PO stays CONTRACTED at 5/10.
        setup = setup_receipt_in_inspecting(
            quantity=10,
            received_quantity=10,
            accepted_quantity=5,
            quality_rating=85,
        )
        validate_success(
            api.accept_receipt(setup["receipt"]["id"], inspector_headers), 200
        )
        # Now post a second supplier-delivery + receipt of 6 more units.
        delivery_note_no = unique_delivery_note_no()
        post_supplier_delivery(
            setup["po"]["id"], delivery_note_no=delivery_note_no, declared_quantity=6
        )
        r2 = validate_success(
            api.create_receipt(
                setup["po"]["id"],
                create_receipt_payload(
                    delivery_note_no=delivery_note_no,
                    received_quantity=6,
                    accepted_quantity=6,
                    quality_rating=90,
                ),
                inspector_headers,
            ),
            201,
        )
        validate_success(api.inspect_receipt(r2["id"], inspector_headers), 200)
        res = api.accept_receipt(r2["id"], inspector_headers)
        validate_error(res, ApiErrorId.ERR_OVER_RECEIPT.value)


# ===========================================================================
# Return path on REJECTED receipt (PRD §3.8)
# ===========================================================================
class TestReceiptReturn:
    def test_return_after_reject(self, api, inspector_headers):
        """PRD §3.8: "A rejected receipt may be returned to the supplier;
        this moves it from REJECTED to RETURNED and is the receipt's
        terminal step on the goods-rejection branch."

        Claim: /receipts/{id}/return on a REJECTED receipt advances it
        to RETURNED.
        """
        setup = setup_receipt_in_inspecting(
            received_quantity=10, accepted_quantity=10, quality_rating=59
        )
        validate_success(
            api.reject_receipt(setup["receipt"]["id"], inspector_headers), 200
        )
        ret = validate_success(
            api.return_receipt(setup["receipt"]["id"], inspector_headers), 200
        )
        assert ret["status"] == "RETURNED"


# ===========================================================================
# Supplier rating recompute (PRD §3.8)
# ===========================================================================
class TestSupplierRatingRecompute:
    def test_supplier_rating_avg_after_acceptance(
        self, api, buyer_headers, inspector_headers
    ):
        """PRD §3.8: "Both accepted and partially-accepted receipts also
        recompute the supplier's rating_avg: it is the sum of
        quality_rating over every receipt of this supplier whose status
        is ACCEPTED or PARTIALLY_ACCEPTED, divided by the count of those
        receipts, rounded half-up to two decimal places."

        Claim: after one ACCEPTED receipt with quality_rating=85, the
        supplier's rating_avg is 85.00.
        """
        setup = setup_receipts_for_invoice(quantity=10, accepted_full=True, quality_rating=85.0)
        supplier = validate_success(
            api.get_supplier(setup["po"]["supplier_id"], buyer_headers), 200
        )
        assert supplier["rating_avg"] == pytest.approx(85.00, abs=0.005)
