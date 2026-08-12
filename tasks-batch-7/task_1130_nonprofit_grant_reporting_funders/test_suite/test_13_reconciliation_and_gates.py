"""Derived-field reconciliation on forward and compensating paths, unfreeze
cascade, and the FINAL report match gate (PRD §2.6, §3.3, §3.4, §3.8)."""
import pytest

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    allocate,
    create_engagement_in_conducted,
    create_posted_expense,
    edit_report,
    file_finding,
    post_activity_in_period,
    resolve_finding,
    set_clock,
    setup_active_grant,
    start_report,
    suspend_grant_with_material_weakness,
    validate_error,
    validate_paginated,
    validate_success,
)

OFFICER = TEST_USERS["officer_headers"]


class TestDerivedFieldReconciliation:
    def test_budget_line_expended_reconciles_on_allocate_and_void(self, api):
        """PRD §2.6: "These cascades are the system's mechanism for keeping
        derived totals (`expended_cents` on lines and funds, `remaining_cents`
        on funds, `unallocated_cents` on expenses, `total_expended_cents` on
        grants, `adjusted_cents` on lines, `period_budgets_cents` on lines)
        continuously reconciled with the underlying activity."
        PRD §3.3: "the budget line's `expended_cents` increases by the
        allocated amount" and on void "for each voided allocation the
        corresponding budget line's `expended_cents` and fund's
        `expended_cents` are decremented by the allocation's amount".

        Design: Corner/cross_cutting_layers/budget_line_expended_reconciles_on_allocate_and_void
        """
        ctx = setup_active_grant()
        gid = ctx["grant"]["id"]
        l1 = ctx["lines"][0]
        fund = ctx["fund"]
        expense = create_posted_expense(gid, amount_cents=2_000_000)
        allocate(expense["id"], l1["id"], fund["id"], 2_000_000)

        lines, _ = validate_paginated(api.list_budget_lines(gid, OFFICER))
        assert lines[0]["expended_cents"] == 2_000_000, (
            f"allocation must raise line expended_cents to 2000000, got "
            f"{lines[0]['expended_cents']}"
        )

        validate_success(api.void_expense(expense["id"], TEST_USERS["finance_headers"]))
        lines_after, _ = validate_paginated(api.list_budget_lines(gid, OFFICER))
        assert lines_after[0]["expended_cents"] == 0, (
            f"void cascade must return line expended_cents to 0, got "
            f"{lines_after[0]['expended_cents']}"
        )

    def test_void_reconciles_grant_total_and_line_together(self, api):
        """PRD §3.3: "for each voided allocation the corresponding budget
        line's `expended_cents` and fund's `expended_cents` are decremented by
        the allocation's amount; and the grant's `total_expended_cents` is
        recomputed."
        PRD §3.3: "voided allocations contribute nothing to any total or
        variance computation."

        Design: Difficulty/compensating_invariant/expense_post_void_conserves_fund_ledger
        """
        ctx = setup_active_grant()
        gid = ctx["grant"]["id"]
        l1 = ctx["lines"][0]
        fund = ctx["fund"]
        set_clock("2026-06-15T00:00:00Z")
        expense = create_posted_expense(gid, amount_cents=2_000_000)
        allocate(expense["id"], l1["id"], fund["id"], 2_000_000)

        grant_before = validate_success(api.get_grant(gid, OFFICER))
        assert grant_before["total_expended_cents"] == 2_000_000

        validate_success(api.void_expense(expense["id"], TEST_USERS["finance_headers"]))

        grant_after = validate_success(api.get_grant(gid, OFFICER))
        assert grant_after["total_expended_cents"] == 0
        lines_after, _ = validate_paginated(api.list_budget_lines(gid, OFFICER))
        assert lines_after[0]["expended_cents"] == 0
        fetched = validate_success(api.get_expense(expense["id"], OFFICER))
        assert fetched["status"] == "VOIDED"


class TestUnfreezeCascade:
    def test_resolution_unfreezes_reports_and_unlocks_explanations(self, api):
        """PRD §3.8: "if no other `OPEN` or `RESPONSE_SUBMITTED`
        `MATERIAL_WEAKNESS` finding remains on any engagement of the grant, the
        grant transitions automatically from `SUSPENDED` back to `ACTIVE`,
        every frozen report of the grant has `frozen` cleared to `false`, and
        every `VarianceExplanation` in `LOCKED` transitions back to `DRAFTED`."

        Design: Difficulty/transitive_cascade/material_weakness_freeze_chain
        """
        ctx = setup_active_grant(
            lines=[{"category": "PERSONNEL", "budgeted_cents": 50_000_000}],
            variance_threshold_pct=3.0,
        )
        gid = ctx["grant"]["id"]
        l1 = ctx["lines"][0]
        fund = ctx["fund"]
        r1 = ctx["reports"][0]

        set_clock("2026-06-15T00:00:00Z")
        start_report(r1["id"])
        post_activity_in_period(gid, l1["id"], fund["id"], 13_000_000, "2026-06-20")
        validate_success(api.create_variance_explanation(
            r1["id"],
            {"budget_line_id": l1["id"], "explanation_text": "hiring surge"},
            OFFICER,
        ), expected_status=201)

        _engagement, finding = suspend_grant_with_material_weakness(
            gid, engagement_type="FINANCIAL_AUDIT",
        )
        # Sanity: chain links 1-3 held (SUSPENDED, frozen, LOCKED).
        assert validate_success(api.get_grant(gid, OFFICER))["status"] == "SUSPENDED"
        assert validate_success(api.get_report(r1["id"], OFFICER))["frozen"] is True
        ves, _ = validate_paginated(api.list_variance_explanations(r1["id"], OFFICER))
        assert ves[0]["status"] == "LOCKED"

        resolve_finding(finding["id"])

        assert validate_success(api.get_grant(gid, OFFICER))["status"] == "ACTIVE"
        assert validate_success(api.get_report(r1["id"], OFFICER))["frozen"] is False
        ves_after, _ = validate_paginated(
            api.list_variance_explanations(r1["id"], OFFICER)
        )
        assert ves_after[0]["status"] == "DRAFTED", (
            f"LOCKED explanation must return to DRAFTED on unfreeze, got "
            f"{ves_after[0]['status']}"
        )


class TestFinalReportMatchGate:
    def test_final_report_submit_match_shortfall_rejected(self, api):
        """PRD §3.4: "For the `FINAL` report only, one further gate applies:
        the verified match total must be at least the grant's
        `required_match_cents`, otherwise submission is rejected with
        `ERR_MATCH_SHORTFALL` (HTTP 422)."
        PRD §3.5: "The verified-only total, `match_verified_only_cents`, sums
        `recognized_value_cents` over contributions in `VERIFIED` status only;
        this is the compliance position and is the figure the `FINAL` report
        submit gate compares against `required_match_cents`."

        Design: Corner/validations/final_report_submit_match_shortfall_rejected
        """
        ctx = setup_active_grant(
            funder_overrides={"requires_match": True},
            required_match_cents=25_000_000,
        )
        r4 = ctx["reports"][3]
        assert r4["period_type"] == "FINAL"

        set_clock("2027-03-15T00:00:00Z")
        start_report(r4["id"])
        edit_report(r4["id"])

        resp = api.submit_report(r4["id"], OFFICER)
        validate_error(resp, ApiErrorId.ERR_MATCH_SHORTFALL)
