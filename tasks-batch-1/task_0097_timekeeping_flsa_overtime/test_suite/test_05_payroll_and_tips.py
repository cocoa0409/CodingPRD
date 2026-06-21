"""Payroll-run locking/finalize/cancel, the compensating-cancel invariant, the
week-include guards, and tip-pool distribution conservation.

Covers Queue A non_linear_state_machine (payroll branch), transitive_cascade
(payroll cancel), cross_entity_state_dependency (week include),
compensating_invariant (payroll + tip pool), combinatorial_formula (tip pool),
and Queue B state_machine/validation tip/payroll instances.
"""
from test_helpers import (
    validate_success, validate_error,
    ApiErrorId,
    setup_ca_employer, setup_approved_week, setup_locked_week_in_run,
    setup_tip_pool_with_contributions,
    create_employee as mk_employee, create_closed_punch, create_draft_week,
    submit_week, approve_week, create_payroll_run, include_week,
    include_week_payload,
    ADMIN, SUP1, SUP2,
)


# ─── Payroll run branch: cancel reverts (Queue A non_linear_state_machine) ──

def test_payroll_run_cancel_reverts_locked_week_to_approved(api):
    """PRD §3.9: "Cancelling an OPEN run instead reverts each LOCKED week back to
    APPROVED and clears each week's payroll_run_id, resets the run's
    total_gross_cents and included_week_count to zero, and moves the run OPEN →
    CANCELLED."

    Design: Difficulty/non_linear_state_machine/payroll_run_branch_finalize_vs_cancel
    """
    ctx = setup_locked_week_in_run(api)
    run = ctx["run"]
    cancelled = validate_success(api.cancel_payroll_run(run["id"], ADMIN), 200)
    assert cancelled["status"] == "CANCELLED"
    assert cancelled["total_gross_cents"] == 0
    assert cancelled["included_week_count"] == 0
    week_after = validate_success(api.get_timesheet_week(ctx["week"]["id"], SUP1), 200)
    assert week_after["status"] == "APPROVED"
    assert week_after["payroll_run_id"] is None


def test_payroll_run_finalize_branch_keeps_week_locked(api):
    """PRD §3.9: "Finalizing a run, by a PayrollAdmin, requires it to be OPEN and to
    hold at least one LOCKED week, else it is rejected with ERR_EMPTY_PAYROLL_RUN;
    finalization moves the run OPEN → FINALIZED, after which it is immutable."

    The complementary fork: from OPEN the run can also FINALIZE, in which case the
    locked week stays LOCKED (no revert), unlike the cancel branch in instance 1.

    Design: Difficulty/non_linear_state_machine/payroll_run_branch_finalize_vs_cancel
    """
    ctx = setup_locked_week_in_run(api)
    finalized = validate_success(api.finalize_payroll_run(ctx["run"]["id"], ADMIN), 200)
    assert finalized["status"] == "FINALIZED"
    assert finalized["total_gross_cents"] == 16000
    assert finalized["included_week_count"] == 1
    week_after = validate_success(api.get_timesheet_week(ctx["week"]["id"], SUP1), 200)
    assert week_after["status"] == "LOCKED"
    assert week_after["payroll_run_id"] == ctx["run"]["id"]


# ─── Payroll cancel cascade (Queue A transitive_cascade) ──

def test_payroll_cancel_cascades_week_revert_and_clears_gross(api):
    """PRD §3.9: "Cancelling an OPEN run instead reverts each LOCKED week back to
    APPROVED and clears each week's payroll_run_id, resets the run's
    total_gross_cents and included_week_count to zero, and moves the run OPEN →
    CANCELLED."

    Design: Difficulty/transitive_cascade/payroll_cancel_cascades_week_revert
    """
    ctx = setup_locked_week_in_run(api)
    # The week's gross (16000) was added to the run on include.
    assert ctx["run"]["total_gross_cents"] == 16000
    cancelled = validate_success(api.cancel_payroll_run(ctx["run"]["id"], ADMIN), 200)
    assert cancelled["status"] == "CANCELLED"
    assert cancelled["total_gross_cents"] == 0
    week_after = validate_success(api.get_timesheet_week(ctx["week"]["id"], SUP1), 200)
    assert week_after["status"] == "APPROVED"
    assert week_after["payroll_run_id"] is None


