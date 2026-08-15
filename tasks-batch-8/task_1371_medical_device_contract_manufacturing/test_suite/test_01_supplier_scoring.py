"""Supplier quality scoring: dual-variant scores, boundaries, penalty reversal."""
import pytest

from test_helpers import (
    ApiErrorId,
    assert_instant_equal,
    assert_supplier,
    complete_audit,
    create_agreement,
    create_audit,
    create_dispositioned_ncr,
    create_ncr,
    create_part,
    create_qualified_supplier,
    create_supplier,
    contain_ncr,
    disposition_ncr,
    get_supplier,
    qe,
    qm,
    sqe,
    validate_error,
    validate_success,
    api_client,
)


class TestSupplierScoreCurrentVsFinalized:
    def test_dispositioned_ncr_penalty_visible_only_in_current_score(self, api):
        """PRD section 2.9: "A nonconformance report whose `fault` is `SUPPLIER`
        contributes a severity penalty — 5 points for `MINOR`, 15 for `MAJOR`, 30
        for `CRITICAL`." and "`applied_penalty_points` sums supplier-fault reports
        in `DISPOSITIONED` or `CLOSED` plus all completed-audit penalties, while
        `applied_finalized_penalty_points` counts only supplier-fault reports in
        `CLOSED` plus the same completed-audit penalties."

        Design: Difficulty/dual_variant_calc/supplier_score_current_vs_finalized
        """
        qs = create_qualified_supplier("SUP-E2", "Acme Components")
        part = create_part(qs["supplier"]["id"], "PN-E2", description="housing")
        ncr = create_dispositioned_ncr(
            "NCR-E2", "CRITICAL", "SUPPLIER", supplier_part_id=part["id"]
        )
        assert ncr["penalty_points_applied"] == 30

        supplier = get_supplier(qs["supplier"]["id"])
        assert supplier["quality_score"] == 70, (
            f"current score must drop by the CRITICAL penalty, got {supplier['quality_score']}"
        )
        assert supplier["quality_score_finalized"] == 100, (
            f"finalized score must not count a DISPOSITIONED report, got {supplier['quality_score_finalized']}"
        )
        assert supplier["risk_tier"] == "LOW"

    def test_closing_ncr_moves_penalty_into_finalized_variant(self, api):
        """PRD section 2.9: "Closing a supplier-fault report moves its penalty from
        the provisional accumulator into the finalized one" and "The `risk_tier`
        derives from `quality_score_finalized` alone: `LOW` when the finalized score
        is at least 90, `MEDIUM` when it is at least 70 but below 90, and `HIGH`
        below 70."

        Design: Difficulty/dual_variant_calc/supplier_score_current_vs_finalized
        """
        qs = create_qualified_supplier("SUP-E2", "Acme Components")
        part = create_part(qs["supplier"]["id"], "PN-E2", description="housing")
        ncr = create_dispositioned_ncr(
            "NCR-E2", "CRITICAL", "SUPPLIER", supplier_part_id=part["id"]
        )

        closed = validate_success(api.close_ncr(ncr["id"], qm()))
        assert closed["status"] == "CLOSED"

        supplier = get_supplier(qs["supplier"]["id"])
        assert supplier["quality_score"] == 70
        assert supplier["quality_score_finalized"] == 70, (
            f"after close the finalized variant must include the penalty, got {supplier['quality_score_finalized']}"
        )
        assert supplier["risk_tier"] == "MEDIUM", (
            f"finalized 70 is inclusive MEDIUM, got {supplier['risk_tier']}"
        )


class TestSupplierScoreExactly50NotSuspended:
    def _drive_score_to_50(self):
        qs = create_qualified_supplier("SUP-B", "Boundary Co")
        part = create_part(qs["supplier"]["id"], "PN-B", description="seal")
        for code, severity in (("NCR-B1", "CRITICAL"), ("NCR-B2", "MAJOR"), ("NCR-B3", "MINOR")):
            create_dispositioned_ncr(code, severity, "SUPPLIER", supplier_part_id=part["id"])
        return qs, part

    def test_score_exactly_50_keeps_supplier_qualified(self, api):
        """PRD section 2.9: "Whenever a recomputation leaves `quality_score` below
        50 on a supplier that is `QUALIFIED`, the supplier is automatically
        suspended" — a score of exactly 50 is not below 50.

        Design: Difficulty/boundary_precision_check/supplier_score_exactly_50_not_suspended
        """
        qs, _part = self._drive_score_to_50()
        supplier = get_supplier(qs["supplier"]["id"])
        assert supplier["quality_score"] == 50, (
            f"30+15+5 penalties must land exactly on 50, got {supplier['quality_score']}"
        )
        assert supplier["status"] == "QUALIFIED", (
            f"auto-suspend is strict <50, supplier must stay QUALIFIED, got {supplier['status']}"
        )

    def test_two_more_points_suspend_the_supplier(self, api):
        """PRD section 3.4: "`penalty_points` is set to twice the minor findings
        plus eight times the major findings, that penalty is added to both
        `applied_penalty_points` and `applied_finalized_penalty_points`" and
        "if the recomputed `quality_score` has fallen below 50 on a `QUALIFIED`
        supplier the automatic suspension cascade fires".

        Design: Difficulty/boundary_precision_check/supplier_score_exactly_50_not_suspended
        """
        qs, _part = self._drive_score_to_50()
        audit = create_audit(qs["supplier"]["id"])
        complete_audit(audit["id"], findings_count=1, major_findings_count=0)
        supplier = get_supplier(qs["supplier"]["id"])
        assert supplier["quality_score"] == 48, (
            f"one minor finding adds 2 points of penalty, got {supplier['quality_score']}"
        )
        assert supplier["status"] == "SUSPENDED"


