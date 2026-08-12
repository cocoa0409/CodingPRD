"""Timesheet billing cycle: creation gates, state machine, provisional vs
final variants, ceiling clamp, committed-spend filter, and budget guards."""
from test_helpers import (
    NON_EXISTENT_UUID,
    ApiErrorId,
    TEST_USERS,
    assert_timesheet,
    create_approved_timesheet,
    create_draft_timesheet,
    create_submitted_timesheet,
    get_engagement,
    get_success_data,
    get_supplier,
    get_timesheet,
    make_worker_headers,
    set_logical_clock,
    setup_staffed_assignment,
    validate_error,
    validate_paginated,
    validate_success,
)

ADMIN = TEST_USERS["program_admin_headers"]
HM = TEST_USERS["hiring_manager_headers"]
FIN = TEST_USERS["finance_analyst_headers"]


def test_timesheet_initial_state_draft(api):
    """PRD: "A new timesheet is in `DRAFT`, with `approved_hours`,
    `provisional_amount_cents`, `final_amount_cents`, `rejection_reason`,
    `void_reason`, `submitted_by_user_id` and `approved_by_user_id` all null."

    Design: Corner/state_machines/timesheet_initial_state_draft
    """
    ctx = setup_staffed_assignment()
    timesheet = validate_success(
        api.create_timesheet(
            {
                "assignment_id": ctx["assignment"]["id"],
                "period_start": "2026-05-04",
                "period_end": "2026-05-10",
                "submitted_hours": 8.0,
            },
            make_worker_headers(ctx["worker"]["id"]),
        ),
        expected_status=201,
    )
    assert_timesheet(timesheet)
    assert timesheet["status"] == "DRAFT"
    assert timesheet["provisional_amount_cents"] is None, (
        "provisional is computed only at submit"
    )
    assert timesheet["final_amount_cents"] is None
    assert timesheet["approved_hours"] is None
    assert timesheet["submitted_by_user_id"] is None
    assert timesheet["approved_by_user_id"] is None


