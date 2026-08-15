"""Cart-run completion: restock math, counters, lateness, and completion
guards (PRD 3.3)."""
from test_helpers import (
    EVS,
    ApiErrorId,
    base_scenario,
    complete_cart_run_payload,
    complete_run,
    fill_unit_to_par,
    read_par,
    read_run,
    read_stock,
    restock_totals,
    schedule_run,
    set_clock,
    setup_unit_with_collection,
    validate_error,
    validate_success,
)


class TestCompletionCascade:
    """Run completion mutates ParLevel.on_hand, and that mutation drives
    LinenStock counters one link deeper (PRD 3.3)."""

    def test_initial_fill_moves_pieces_to_unit(self, api):
        """PRD 3.3: "Then, per stocked item, the deficit is the item's
        `effective_par` minus the unit's post-collection `on_hand`, or zero
        when that difference is negative."
        PRD 3.3: "The delivered pieces are added to the unit's `on_hand` and
        subtracted from the stock's `in_circulation`, while the soiled pieces
        are added to the stock's `in_wash`."

        Design: Difficulty/transitive_cascade/cart_run_completion_stock_cascade_depth2
        """
        ctx = base_scenario()
        fill_unit_to_par(ctx)

        par = read_par(ctx["par"]["id"])
        stock = read_stock(ctx["stock"]["id"])
        assert par["on_hand"] == 20, (
            f"fill run must stock the unit to par 20, got {par['on_hand']}"
        )
        assert stock["in_circulation"] == 80, (
            "20 delivered pieces must leave circulation: "
            f"100 - 20 = 80, got {stock['in_circulation']}"
        )

    def test_collection_run_restock_consumes_circulation(self, api):
        """PRD 3.3: "First the unit's `on_hand` for each collected stock is
        reduced by the soiled pieces."
        PRD 3.3: "The delivered pieces are added to the unit's `on_hand` and
        subtracted from the stock's `in_circulation`, while the soiled pieces
        are added to the stock's `in_wash`."

        Design: Difficulty/transitive_cascade/cart_run_completion_stock_cascade_depth2
        """
        ctx = setup_unit_with_collection(soiled_pieces=8)

        par = read_par(ctx["par"]["id"])
        stock = read_stock(ctx["stock"]["id"])
        assert par["on_hand"] == 20, (
            "on_hand must round-trip 20 - 8 soiled + 8 restocked = 20, "
            f"got {par['on_hand']}"
        )
        assert stock["in_circulation"] == 72, (
            f"circulation must fall to 80 - 8 = 72, got {stock['in_circulation']}"
        )
        assert stock["in_wash"] == 8, (
            f"8 soiled pieces must enter the wash pipeline, got {stock['in_wash']}"
        )


class TestZeroDeficitRestock:
    """On_hand already at effective par yields a zero-piece restock that
    still completes cleanly (PRD 3.3)."""

    def test_zero_restock_completes_without_shortage(self, api):
        """PRD 3.3: "Then, per stocked item, the deficit is the item's
        `effective_par` minus the unit's post-collection `on_hand`, or zero
        when that difference is negative."
        PRD 3.3: "The delivered quantity is the smaller of the deficit and
        the stock's `in_circulation`."

        Design: Difficulty/boundary_precision_check/restock_zero_when_on_hand_equals_par
        """
        ctx = base_scenario()
        fill_unit_to_par(ctx)
        run2 = schedule_run(
            ctx["unit"]["id"], "2026-08-02T11:00:00Z", "2026-08-02T12:00:00Z"
        )

        completed = validate_success(
            api.complete_cart_run(
                run2["id"],
                complete_cart_run_payload(soiled_lines=[], storage_attested=True),
                EVS,
            ),
            200,
        )
        assert completed["status"] == "COMPLETED"
        assert completed["shortage_flag"] is False
        totals = restock_totals(completed.get("restock_lines"))
        assert totals.get(ctx["stock"]["id"], 0) == 0, (
            f"deficit is exactly 0, so 0 pieces must be delivered, got {totals}"
        )

    def test_zero_restock_leaves_counters_unchanged(self, api):
        """PRD 3.3: "The delivered pieces are added to the unit's `on_hand`
        and subtracted from the stock's `in_circulation`, while the soiled
        pieces are added to the stock's `in_wash`."
        PRD 2.7: "Piece movements between these counters are atomic within
        the request that triggers them — a cart completion, a manifest
        creation, a vendor return, a surge allocation, or an adjustment
        either applies all of its counter mutations or none of them."

        Design: Difficulty/boundary_precision_check/restock_zero_when_on_hand_equals_par
        """
        ctx = base_scenario()
        fill_unit_to_par(ctx)
        run2 = schedule_run(
            ctx["unit"]["id"], "2026-08-02T11:00:00Z", "2026-08-02T12:00:00Z"
        )
        complete_run(run2["id"], soiled_lines=[])

        par = read_par(ctx["par"]["id"])
        stock = read_stock(ctx["stock"]["id"])
        assert par["on_hand"] == 20
        assert stock["in_circulation"] == 80
        assert stock["in_wash"] == 0


