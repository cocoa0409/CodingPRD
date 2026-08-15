"""Shipment booking gates (production, PSI, compliance), document handover
ordering, quantity bounds, shipment cancel compensation, and the document
expiry cascade."""
from test_helpers import (
    ApiErrorId,
    advance_to_production_complete,
    book_and_pass_psi,
    book_inspection,
    book_shipment,
    confirm_receipt,
    create_shipment_payload,
    get_compliance_document,
    get_factory,
    get_purchase_order,
    get_shipment,
    handover_documents,
    make_buyer_manager_headers,
    make_factory_rep_headers,
    make_inspector_headers,
    make_sourcing_agent_headers,
    record_result,
    set_clock,
    setup_po_scenario,
    validate_error,
    validate_success,
)


def _po_ready_to_ship(ordered_qty=10, docs_expires_at="2027-06-01T00:00:00Z"):
    """PO with production complete and a passing PSI — ready to ship."""
    ctx = setup_po_scenario(ordered_qty=ordered_qty, unit_price_cents=100,
                            with_inspector=True, docs_expires_at=docs_expires_at)
    advance_to_production_complete(ctx)
    book_and_pass_psi(ctx, lot_size=ordered_qty)
    ctx["po"] = get_purchase_order(ctx["po"]["id"])
    return ctx


class TestShipmentPsiGate:
    def _po_with_failed_psi(self):
        ctx = setup_po_scenario(ordered_qty=10, unit_price_cents=100,
                                with_inspector=True)
        advance_to_production_complete(ctx)
        failed = book_inspection(ctx["po"]["id"], ctx["agent"]["id"],
                                 ctx["inspector"]["id"], inspection_type="PSI",
                                 scheduled_date="2026-08-10", duration_days=1,
                                 lot_size=10)
        record_result(failed["id"], ctx["inspector"]["id"],
                      defects_critical=0, defects_major=4, defects_minor=0)
        return ctx

    def test_shipment_rejected_when_latest_psi_failed(self, api):
        """PRD: "Booking enforces three readiness gates in §2.12 order: the factory must be `ACTIVE` (`ERR_FACTORY_SUSPENDED`); the PO's `ship_blocked` must be false (`ERR_FACTORY_NOT_COMPLIANT`); `production_status` must be `PRODUCTION_COMPLETE` (`ERR_PO_NOT_READY_FOR_PSI`); and `latest_psi_result` must be `PASSED` (`ERR_NO_PASSING_PSI`)."

        Design: Difficulty/cross_entity_state_dependency/shipment_gated_by_latest_psi_result
        """
        ctx = self._po_with_failed_psi()
        assert get_purchase_order(ctx["po"]["id"])["latest_psi_result"] == "FAILED"
        validate_error(
            api.create_shipment(
                ctx["po"]["id"], create_shipment_payload(shipped_qty=10),
                make_sourcing_agent_headers(ctx["agent"]["id"]),
            ),
            ApiErrorId.ERR_NO_PASSING_PSI,
        )

    def test_shipment_allowed_after_passing_reinspection(self, api):
        """PRD: "When the inspection is a `PSI`, the PO's `latest_psi_result` is rewritten to this result; the field always reflects the latest `RESULT_RECORDED` PSI by `updated_at` descending, tie-broken by `created_at` descending."
        PRD: "a booking that drives `open_qty` to zero advances the PO to `SHIPPED` directly (or from `PARTIALLY_SHIPPED` to `SHIPPED`)"

        Design: Difficulty/cross_entity_state_dependency/shipment_gated_by_latest_psi_result
        """
        ctx = self._po_with_failed_psi()
        passed = book_inspection(ctx["po"]["id"], ctx["agent"]["id"],
                                 ctx["inspector"]["id"], inspection_type="PSI",
                                 scheduled_date="2026-08-12", duration_days=1,
                                 lot_size=10)
        record_result(passed["id"], ctx["inspector"]["id"],
                      defects_critical=0, defects_major=2, defects_minor=1)
        assert get_purchase_order(ctx["po"]["id"])["latest_psi_result"] == "PASSED"

        shipment = book_shipment(ctx["po"]["id"], ctx["agent"]["id"], 10, "V2")
        assert shipment["status"] == "BOOKED"
        po = get_purchase_order(ctx["po"]["id"])
        assert po["status"] == "SHIPPED"
        assert po["open_qty"] == 0


