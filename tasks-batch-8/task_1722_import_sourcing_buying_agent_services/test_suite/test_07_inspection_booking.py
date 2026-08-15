"""Inspection booking gates: production-readiness, inspector half-open window
overlap, compliance-vs-overlap priority, result recording, and inspector
ownership."""
from test_helpers import (
    ApiErrorId,
    advance_to_production_complete,
    book_inspection,
    create_inspection_payload,
    create_inspector,
    create_milestone,
    get_factory,
    get_inspection,
    get_purchase_order,
    make_inspector_headers,
    make_sourcing_agent_headers,
    record_result,
    set_clock,
    setup_compliance_docs,
    setup_po_scenario,
    submit_milestone,
    upload_and_verify_doc,
    validate_error,
    validate_success,
    verify_milestone,
)


def _po_in_production():
    """PO with a locked FULL(100) plan submitted but not verified."""
    ctx = setup_po_scenario(ordered_qty=10, unit_price_cents=100, with_docs=True)
    milestone = create_milestone(ctx["po"]["id"], ctx["agent"]["id"],
                                 name="FULL", weight_pct=100)
    submit_milestone(milestone["id"], ctx["factory"]["id"])
    ctx["milestone"] = milestone
    return ctx


def _po_production_complete():
    ctx = setup_po_scenario(ordered_qty=10, unit_price_cents=100, with_docs=True,
                            with_inspector=True)
    advance_to_production_complete(ctx)
    return ctx


class TestProductionReadinessGates:
    def test_dupro_rejected_when_production_not_started(self, api):
        """PRD: "a `DUPRO` booking requires `production_status` `IN_PRODUCTION` (`ERR_PO_NOT_READY_FOR_DUPRO`); a `PSI` booking requires `production_status` `PRODUCTION_COMPLETE` (`ERR_PO_NOT_READY_FOR_PSI`)"

        Design: Corner/state_machines/dupro_rejected_when_production_not_started
        """
        ctx = setup_po_scenario(ordered_qty=10, unit_price_cents=100, with_docs=True,
                                with_inspector=True)
        # Plan created (locked) but never submitted: production_status PLACED.
        create_milestone(ctx["po"]["id"], ctx["agent"]["id"], name="FULL", weight_pct=100)
        validate_error(
            api.create_inspection(
                ctx["po"]["id"],
                create_inspection_payload(
                    inspector_id=ctx["inspector"]["id"], inspection_type="DUPRO",
                    scheduled_date="2026-08-05", duration_days=1, lot_size=10,
                ),
                make_sourcing_agent_headers(ctx["agent"]["id"]),
            ),
            ApiErrorId.ERR_PO_NOT_READY_FOR_DUPRO,
        )

    def test_psi_rejected_before_production_complete(self, api):
        """PRD: "a `DUPRO` booking requires `production_status` `IN_PRODUCTION` (`ERR_PO_NOT_READY_FOR_DUPRO`); a `PSI` booking requires `production_status` `PRODUCTION_COMPLETE` (`ERR_PO_NOT_READY_FOR_PSI`)"

        Design: Corner/state_machines/psi_rejected_before_production_complete
        """
        ctx = _po_in_production()
        inspector = create_inspector()
        validate_error(
            api.create_inspection(
                ctx["po"]["id"],
                create_inspection_payload(
                    inspector_id=inspector["id"], inspection_type="PSI",
                    scheduled_date="2026-08-05", duration_days=1, lot_size=10,
                ),
                make_sourcing_agent_headers(ctx["agent"]["id"]),
            ),
            ApiErrorId.ERR_PO_NOT_READY_FOR_PSI,
        )


