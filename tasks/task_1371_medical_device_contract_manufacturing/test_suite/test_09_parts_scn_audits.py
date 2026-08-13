"""Supplier parts, change notifications, audits: windows, cascades, reinstate."""
from test_helpers import (
    ApiErrorId,
    add_component,
    complete_lot,
    create_agreement,
    create_audit,
    create_audit_payload,
    create_lot,
    create_part,
    create_qualified_supplier,
    create_scn,
    create_scn_payload,
    create_supplier,
    create_validated_stack,
    disposition_ncr,
    contain_ncr,
    create_ncr,
    get_lot,
    get_part,
    get_supplier,
    qe,
    sqe,
    validate_error,
    validate_paginated,
    validate_success,
    api_client,
)


class TestAuditNoticeWindowBoundary:
    def _qualified_supplier(self):
        return create_qualified_supplier("SUP-A30", "Notice Co", audit_notice_days=30)

    def test_audit_start_exactly_30_days_out_accepted(self, api):
        """PRD section 3.4: "the window's start must respect the notice period of
        the supplier's `ACTIVE` agreement — `scheduled_start` must be at least
        `audit_notice_days` days after now (`ERR_AUDIT_NOTICE_WINDOW_BREACHED`)"
        — at the default clock of 2026-08-01, exactly 30 days out satisfies
        "at least".

        Design: Difficulty/boundary_precision_check/audit_notice_window_exactly_30_days
        """
        qs = self._qualified_supplier()
        audit = create_audit(
            qs["supplier"]["id"],
            scheduled_start="2026-08-31T00:00:00Z",
            scheduled_end="2026-09-01T00:00:00Z",
        )
        assert audit["status"] == "SCHEDULED"

    def test_audit_start_29_days_out_rejected(self, api):
        """PRD section 3.4: "`scheduled_start` must be at least
        `audit_notice_days` days after now (`ERR_AUDIT_NOTICE_WINDOW_BREACHED`)"
        — 29 days is less than the 30-day notice of the active agreement.

        Design: Difficulty/boundary_precision_check/audit_notice_window_exactly_30_days
        """
        qs = self._qualified_supplier()
        resp = api.create_audit(
            qs["supplier"]["id"],
            create_audit_payload(
                scheduled_start="2026-08-30T00:00:00Z",
                scheduled_end="2026-08-31T00:00:00Z",
            ),
            sqe(),
        )
        validate_error(resp, ApiErrorId.ERR_AUDIT_NOTICE_WINDOW_BREACHED)


class TestSupplierAuditHalfOpenAdjacency:
    def _setup_audit_a(self):
        qs = create_qualified_supplier("SUP-AU", "Audit Co", audit_notice_days=30)
        audit_a = create_audit(
            qs["supplier"]["id"],
            scheduled_start="2026-09-10T00:00:00Z",
            scheduled_end="2026-09-12T00:00:00Z",
        )
        return qs, audit_a

    def test_adjacent_window_allowed_overlap_rejected(self, api):
        """PRD section 3.4: "defining a half-open window: the start instant is
        occupied, the end instant is free, so two audits whose endpoints merely
        touch do not overlap. An audit whose window overlaps another `SCHEDULED`
        audit of the same supplier is rejected with `ERR_AUDIT_WINDOW_OVERLAP`."

        Design: Difficulty/resource_temporal_overlap/supplier_audit_half_open_adjacency
        """
        qs, _audit_a = self._setup_audit_a()
        audit_b = create_audit(
            qs["supplier"]["id"],
            scheduled_start="2026-09-12T00:00:00Z",
            scheduled_end="2026-09-13T00:00:00Z",
        )
        assert audit_b["status"] == "SCHEDULED", "touching endpoints must not overlap"

        resp = api.create_audit(
            qs["supplier"]["id"],
            create_audit_payload(
                scheduled_start="2026-09-11T00:00:00Z",
                scheduled_end="2026-09-12T00:00:00Z",
            ),
            sqe(),
        )
        validate_error(resp, ApiErrorId.ERR_AUDIT_WINDOW_OVERLAP)

    def test_cancelled_audit_frees_its_window(self, api):
        """PRD section 3.4: "An audit whose window overlaps another `SCHEDULED`
        audit of the same supplier is rejected with `ERR_AUDIT_WINDOW_OVERLAP`"
        — a `CANCELLED` audit is no longer `SCHEDULED`, so its window is free.

        Design: Difficulty/resource_temporal_overlap/supplier_audit_half_open_adjacency
        """
        qs, _audit_a = self._setup_audit_a()
        audit_b = create_audit(
            qs["supplier"]["id"],
            scheduled_start="2026-09-12T00:00:00Z",
            scheduled_end="2026-09-13T00:00:00Z",
        )
        cancelled = validate_success(api.cancel_audit(audit_b["id"], sqe()))
        assert cancelled["status"] == "CANCELLED"
        audit_d = create_audit(
            qs["supplier"]["id"],
            scheduled_start="2026-09-12T00:00:00Z",
            scheduled_end="2026-09-13T00:00:00Z",
        )
        assert audit_d["status"] == "SCHEDULED"


