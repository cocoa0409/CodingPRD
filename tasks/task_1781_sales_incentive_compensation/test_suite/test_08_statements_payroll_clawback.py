"""Payout statements, payroll export, and the cancel-after-close clawback
chain; the draw-ledger conservation invariant; plan effectiveness analytics."""
from test_helpers import (
    ApiErrorId,
    CANONICAL_CURVE_TIERS,
    TEST_USERS,
    assert_draw_ledger_invariant,
    assert_payroll_export,
    book_transaction,
    cancel_transaction,
    close_period,
    create_payroll_export_payload,
    create_program,
    create_rep,
    get_assignment,
    get_only_credit_entry,
    get_program,
    get_statement_for,
    list_adjustments,
    setup_accepted_assignment,
    setup_assignment,
    setup_closed_period,
    setup_exported_period,
    setup_manager_rep,
    setup_program_with_plan,
    terminate_assignment,
    validate_error,
    validate_paginated,
    validate_success,
)

ADMIN = TEST_USERS["comp_admin_headers"]
MANAGER = TEST_USERS["comp_manager_headers"]


class TestPayrollExport:
    def test_payroll_export_immutable_record(self, api):
        """PRD §2.5: "Because an export is an immutable, append-only record of
        a payout file, it carries only `id` and `created_at`; both `updated_at`
        and `version` are absent from it."
        PRD §3.8: "A successful export transitions every approved statement of
        the program and period from `APPROVED` to `EXPORTED`, collects their
        identifiers into the export's `statement_ids`, records their number as
        `statement_count`, and sums their `net_payable_cents` into
        `total_cents`."

        Design: Corner/entities/payroll_export_immutable_record
        """
        sc = setup_exported_period(program_name="Prog PE", plan_name="Plan PE",
                                   rep_name="Rep PE", employee_ref="PE-R1",
                                   amount_cents=200000)
        export = sc["export"]
        assert_payroll_export(export)
        # Flat 10% curve over 200000 earned: net 20000.
        assert export["total_cents"] == 20000
        assert export["statement_count"] == 1
        assert export["statement_ids"] == [sc["statement"]["id"]]

        exports, meta = validate_paginated(
            api.list_payroll_exports(sc["program"]["id"], ADMIN))
        assert len(exports) == 1
        assert exports[0]["id"] == export["id"]

    def test_export_of_open_period_rejected(self, api):
        """PRD §3.8: "The temporal guard fires first: the period must already
        be closed — a `period_index` that has reached or passed the program's
        `current_period_index` is rejected with
        `ERR_PAYROLL_PERIOD_NOT_CLOSED`."

        Design: Corner/validations/payroll_export_open_period_rejected
        """
        program = create_program("Prog PO")  # current_period_index == 1
        resp = api.create_payroll_export(
            create_payroll_export_payload(program["id"], 1), ADMIN)
        validate_error(resp, ApiErrorId.ERR_PAYROLL_PERIOD_NOT_CLOSED, 409)

    def test_duplicate_payroll_export_rejected(self, api):
        """PRD §3.8: "One export exists per program and period; a second
        attempt is rejected with `ERR_PAYROLL_EXPORT_EXISTS`."
        PRD §3.8: "That total relieves the program's accrual:
        `accrued_balance_cents` decreases by `total_cents`, completing the
        liability cycle that period close began."

        Design: Corner/validations/payroll_export_duplicate_rejected
        """
        sc = setup_exported_period(program_name="Prog PX", plan_name="Plan PX",
                                   rep_name="Rep PX", employee_ref="PX-R1",
                                   amount_cents=200000)
        assert sc["program"]["accrued_balance_cents"] == 0, (
            "the accrual (20000 after close) was relieved exactly once"
        )

        resp = api.create_payroll_export(
            create_payroll_export_payload(sc["program"]["id"], 1), ADMIN)
        validate_error(resp, ApiErrorId.ERR_PAYROLL_EXPORT_EXISTS, 409)
        assert get_program(sc["program"]["id"])["accrued_balance_cents"] == 0

    def test_export_blocked_by_draft_statement(self, api):
        """PRD §3.8: "And every statement of that program and period must
        already be `APPROVED` — a single lingering `DRAFT` statement blocks the
        export with `ERR_STATEMENTS_NOT_APPROVED`."

        Design: Corner/validations/payroll_export_with_draft_statements_rejected
        """
        sc = setup_closed_period(program_name="Prog PU", plan_name="Plan PU",
                                 rep_name="Rep PU", employee_ref="PU-R1",
                                 amount_cents=200000)
        assert sc["statement"]["status"] == "DRAFT"

        resp = api.create_payroll_export(
            create_payroll_export_payload(sc["program"]["id"], 1), ADMIN)
        validate_error(resp, ApiErrorId.ERR_STATEMENTS_NOT_APPROVED, 409)
        stmt = get_statement_for(sc["assignment"]["id"], 1)
        assert stmt["status"] == "DRAFT"
        exports, _meta = validate_paginated(
            api.list_payroll_exports(sc["program"]["id"], ADMIN))
        assert exports == []

    def test_approve_exported_statement_rejected(self, api):
        """PRD §2.9: "**State preconditions** — the target resource is in a
        valid from-state for the requested transition. Where a dedicated code
        exists it is used — `ERR_PLAN_NOT_PUBLISHED` on assignment creation and
        acceptance, `ERR_TRANSACTION_ALREADY_CANCELLED` on a repeat cancel —
        and all other illegal transitions, including acting on terminal states,
        surface `ERR_INVALID_STATE_TRANSITION`."
        PRD §3.7: "Statements rest in `DRAFT` until a `CompManager` approves
        them — approval moves a statement from `DRAFT` to `APPROVED` and is the
        prerequisite for payroll export."

        Design: Corner/state_machines/statement_approve_after_export_rejected
        """
        sc = setup_exported_period(program_name="Prog SX", plan_name="Plan SX",
                                   rep_name="Rep SX", employee_ref="SX-R1",
                                   amount_cents=200000)
        resp = api.approve_statement(sc["statement"]["id"], MANAGER)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE_TRANSITION, 409)
        stmt = get_statement_for(sc["assignment"]["id"], 1)
        assert stmt["status"] == "EXPORTED"