class TestSupplierPenaltyReversalZeroDrift:
    def _setup_ncr(self):
        qs = create_qualified_supplier("SUP-PD", "Pendulum")
        part = create_part(qs["supplier"]["id"], "PN-PD", description="spring")
        ncr = create_ncr(
            ncr_code="NCR-PD", severity="MAJOR",
            description="spring fatigue", supplier_part_id=part["id"],
        )
        contain_ncr(ncr["id"])
        return qs, part, ncr

    def test_disposition_then_reopen_restores_score_exactly(self, api):
        """PRD section 3.7: "A supplier-fault penalty is reversed precisely:
        `penalty_points_applied` is subtracted from `applied_penalty_points`,
        `quality_score` is recomputed, `penalty_points_applied` returns to 0,
        `fault` resets to `UNDETERMINED`, and `disposition` resets to `NONE`."

        Design: Difficulty/compensating_invariant/supplier_penalty_reversal_zero_drift
        """
        qs, _part, ncr = self._setup_ncr()
        disposition_ncr(ncr["id"], "RETURN_TO_SUPPLIER", "SUPPLIER")
        supplier = get_supplier(qs["supplier"]["id"])
        assert supplier["quality_score"] == 85
        assert supplier["applied_penalty_points"] == 15

        validate_success(api.reopen_ncr(ncr["id"], qe()))
        supplier = get_supplier(qs["supplier"]["id"])
        assert supplier["quality_score"] == 100, (
            f"reopen must reverse the penalty exactly, got {supplier['quality_score']}"
        )
        assert supplier["applied_penalty_points"] == 0
        reopened = validate_success(api.get_ncr(ncr["id"], qe()))
        assert reopened["fault"] == "UNDETERMINED"
        assert reopened["disposition"] == "NONE"

    def test_internal_redisposition_applies_no_penalty(self, api):
        """PRD section 3.7: "Disposition is where supplier accountability lands:
        when `fault` is `SUPPLIER`, the severity penalty — 5 points for `MINOR`,
        15 for `MAJOR`, 30 for `CRITICAL` — is recorded as
        `penalty_points_applied`" — an `INTERNAL` fault records none.

        Design: Difficulty/compensating_invariant/supplier_penalty_reversal_zero_drift
        """
        qs, _part, ncr = self._setup_ncr()
        disposition_ncr(ncr["id"], "RETURN_TO_SUPPLIER", "SUPPLIER")
        validate_success(api.reopen_ncr(ncr["id"], qe()))
        contain_ncr(ncr["id"])
        redispositioned = disposition_ncr(ncr["id"], "USE_AS_IS", "INTERNAL")
        assert redispositioned["penalty_points_applied"] == 0
        supplier = get_supplier(qs["supplier"]["id"])
        assert supplier["quality_score"] == 100
        assert supplier["applied_penalty_points"] == 0


