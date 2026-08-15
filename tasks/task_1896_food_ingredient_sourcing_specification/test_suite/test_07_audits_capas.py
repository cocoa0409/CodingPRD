"""Supplier audits and corrective actions: cyclic resubmission, close gating,
window membership, cadence scheduling, overdue reconciliation."""

from test_helpers import (
    ApiErrorId,
    assert_audit,
    create_capa,
    create_qualified_supplier,
    create_reported_audit,
    make_quality_manager_headers,
    make_sqe_headers,
    QM_1,
    SQE_1,
    reject_capa,
    schedule_audit,
    set_clock,
    issue_audit_report,
    start_audit,
    submit_capa,
    validate_error,
    validate_paginated,
    validate_success,
    verify_capa,
)


class TestCapaResubmissionLoop:
    def test_capa_resubmission_loop_to_verified(self, api):
        """PRD §3.9: "A `SupplierQualityEngineer` submits a CAPA response by posting
        `response_text`; this moves the CAPA from `OPEN` to `SUBMITTED`, and the
        same action resubmits a `REJECTED` CAPA back to `SUBMITTED` (the
        resubmission loop is cyclic). A `QualityManager` then verifies the response
        by posting `verification_note` of at least ten characters, moving the CAPA
        to `VERIFIED` (terminal), or rejects it by posting a similar note, moving
        it back to `REJECTED`."

        Design: Difficulty/non_linear_state_machine/corrective_action_resubmission_loop_and_audit_close_gate
        """
        supplier = create_qualified_supplier("SUP-Q", risk_tier="TIER_B", questionnaire_score=80)
        audit = create_reported_audit(
            supplier["id"], audit_score=65, findings_summary="pest control gaps",
        )
        capa = create_capa(
            supplier["id"], audit["id"],
            description="install bait stations", due_date="2026-08-20T00:00:00Z",
        )
        assert capa["status"] == "OPEN"

        submitted = submit_capa(supplier["id"], audit["id"], capa["id"], response_text="stations ordered")
        assert submitted["status"] == "SUBMITTED"
        rejected = reject_capa(supplier["id"], audit["id"], capa["id"], note="evidence insufficient")
        assert rejected["status"] == "REJECTED", "cyclic loop entered: SUBMITTED -> REJECTED"

        resubmitted = submit_capa(
            supplier["id"], audit["id"], capa["id"],
            response_text="stations installed, photos attached",
        )
        assert resubmitted["status"] == "SUBMITTED", "REJECTED -> SUBMITTED resubmission"
        verified = verify_capa(supplier["id"], audit["id"], capa["id"], note="verified on site visit")
        assert verified["status"] == "VERIFIED"

        closed = validate_success(api.close_audit(supplier["id"], audit["id"], make_quality_manager_headers(QM_1)))
        assert closed["status"] == "CLOSED"

    def test_audit_close_blocked_while_capa_rejected(self, api):
        """PRD §3.9: "It is rejected with `ERR_OPEN_CAPAS_EXIST` if any corrective
        action of the audit is not in `VERIFIED` status." — a CAPA sitting in
        `REJECTED` (mid-loop) still blocks the parent audit's close.

        Design: Difficulty/non_linear_state_machine/corrective_action_resubmission_loop_and_audit_close_gate
        """
        supplier = create_qualified_supplier("SUP-Q2", risk_tier="TIER_B", questionnaire_score=80)
        audit = create_reported_audit(
            supplier["id"], audit_score=65, findings_summary="pest control gaps",
        )
        capa = create_capa(
            supplier["id"], audit["id"],
            description="install bait stations", due_date="2026-08-20T00:00:00Z",
        )
        submit_capa(supplier["id"], audit["id"], capa["id"], response_text="stations ordered")
        reject_capa(supplier["id"], audit["id"], capa["id"], note="evidence insufficient")

        resp = api.close_audit(supplier["id"], audit["id"], make_quality_manager_headers(QM_1))
        validate_error(resp, ApiErrorId.ERR_OPEN_CAPAS_EXIST)