class TestClawbackChain:
    def _scenario(self, api):
        """Manager + rep (rollup 5000), 200000 to the rep posted in period 1,
        period 1 closed (credits LOCKED); cancel lands in open period 2."""
        sc = setup_manager_rep(program_name="Prog Claw", plan_name="Plan CL",
                               rollup_rate_bps=5000,
                               curve_tiers=CANONICAL_CURVE_TIERS,
                               manager_ref="CL-M1", rep_ref="CL-R1")
        txn = book_transaction(sc["program"]["id"], "CL-T1", 200000,
                               [{"rep_id": sc["rep"]["id"], "split_bps": 10000}])
        close_period(sc["program"]["id"])
        return sc, txn

    def test_cancel_reverses_locked_credits(self, api):
        """PRD §3.5: "Cancellation is a deep reversal: every credit entry of
        the transaction in `PENDING`, `POSTED`, or `LOCKED` moves to
        `REVERSED`, roll-up children included — reversing any entry likewise
        reverses its own `ROLLUP` children still in `PENDING` or `POSTED`
        under the same rules."

        Design: Difficulty/transitive_cascade/transaction_cancel_clawback_chain
        """
        sc, txn = self._scenario(api)
        direct = get_only_credit_entry(transaction_id=txn["id"],
                                       rep_id=sc["rep"]["id"])
        cancelled = cancel_transaction(txn["id"])
        assert cancelled["status"] == "CANCELLED"

        assert (get_only_credit_entry(transaction_id=txn["id"],
                                      rep_id=sc["rep"]["id"])
                ["status"] == "REVERSED")
        rollup = get_only_credit_entry(parent_credit_id=direct["id"])
        assert rollup["status"] == "REVERSED"

    def test_locked_reversal_spawns_clawback_adjustments(self, api):
        """PRD §3.5: "Reversing a `LOCKED` entry — which only transaction
        cancellation can do, since locked credits survive assignment
        termination — does not rewrite the closed period; instead it creates a
        **clawback adjustment** on that entry's assignment: an `Adjustment`
        with `source` equal to `CLAWBACK`, `amount_cents` equal to the negated
        credit amount, `status` already `APPROVED`, and `period_index` set to
        the current open period, where it will settle at the next close."

        Design: Difficulty/transitive_cascade/transaction_cancel_clawback_chain
        """
        sc, txn = self._scenario(api)
        cancel_transaction(txn["id"])

        rep_adjustments = list_adjustments(
            assignment_id=sc["rep_assignment"]["id"])
        assert len(rep_adjustments) == 1
        adj = rep_adjustments[0]
        assert adj["amount_cents"] == -200000
        assert adj["source"] == "CLAWBACK"
        assert adj["status"] == "APPROVED"
        assert adj["period_index"] == 2, "the clawback settles into the open period"

        manager_adjustments = list_adjustments(
            assignment_id=sc["manager_assignment"]["id"])
        assert len(manager_adjustments) == 1
        assert manager_adjustments[0]["amount_cents"] == -100000
        assert manager_adjustments[0]["source"] == "CLAWBACK"

        assert (get_assignment(sc["rep_assignment"]["id"])
                ["current_period_earned_cents"] == 0), (
            "a LOCKED reversal does not touch the open-period earned counter"
        )