def test_completion_response_carries_post_mutation_state(api):
    """PRD 2.2: "Unless otherwise noted, operations that create or modify a
    resource will return the created or updated resource object in the data
    field."
    PRD 3.3: "On completion the run moves from `SCHEDULED` to `COMPLETED`,
    and restocking is computed line by line."
    PRD 3.3: "Finally `completed_at` is stamped from the logical clock, and
    `late_delivery` is set to true when `completed_at` falls after
    `scheduled_end`."

    Design: Corner/consistency_model/immediate_consistency_on_complete
    """
    ctx = base_scenario()
    set_clock("2026-08-02T08:00:00Z")
    run = schedule_run(
        ctx["unit"]["id"], "2026-08-02T08:00:00Z", "2026-08-02T09:00:00Z"
    )

    completed = validate_success(
        api.complete_cart_run(
            run["id"],
            complete_cart_run_payload(soiled_lines=[], storage_attested=True),
            EVS,
        ),
        200,
    )
    assert completed["status"] == "COMPLETED"
    totals = restock_totals(completed.get("restock_lines"))
    assert totals == {ctx["stock"]["id"]: 20}, (
        "fill from zero on_hand must deliver par 20 of the sheet stock, "
        f"got {totals}"
    )
    assert completed["late_delivery"] is False


def test_complete_completed_run_rejected(api):
    """PRD 3.3: "On completion the run moves from `SCHEDULED` to `COMPLETED`,
    and restocking is computed line by line."
    PRD 3.3: "When the unit is satisfied, the clerk confirms final counts:
    reconciliation moves a run from `COMPLETED` to `RECONCILED`, or from
    `RECOUNTED` to `RECONCILED`, and `RECONCILED` is terminal — any further
    transition attempt on a terminal resource is rejected with
    `ERR_ALREADY_TERMINAL`, while a transition from any other invalid
    from-state is rejected with `ERR_INVALID_STATE`."

    Design: Corner/state_machines/complete_completed_run_rejected
    """
    ctx = base_scenario()
    run = schedule_run(
        ctx["unit"]["id"], "2026-08-02T08:00:00Z", "2026-08-02T09:00:00Z"
    )
    complete_run(run["id"], soiled_lines=[])

    res = api.complete_cart_run(
        run["id"],
        complete_cart_run_payload(soiled_lines=[], storage_attested=True),
        EVS,
    )
    validate_error(res, ApiErrorId.ERR_INVALID_STATE)

    par = read_par(ctx["par"]["id"])
    assert par["on_hand"] == 20, (
        "rejected second completion must not restock twice, "
        f"got on_hand {par['on_hand']}"
    )


def test_storage_attestation_required(api, evs_operator_headers):
    """PRD 3.3: "Completion without a true `storage_attested` is rejected
    with `ERR_STORAGE_NOT_ATTESTED`."

    Design: Corner/validations/storage_attestation_required
    """
    ctx = base_scenario()
    run = schedule_run(
        ctx["unit"]["id"], "2026-08-02T08:00:00Z", "2026-08-02T09:00:00Z"
    )

    res = api.complete_cart_run(
        run["id"],
        complete_cart_run_payload(soiled_lines=[], storage_attested=False),
        evs_operator_headers,
    )
    validate_error(res, ApiErrorId.ERR_STORAGE_NOT_ATTESTED)
    assert read_run(run["id"])["status"] == "SCHEDULED"


def test_count_exceeds_on_hand_rejected(api, evs_operator_headers):
    """PRD 3.3: "Each soiled line's `pieces` must not exceed the unit's
    current `on_hand` for that stock, or the completion is rejected with
    `ERR_COUNT_EXCEEDS_ON_HAND`."

    Design: Corner/validations/count_exceeds_on_hand_rejected
    """
    ctx = base_scenario()
    fill_unit_to_par(ctx)
    run2 = schedule_run(
        ctx["unit"]["id"], "2026-08-02T11:00:00Z", "2026-08-02T12:00:00Z"
    )

    res = api.complete_cart_run(
        run2["id"],
        complete_cart_run_payload(
            soiled_lines=[{"stock_id": ctx["stock"]["id"], "pieces": 25}],
            storage_attested=True,
        ),
        evs_operator_headers,
    )
    validate_error(res, ApiErrorId.ERR_COUNT_EXCEEDS_ON_HAND)
    assert read_run(run2["id"])["status"] == "SCHEDULED"


def test_late_delivery_flag_follows_logical_clock(api, evs_operator_headers):
    """PRD 3.3: "Finally `completed_at` is stamped from the logical clock,
    and `late_delivery` is set to true when `completed_at` falls after
    `scheduled_end`."
    PRD 2.5: "The logical clock determines cart-run completion timestamps
    (`completed_at`), lateness evaluation (`late_delivery`), and the trailing
    30-day window used for unit quality standing."

    Design: Corner/endpoints/late_delivery_flag_when_completed_after_window
    """
    ctx = base_scenario(cart_cycle="TWICE_DAILY")
    set_clock("2026-08-02T08:00:00Z")
    run1 = schedule_run(
        ctx["unit"]["id"], "2026-08-02T08:00:00Z", "2026-08-02T09:00:00Z"
    )
    run2 = schedule_run(
        ctx["unit"]["id"], "2026-08-02T11:00:00Z", "2026-08-02T12:00:00Z"
    )
    set_clock("2026-08-02T09:30:00Z")

    completed1 = validate_success(
        api.complete_cart_run(
            run1["id"],
            complete_cart_run_payload(soiled_lines=[], storage_attested=True),
            evs_operator_headers,
        ),
        200,
    )
    completed2 = validate_success(
        api.complete_cart_run(
            run2["id"],
            complete_cart_run_payload(soiled_lines=[], storage_attested=True),
            evs_operator_headers,
        ),
        200,
    )
    assert completed1["late_delivery"] is True, (
        "09:30 completion of an 08:00-09:00 window must be flagged late"
    )
    assert completed2["late_delivery"] is False, (
        "09:30 completion of an 11:00-12:00 window must not be flagged late"
    )