class TestDocumentExpiryCascade:
    def test_clock_sweep_expires_document_and_flips_posture(self, api):
        """PRD: "Advancing the clock triggers two sweeps: every `VERIFIED` `ComplianceDocument` whose `expires_at` is strictly earlier than the new clock value transitions to `EXPIRED` (with the compliance-posture cascade described in §2.9)"
        PRD: "Every time the posture flips, the platform rewrites `ship_blocked` on every one of the factory's live POs: `ship_blocked` becomes true when the posture flips to `NON_COMPLIANT`, false when it flips back to `COMPLIANT`."

        Design: Difficulty/transitive_cascade/document_expiry_cascade_blocks_shipment
        """
        ctx = _po_ready_to_ship(docs_expires_at="2026-08-15T00:00:00Z")
        set_clock("2026-08-16T00:00:00Z")
        for doc in ctx["docs"]:
            assert get_compliance_document(doc["id"])["status"] == "EXPIRED"
        factory = get_factory(ctx["factory"]["id"])
        assert factory["compliance_posture"] == "NON_COMPLIANT"
        po = get_purchase_order(ctx["po"]["id"])
        assert po["ship_blocked"] is True

    def test_shipment_booking_blocked_after_posture_flip(self, api):
        """PRD: "Advancing the logical clock past a document's `expires_at` sweeps it from `VERIFIED` to `EXPIRED`, recomputes posture, and — if the posture flips to `NON_COMPLIANT` — sets `ship_blocked` to true on every live PO of the factory."
        PRD: "the PO's `ship_blocked` must be false (`ERR_FACTORY_NOT_COMPLIANT`)"

        Design: Difficulty/transitive_cascade/document_expiry_cascade_blocks_shipment
        """
        ctx = _po_ready_to_ship(docs_expires_at="2026-08-15T00:00:00Z")
        set_clock("2026-08-16T00:00:00Z")
        validate_error(
            api.create_shipment(
                ctx["po"]["id"], create_shipment_payload(shipped_qty=10),
                make_sourcing_agent_headers(ctx["agent"]["id"]),
            ),
            ApiErrorId.ERR_FACTORY_NOT_COMPLIANT,
        )


class TestShipmentStateMachine:
    def test_shipment_skip_handover_to_confirm_rejected(self, api):
        """PRD: "The shipment must be `BOOKED` and the caller must belong to the PO's factory. Handover advances the shipment from `BOOKED` to `DOCS_HANDED_OVER` and flips `po.document_status` from `PENDING` to `HANDED_OVER` on the first such handover."
        PRD: "The buyer confirms receipt of a handed-over shipment; the shipment must be `DOCS_HANDED_OVER` (`ERR_SHIPMENT_STATE_INVALID` otherwise) and the caller must own the PO's `buyer_id`."

        Design: Corner/state_machines/shipment_skip_handover_to_confirm_rejected
        """
        ctx = _po_ready_to_ship()
        shipment = book_shipment(ctx["po"]["id"], ctx["agent"]["id"], 10, "V1")

        validate_error(
            api.confirm_shipment_receipt(
                shipment["id"], make_buyer_manager_headers(ctx["buyer"]["id"])
            ),
            ApiErrorId.ERR_SHIPMENT_STATE_INVALID,
        )
        handed = handover_documents(shipment["id"], ctx["factory"]["id"])
        assert handed["status"] == "DOCS_HANDED_OVER"
        validate_error(
            api.handover_shipment_documents(
                shipment["id"], {"doc_refs": ["BL-1b"]},
                make_factory_rep_headers(ctx["factory"]["id"]),
            ),
            ApiErrorId.ERR_SHIPMENT_STATE_INVALID,
        )
        assert get_purchase_order(ctx["po"]["id"])["document_status"] == "HANDED_OVER"

    def test_ship_qty_zero_and_over_open_rejected(self, api):
        """PRD: "`shipped_qty` must be at least 1 and at most the PO's current `open_qty` (`ERR_SHIP_QTY_INVALID`, HTTP 422)."

        Design: Corner/validations/ship_qty_zero_and_over_open_rejected
        """
        ctx = _po_ready_to_ship()
        for bad_qty in (0, 11):
            validate_error(
                api.create_shipment(
                    ctx["po"]["id"], create_shipment_payload(shipped_qty=bad_qty),
                    make_sourcing_agent_headers(ctx["agent"]["id"]),
                ),
                ApiErrorId.ERR_SHIP_QTY_INVALID,
            )
        po = get_purchase_order(ctx["po"]["id"])
        assert po["shipped_qty"] == 0
        assert po["status"] == "ACTIVE"

    def test_cascading_shipment_cancel_reverts_po_status(self, api):
        """PRD: "Cancellation subtracts the shipment's `shipped_qty` from `po.shipped_qty` and recomputes `open_qty`; if the PO had been `PARTIALLY_SHIPPED` and this cancellation removes its last live shipment, the PO reverts from `PARTIALLY_SHIPPED` back to `ACTIVE`."

        Design: Corner/cross_cutting_layers/cascading_shipment_cancel_reverts_po_status
        """
        ctx = _po_ready_to_ship()
        shipment = book_shipment(ctx["po"]["id"], ctx["agent"]["id"], 4, "V4")
        assert get_purchase_order(ctx["po"]["id"])["status"] == "PARTIALLY_SHIPPED"

        cancelled = validate_success(
            api.cancel_shipment(
                shipment["id"], make_sourcing_agent_headers(ctx["agent"]["id"])
            )
        )
        assert cancelled["status"] == "CANCELLED"
        po = get_purchase_order(ctx["po"]["id"])
        assert po["shipped_qty"] == 0
        assert po["open_qty"] == 10
        assert po["status"] == "ACTIVE"