class TestDrawLedgerConservation:
    def _scenario(self, api):
        """Recoverable 50000-draw assignment, no transactions."""
        return setup_accepted_assignment(
            program_name="Prog Draw", plan_name="Plan DR", rep_name="Rep DR",
            employee_ref="DR-R1",
            assignment_overrides={"draw_amount_cents_per_period": 50000,
                                  "draw_recoverable": True})

    def test_draw_accrues_into_outstanding_at_close(self, api):
        """PRD §3.7: "`draw_paid_cents` equals the assignment's
        `draw_amount_cents_per_period`, since the assignment is `ACTIVE` at
        close. When the assignment is `draw_recoverable`, the paid draw first
        accrues: `draw_outstanding_cents` increases by the paid amount."
        PRD §3.7: "The draw ledger maintains one invariant at every observable
        instant: `draw_outstanding_cents` equals the recoverable draws paid
        across all of the assignment's closed statements, minus the
        `draw_recovered_cents` across those statements, minus the
        `draw_forgiven_cents` recorded against the assignment."

        Design: Difficulty/compensating_invariant/draw_ledger_conservation
        """
        sc = self._scenario(api)
        close_period(sc["program"]["id"])
        stmt = get_statement_for(sc["assignment"]["id"], 1)
        assert stmt["draw_paid_cents"] == 50000
        assert stmt["draw_recovered_cents"] == 0, "gross is 0, nothing to recover from"
        assert stmt["net_payable_cents"] == 0

        assignment = get_assignment(sc["assignment"]["id"])
        assert assignment["draw_outstanding_cents"] == 50000
        assert_draw_ledger_invariant(assignment, [stmt])

    def test_termination_forgives_draw_debt(self, api):
        """PRD §3.3: "Finally, if the assignment is `draw_recoverable`, its
        remaining draw debt is forgiven in full: `draw_forgiven_cents`
        increases by `draw_outstanding_cents`, which is then zeroed."

        Design: Difficulty/compensating_invariant/draw_ledger_conservation
        """
        sc = self._scenario(api)
        close_period(sc["program"]["id"])
        stmt = get_statement_for(sc["assignment"]["id"], 1)

        terminated = terminate_assignment(sc["assignment"]["id"])
        assert terminated["status"] == "TERMINATED"
        assert terminated["draw_forgiven_cents"] == 50000
        assert terminated["draw_outstanding_cents"] == 0
        assert_draw_ledger_invariant(terminated, [stmt])


class TestPlanEffectiveness:
    def test_plan_effectiveness_aggregation(self, api):
        """PRD §3.9: "The report carries the `plan_id`; `assignments_count`,
        the count of all assignments of the plan regardless of status;
        `statements_count`, the size of the source set; `avg_attainment_bps`,
        the sum of the statements' `attainment_bps` divided by the statement
        count and rounded down to a whole number — zero when no statements
        exist; `total_earned_cents`, the sum of `earned_total_cents`; and
        `total_payout_cents`, the sum of `net_payable_cents`."
        PRD §3.9: "A `distribution` object buckets statements by attainment
        with inclusive lower bounds and exclusive upper bounds: `LT_8000`
        counts attainment below 8000 basis points, `B8000_10000` counts
        attainment of at least 8000 and below 10000, and `GTE_10000` counts
        attainment of at least 10000 — quota achieved or better."

        Design: Corner/calculations/plan_effectiveness_aggregation
        """
        sc = setup_program_with_plan(program_name="Prog AN", plan_name="Plan AN",
                                     curve_tiers=CANONICAL_CURVE_TIERS)
        rep_a = create_rep(sc["program"]["id"], "AN RepA", "AN-RA")
        rep_b = create_rep(sc["program"]["id"], "AN RepB", "AN-RB")
        setup_assignment(sc["program"], sc["plan"], rep_a, accept=True)
        setup_assignment(sc["program"], sc["plan"], rep_b, accept=True)
        book_transaction(sc["program"]["id"], "AN-T1", 1000000,
                         [{"rep_id": rep_a["id"], "split_bps": 10000}])
        book_transaction(sc["program"]["id"], "AN-T2", 500000,
                         [{"rep_id": rep_b["id"], "split_bps": 10000}])
        close_period(sc["program"]["id"])

        resp = api.get_plan_effectiveness(sc["plan"]["id"], ADMIN)
        report = validate_success(resp, 200)
        assert report["assignments_count"] == 2
        assert report["statements_count"] == 2
        # floor((10000 + 5000) / 2)
        assert report["avg_attainment_bps"] == 7500
        assert report["total_earned_cents"] == 1500000
        assert report["total_payout_cents"] == 160000  # 110000 + 50000
        assert report["distribution"] == {
            "LT_8000": 1, "B8000_10000": 0, "GTE_10000": 1}, (
            "10000 bps lands in GTE_10000 — inclusive lower bound"
        )