class TestScnCreateValidation:
    def test_scn_create_invalid_enum_returns_400(self, api):
        """PRD section 3.5: "a `change_description`, an `impact_class` of `MINOR`
        or `MAJOR`, a `proposed_effective_date`" and PRD section 2.10 step 3:
        "enum values are valid ... (`ERR_VALIDATION`)".

        Design: Corner/entities/scn_create_invalid_enum_returns_400
        """
        qs = create_qualified_supplier("SUP-E1", "Enum Co")
        resp = api.create_scn(
            qs["supplier"]["id"],
            create_scn_payload(
                change_description="resin swap",
                impact_class="HUGE",
                proposed_effective_date="2026-12-01T00:00:00Z",
            ),
            sqe(),
        )
        validate_error(resp, ApiErrorId.ERR_VALIDATION)

    def test_temporal_failure_masks_referential_failure(self, api):
        """PRD section 2.10: "a failure at any step masks all later checks — the
        caller sees the earliest applicable error" with step "10. **Temporal
        windows.** ... change-notice window (`ERR_CHANGE_NOTICE_WINDOW_BREACHED`)"
        ahead of step "11. **Cross-reference coherence.** Part belongs to the
        path supplier (`ERR_PART_NOT_OF_SUPPLIER`)".

        Design: Difficulty/priority_pair_validation_conflict/temporal_vs_referential_on_scn_create
        """
        qs1 = create_qualified_supplier("SUP-T1", "Temp One", change_notice_days=90)
        sup2 = create_supplier("SUP-T2", "Temp Two")
        part2 = create_part(sup2["id"], "PN-T2", description="lens")

        resp = api.create_scn(
            qs1["supplier"]["id"],
            create_scn_payload(
                supplier_part_id=part2["id"],
                change_description="resin change",
                impact_class="MINOR",
                proposed_effective_date="2026-08-15T00:00:00Z",
            ),
            sqe(),
        )
        validate_error(resp, ApiErrorId.ERR_CHANGE_NOTICE_WINDOW_BREACHED)
        page, _meta = validate_paginated(
            api.list_scns(sqe(), params={"supplier_id": qs1["supplier"]["id"]})
        )
        assert page == []

    def test_referential_failure_surfaces_when_temporal_passes(self, api):
        """PRD section 3.5: "optionally a `supplier_part_id` scoping the change —
        when present, that part must belong to the path supplier
        (`ERR_PART_NOT_OF_SUPPLIER`)"."

        Design: Difficulty/priority_pair_validation_conflict/temporal_vs_referential_on_scn_create
        """
        qs1 = create_qualified_supplier("SUP-T1", "Temp One", change_notice_days=90)
        sup2 = create_supplier("SUP-T2", "Temp Two")
        part2 = create_part(sup2["id"], "PN-T2", description="lens")

        resp = api.create_scn(
            qs1["supplier"]["id"],
            create_scn_payload(
                supplier_part_id=part2["id"],
                change_description="resin change",
                impact_class="MINOR",
                proposed_effective_date="2026-12-01T00:00:00Z",
            ),
            sqe(),
        )
        validate_error(resp, ApiErrorId.ERR_PART_NOT_OF_SUPPLIER)