class TestTimesheetRequiresAssignmentActive:
    def test_create_on_pending_assignment_rejected(self, api):
        """PRD: "And both creation and submission require the assignment to
        be `ACTIVE`; against a non-active assignment the request fails with
        `ERR_ASSIGNMENT_NOT_ACTIVE` (409)."

        Design: Difficulty/cross_entity_state_dependency/timesheet_requires_assignment_active
        """
        ctx = setup_staffed_assignment(activate=False)
        assert ctx["assignment"]["status"] == "PENDING"
        resp = api.create_timesheet(
            {
                "assignment_id": ctx["assignment"]["id"],
                "period_start": "2026-05-04",
                "period_end": "2026-05-10",
                "submitted_hours": 8.0,
            },
            make_worker_headers(ctx["worker"]["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_ASSIGNMENT_NOT_ACTIVE)

    def test_rejected_create_persists_no_timesheet(self, api):
        """PRD: "And both creation and submission require the assignment to
        be `ACTIVE`; against a non-active assignment the request fails with
        `ERR_ASSIGNMENT_NOT_ACTIVE` (409)."

        Design: Difficulty/cross_entity_state_dependency/timesheet_requires_assignment_active
        """
        ctx = setup_staffed_assignment(activate=False)
        validate_error(
            api.create_timesheet(
                {
                    "assignment_id": ctx["assignment"]["id"],
                    "period_start": "2026-05-04",
                    "period_end": "2026-05-10",
                    "submitted_hours": 8.0,
                },
                make_worker_headers(ctx["worker"]["id"]),
            ),
            ApiErrorId.ERR_ASSIGNMENT_NOT_ACTIVE,
        )
        _, meta = validate_paginated(
            api.list_timesheets(ADMIN, params={"assignment_id": ctx["assignment"]["id"]})
        )
        assert meta["total_count"] == 0, "the gated create persists no timesheet"


def test_approve_draft_timesheet_rejected(api):
    """PRD: "Approval belongs to the `HiringManager` and computes the `FINAL`
    variant." (declared from `SUBMITTED`)
    PRD: "State validity — the target resource must be in a valid from-state
    for the requested transition. A generic wrong-from-state rejection is
    `ERR_INVALID_STATE` (409)"

    Design: Corner/state_machines/approve_draft_timesheet_rejected
    """
    ctx = setup_staffed_assignment()
    timesheet = create_draft_timesheet(
        ctx["assignment"]["id"], ctx["worker"]["id"], submitted_hours=8.0
    )
    resp = api.approve_timesheet(timesheet["id"], {}, HM)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
    after = get_timesheet(timesheet["id"])
    assert after["status"] == "DRAFT", "no partial mutation"
    _, meta = validate_paginated(
        api.list_spend_ledger_entries(FIN, params={"timesheet_id": timesheet["id"]})
    )
    assert meta["total_count"] == 0, "no ledger entry for a rejected approval"
    _, meta_inv = validate_paginated(
        api.list_invoices(FIN, params={"supplier_id": ctx["supplier"]["id"]})
    )
    assert meta_inv["total_count"] == 0, "no invoice auto-created"
    assert get_engagement(ctx["engagement"]["id"])["committed_spend_cents"] == 0


def test_double_approve_rejected(api):
    """PRD: "State validity — the target resource must be in a valid
    from-state for the requested transition. A generic wrong-from-state
    rejection is `ERR_INVALID_STATE` (409)"
    PRD: "Link 1: a spend ledger entry of type `TIMESHEET_APPROVED` is
    appended with a positive `delta_cents` equal to `final_amount_cents`, and
    the supplier's `spend_ytd_cents` is recomputed."

    Design: Corner/state_machines/double_approve_rejected
    """
    ctx = setup_staffed_assignment(bill_rate_cents=9000)
    timesheet = create_approved_timesheet(
        ctx["assignment"]["id"], ctx["worker"]["id"], submitted_hours=10.0
    )
    assert timesheet["status"] == "APPROVED"
    assert timesheet["final_amount_cents"] == 90_000

    resp = api.approve_timesheet(timesheet["id"], {}, HM)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
    entries, meta = validate_paginated(
        api.list_spend_ledger_entries(FIN, params={"timesheet_id": timesheet["id"]})
    )
    assert meta["total_count"] == 1, "approval side effects fired exactly once"
    assert entries[0]["delta_cents"] == 90_000
    assert get_supplier(ctx["supplier"]["id"])["spend_ytd_cents"] == 90_000, (
        "no double-count"
    )


class TestHoursBoundary:
    def test_exactly_60_hours_accepted(self, api):
        """PRD: "a decimal value with at most two decimal places and at most
        60.00, where exactly 60.00 is allowed and anything larger is rejected
        with `ERR_HOURS_EXCEED_MAX` (422)."

        Design: Corner/errors/weekly_hours_max_boundary
        """
        ctx = setup_staffed_assignment(
            engagement_overrides={"budget_cents": 5_000_000}
        )
        timesheet = validate_success(
            api.create_timesheet(
                {
                    "assignment_id": ctx["assignment"]["id"],
                    "period_start": "2026-05-04",
                    "period_end": "2026-05-10",
                    "submitted_hours": 60.0,
                },
                make_worker_headers(ctx["worker"]["id"]),
            ),
            expected_status=201,
        )
        assert timesheet["submitted_hours"] == 60.0, "boundary value allowed"

    def test_60_01_hours_rejected(self, api):
        """PRD: "a decimal value with at most two decimal places and at most
        60.00, where exactly 60.00 is allowed and anything larger is rejected
        with `ERR_HOURS_EXCEED_MAX` (422)."

        Design: Corner/errors/weekly_hours_max_boundary
        """
        ctx = setup_staffed_assignment(
            engagement_overrides={"budget_cents": 5_000_000}
        )
        resp = api.create_timesheet(
            {
                "assignment_id": ctx["assignment"]["id"],
                "period_start": "2026-05-11",
                "period_end": "2026-05-17",
                "submitted_hours": 60.01,
            },
            make_worker_headers(ctx["worker"]["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_HOURS_EXCEED_MAX)


def test_duplicate_timesheet_period_returns_409(api):
    """PRD: "Only one timesheet may exist per assignment per `period_start`;
    a second one yields `ERR_DUPLICATE_TIMESHEET_PERIOD` (409)."

    Design: Corner/errors/duplicate_timesheet_period_returns_409
    """
    ctx = setup_staffed_assignment()
    create_draft_timesheet(
        ctx["assignment"]["id"], ctx["worker"]["id"],
        period_start="2026-05-04", period_end="2026-05-10", submitted_hours=8.0,
    )
    resp = api.create_timesheet(
        {
            "assignment_id": ctx["assignment"]["id"],
            "period_start": "2026-05-04",
            "period_end": "2026-05-10",
            "submitted_hours": 6.0,
        },
        make_worker_headers(ctx["worker"]["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_DUPLICATE_TIMESHEET_PERIOD)
    _, meta = validate_paginated(
        api.list_timesheets(ADMIN, params={"assignment_id": ctx["assignment"]["id"]})
    )
    assert meta["total_count"] == 1, "the first timesheet is untouched"


def test_timesheet_period_outside_assignment_rejected(api):
    """PRD: "The period must lie entirely inside the assignment's
    `start_date` to `end_date` span, else `ERR_PERIOD_OUTSIDE_ASSIGNMENT`
    (422)."

    Design: Corner/validations/timesheet_period_outside_assignment_rejected
    """
    ctx = setup_staffed_assignment(start_date="2026-05-01", end_date="2026-08-31")
    resp = api.create_timesheet(
        {
            "assignment_id": ctx["assignment"]["id"],
            "period_start": "2026-04-27",
            "period_end": "2026-05-03",
            "submitted_hours": 8.0,
        },
        make_worker_headers(ctx["worker"]["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_PERIOD_OUTSIDE_ASSIGNMENT)
    # period_start 2026-04-27 precedes the assignment's 2026-05-01 start


class TestProvisionalVsFinalBilling:
    def test_provisional_uses_submitted_hours_unclamped_rate(self, api):
        """PRD: "computes the `PROVISIONAL` billing variant:
        `provisional_amount_cents` is the `submitted_hours` multiplied by the
        assignment's unclamped `bill_rate_cents`, rounded half up to whole
        cents."

        Design: Difficulty/dual_variant_calc/timesheet_provisional_vs_final_billing
        """
        ctx = setup_staffed_assignment(bill_rate_cents=9500, pay_rate_cents=8000)
        timesheet = create_draft_timesheet(
            ctx["assignment"]["id"], ctx["worker"]["id"],
            period_start="2026-05-04", period_end="2026-05-10",
            submitted_hours=37.5,
        )
        submitted = validate_success(
            api.submit_timesheet(
                timesheet["id"], make_worker_headers(ctx["worker"]["id"])
            )
        )
        assert submitted["status"] == "SUBMITTED"
        assert submitted["submitted_by_user_id"] == ctx["worker"]["id"]
        assert submitted["provisional_amount_cents"] == 356_250, (
            "37.5 x 9500 with the unclamped bill rate"
        )

    def test_final_uses_approved_hours_and_is_the_only_ledgered_variant(self, api):
        """PRD: "The provisional amount is an estimate only — it is never
        ledgered."
        PRD: "`final_amount_cents` is the `approved_hours` multiplied by that
        effective rate, rounded half up to whole cents."
        PRD: "Link 1: a spend ledger entry of type `TIMESHEET_APPROVED` is
        appended with a positive `delta_cents` equal to `final_amount_cents`,
        and the supplier's `spend_ytd_cents` is recomputed."

        Design: Difficulty/dual_variant_calc/timesheet_provisional_vs_final_billing
        """
        ctx = setup_staffed_assignment(bill_rate_cents=9500, pay_rate_cents=8000)
        timesheet = create_submitted_timesheet(
            ctx["assignment"]["id"], ctx["worker"]["id"],
            period_start="2026-05-04", period_end="2026-05-10",
            submitted_hours=37.5,
        )
        approved = validate_success(
            api.approve_timesheet(timesheet["id"], {"approved_hours": 35.0}, HM)
        )
        assert approved["status"] == "APPROVED"
        assert approved["approved_hours"] == 35.0
        assert approved["final_amount_cents"] == 332_500, (
            "35.0 x min(9500, 12000) — the two variants diverge on identical "
            "assignment/rate data"
        )
        entries, meta = validate_paginated(
            api.list_spend_ledger_entries(FIN, params={"timesheet_id": timesheet["id"]})
        )
        assert meta["total_count"] == 1
        assert entries[0]["entry_type"] == "TIMESHEET_APPROVED"
        assert entries[0]["delta_cents"] == 332_500, (
            "only the FINAL variant is ledgered; the provisional 356250 never "
            "touches the ledger"
        )
        assert get_supplier(ctx["supplier"]["id"])["spend_ytd_cents"] == 332_500


class TestApprovalClampsToRevisedCeiling:
    def _setup_submitted_under_original_card(self, api):
        ctx = setup_staffed_assignment(
            card_overrides={"effective_from": "2026-01-01",
                            "effective_to": "2026-06-01"},
            bill_rate_cents=9500,
            pay_rate_cents=8000,
            start_date="2026-05-04",
            end_date="2026-08-31",
        )
        set_logical_clock("2026-05-20T00:00:00Z")
        timesheet = create_submitted_timesheet(
            ctx["assignment"]["id"], ctx["worker"]["id"],
            period_start="2026-05-18", period_end="2026-05-24",
            submitted_hours=10.0,
        )
        return ctx, timesheet

    def test_provisional_computed_under_original_ceiling(self, api):
        """PRD: "computes the `PROVISIONAL` billing variant:
        `provisional_amount_cents` is the `submitted_hours` multiplied by the
        assignment's unclamped `bill_rate_cents`, rounded half up to whole
        cents."

        Design: Corner/calculations/approval_clamps_to_revised_ceiling
        """
        _ctx, timesheet = self._setup_submitted_under_original_card(api)
        assert timesheet["provisional_amount_cents"] == 95_000, (
            "10.0 x 9500 submitted while the 12000-ceiling card governs"
        )

    def test_final_clamped_to_revision_governing_approval_date(self, api):
        """PRD: "The effective rate for the final amount is the smaller of
        the assignment's `bill_rate_cents` and the governing rate card's
        `bill_rate_ceiling_cents` — the governing card being the `ACTIVE`
        card for the engagement's key whose half-open window contains the
        logical clock date at approval time, so the ceiling clamp binds
        exactly when the governing card changed between submit and approve."

        Design: Corner/calculations/approval_clamps_to_revised_ceiling
        """
        ctx, timesheet = self._setup_submitted_under_original_card(api)
        revision = get_success_data(
            api.create_rate_card_revision(
                ctx["rate_card"]["id"],
                {
                    "expected_rate_card_version": ctx["rate_card"]["version"],
                    "bill_rate_ceiling_cents": 9000,
                    "effective_from": "2026-06-01",
                    "effective_to": "2027-01-01",
                },
                ADMIN,
            )
        )
        assert revision["supersedes_id"] == ctx["rate_card"]["id"]
        get_success_data(api.activate_rate_card(revision["id"], ADMIN))
        set_logical_clock("2026-06-15T00:00:00Z")

        approved = validate_success(api.approve_timesheet(timesheet["id"], {}, HM))
        assert approved["final_amount_cents"] == 90_000, (
            "10.0 x min(9500, 9000) — the revision governing the approval date "
            "clamps the rate"
        )
        original_after = get_success_data(api.get_rate_card(ctx["rate_card"]["id"], ADMIN))
        revision_after = get_success_data(api.get_rate_card(revision["id"], ADMIN))
        assert original_after["status"] == "ACTIVE"
        assert revision_after["status"] == "ACTIVE", (
            "both cards ACTIVE with disjoint half-open windows "
            "([2026-01-01, 2026-06-01) and [2026-06-01, 2027-01-01))"
        )


class TestCommittedSpendStateFilter:
    def _setup_submitted_and_rejected(self, api):
        ctx = setup_staffed_assignment(bill_rate_cents=9000)
        t1 = create_submitted_timesheet(
            ctx["assignment"]["id"], ctx["worker"]["id"],
            period_start="2026-05-04", period_end="2026-05-10",
            submitted_hours=10.0,
        )
        t2 = create_submitted_timesheet(
            ctx["assignment"]["id"], ctx["worker"]["id"],
            period_start="2026-05-11", period_end="2026-05-17",
            submitted_hours=5.0,
        )
        rejected = get_success_data(
            api.reject_timesheet(t2["id"], {"reason": "bad cost code"}, HM)
        )
        assert rejected["status"] == "REJECTED"
        return ctx, t1, t2

    def test_submitted_and_rejected_contribute_zero(self, api):
        """PRD: "Timesheets in `DRAFT`, `SUBMITTED`, `REJECTED` or `VOIDED`
        contribute zero; milestones `DELIVERED` or `REJECTED` contribute zero
        — the state filter is explicit, not incidental."

        Design: Corner/calculations/committed_spend_excludes_non_approved_states
        """
        ctx, _t1, _t2 = self._setup_submitted_and_rejected(api)
        engagement = get_engagement(ctx["engagement"]["id"])
        assert engagement["committed_spend_cents"] == 0, (
            "SUBMITTED 10h and REJECTED 5h both excluded"
        )

    def test_only_approved_finals_enter_committed_spend(self, api):
        """PRD: "Committed spend, referenced by every budget guard above, is
        defined precisely: the sum of `final_amount_cents` over the
        engagement's timesheets in `APPROVED` status, plus the sum of
        `amount_cents` over the engagement's milestones in `ACCEPTED`
        acceptance status."

        Design: Corner/calculations/committed_spend_excludes_non_approved_states
        """
        ctx, t1, _t2 = self._setup_submitted_and_rejected(api)
        validate_success(api.approve_timesheet(t1["id"], {}, HM))
        engagement = get_engagement(ctx["engagement"]["id"])
        assert engagement["committed_spend_cents"] == 90_000, (
            "T1's approved final enters; REJECTED T2 still excluded"
        )


class TestBudgetExactFit:
    def _setup_tight_budget(self, api):
        ctx = setup_staffed_assignment(
            bill_rate_cents=8000, pay_rate_cents=8000,
            engagement_overrides={"budget_cents": 400_000, "duration_months": 3},
        )
        t1 = create_approved_timesheet(
            ctx["assignment"]["id"], ctx["worker"]["id"],
            period_start="2026-05-04", period_end="2026-05-10",
            submitted_hours=40.0,
        )
        t2 = create_approved_timesheet(
            ctx["assignment"]["id"], ctx["worker"]["id"],
            period_start="2026-05-11", period_end="2026-05-17",
            submitted_hours=10.0,
        )
        return ctx, t1, t2

    def test_exact_budget_fit_approval_allowed(self, api):
        """PRD: "the engagement's `committed_spend_cents` plus this
        `final_amount_cents` must not exceed `budget_cents` — an exact fit is
        allowed — otherwise approval is rejected with `ERR_BUDGET_EXCEEDED`
        (422)."

        Design: Corner/validations/budget_exact_fit_allowed_then_next_cent_rejected
        """
        ctx, t1, t2 = self._setup_tight_budget(api)
        assert t1["final_amount_cents"] == 320_000
        assert t2["final_amount_cents"] == 80_000
        engagement = get_engagement(ctx["engagement"]["id"])
        assert engagement["committed_spend_cents"] == 400_000
        assert engagement["committed_spend_cents"] == engagement["budget_cents"], (
            "<= allows equality"
        )

    def test_next_cent_over_budget_rejected(self, api):
        """PRD: "the engagement's `committed_spend_cents` plus this
        `final_amount_cents` must not exceed `budget_cents` — an exact fit is
        allowed — otherwise approval is rejected with `ERR_BUDGET_EXCEEDED`
        (422)."

        Design: Corner/validations/budget_exact_fit_allowed_then_next_cent_rejected
        """
        ctx, _t1, _t2 = self._setup_tight_budget(api)
        t3 = create_submitted_timesheet(
            ctx["assignment"]["id"], ctx["worker"]["id"],
            period_start="2026-05-18", period_end="2026-05-24",
            submitted_hours=0.01,
        )
        resp = api.approve_timesheet(t3["id"], {}, HM)
        validate_error(resp, ApiErrorId.ERR_BUDGET_EXCEEDED)
        # 0.01h x 8000 = 80 cents; 400000 + 80 > 400000
        assert get_timesheet(t3["id"])["status"] == "SUBMITTED", (
            "rejected approval leaves the timesheet SUBMITTED"
        )
        assert get_engagement(ctx["engagement"]["id"])["committed_spend_cents"] == 400_000


class TestApproveStateBeforeFiscal:
    def _setup_rejected_timesheet_over_budget(self, api):
        ctx = setup_staffed_assignment(
            bill_rate_cents=9500, pay_rate_cents=8000,
            engagement_overrides={"budget_cents": 400_000, "duration_months": 3},
        )
        create_approved_timesheet(
            ctx["assignment"]["id"], ctx["worker"]["id"],
            period_start="2026-05-04", period_end="2026-05-10",
            submitted_hours=40.0,
        )  # commits 380000 of 400000
        t2 = create_submitted_timesheet(
            ctx["assignment"]["id"], ctx["worker"]["id"],
            period_start="2026-05-11", period_end="2026-05-17",
            submitted_hours=10.0,
        )
        get_success_data(
            api.reject_timesheet(t2["id"], {"reason": "wrong project code"}, HM)
        )
        return ctx, t2

    def test_approve_rejected_timesheet_yields_invalid_state_not_budget_exceeded(self, api):
        """PRD: "A single request can violate several rules at once. When it
        does, the error that surfaces is determined by a fixed precedence
        order, evaluated from first to last:"
        PRD: "5. **State validity** — the target resource must be in a valid
        from-state for the requested transition. A generic wrong-from-state
        rejection is `ERR_INVALID_STATE` (409)"
        PRD: "10. **Fiscal limits** — rate ceilings, markup caps, pay floors,
        budget limits and empty invoices"

        Design: Difficulty/priority_pair_validation_conflict/timesheet_approve_state_before_fiscal
        """
        ctx, t2 = self._setup_rejected_timesheet_over_budget(api)
        resp = api.approve_timesheet(t2["id"], {}, HM)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
        assert resp.json()["data"]["error_id"] != "ERR_BUDGET_EXCEEDED", (
            "the state failure (timesheet REJECTED) outranks the fiscal failure "
            "(95000 > 20000 remaining)"
        )

    def test_failed_approve_leaves_no_ledger_or_line(self, api):
        """PRD: "Link 1: a spend ledger entry of type `TIMESHEET_APPROVED` is
        appended with a positive `delta_cents` equal to `final_amount_cents`"
        — the side effects belong to a successful approval.
        PRD: "Rejection moves `SUBMITTED` → `REJECTED` and records the
        request's `reason` into `rejection_reason`"

        Design: Difficulty/priority_pair_validation_conflict/timesheet_approve_state_before_fiscal
        """
        ctx, t2 = self._setup_rejected_timesheet_over_budget(api)
        validate_error(
            api.approve_timesheet(t2["id"], {}, HM), ApiErrorId.ERR_INVALID_STATE
        )
        after = get_timesheet(t2["id"])
        assert after["status"] == "REJECTED"
        assert after["final_amount_cents"] is None
        _, meta_ledger = validate_paginated(
            api.list_spend_ledger_entries(FIN, params={"timesheet_id": t2["id"]})
        )
        assert meta_ledger["total_count"] == 0
        _, meta_lines = validate_paginated(
            api.list_invoice_lines(FIN, params={"timesheet_id": t2["id"]})
        )
        assert meta_lines["total_count"] == 0


def test_approve_nonexistent_timesheet_returns_not_found(api):
    """PRD: "Existence — path identifiers resolve left to right; a missing
    resource yields `ERR_NOT_FOUND` (404)."
    PRD: "A single request can violate several rules at once. When it does,
    the error that surfaces is determined by a fixed precedence order,
    evaluated from first to last:"

    Design: Corner/validations/priority_existence_before_state
    """
    resp = api.approve_timesheet(NON_EXISTENT_UUID, {}, HM)
    validate_error(resp, ApiErrorId.ERR_NOT_FOUND)
    assert resp.status_code == 404, "existence outranks state"
