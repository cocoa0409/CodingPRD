"""Expenses, allocations, and the void compensating path (PRD §3.3)."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    add_fund,
    allocate,
    assert_allocation,
    create_expense,
    create_posted_expense,
    edit_report,
    post_activity_in_period,
    set_clock,
    setup_active_grant,
    setup_draft_grant,
    start_report,
    submit_report,
    validate_error,
    validate_paginated,
    validate_success,
)

OFFICER = TEST_USERS["officer_headers"]
FINANCE = TEST_USERS["finance_headers"]


class TestAllocationGating:
    def test_allocation_on_draft_expense_rejected(self, api):
        """PRD §3.3: "Only a `POSTED` expense can be allocated."
        PRD §3.3: "Allocating against an expense still in `DRAFT` is rejected
        with `ERR_EXPENSE_NOT_POSTED` (HTTP 409)."

        Design: Difficulty/cross_entity_state_dependency/allocation_gated_on_expense_posted
        """
        ctx = setup_active_grant()
        set_clock("2026-06-15T00:00:00Z")
        expense = create_expense(ctx["grant"]["id"], amount_cents=100_000)
        assert expense["status"] == "DRAFT"

        resp = api.create_allocation(
            expense["id"],
            {
                "budget_line_id": ctx["lines"][0]["id"],
                "fund_id": ctx["fund"]["id"],
                "amount_cents": 40_000,
            },
            OFFICER,
        )
        validate_error(resp, ApiErrorId.ERR_EXPENSE_NOT_POSTED)

    def test_allocation_after_post_succeeds_and_updates_unallocated(self, api):
        """PRD §3.3: "the expense's `unallocated_cents` — its `amount_cents`
        minus the sum over its active allocations — is recomputed."
        PRD §3.3: "Each allocation row carries a system-set `status` of
        `ACTIVE` and records the allocator's `X-User-ID` as
        `created_by_user_id`."

        Design: Difficulty/cross_entity_state_dependency/allocation_gated_on_expense_posted
        """
        ctx = setup_active_grant()
        set_clock("2026-06-15T00:00:00Z")
        expense = create_posted_expense(ctx["grant"]["id"], amount_cents=100_000)

        resp = api.create_allocation(
            expense["id"],
            {
                "budget_line_id": ctx["lines"][0]["id"],
                "fund_id": ctx["fund"]["id"],
                "amount_cents": 40_000,
            },
            OFFICER,
        )
        allocation = validate_success(resp, expected_status=201)
        assert_allocation(allocation)
        assert allocation["status"] == "ACTIVE"

        fetched = validate_success(api.get_expense(expense["id"], OFFICER))
        assert fetched["unallocated_cents"] == 60_000, (
            f"100000 - 40000 must leave 60000 unallocated, got "
            f"{fetched['unallocated_cents']}"
        )


class TestExpenseVoid:
    def test_expense_void_from_draft_rejected(self, api):
        """PRD §3.3: "A `FinanceManager` may void a `POSTED` expense" — the
        POSTED -> VOIDED arc is the only void arc, so voiding a DRAFT expense is
        a generic state-machine rejection.
        PRD §5: `ERR_INVALID_STATE` (409) is the "generic state-machine
        rejection: trigger not valid from current state".

        Design: Corner/state_machines/expense_void_from_draft_rejected
        """
        ctx = setup_active_grant()
        expense = create_expense(ctx["grant"]["id"], amount_cents=100_000)

        resp = api.void_expense(expense["id"], FINANCE)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
        fetched = validate_success(api.get_expense(expense["id"], OFFICER))
        assert fetched["status"] == "DRAFT"

    def test_expense_post_void_conserves_fund_ledger(self, api):
        """PRD §3.3: "A successful void moves the expense to `VOIDED` and
        cascades: every active allocation of the expense transitions to
        `VOIDED`; for each voided allocation the corresponding budget line's
        `expended_cents` and fund's `expended_cents` are decremented by the
        allocation's amount; and the grant's `total_expended_cents` is
        recomputed."
        PRD §2.6: "When a posted expense is voided, every active allocation of
        that expense is voided with it and the affected budget-line, fund, and
        grant totals are decremented in the same transaction."

        Design: Difficulty/compensating_invariant/expense_post_void_conserves_fund_ledger
        """
        ctx = setup_active_grant()
        gid = ctx["grant"]["id"]
        l1 = ctx["lines"][0]
        fund = ctx["fund"]
        set_clock("2026-06-15T00:00:00Z")
        expense = create_posted_expense(gid, amount_cents=2_000_000)
        allocate(expense["id"], l1["id"], fund["id"], 2_000_000)

        funds, _ = validate_paginated(api.list_funds(gid, OFFICER))
        assert funds[0]["expended_cents"] == 2_000_000

        voided = validate_success(api.void_expense(expense["id"], FINANCE))
        assert voided["status"] == "VOIDED"

        funds_after, _ = validate_paginated(api.list_funds(gid, OFFICER))
        assert funds_after[0]["expended_cents"] == 0, (
            "the post+void pair must leave the fund ledger unchanged: "
            f"expected 0, got {funds_after[0]['expended_cents']}"
        )

        allocations, _ = validate_paginated(api.list_allocations(OFFICER))
        assert allocations[0]["status"] == "VOIDED", (
            "void must cascade ACTIVE -> VOIDED on every allocation of the "
            "expense"
        )

    def test_expense_void_locked_by_submitted_report(self, api):
        """PRD §3.3: "A `FinanceManager` may void a `POSTED` expense, but only
        while none of its active allocations has an `expense_date` falling
        inside a report period whose `Report` is `SUBMITTED`, `UNDER_REVIEW`, or
        `ACCEPTED`; if any allocation is so locked, the void is rejected with
        `ERR_EXPENSE_LOCKED_BY_REPORT` (HTTP 409)."

        Design: Corner/validations/expense_void_locked_by_submitted_report
        """
        ctx = setup_active_grant()
        gid = ctx["grant"]["id"]
        l1 = ctx["lines"][0]
        fund = ctx["fund"]
        r1 = ctx["reports"][0]

        set_clock("2026-06-15T00:00:00Z")
        expense = create_posted_expense(gid, amount_cents=2_000_000,
                                        expense_date="2026-06-20")
        allocate(expense["id"], l1["id"], fund["id"], 2_000_000)
        start_report(r1["id"])
        edit_report(r1["id"])
        # PRD §3.4 submit gate: "every budget line of the grant whose
        # period-only absolute variance percentage is at least the grant's
        # `variance_threshold_pct` must have a `VarianceExplanation` row".
        # Posting 2_000_000 against a 25_000_000 period budget produces a
        # -92% variance that breaches the default 10% threshold, so the
        # submit is gated until an explanation row exists.
        validate_success(api.create_variance_explanation(
            r1["id"],
            {"budget_line_id": l1["id"], "explanation_text": "slow ramp-up"},
            OFFICER,
        ), expected_status=201)
        submit_report(r1["id"])  # P1 report now SUBMITTED

        resp = api.void_expense(expense["id"], FINANCE)
        validate_error(resp, ApiErrorId.ERR_EXPENSE_LOCKED_BY_REPORT)


class TestFiscalCaps:
    def test_expense_overallocated_rejected(self, api):
        """PRD §3.3: "the allocation may not exceed the expense's
        `unallocated_cents` (`ERR_EXPENSE_OVERALLOCATED`, 422)".

        Design: Corner/validations/expense_overallocated_rejected
        """
        ctx = setup_active_grant()
        gid = ctx["grant"]["id"]
        l1 = ctx["lines"][0]
        fund = ctx["fund"]
        expense = create_posted_expense(gid, amount_cents=100_000)
        allocate(expense["id"], l1["id"], fund["id"], 60_000)

        resp = api.create_allocation(
            expense["id"],
            {
                "budget_line_id": l1["id"],
                "fund_id": fund["id"],
                "amount_cents": 50_000,
            },
            OFFICER,
        )
        validate_error(resp, ApiErrorId.ERR_EXPENSE_OVERALLOCATED)
        fetched = validate_success(api.get_expense(expense["id"], OFFICER))
        assert fetched["unallocated_cents"] == 40_000

    def test_budget_line_exceeded_trigger(self, api):
        """PRD §3.3: "it may not push the line's `expended_cents` above its
        `adjusted_cents` (`ERR_BUDGET_LINE_EXCEEDED`, 422)".

        Design: Corner/errors/budget_line_exceeded_trigger
        """
        ctx = setup_active_grant(
            lines=[{"category": "PERSONNEL", "budgeted_cents": 10_000_000}],
        )
        gid = ctx["grant"]["id"]
        l1 = ctx["lines"][0]
        fund = ctx["fund"]
        expense = create_posted_expense(gid, amount_cents=20_000_000)

        resp = api.create_allocation(
            expense["id"],
            {
                "budget_line_id": l1["id"],
                "fund_id": fund["id"],
                "amount_cents": 10_000_001,
            },
            OFFICER,
        )
        validate_error(resp, ApiErrorId.ERR_BUDGET_LINE_EXCEEDED)

    def test_fund_exceeded_trigger(self, api):
        """PRD §3.3: "and it may not push the fund's `expended_cents` above its
        `allocated_cents` (`ERR_FUND_EXCEEDED`, 422)."
        PRD §3.1: "Both budget-line and fund creation are only possible while
        the grant is in `DRAFT`." — additional funds are added pre-activation.

        Design: Corner/errors/fund_exceeded_trigger
        """
        ctx = setup_active_grant(
            extra_funds=[{"allocated_cents": 1000}],
        )
        gid = ctx["grant"]["id"]
        l1 = ctx["lines"][0]
        tiny_fund = ctx["extra_funds"][0]
        expense = create_posted_expense(gid, amount_cents=5000)

        resp = api.create_allocation(
            expense["id"],
            {
                "budget_line_id": l1["id"],
                "fund_id": tiny_fund["id"],
                "amount_cents": 5000,
            },
            OFFICER,
        )
        validate_error(resp, ApiErrorId.ERR_FUND_EXCEEDED)

    def test_cross_grant_allocation_reference_rejected(self, api):
        """PRD §3.3: "The referenced budget line and fund must both belong to
        the same grant as the expense; a cross-grant reference is rejected with
        `ERR_VALIDATION` (HTTP 400)."

        Design: Corner/validations/cross_grant_allocation_reference_rejected
        """
        ctx_a = setup_active_grant(
            lines=[{"category": "PERSONNEL", "budgeted_cents": 1_000_000}],
            award_amount_cents=1_000_000,
        )
        ctx_b = setup_active_grant(
            lines=[{"category": "PERSONNEL", "budgeted_cents": 1_000_000}],
            award_amount_cents=1_000_000,
        )
        expense_b = create_posted_expense(ctx_b["grant"]["id"], amount_cents=5000)

        resp = api.create_allocation(
            expense_b["id"],
            {
                "budget_line_id": ctx_a["lines"][0]["id"],  # belongs to grant A
                "fund_id": ctx_b["fund"]["id"],
                "amount_cents": 5000,
            },
            OFFICER,
        )
        validate_error(resp, ApiErrorId.ERR_VALIDATION)


class TestGrantActivityGuards:
    def test_expense_create_on_draft_grant_rejected(self, api):
        """PRD §3.3: "Creation is blocked unless the grant is `ACTIVE`: against
        a grant in `DRAFT`, `CLOSEOUT`, or `CLOSED` the create is rejected with
        `ERR_GRANT_NOT_ACTIVE` (HTTP 409), and against a `SUSPENDED` grant it is
        rejected with `ERR_GRANT_SUSPENDED` (HTTP 409)."

        Design: Corner/errors/expense_create_on_draft_grant_rejected
        """
        ctx = setup_draft_grant()  # never activated
        resp = api.create_expense(
            ctx["grant"]["id"],
            {
                "expense_date": "2026-06-20",
                "vendor": "V",
                "description": "D",
                "amount_cents": 5000,
            },
            OFFICER,
        )
        validate_error(resp, ApiErrorId.ERR_GRANT_NOT_ACTIVE)