def test_week_reverted_by_cancel_is_re_includable(api):
    """PRD §3.9: "Cancelling an OPEN run instead reverts each LOCKED week back to
    APPROVED and clears each week's payroll_run_id".
    PRD §3.9: "The administrator locks an approved week into the run by supplying
    the timesheet_week_id and the OCC field expected_timesheet_week_version. Locking
    requires the week to be APPROVED".

    The revert cascade leaves the week genuinely APPROVED again — provable by
    locking it into a fresh run, a distinct downstream effect from the gross-ledger
    reset in instance 1.

    Design: Difficulty/transitive_cascade/payroll_cancel_cascades_week_revert
    """
    ctx = setup_locked_week_in_run(api)
    validate_success(api.cancel_payroll_run(ctx["run"]["id"], ADMIN), 200)
    week_after = validate_success(api.get_timesheet_week(ctx["week"]["id"], SUP1), 200)
    assert week_after["status"] == "APPROVED"
    run2 = create_payroll_run(api, ctx["employer"]["id"], "2026-06-01", "2026-06-07")
    relocked = include_week(api, run2["id"], ctx["week"]["id"], week_after["version"])
    assert relocked["included_week_count"] == 1
    assert relocked["total_gross_cents"] == 16000


# ─── Compensating invariant: include-then-cancel conserves gross (Queue A) ──

def test_payroll_include_then_cancel_conserves_gross_ledger(api):
    """PRD §3.9: "A successful lock sets the week's payroll_run_id, advances it
    APPROVED → LOCKED, increments the week's version, increments the run's
    included_week_count, and adds the week's gross_wages_cents to the run's
    total_gross_cents."
    PRD §3.9: "Cancelling an OPEN run instead reverts each LOCKED week back to
    APPROVED and clears each week's payroll_run_id, resets the run's
    total_gross_cents and included_week_count to zero".

    Design: Difficulty/compensating_invariant/payroll_include_then_cancel_conserves_gross
    """
    ctx = setup_locked_week_in_run(api)
    assert ctx["run"]["total_gross_cents"] == 16000
    assert ctx["run"]["included_week_count"] == 1
    cancelled = validate_success(api.cancel_payroll_run(ctx["run"]["id"], ADMIN), 200)
    assert cancelled["total_gross_cents"] == 0
    assert cancelled["included_week_count"] == 0
    week_after = validate_success(api.get_timesheet_week(ctx["week"]["id"], SUP1), 200)
    assert week_after["status"] == "APPROVED"


def test_payroll_include_adds_exact_week_gross_to_run(api):
    """PRD §3.9: "A successful lock sets the week's payroll_run_id, advances it
    APPROVED → LOCKED, increments the week's version, increments the run's
    included_week_count, and adds the week's gross_wages_cents to the run's
    total_gross_cents."

    The forward leg of the conservation: locking an 8h week (gross 16000) drives the
    run ledger from (0, 0) to exactly (16000, 1) — the quantity that the cancel in
    instance 1 must later return to zero.

    Design: Difficulty/compensating_invariant/payroll_include_then_cancel_conserves_gross
    """
    ctx = setup_approved_week(api)
    run = create_payroll_run(api, ctx["employer"]["id"], "2026-06-01", "2026-06-07")
    before = validate_success(api.get_payroll_run(run["id"], ADMIN), 200)
    assert before["total_gross_cents"] == 0
    assert before["included_week_count"] == 0
    after = include_week(api, run["id"], ctx["week"]["id"], ctx["week"]["version"])
    assert after["total_gross_cents"] == 16000
    assert after["included_week_count"] == 1


# ─── Cross-entity: include blocked by finalized run (Queue A) ──

def test_week_include_blocked_by_finalized_run(api):
    """PRD §3.9: "Locking requires the week to be APPROVED ... and requires the run
    to be OPEN and to cover the week".
    PRD §3.9: "finalization moves the run OPEN → FINALIZED, after which it is
    immutable."

    Design: Difficulty/cross_entity_state_dependency/week_include_blocked_by_payroll_run_state
    """
    employer, ruleset, worksite = setup_ca_employer(api)
    # First week: locked then run finalized.
    e1 = mk_employee(api, employer["id"], worksite["id"], "NON_EXEMPT", base_rate_cents=2000)
    create_closed_punch(api, e1["id"], worksite["id"],
                        "2026-06-01T08:00:00Z", "2026-06-01T16:00:00Z",
                        "2026-06-01T08:00:00Z", "2026-06-01T16:00:00Z")
    w1 = create_draft_week(api, e1["id"], "2026-06-01")
    s1 = submit_week(api, w1["id"], SUP1)
    a1 = approve_week(api, w1["id"], s1["version"], SUP2)
    run = create_payroll_run(api, employer["id"], "2026-06-01", "2026-06-07")
    include_week(api, run["id"], w1["id"], a1["version"])
    validate_success(api.finalize_payroll_run(run["id"], ADMIN), 200)
    # Second week, also approved, attempts to include into the FINALIZED run.
    e2 = mk_employee(api, employer["id"], worksite["id"], "NON_EXEMPT", base_rate_cents=2000)
    create_closed_punch(api, e2["id"], worksite["id"],
                        "2026-06-01T08:00:00Z", "2026-06-01T16:00:00Z",
                        "2026-06-01T08:00:00Z", "2026-06-01T16:00:00Z")
    w2 = create_draft_week(api, e2["id"], "2026-06-01")
    s2 = submit_week(api, w2["id"], SUP1)
    a2 = approve_week(api, w2["id"], s2["version"], SUP2)
    resp = api.include_week_in_run(run["id"], include_week_payload(w2["id"], a2["version"]), ADMIN)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value, 409)