class TestAuditDueSchedule:
    def test_audit_due_schedule_tier_intervals(self, api):
        """PRD section 2.9: "`next_audit_due_at` is `last_audit_completed_at`
        plus 24 months for `LOW`, 12 months for `MEDIUM`, or 6 months for `HIGH`,
        using calendar-month arithmetic (§2.12). A supplier that has never been
        audited is due at its `created_at` plus 12 months. `is_audit_overdue` is
        true when `next_audit_due_at` is at or before the logical now — the
        comparison is inclusive, so an audit due exactly now counts as overdue".

        Design: Corner/calculations/audit_due_schedule_tier_intervals
        """
        qs = create_qualified_supplier("SUP-AD", "AuditDue", audit_notice_days=30)
        supplier_id = qs["supplier"]["id"]
        assert_instant_equal(
            qs["supplier"]["next_audit_due_at"], "2027-08-01T00:00:00Z",
            "never-audited next_audit_due_at (created_at + 12 months)",
        )

        audit = create_audit(supplier_id, scheduled_start="2026-09-10T00:00:00Z",
                             scheduled_end="2026-09-11T00:00:00Z")
        complete_audit(audit["id"], findings_count=0, major_findings_count=0)

        after = get_supplier(supplier_id)
        assert after["risk_tier"] == "LOW"
        # The audit completed at the default logical clock 2026-08-01.
        assert_instant_equal(
            after["next_audit_due_at"], "2028-08-01T00:00:00Z",
            "LOW tier: last_audit_completed_at + 24 months",
        )
        assert after["is_audit_overdue"] is False

        from test_helpers import set_clock

        set_clock("2028-08-01T00:00:00Z")
        overdue = get_supplier(supplier_id)
        assert overdue["is_audit_overdue"] is True, (
            "due exactly at now counts as overdue (inclusive comparison)"
        )


class TestSupplierDefaultsAndConstraints:
    def test_supplier_creation_applies_defaults(self, api):
        """PRD section 3.4: "The supplier begins in `PENDING_QUALIFICATION` with
        `quality_score` and `quality_score_finalized` both at 100, `risk_tier`
        `LOW`, `last_audit_completed_at` null, `next_audit_due_at` set to its
        `created_at` plus twelve months, and `is_audit_overdue` false."

        Design: Corner/entities/supplier_creation_applies_defaults
        """
        supplier = create_supplier("SUP-D1", "Default Co")
        assert_supplier(supplier)
        assert supplier["status"] == "PENDING_QUALIFICATION"
        assert supplier["quality_score"] == 100
        assert supplier["quality_score_finalized"] == 100
        assert supplier["applied_penalty_points"] == 0
        assert supplier["risk_tier"] == "LOW"
        assert supplier["is_audit_overdue"] is False
        assert_instant_equal(
            supplier["next_audit_due_at"], "2027-08-01T00:00:00Z", "next_audit_due_at"
        )

    def test_supplier_system_field_input_ignored(self, api):
        """PRD section 3.4: "A `SupplierQualityEngineer` registers a supplier with
        a unique `supplier_code` and a legal `name`. The supplier begins in
        `PENDING_QUALIFICATION` with `quality_score` and `quality_score_finalized`
        both at 100" — the client cannot write system-managed state.

        Design: Corner/entities/supplier_system_field_input_ignored
        """
        resp = api.create_supplier(
            {"supplier_code": "SUP-I1", "name": "Ignored Co", "status": "QUALIFIED",
             "quality_score": 5},
            sqe(),
        )
        supplier = validate_success(resp, expected_status=201)
        assert supplier["status"] == "PENDING_QUALIFICATION"
        assert supplier["quality_score"] == 100

    def test_duplicate_supplier_code_returns_409(self, api):
        """PRD section 3.4: "A `SupplierQualityEngineer` registers a supplier with
        a unique `supplier_code`" and PRD section 2.10 step 12: "unique codes
        (`ERR_DUPLICATE_CODE`)".

        Design: Corner/entities/duplicate_supplier_code_returns_409
        """
        create_supplier("SUP-DUP", "First")
        resp = api.create_supplier({"supplier_code": "SUP-DUP", "name": "Second"}, sqe())
        validate_error(resp, ApiErrorId.ERR_DUPLICATE_CODE)

    def test_supplier_list_pagination(self, api):
        """PRD section 2.3: "The `limit` parameter caps the number of items
        returned: it defaults to 10 when omitted, with a minimum of 1 and a
        maximum of 100. The `offset` parameter skips that many items" and "List
        responses include four pagination fields in the `meta` object of the
        envelope: `limit`, `offset`, `total_count`, and `has_more`."

        Design: Corner/entities/supplier_list_pagination
        """
        from test_helpers import validate_paginated

        for code, name in (("SUP-P1", "P1"), ("SUP-P2", "P2"), ("SUP-P3", "P3")):
            create_supplier(code, name)
        page1, meta1 = validate_paginated(
            api.list_suppliers(sqe(), params={"limit": 2, "offset": 0})
        )
        assert len(page1) == 2
        assert meta1["total_count"] == 3
        assert meta1["has_more"] is True
        page2, meta2 = validate_paginated(
            api.list_suppliers(sqe(), params={"limit": 2, "offset": 2})
        )
        assert len(page2) == 1
        assert meta2["total_count"] == 3
        assert meta2["has_more"] is False
