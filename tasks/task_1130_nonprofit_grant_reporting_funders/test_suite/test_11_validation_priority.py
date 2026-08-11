"""Validation priority order: when one request violates two rules, the
higher-priority category's error is observed (PRD §2.10)."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    add_budget_line,
    add_fund,
    allocate,
    create_engagement_in_conducted,
    create_posted_expense,
    edit_report,
    file_finding,
    post_activity_in_period,
    set_clock,
    setup_active_grant,
    start_report,
    suspend_grant_with_material_weakness,
    validate_error,
)

OFFICER = TEST_USERS["officer_headers"]


class TestSuspendStateBeatsMissingExplanation:
    def test_suspended_submit_reports_state_error_not_variance_gate(self, api):
        """PRD §2.10: "When a request fails several rules at once, the error the
        client observes is determined by a fixed priority order; lower-numbered
        categories are evaluated first." State preconditions sit at category 5
        and referential submission-content gates at category 9: "5. State
        preconditions — the generic state-machine from-state checks plus the
        named state guards (`ERR_INVALID_STATE`, `ERR_GRANT_NOT_ACTIVE`,
        `ERR_GRANT_SUSPENDED`, ...)" and "9. Referential and submission-content
        rules — ... the variance-explanation gate
        (`ERR_VARIANCE_EXPLANATION_REQUIRED`) ...".

        Design: Difficulty/priority_pair_validation_conflict/suspend_state_beats_missing_explanation
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
        # 13000000 vs 12500000 period budget -> +4.00% >= 3.0: the variance
        # gate would fail (no explanation row exists).
        post_activity_in_period(gid, l1["id"], fund["id"], 13_000_000, "2026-06-20")
        edit_report(r1["id"])  # narrative + outcome present
        # Now suspend the grant: both the p5 state gate and the p9
        # variance-explanation gate are violated by the same submit.
        suspend_grant_with_material_weakness(gid)

        resp = api.submit_report(r1["id"], OFFICER)
        validate_error(resp, ApiErrorId.ERR_GRANT_SUSPENDED)

    def test_suspended_submit_state_error_regardless_of_content(self, api):
        """PRD §3.4: "Its guards, evaluated in the priority order of §2.10, are:
        the grant must not be `SUSPENDED` and the report must not be frozen — a
        violation is rejected with `ERR_GRANT_SUSPENDED`."
        PRD §2.10: state preconditions (category 5) are evaluated before the
        referential and submission-content rules of category 9.

        Design: Difficulty/priority_pair_validation_conflict/suspend_state_beats_missing_explanation
        """
        ctx = setup_active_grant(variance_threshold_pct=3.0)
        gid = ctx["grant"]["id"]
        r1 = ctx["reports"][0]
        set_clock("2026-06-15T00:00:00Z")
        start_report(r1["id"])
        # Deliberately leave narrative/outcome EMPTY so both the content gate
        # and the suspension gate would fail; suspension (p5) must still win.
        suspend_grant_with_material_weakness(gid, engagement_type="SITE_VISIT")

        resp = api.submit_report(r1["id"], OFFICER)
        validate_error(resp, ApiErrorId.ERR_GRANT_SUSPENDED)


class TestRestrictionBeatsFundOverflow:
    def test_restricted_fund_category_violation_beats_fiscal_cap(self, api):
        """PRD §2.10: "6. Fund restriction — a restricted fund's category gate,
        yielding `ERR_RESTRICTION_VIOLATION`." precedes "10. Fiscal limits —
        the per-allocation caps, yielding `ERR_EXPENSE_OVERALLOCATED`,
        `ERR_BUDGET_LINE_EXCEEDED`, and `ERR_FUND_EXCEEDED`."
        PRD §2.10: "a fiscal cap never masks a restriction violation."
        PRD §3.3: "If the chosen fund is `RESTRICTED`, the line's `category`
        must appear in the fund's `allowed_categories` (with an empty array
        permitting every category); otherwise the allocation is rejected with
        `ERR_RESTRICTION_VIOLATION` (HTTP 422)."

        Design: Difficulty/priority_pair_validation_conflict/restriction_beats_fund_overflow
        """
        # PRD §3.1: "Both budget-line and fund creation are only possible
        # while the grant is in `DRAFT`." — the restricted fund is added
        # pre-activation via extra_funds.
        ctx = setup_active_grant(
            lines=[{"category": "TRAVEL", "budgeted_cents": 20_000_000}],
            extra_funds=[{
                "fund_type": "RESTRICTED",
                "allocated_cents": 1000,
                "purpose_restriction": "program only",
                "allowed_categories": ["PERSONNEL", "SUPPLIES"],
            }],
        )
        gid = ctx["grant"]["id"]
        l2 = ctx["lines"][0]
        restricted = ctx["extra_funds"][0]
        set_clock("2026-06-15T00:00:00Z")
        expense = create_posted_expense(gid, amount_cents=5000)

        # 5000 > 1000 remaining in the fund AND TRAVEL not in
        # allowed_categories: both p6 and p10 fail; p6 must win.
        resp = api.create_allocation(
            expense["id"],
            {
                "budget_line_id": l2["id"],
                "fund_id": restricted["id"],
                "amount_cents": 5000,
            },
            OFFICER,
        )
        validate_error(resp, ApiErrorId.ERR_RESTRICTION_VIOLATION)

    def test_restricted_fund_violation_reported_even_with_ample_expense_room(self, api):
        """PRD §3.3: "If the chosen fund is `RESTRICTED`, the line's `category`
        must appear in the fund's `allowed_categories` (with an empty array
        permitting every category); otherwise the allocation is rejected with
        `ERR_RESTRICTION_VIOLATION` (HTTP 422)."
        PRD §2.10: fund restriction (category 6) is evaluated before business
        constraints, temporal rules, referential rules, and fiscal limits.

        Design: Difficulty/priority_pair_validation_conflict/restriction_beats_fund_overflow
        """
        # PRD §3.1: funds are created while the grant is DRAFT, so the
        # restricted fund is added pre-activation via extra_funds.
        ctx = setup_active_grant(
            lines=[{"category": "TRAVEL", "budgeted_cents": 20_000_000}],
            extra_funds=[{
                "fund_type": "RESTRICTED",
                "allocated_cents": 100_000_000,  # ample room: only the category gate fails
                "purpose_restriction": "program only",
                "allowed_categories": ["PERSONNEL", "SUPPLIES"],
            }],
        )
        gid = ctx["grant"]["id"]
        l2 = ctx["lines"][0]
        restricted = ctx["extra_funds"][0]
        set_clock("2026-06-15T00:00:00Z")
        expense = create_posted_expense(gid, amount_cents=5000)

        resp = api.create_allocation(
            expense["id"],
            {
                "budget_line_id": l2["id"],
                "fund_id": restricted["id"],
                "amount_cents": 5000,
            },
            OFFICER,
        )
        validate_error(resp, ApiErrorId.ERR_RESTRICTION_VIOLATION)