class TestInspectorWindowOverlap:
    def test_inspector_overlapping_window_rejected(self, api):
        """PRD: "The inspection window is half-open — it covers `scheduled_date` up to but not including `scheduled_date + duration_days`."
        PRD: "the inspector must not already have a `BOOKED` (or otherwise live) inspection whose half-open window overlaps the requested one (`ERR_INSPECTION_WINDOW_CONFLICT`)"

        Design: Difficulty/resource_temporal_overlap/inspector_half_open_window_adjacency_vs_overlap
        """
        ctx = _po_in_production()
        inspector = create_inspector()
        book_inspection(ctx["po"]["id"], ctx["agent"]["id"], inspector["id"],
                        inspection_type="DUPRO", scheduled_date="2026-08-10",
                        duration_days=2, lot_size=10)
        validate_error(
            api.create_inspection(
                ctx["po"]["id"],
                create_inspection_payload(
                    inspector_id=inspector["id"], inspection_type="DUPRO",
                    scheduled_date="2026-08-11", duration_days=1, lot_size=10,
                ),
                make_sourcing_agent_headers(ctx["agent"]["id"]),
            ),
            ApiErrorId.ERR_INSPECTION_WINDOW_CONFLICT,
        )

    def test_inspector_adjacent_window_accepted(self, api):
        """PRD: "The inspection window is half-open — it covers `scheduled_date` up to but not including `scheduled_date + duration_days`."
        The existing window is [2026-08-10, 2026-08-12); a new booking starting
        2026-08-12 merely touches the open end and is accepted.

        Design: Difficulty/resource_temporal_overlap/inspector_half_open_window_adjacency_vs_overlap
        """
        ctx = _po_in_production()
        inspector = create_inspector()
        book_inspection(ctx["po"]["id"], ctx["agent"]["id"], inspector["id"],
                        inspection_type="DUPRO", scheduled_date="2026-08-10",
                        duration_days=2, lot_size=10)
        adjacent = validate_success(
            api.create_inspection(
                ctx["po"]["id"],
                create_inspection_payload(
                    inspector_id=inspector["id"], inspection_type="DUPRO",
                    scheduled_date="2026-08-12", duration_days=1, lot_size=10,
                ),
                make_sourcing_agent_headers(ctx["agent"]["id"]),
            ),
            expected_status=201,
        )
        assert adjacent["status"] == "BOOKED"


class TestSafetyBeatsOverlapPriority:
    @staticmethod
    def _cancel(api, inspection_id, agent_id):
        return api.cancel_inspection(
            inspection_id, make_sourcing_agent_headers(agent_id)
        )

    def _ship_blocked_with_overlapping_inspector(self, api, advance_clock):
        """PO whose inspector already holds [2026-08-20,+2d); when
        advance_clock is True the PRODUCT_TEST document has expired, flipping
        the factory NON_COMPLIANT and setting ship_blocked on the PO."""
        ctx = setup_po_scenario(ordered_qty=10, unit_price_cents=100, with_docs=False,
                                with_inspector=True)
        upload_and_verify_doc(ctx["factory"]["id"], ctx["agent"]["id"],
                              "SOCIAL_AUDIT", expires_at="2027-01-01T00:00:00Z")
        upload_and_verify_doc(ctx["factory"]["id"], ctx["agent"]["id"],
                              "PRODUCT_TEST", expires_at="2026-08-15T00:00:00Z")
        milestone = create_milestone(ctx["po"]["id"], ctx["agent"]["id"],
                                     name="FULL", weight_pct=100)
        submit_milestone(milestone["id"], ctx["factory"]["id"])
        # A cancelled booking frees the inspector's earlier window.
        dup1 = book_inspection(ctx["po"]["id"], ctx["agent"]["id"],
                               ctx["inspector"]["id"], inspection_type="DUPRO",
                               scheduled_date="2026-08-05", duration_days=1,
                               lot_size=10)
        validate_success(
            self._cancel(api, dup1["id"], ctx["agent"]["id"])
        )
        book_inspection(ctx["po"]["id"], ctx["agent"]["id"], ctx["inspector"]["id"],
                        inspection_type="DUPRO", scheduled_date="2026-08-20",
                        duration_days=2, lot_size=10)
        verify_milestone(milestone["id"], ctx["agent"]["id"])
        if advance_clock:
            set_clock("2026-08-16T00:00:00Z")
        return ctx

    def test_ship_blocked_po_booking_reports_compliance_not_window_conflict(self, api):
        """PRD §2.12: "**Compliance and factory-status gates** — shipment booking and inspection booking require `ship_blocked` false (`ERR_FACTORY_NOT_COMPLIANT`); quotation create/accept, shipment booking, and inspection booking require the factory `ACTIVE` (`ERR_FACTORY_SUSPENDED`)."
        PRD §2.12: "A later-priority failure is masked by any earlier-priority failure on the same request."
        The requested window also overlaps the inspector's live booking, but the
        priority-7 compliance failure masks the priority-9 structural one.

        Design: Difficulty/priority_pair_validation_conflict/inspection_booking_safety_beats_inspector_overlap_constraint
        """
        ctx = self._ship_blocked_with_overlapping_inspector(api, advance_clock=True)
        factory = get_factory(ctx["factory"]["id"])
        assert factory["compliance_posture"] == "NON_COMPLIANT"
        assert get_purchase_order(ctx["po"]["id"])["ship_blocked"] is True
        validate_error(
            api.create_inspection(
                ctx["po"]["id"],
                create_inspection_payload(
                    inspector_id=ctx["inspector"]["id"], inspection_type="PSI",
                    scheduled_date="2026-08-21", duration_days=1, lot_size=10,
                ),
                make_sourcing_agent_headers(ctx["agent"]["id"]),
            ),
            ApiErrorId.ERR_FACTORY_NOT_COMPLIANT,
        )

    def test_overlapping_window_reports_conflict_when_compliant(self, api):
        """PRD: "the inspector must not already have a `BOOKED` (or otherwise live) inspection whose half-open window overlaps the requested one (`ERR_INSPECTION_WINDOW_CONFLICT`)"
        With the compliance gate passing (documents unexpired), the same
        overlapping request surfaces the priority-9 structural error.

        Design: Difficulty/priority_pair_validation_conflict/inspection_booking_safety_beats_inspector_overlap_constraint
        """
        ctx = self._ship_blocked_with_overlapping_inspector(api, advance_clock=False)
        assert get_purchase_order(ctx["po"]["id"])["ship_blocked"] is False
        validate_error(
            api.create_inspection(
                ctx["po"]["id"],
                create_inspection_payload(
                    inspector_id=ctx["inspector"]["id"], inspection_type="PSI",
                    scheduled_date="2026-08-21", duration_days=1, lot_size=10,
                ),
                make_sourcing_agent_headers(ctx["agent"]["id"]),
            ),
            ApiErrorId.ERR_INSPECTION_WINDOW_CONFLICT,
        )