class TestAuditCloseGatingOnCapaChildren:
    def _setup_two_capas(self):
        """REPORT_ISSUED audit with two CAPAs; CAPA-1 verified, CAPA-2 left OPEN."""
        supplier = create_qualified_supplier("SUP-A2", questionnaire_score=92)
        audit = create_reported_audit(
            supplier["id"], audit_score=88, findings_summary="minor labeling gaps",
        )
        capa1 = create_capa(
            supplier["id"], audit["id"],
            description="fix label template", due_date="2026-08-20T00:00:00Z",
        )
        capa2 = create_capa(
            supplier["id"], audit["id"],
            description="retrain line operators", due_date="2026-08-25T00:00:00Z",
        )
        submit_capa(supplier["id"], audit["id"], capa1["id"], response_text="template corrected")
        verify_capa(supplier["id"], audit["id"], capa1["id"], note="label verified correct")
        return supplier, audit, capa1, capa2

    def test_audit_close_blocked_by_open_capa(self, api):
        """PRD §3.9: "Closing the audit moves a `REPORT_ISSUED` audit to `CLOSED`.
        It is rejected with `ERR_OPEN_CAPAS_EXIST` if any corrective action of the
        audit is not in `VERIFIED` status."

        Design: Difficulty/cross_entity_state_dependency/audit_close_depends_on_corrective_action_children_states
        """
        supplier, audit, _capa1, capa2 = self._setup_two_capas()
        assert capa2["status"] == "OPEN"
        resp = api.close_audit(supplier["id"], audit["id"], make_quality_manager_headers(QM_1))
        validate_error(resp, ApiErrorId.ERR_OPEN_CAPAS_EXIST)

    def test_audit_close_succeeds_when_all_capas_verified(self, api, quality_manager_headers):
        """PRD §3.9: "On close, the supplier's `last_audit_closed_at` is set to the
        clock, the supplier's composite risk score is recomputed (the audit
        component becomes 100 minus the `audit_score`), and the next audit is
        auto-scheduled per the cadence rule."

        Design: Difficulty/cross_entity_state_dependency/audit_close_depends_on_corrective_action_children_states
        """
        supplier, audit, _capa1, capa2 = self._setup_two_capas()
        submit_capa(supplier["id"], audit["id"], capa2["id"], response_text="operators retrained")
        verify_capa(supplier["id"], audit["id"], capa2["id"], note="training records verified")

        closed = validate_success(api.close_audit(supplier["id"], audit["id"], make_quality_manager_headers(QM_1)))
        assert closed["status"] == "CLOSED"

        after = validate_success(api.get_supplier(supplier["id"], quality_manager_headers))
        assert after["last_audit_closed_at"] is not None
        assert after["last_audit_closed_at"].startswith("2026-08-01"), (
            "last_audit_closed_at is set to the logical clock at close"
        )


class TestAuditWindowMembership:
    def test_audit_start_at_window_start_succeeds(self, api):
        """PRD §3.9: "It is rejected with `ERR_INVALID_STATE` if the audit is not
        `SCHEDULED`, with `ERR_AUDIT_WINDOW_NOT_OPEN` if the logical clock is
        outside the `[scheduled_window_start, scheduled_window_end)` window, and
        with `ERR_AUDIT_ALREADY_OPEN` if another audit of the same supplier is
        `IN_PROGRESS` or `REPORT_ISSUED`." — the clock at exactly `window_start` is
        inside the half-open window (inclusive lower bound).

        Design: Difficulty/resource_temporal_overlap/audit_window_membership_guards_start_endpoint
        """
        supplier = create_qualified_supplier("SUP-W1")
        audit = schedule_audit(
            supplier["id"], "2026-08-10T00:00:00Z", "2026-08-20T00:00:00Z",
        )
        set_clock("2026-08-10T00:00:00Z")
        started = validate_success(
            api.start_audit(supplier["id"], audit["id"], make_sqe_headers(SQE_1))
        )
        assert_audit(started)
        assert started["status"] == "IN_PROGRESS"

    def test_audit_start_at_window_end_rejected(self, api):
        """PRD §3.9: "with `ERR_AUDIT_WINDOW_NOT_OPEN` if the logical clock is
        outside the `[scheduled_window_start, scheduled_window_end)` window" — the
        clock at exactly `window_end` is outside the half-open window (exclusive
        upper bound).

        Design: Difficulty/resource_temporal_overlap/audit_window_membership_guards_start_endpoint
        """
        supplier = create_qualified_supplier("SUP-W2")
        audit = schedule_audit(
            supplier["id"], "2026-08-10T00:00:00Z", "2026-08-20T00:00:00Z",
        )
        set_clock("2026-08-20T00:00:00Z")
        resp = api.start_audit(supplier["id"], audit["id"], make_sqe_headers(SQE_1))
        validate_error(resp, ApiErrorId.ERR_AUDIT_WINDOW_NOT_OPEN)


