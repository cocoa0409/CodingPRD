"""Cart-run dispute-recount cycle, terminal lockdown, and clerk ownership
(PRD 3.3)."""
from test_helpers import (
    ApiErrorId,
    base_scenario,
    complete_run,
    create_par,
    create_unit,
    dispute_run,
    make_unit_clerk_headers,
    read_par,
    read_run,
    read_stock,
    reconcile_run,
    recount_run,
    schedule_run,
    setup_unit_with_collection,
    validate_error,
)


class TestDisputeRecountCycle:
    """COMPLETED -> DISPUTED -> RECOUNTED -> DISPUTED -> ... -> RECONCILED."""

    def test_cycle_status_sequence(self, api):
        """PRD 3.3: "If the unit is still dissatisfied, a `RECOUNTED` run may
        be disputed again, returning to `DISPUTED` — the dispute–recount cycle
        may repeat."
        PRD 3.3: "When the unit is satisfied, the clerk confirms final counts:
        reconciliation moves a run from `COMPLETED` to `RECONCILED`, or from
        `RECOUNTED` to `RECONCILED`, and `RECONCILED` is terminal — any
        further transition attempt on a terminal resource is rejected with
        `ERR_ALREADY_TERMINAL`, while a transition from any other invalid
        from-state is rejected with `ERR_INVALID_STATE`."

        Design: Difficulty/non_linear_state_machine/cart_run_dispute_recount_cycle
        """
        ctx = setup_unit_with_collection(soiled_pieces=8, reconcile=False)
        run_id = ctx["collect_run"]["id"]
        unit_id = ctx["unit"]["id"]
        stock_id = ctx["stock"]["id"]

        disputed = dispute_run(run_id, unit_id)
        assert disputed["status"] == "DISPUTED"

        recounted = recount_run(
            run_id, unit_id, [{"stock_id": stock_id, "pieces": 6}]
        )
        assert recounted["status"] == "RECOUNTED"

        disputed_again = dispute_run(run_id, unit_id)
        assert disputed_again["status"] == "DISPUTED", (
            "a RECOUNTED run must be disputable again"
        )

        recount_run(run_id, unit_id, [{"stock_id": stock_id, "pieces": 6}])
        reconciled = reconcile_run(run_id, unit_id)
        assert reconciled["status"] == "RECONCILED"

    def test_recount_compensation_and_overstock(self, api):
        """PRD 3.3: "A recount moves the run from `DISPUTED` to `RECOUNTED`
        and applies compensation: for each corrected line, the unit's
        `on_hand` increases by the difference between the original and
        corrected soiled counts, and the stock's `in_wash` decreases by the
        same difference."
        PRD 3.3: "Overstock above par that results from this compensation is
        allowed and is not clamped."

        Design: Difficulty/non_linear_state_machine/cart_run_dispute_recount_cycle
        """
        ctx = setup_unit_with_collection(soiled_pieces=8, reconcile=False)
        run_id = ctx["collect_run"]["id"]
        unit_id = ctx["unit"]["id"]
        stock_id = ctx["stock"]["id"]

        dispute_run(run_id, unit_id)
        recount_run(run_id, unit_id, [{"stock_id": stock_id, "pieces": 6}])

        par = read_par(ctx["par"]["id"])
        stock = read_stock(stock_id)
        assert par["on_hand"] == 22, (
            "correcting 8 -> 6 returns 2 pieces to the unit: "
            f"20 + 2 = 22, got {par['on_hand']}"
        )
        assert stock["in_wash"] == 6, (
            f"in_wash must drop by the same 2: 8 - 2 = 6, got {stock['in_wash']}"
        )


def test_dispute_reconciled_run_returns_already_terminal(api):
    """PRD 3.3: "When the unit is satisfied, the clerk confirms final counts:
    reconciliation moves a run from `COMPLETED` to `RECONCILED`, or from
    `RECOUNTED` to `RECONCILED`, and `RECONCILED` is terminal — any further
    transition attempt on a terminal resource is rejected with
    `ERR_ALREADY_TERMINAL`, while a transition from any other invalid
    from-state is rejected with `ERR_INVALID_STATE`."

    Design: Corner/state_machines/dispute_reconciled_run_returns_already_terminal
    """
    ctx = setup_unit_with_collection(soiled_pieces=8, reconcile=True)
    res = api.dispute_cart_run(
        ctx["collect_run"]["id"], {}, make_unit_clerk_headers(ctx["unit"]["id"])
    )
    validate_error(res, ApiErrorId.ERR_ALREADY_TERMINAL)


def test_clerk_cannot_reconcile_other_unit_run(api):
    """PRD 3.3: "A `UnitClerk` whose `X-User-ID` equals the run's `unit_id` —
    a mismatch is rejected with `ERR_UNIT_OWNERSHIP` — may dispute a
    `COMPLETED` run, moving it to `DISPUTED` with an optional `reason`."
    PRD 2.1: "When `X-User-Role` is `UnitClerk`, `X-User-ID` is the `id` of
    the acting `Unit`; ownership checks on any resource that references a unit
    compare the resource's `unit_id` field to `X-User-ID`."

    Design: Corner/validations/clerk_cannot_reconcile_other_unit_run
    """
    ctx = base_scenario()
    unit2 = create_unit(ctx["facility"]["id"], name="4 West", unit_tier="STANDARD")
    create_par(unit2["id"], ctx["stock"]["id"], 10, "DAILY")
    run_u2 = schedule_run(
        unit2["id"], "2026-08-02T08:00:00Z", "2026-08-02T09:00:00Z"
    )
    complete_run(run_u2["id"], soiled_lines=[])

    res = api.reconcile_cart_run(
        run_u2["id"], make_unit_clerk_headers(ctx["unit"]["id"])
    )
    validate_error(res, ApiErrorId.ERR_UNIT_OWNERSHIP)
    assert read_run(run_u2["id"])["status"] == "COMPLETED"