def test_week_include_blocked_by_cancelled_run(api):
    """PRD §3.9: "Locking requires the week to be APPROVED ... and requires the run
    to be OPEN and to cover the week".
    PRD §3.9: "Cancelling an OPEN run instead reverts each LOCKED week back to
    APPROVED ... and moves the run OPEN → CANCELLED."

    The week's LOCKED transition depends on the run's state from the other side of
    the fork: against a CANCELLED run (also not OPEN) the include is likewise
    rejected ERR_INVALID_STATE.

    Design: Difficulty/cross_entity_state_dependency/week_include_blocked_by_payroll_run_state
    """
    ctx = setup_approved_week(api)
    run = create_payroll_run(api, ctx["employer"]["id"], "2026-06-01", "2026-06-07")
    validate_success(api.cancel_payroll_run(run["id"], ADMIN), 200)
    resp = api.include_week_in_run(
        run["id"], include_week_payload(ctx["week"]["id"], ctx["week"]["version"]), ADMIN)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value, 409)


# ─── Finalized run terminal lockdown (Queue B) ────────

def test_cancel_finalized_run_invalid_state(api):
    """PRD §3.9: "finalization moves the run OPEN → FINALIZED, after which it is
    immutable. ... FINALIZED and CANCELLED are the run's terminal states."

    Design: Corner/state_machines/finalized_run_terminal_lockdown
    """
    ctx = setup_locked_week_in_run(api)
    validate_success(api.finalize_payroll_run(ctx["run"]["id"], ADMIN), 200)
    resp = api.cancel_payroll_run(ctx["run"]["id"], ADMIN)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value, 409)


# ─── Validations: include outside period, empty pool, empty run (Queue B) ──

def test_include_week_outside_period_rejected(api):
    """PRD §3.9: "requires the run to be OPEN and to cover the week, meaning the
    week's workweek_start falls within [period_start, period_end]; a week outside
    that span is rejected with ERR_WEEK_OUTSIDE_PERIOD (HTTP 422)."

    Design: Corner/validations/include_week_outside_period_rejected
    """
    employer, ruleset, worksite = setup_ca_employer(api)
    employee = mk_employee(api, employer["id"], worksite["id"], "NON_EXEMPT", base_rate_cents=2000)
    create_closed_punch(api, employee["id"], worksite["id"],
                        "2026-06-08T08:00:00Z", "2026-06-08T16:00:00Z",
                        "2026-06-08T08:00:00Z", "2026-06-08T16:00:00Z")
    week = create_draft_week(api, employee["id"], "2026-06-08")
    submitted = submit_week(api, week["id"], SUP1)
    approved = approve_week(api, week["id"], submitted["version"], SUP2)
    run = create_payroll_run(api, employer["id"], "2026-06-01", "2026-06-07")
    resp = api.include_week_in_run(
        run["id"], include_week_payload(week["id"], approved["version"]), ADMIN)
    validate_error(resp, ApiErrorId.ERR_WEEK_OUTSIDE_PERIOD.value, 422)


def test_distribute_empty_tip_pool_rejected(api):
    """PRD §3.5: "Distribution, performed by a Supervisor, is allowed only from OPEN
    and requires at least one contributing declaration with positive total weight,
    failing which it is rejected with ERR_EMPTY_TIP_POOL."

    Design: Corner/validations/distribute_empty_tip_pool_rejected
    """
    from test_helpers import create_tip_pool
    employer, ruleset, worksite = setup_ca_employer(api)
    pool = create_tip_pool(api, worksite["id"], "2026-06-01")
    resp = api.distribute_tip_pool(pool["id"], SUP1)
    validate_error(resp, ApiErrorId.ERR_EMPTY_TIP_POOL.value, 409)


def test_finalize_empty_payroll_run_rejected(api):
    """PRD §3.9: "Finalizing a run, by a PayrollAdmin, requires it to be OPEN and to
    hold at least one LOCKED week, else it is rejected with ERR_EMPTY_PAYROLL_RUN".

    Design: Corner/validations/finalize_empty_payroll_run_rejected
    """
    employer, ruleset, worksite = setup_ca_employer(api)
    run = create_payroll_run(api, employer["id"], "2026-06-01", "2026-06-07")
    resp = api.finalize_payroll_run(run["id"], ADMIN)
    validate_error(resp, ApiErrorId.ERR_EMPTY_PAYROLL_RUN.value, 409)