class TestAuditCadenceAndSweeps:
    def test_audit_cadence_next_window_from_tier(self, api, quality_manager_headers):
        """PRD §3.10: "The base cadence is twelve months for a `TIER_A` supplier,
        six months for `TIER_B`, and three months for `TIER_C`. ... Otherwise the
        next `scheduled_window_start` is `last_audit_closed_at` plus the base
        cadence in whole months (same day-of-month, clamped to month end), and
        `cadence_source` is `TIER_CADENCE`. In both cases `scheduled_window_end` is
        `scheduled_window_start` plus 14 days — a fixed audit-window length." —
        TIER_B closed at clock 2026-08-03 schedules 2027-02-03 .. 2027-02-17.

        Design: Corner/calculations/audit_cadence_next_window_from_tier
        """
        supplier = create_qualified_supplier("SUP-CAD", risk_tier="TIER_B", questionnaire_score=88)
        audit = schedule_audit(supplier["id"], "2026-08-01T00:00:00Z", "2026-08-15T00:00:00Z")
        set_clock("2026-08-03T00:00:00Z")
        start_audit(supplier["id"], audit["id"])
        issue_audit_report(supplier["id"], audit["id"], 85, "clean audit")

        closed = validate_success(api.close_audit(supplier["id"], audit["id"], make_quality_manager_headers(QM_1)))
        assert closed["status"] == "CLOSED"

        audits, _meta = validate_paginated(api.list_audits(supplier["id"], quality_manager_headers))
        scheduled = [a for a in audits if a["status"] == "SCHEDULED"]
        assert len(scheduled) == 1, "closing an audit auto-schedules exactly one successor"
        nxt = scheduled[0]
        assert_audit(nxt)
        assert nxt["scheduled_window_start"].startswith("2027-02-03"), (
            f"last_audit_closed_at 2026-08-03 + 6 months (TIER_B); got {nxt['scheduled_window_start']}"
        )
        assert nxt["scheduled_window_end"].startswith("2027-02-17"), (
            f"fixed 14-day audit window; got {nxt['scheduled_window_end']}"
        )
        assert nxt["cadence_source"] == "TIER_CADENCE"

    def test_overdue_capa_count_reconciles_on_clock_sweep(self, api, quality_manager_headers):
        """PRD §3.9: "The supplier's `open_overdue_capa_count` is the count of
        corrective actions in `SUBMITTED` or `REJECTED` status whose `due_date` is
        strictly before the current clock, plus `OPEN` rows past due." — at exactly
        `due_date` the row is not yet past due (strictly-before semantics).

        Design: Corner/cross_cutting_layers/overdue_capa_count_reconciles_on_clock_sweep
        """
        supplier = create_qualified_supplier("SUP-OD")
        audit = create_reported_audit(supplier["id"], audit_score=75, findings_summary="one finding")
        create_capa(
            supplier["id"], audit["id"],
            description="fix sieve integrity", due_date="2026-08-05T00:00:00Z",
        )

        def overdue_count():
            return validate_success(api.get_supplier(supplier["id"], quality_manager_headers))[
                "open_overdue_capa_count"
            ]

        assert overdue_count() == 0, "before due_date: nothing overdue"
        set_clock("2026-08-05T00:00:00Z")
        assert overdue_count() == 0, "at exactly due_date the row is not yet past due"
        set_clock("2026-08-05T00:00:01Z")
        assert overdue_count() == 1, "one second after due_date the OPEN row is past due"

    def test_second_open_audit_blocked(self, api):
        """PRD §3.9: "with `ERR_AUDIT_ALREADY_OPEN` if another audit of the same
        supplier is `IN_PROGRESS` or `REPORT_ISSUED`" — the first audit is
        IN_PROGRESS, so the second cannot start even inside its own window.

        Design: Corner/errors/second_open_audit_blocked
        """
        supplier = create_qualified_supplier("SUP-AO")
        audit1 = schedule_audit(supplier["id"], "2026-08-01T00:00:00Z", "2026-08-15T00:00:00Z")
        start_audit(supplier["id"], audit1["id"])  # IN_PROGRESS at the default clock
        audit2 = schedule_audit(supplier["id"], "2026-08-10T00:00:00Z", "2026-08-20T00:00:00Z")

        set_clock("2026-08-10T00:00:00Z")  # inside audit2's own window
        resp = api.start_audit(supplier["id"], audit2["id"], make_sqe_headers(SQE_1))
        validate_error(resp, ApiErrorId.ERR_AUDIT_ALREADY_OPEN)
