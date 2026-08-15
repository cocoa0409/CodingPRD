"""Eligibility audits: the OPENED -> FINDINGS_ISSUED -> RESOLVED branch,
segregation of duties, and clawback adjustments."""
from test_helpers import (
    ApiErrorId,
    get_audit,
    get_filing,
    get_reimbursement,
    make_plan_administrator_headers,
    setup_audit_findings_issued,
    validate_error,
    validate_success,
)


def _resolve(api, audit_id, adjustment_cents, user_id):
    return api.resolve_audit(audit_id, {"adjustment_cents": adjustment_cents},
                             make_plan_administrator_headers(user_id))


class TestAuditBranching:
    def test_audit_resolves_with_negative_adjustment_clawback(self, api):
        """PRD §3.8: "Resolution belongs to the employer side: a
        `PlanAdministrator` resolves an audit in `FINDINGS_ISSUED`, moving it
        to the terminal `RESOLVED` state and recording the `adjustment_cents`
        from the payload."
        PRD §3.8: "A negative adjustment is a clawback from the plan: the
        filing's `approved_amount_cents` is reduced by the absolute value of
        the adjustment, and the accumulation rows affected by the change are
        recomputed."

        Design: Difficulty/non_linear_state_machine/audit_branching_findings_vs_direct_resolution
        """
        ctx = setup_audit_findings_issued(plan_name="Zeta",
                                          approved_amount_cents=5_000_000)
        resp = _resolve(api, ctx["audit"]["id"], -1_000_000, "admin-y")
        audit = validate_success(resp, 200)
        assert audit["status"] == "RESOLVED"
        assert audit["adjustment_cents"] == -1_000_000
        filing = get_filing(ctx["filing"]["id"])
        assert filing["approved_amount_cents"] == 4_000_000, (
            f"Approved 5000000 less |adjustment| 1000000 must be 4000000, "
            f"got {filing['approved_amount_cents']}")

    def test_audit_resolves_with_zero_adjustment_approved_unchanged(self, api):
        """PRD §3.8: "A negative adjustment is a clawback from the plan: the
        filing's `approved_amount_cents` is reduced by the absolute value of
        the adjustment, and the accumulation rows affected by the change are
        recomputed."
        PRD §3.8: "Issuing findings moves it from `OPENED` to
        `FINDINGS_ISSUED` without side effects."

        Design: Difficulty/non_linear_state_machine/audit_branching_findings_vs_direct_resolution
        """
        ctx = setup_audit_findings_issued(plan_name="Zeta",
                                          approved_amount_cents=5_000_000)
        assert ctx["audit"]["status"] == "FINDINGS_ISSUED"
        resp = _resolve(api, ctx["audit"]["id"], 0, "admin-y")
        audit = validate_success(resp, 200)
        assert audit["status"] == "RESOLVED"
        assert audit["adjustment_cents"] == 0
        # Zero adjustment is not a clawback: approved_amount_cents stands.
        assert get_filing(ctx["filing"]["id"])["approved_amount_cents"] == 5_000_000


class TestSegregationOfDuties:
    def test_submitter_cannot_resolve_own_audit(self, api):
        """PRD §2.11: "The operator who resolves an audit must not be the
        operator who submitted the filing under audit, compared by
        `X-User-ID`. A resolution attempted by the same operator identifier
        that submitted the underlying filing is rejected with
        `ERR_SEGREGATION_OF_DUTIES` (HTTP 403)."

        Design: Difficulty/cross_entity_state_dependency/audit_resolve_blocked_by_segregation_of_duties
        """
        ctx = setup_audit_findings_issued(plan_name="Xi",
                                          analyst_user_id="analyst-u1",
                                          through_paid=False)
        # The filing was created and submitted under X-User-ID "analyst-u1";
        # resolving with the same operator identifier is forbidden.
        resp = _resolve(api, ctx["audit"]["id"], 0, "analyst-u1")
        validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES)
        assert get_audit(ctx["audit"]["id"])["status"] == "FINDINGS_ISSUED"

    def test_different_operator_resolves_audit(self, api):
        """PRD §2.11: "The operator who resolves an audit must not be the
        operator who submitted the filing under audit, compared by
        `X-User-ID`."
        PRD §3.8: "Resolution belongs to the employer side: a
        `PlanAdministrator` resolves an audit in `FINDINGS_ISSUED`, moving it
        to the terminal `RESOLVED` state and recording the `adjustment_cents`
        from the payload."

        Design: Difficulty/cross_entity_state_dependency/audit_resolve_blocked_by_segregation_of_duties
        """
        ctx = setup_audit_findings_issued(plan_name="Xi",
                                          analyst_user_id="analyst-u1",
                                          through_paid=False)
        resp = _resolve(api, ctx["audit"]["id"], 0, "admin-unrelated")
        audit = validate_success(resp, 200)
        assert audit["status"] == "RESOLVED"
        assert audit["adjustment_cents"] == 0


class TestNegativeAdjustmentInvariant:
    def test_clawback_reduces_approved_by_exact_adjustment(self, api):
        """PRD §3.8: "A negative adjustment is a clawback from the plan: the
        filing's `approved_amount_cents` is reduced by the absolute value of
        the adjustment, and the accumulation rows affected by the change are
        recomputed."

        Design: Difficulty/compensating_invariant/audit_negative_adjustment_preserves_approved_minus_reimbursed
        """
        ctx = setup_audit_findings_issued(plan_name="Sigma",
                                          approved_amount_cents=5_000_000)
        resp = _resolve(api, ctx["audit"]["id"], -2_000_000, "admin-y")
        validate_success(resp, 200)
        filing = get_filing(ctx["filing"]["id"])
        assert filing["approved_amount_cents"] == 3_000_000, (
            f"Approved 5000000 less |−2000000| must be 3000000, got "
            f"{filing['approved_amount_cents']}")
        # The posted reimbursement record itself is not mutated by the audit.
        reimbursement = get_reimbursement(ctx["reimbursement"]["id"])
        assert reimbursement["status"] == "POSTED"
        assert reimbursement["received_amount_cents"] == 5_000_000

    def test_clawback_shifts_approved_minus_reimbursed_balance_exactly(self, api):
        """PRD §3.8: "A negative adjustment is a clawback from the plan: the
        filing's `approved_amount_cents` is reduced by the absolute value of
        the adjustment, and the accumulation rows affected by the change are
        recomputed."

        Design: Difficulty/compensating_invariant/audit_negative_adjustment_preserves_approved_minus_reimbursed
        """
        ctx = setup_audit_findings_issued(plan_name="Sigma",
                                          approved_amount_cents=5_000_000)
        posted = ctx["reimbursement"]["received_amount_cents"]
        before = get_filing(ctx["filing"]["id"])["approved_amount_cents"] - posted

        resp = _resolve(api, ctx["audit"]["id"], -1_500_000, "admin-y")
        validate_success(resp, 200)
        filing = get_filing(ctx["filing"]["id"])
        assert filing["approved_amount_cents"] == 3_500_000
        after = filing["approved_amount_cents"] - posted
        assert after - before == -1_500_000, (
            "The approved-minus-reimbursed balance must shift by exactly the "
            "adjustment, not more, not less")
        assert get_reimbursement(ctx["reimbursement"]["id"])["status"] == "POSTED"