class TestResultRecording:
    def test_inspection_record_twice_rejected(self, api):
        """PRD: "The inspection must be `BOOKED` (`ERR_INSPECTION_NOT_RECORDABLE` otherwise) and the caller must be the inspection's `inspector_id`."

        Design: Corner/state_machines/inspection_record_twice_rejected
        """
        ctx = _po_production_complete()
        inspection = book_inspection(ctx["po"]["id"], ctx["agent"]["id"],
                                     ctx["inspector"]["id"], inspection_type="PSI",
                                     scheduled_date="2026-08-10", duration_days=1,
                                     lot_size=10)
        recorded = record_result(inspection["id"], ctx["inspector"]["id"],
                                 defects_critical=0, defects_major=1, defects_minor=1)
        assert recorded["status"] == "RESULT_RECORDED"
        assert recorded["result"] == "PASSED"

        validate_error(
            api.record_inspection_result(
                inspection["id"],
                {"defects_critical": 0, "defects_major": 0, "defects_minor": 0},
                make_inspector_headers(ctx["inspector"]["id"]),
            ),
            ApiErrorId.ERR_INSPECTION_NOT_RECORDABLE,
        )
        after = get_inspection(inspection["id"])
        assert after["result"] == "PASSED"
        assert after["defects_major"] == 1

    def test_rbac_inspector_cannot_record_others_inspection(self, api):
        """PRD: "`Inspector` — third-party inspector; records AQL results only on inspections assigned to that inspector."
        PRD: "Ownership scoping (`BuyerManager` checks `buyer_id`, `SourcingAgent` checks `assigned_agent_id`, `FactoryRep` checks `factory_id`, `Inspector` checks `inspector_id`) is enforced on every role-scoped write endpoint. A violation is rejected with `ERR_OWNERSHIP_SCOPE_VIOLATION` (HTTP 403)."

        Design: Corner/roles/rbac_inspector_cannot_record_others_inspection
        """
        ctx = _po_production_complete()
        other = create_inspector("Inspector Two", "CN-North")
        inspection = book_inspection(ctx["po"]["id"], ctx["agent"]["id"],
                                     ctx["inspector"]["id"], inspection_type="PSI",
                                     scheduled_date="2026-08-10", duration_days=1,
                                     lot_size=10)
        validate_error(
            api.record_inspection_result(
                inspection["id"],
                {"defects_critical": 0, "defects_major": 0, "defects_minor": 0},
                make_inspector_headers(other["id"]),
            ),
            ApiErrorId.ERR_OWNERSHIP_SCOPE_VIOLATION,
        )
        after = get_inspection(inspection["id"])
        assert after["status"] == "BOOKED"
        assert after["result"] == "NONE"