class TestScnAcceptCascade:
    def test_scn_accepted_terminal_lockdown(self, api):
        """PRD section 3.5: "Review moves the notification `SUBMITTED` →
        `UNDER_REVIEW` → `ACCEPTED` or `REJECTED`, with both outcomes terminal."
        and "A `MINOR` acceptance changes nothing downstream."

        Design: Corner/state_machines/scn_accepted_terminal_lockdown
        """
        qs = create_qualified_supplier("SUP-ST", "ST Co", change_notice_days=90)
        scn = create_scn(
            qs["supplier"]["id"],
            impact_class="MINOR",
            proposed_effective_date="2026-12-01T00:00:00Z",
            change_description="label ink change",
        )
        validate_success(api.start_scn_review(scn["id"], sqe()))
        accepted = validate_success(api.accept_scn(scn["id"], sqe()))
        assert accepted["status"] == "ACCEPTED"

        resp = api.start_scn_review(scn["id"], sqe())
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE_TRANSITION)
        resp = api.reject_scn(scn["id"], sqe())
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE_TRANSITION)

    def test_scn_accept_major_critical_full_cascade(self, api):
        """PRD section 3.5: "A `MAJOR` acceptance with a part scope places that
        part `ON_HOLD` if it was `QUALIFIED` and cascades `SUPPLIER_QUALITY`
        holds to its in-flight lots; and when the affected part is `critical`,
        every validation protocol in `VALIDATED` whose pinned DMR revision has
        lots containing that part transitions to `REVALIDATION_REQUIRED` with
        `revalidation_reason` `SUPPLIER_CHANGE`"."

        Design: Corner/endpoints/scn_accept_major_critical_full_cascade
        """
        stack = create_validated_stack("DEV-MJ")
        qs = create_qualified_supplier("SUP-MJ", "MJ Co", change_notice_days=90)
        part = create_part(
            qs["supplier"]["id"], "PN-MJ", critical=True,
            description="catheter valve", receive_qty=100,
        )
        lot = create_lot("LT-MJ", stack["dmr"]["id"], stack["protocol"]["id"])
        add_component(lot["id"], part["id"], quantity_used=10, supplier_lot_number="SL-MJ")
        complete_lot(lot["id"])

        scn = create_scn(
            qs["supplier"]["id"],
            impact_class="MAJOR",
            proposed_effective_date="2026-12-01T00:00:00Z",
            supplier_part_id=part["id"],
            change_description="valve resin supplier swap",
        )
        validate_success(api.start_scn_review(scn["id"], sqe()))
        accepted = validate_success(api.accept_scn(scn["id"], sqe()))
        assert accepted["status"] == "ACCEPTED"

        assert get_part(part["id"])["status"] == "ON_HOLD"
        held = get_lot(lot["id"])
        assert held["hold_status"] == "ON_HOLD"
        assert held["hold_reason"] == "SUPPLIER_QUALITY"
        protocol = validate_success(api.get_protocol(stack["protocol"]["id"], sqe()))
        assert protocol["status"] == "REVALIDATION_REQUIRED"
        assert protocol["revalidation_reason"] == "SUPPLIER_CHANGE"


class TestPartReinstateGuards:
    def test_part_reinstate_blocked_by_pending_scn(self, api):
        """PRD section 3.5: "no change notification on that part may be sitting
        in `SUBMITTED` or `UNDER_REVIEW` (`ERR_SCN_PENDING`)"."

        Design: Corner/endpoints/part_reinstate_blocked_by_pending_scn
        """
        qs = create_qualified_supplier("SUP-PS", "PS Co", change_notice_days=90)
        part = create_part(qs["supplier"]["id"], "PN-PS", description="hinge")
        ncr = create_ncr(
            ncr_code="NCR-PS", severity="MAJOR", description="hinge crack",
            supplier_part_id=part["id"],
        )
        contain_ncr(ncr["id"])
        disposition_ncr(ncr["id"], "RETURN_TO_SUPPLIER", "SUPPLIER")
        assert get_part(part["id"])["status"] == "ON_HOLD"

        create_scn(
            qs["supplier"]["id"],
            impact_class="MINOR",
            proposed_effective_date="2026-12-01T00:00:00Z",
            supplier_part_id=part["id"],
            change_description="mold change",
        )
        resp = api.reinstate_part(part["id"], sqe())
        validate_error(resp, ApiErrorId.ERR_SCN_PENDING)
        assert get_part(part["id"])["status"] == "ON_HOLD"

    def test_part_reinstate_blocked_while_supplier_suspended(self, api):
        """PRD section 3.5: "the supplier must be neither `SUSPENDED` nor
        `DISQUALIFIED` (`ERR_SUPPLIER_NOT_CLEAR`)" and PRD section 3.4:
        "Reinstatement returns the supplier's `ON_HOLD` parts to `QUALIFIED`"."

        Design: Corner/endpoints/part_reinstate_blocked_while_supplier_suspended
        """
        qs = create_qualified_supplier("SUP-SS", "SS Co")
        part = create_part(qs["supplier"]["id"], "PN-SS", description="axle")
        validate_success(api.suspend_supplier(qs["supplier"]["id"], sqe()))
        assert get_part(part["id"])["status"] == "ON_HOLD"

        resp = api.reinstate_part(part["id"], sqe())
        validate_error(resp, ApiErrorId.ERR_SUPPLIER_NOT_CLEAR)

        reinstated = validate_success(api.reinstate_supplier(qs["supplier"]["id"], sqe()))
        assert reinstated["status"] == "QUALIFIED"
        assert get_part(part["id"])["status"] == "QUALIFIED"