# ─── Tip-pool distribution conservation (Queue A combinatorial + compensating) ──

def test_tip_pool_distribute_conserves_pooled_cents(api):
    """PRD §3.5: "On distribution the pool moves OPEN → DISTRIBUTED,
    distributed_cents is set equal to pooled_cents, and the pooled money is
    allocated across the contributing employees in proportion to how much each
    worked that day."

    Design: Difficulty/combinatorial_formula/tip_pool_round_then_waterfall_order
    """
    ctx = setup_tip_pool_with_contributions(api, contributions=[
        {"name": "A", "clock_out": "2026-06-01T18:00:00Z", "declared_cents": 4000},  # 10h
        {"name": "B", "clock_out": "2026-06-01T18:00:00Z", "declared_cents": 3500},  # 10h
        {"name": "C", "clock_out": "2026-06-01T15:00:00Z", "declared_cents": 2500},  # 7h
    ])
    data = validate_success(api.distribute_tip_pool(ctx["pool"]["id"], SUP1), 200)
    assert data["pooled_cents"] == 10000
    assert data["distributed_cents"] == 10000
    assert data["status"] == "DISTRIBUTED"


def test_tip_pool_pooled_cents_sums_contributing_declarations(api):
    """PRD §3.5: "When a declaration names a pool, the owning tip pool's pooled_cents
    is recomputed as the sum of declared_cents over every declaration whose pool_id
    points at that pool."
    PRD §3.5: "First, pooled_cents is summed from the contributing declarations."

    The floor-then-waterfall allocation starts from pooled_cents; before any
    distribution the pool already reports the exact contributing sum
    (4000 + 3500 + 2500 = 10000).

    Design: Difficulty/combinatorial_formula/tip_pool_round_then_waterfall_order
    """
    ctx = setup_tip_pool_with_contributions(api, contributions=[
        {"name": "A", "clock_out": "2026-06-01T18:00:00Z", "declared_cents": 4000},
        {"name": "B", "clock_out": "2026-06-01T18:00:00Z", "declared_cents": 3500},
        {"name": "C", "clock_out": "2026-06-01T15:00:00Z", "declared_cents": 2500},
    ])
    # The pool snapshot returned by the fixture reflects the recomputed sum.
    assert ctx["pool"]["pooled_cents"] == 10000
    assert ctx["pool"]["status"] == "OPEN"


def test_tip_pool_distribute_conserves_two_employee_split(api):
    """PRD §3.5: "Because flooring leaves a remainder — pooled_cents minus the sum
    of the floored shares — the leftover cents are handed out one cent at a time to
    employees ordered by descending weight, breaking ties by the employee's
    created_at ascending (never by id), until no remainder remains."

    Design: Difficulty/compensating_invariant/tip_pool_distribute_conserves_tip_cents
    """
    ctx = setup_tip_pool_with_contributions(api, contributions=[
        {"name": "A", "clock_out": "2026-06-01T18:00:00Z", "declared_cents": 6000},  # 10h
        {"name": "B", "clock_out": "2026-06-01T13:00:00Z", "declared_cents": 4000},  # 5h
    ])
    data = validate_success(api.distribute_tip_pool(ctx["pool"]["id"], SUP1), 200)
    assert data["pooled_cents"] == 10000
    assert data["distributed_cents"] == 10000
    assert data["status"] == "DISTRIBUTED"


def test_tip_pool_distributed_cents_set_equal_to_pooled(api):
    """PRD §3.5: "On distribution the pool moves OPEN → DISTRIBUTED,
    distributed_cents is set equal to pooled_cents, and the pooled money is
    allocated across the contributing employees in proportion to how much each
    worked that day."

    A different weighting (12000 split across 8h/4h workers) re-confirms the
    conserved quantity: distributed_cents lands exactly on pooled_cents with no
    rounding drift.

    Design: Difficulty/compensating_invariant/tip_pool_distribute_conserves_tip_cents
    """
    ctx = setup_tip_pool_with_contributions(api, contributions=[
        {"name": "A", "clock_out": "2026-06-01T16:00:00Z", "declared_cents": 7000},  # 8h
        {"name": "B", "clock_out": "2026-06-01T12:00:00Z", "declared_cents": 5000},  # 4h
    ])
    data = validate_success(api.distribute_tip_pool(ctx["pool"]["id"], SUP1), 200)
    assert data["pooled_cents"] == 12000
    assert data["distributed_cents"] == 12000
    assert data["status"] == "DISTRIBUTED"
