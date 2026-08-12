"""Batch intakes: FIFO auto-fill, draw bounds, cancel compensation, sap
conservation, FK reverse lookups (PRD §2.8, §3.6, §4)."""
import pytest

from test_helpers import (
    ApiErrorId,
    assert_sap_conservation,
    collect_confirmed_run,
    create_auto_fill_payload,
    create_batch_intake_payload,
    create_filling_batch,
    create_sap_run_payload,
    draw_from_run,
    make_fieldcrew_headers,
    make_sugarmaker_headers,
    setup_live_operation,
    validate_error,
    validate_paginated,
    validate_success,
)


def test_fifo_autofill_order_and_partial_draw(api, manager_headers):
    """PRD §3.6: "an auto-fill capability takes a `target_gallons` and draws
    FIFO: it considers the season's `CONFIRMED` runs with positive
    `gallons_remaining` in chronological order by `collected_at` (ties broken
    by `created_at`), drawing from each run the smaller of its remaining
    gallons and the outstanding need, stopping when the need is met."
    PRD §3.6: "if the total available is less than the target, the fill draws
    everything available and stops (partial fills are allowed)."

    Design: Corner/calculations/fifo_autofill_order_and_partial_draw
    """
    ctx = setup_live_operation()
    run_a = collect_confirmed_run(ctx, 100.0, 2.0, clock="2027-03-02T08:00:00Z")
    run_b = collect_confirmed_run(ctx, 60.0, 3.0, clock="2027-03-03T08:00:00Z")
    batch = create_filling_batch(ctx, capacity=500)

    filled = validate_success(
        api.auto_fill_batch(batch["id"], create_auto_fill_payload(150),
                            make_sugarmaker_headers(ctx["boiler"]["id"])),
        200)
    assert filled["sap_gallons_in"] == pytest.approx(150.0, abs=0.004)

    intakes_a, _ = validate_paginated(
        api.list_sap_run_intakes(run_a["id"], manager_headers))
    intakes_b, _ = validate_paginated(
        api.list_sap_run_intakes(run_b["id"], manager_headers))
    assert len(intakes_a) == 1 and len(intakes_b) == 1
    assert intakes_a[0]["gallons_drawn"] == pytest.approx(100.0, abs=0.004), (
        "FIFO drains the earlier run fully first")
    assert intakes_b[0]["gallons_drawn"] == pytest.approx(50.0, abs=0.004), (
        "then takes a partial draw from the later run")
    assert intakes_a[0]["draw_sequence"] < intakes_b[0]["draw_sequence"], (
        "per-batch monotone draw_sequence follows the FIFO order")

    run_b_after = validate_success(api.get_sap_run(run_b["id"], manager_headers), 200)
    assert run_b_after["gallons_remaining"] == pytest.approx(10.0, abs=0.004)


def test_autofill_empty_candidate_set(api, manager_headers):
    """PRD §3.6: "If the candidate set is empty — no confirmed run with any
    remaining gallons — the auto-fill is rejected with `ERR_NO_SAP_AVAILABLE`"

    Design: Corner/calculations/autofill_empty_candidate_set
    """
    ctx = setup_live_operation()
    # The only run is DRAFT (never confirmed), so the candidate set is empty.
    validate_success(
        api.create_sap_run(
            create_sap_run_payload(ctx["bush"]["id"], ctx["window"]["id"],
                                   ctx["tapper"]["id"], gallons_collected=10.0),
            make_fieldcrew_headers(ctx["tapper"]["id"])),
        201)
    batch = create_filling_batch(ctx, capacity=200)

    res = api.auto_fill_batch(batch["id"], create_auto_fill_payload(100),
                              make_sugarmaker_headers(ctx["boiler"]["id"]))
    validate_error(res, ApiErrorId.ERR_NO_SAP_AVAILABLE)

    batch_after = validate_success(api.get_batch(batch["id"], manager_headers), 200)
    assert batch_after["sap_gallons_in"] == pytest.approx(0.0, abs=0.004)


def test_draw_exceeds_remaining_rejected(api, manager_headers):
    """PRD §3.6: "the draw must be greater than zero and may not exceed the
    run's current `gallons_remaining` (otherwise `ERR_DRAW_EXCEEDS_REMAINING`)"

    Design: Corner/validations/draw_exceeds_remaining_rejected
    """
    ctx = setup_live_operation()
    run = collect_confirmed_run(ctx, 10.0, 2.0)
    batch = create_filling_batch(ctx, capacity=200)

    res = api.create_batch_intake(
        batch["id"], create_batch_intake_payload(run["id"], 10.01),
        make_sugarmaker_headers(ctx["boiler"]["id"]))
    validate_error(res, ApiErrorId.ERR_DRAW_EXCEEDS_REMAINING)

    intake = validate_success(
        api.create_batch_intake(
            batch["id"], create_batch_intake_payload(run["id"], 10.0),
            make_sugarmaker_headers(ctx["boiler"]["id"])),
        201)
    assert intake["gallons_drawn"] == pytest.approx(10.0, abs=0.004)

    run_after = validate_success(api.get_sap_run(run["id"], manager_headers), 200)
    assert run_after["gallons_remaining"] == pytest.approx(0.0, abs=0.004)


def test_draw_then_cancel_restores_sap_conservation(api, manager_headers):
    """PRD §2.8: "A sap run's `gallons_remaining` equals its
    `gallons_collected` minus the sum of `gallons_drawn` over batch intakes of
    that run whose batch is in `FILLING`, `BOILING`, or `FINISHED`; draws
    belonging to a `CANCELLED` batch do not count against the run."
    PRD §3.6: "Cancelling moves `FILLING → CANCELLED` and compensates every
    intake: for each intake of the batch, the run's `gallons_remaining` is
    increased by that intake's `gallons_drawn`, so draws of a cancelled batch
    no longer count against their runs."

    Design: Difficulty/compensating_invariant/batch_cancel_restores_sap_conservation
    """
    ctx = setup_live_operation()
    run = collect_confirmed_run(ctx, 100.0, 2.0)
    batch = create_filling_batch(ctx, capacity=200)
    draw_from_run(ctx, batch["id"], run["id"], 40.0)

    mid = validate_success(api.get_sap_run(run["id"], manager_headers), 200)
    assert mid["gallons_remaining"] == pytest.approx(60.0, abs=0.004)
    assert_sap_conservation(mid, drawn_outside_cancelled=40.0)

    cancelled = validate_success(
        api.cancel_batch(batch["id"], make_sugarmaker_headers(ctx["boiler"]["id"])),
        200)
    assert cancelled["status"] == "CANCELLED"

    after = validate_success(api.get_sap_run(run["id"], manager_headers), 200)
    assert after["gallons_remaining"] == pytest.approx(100.0, abs=0.004)
    assert_sap_conservation(after, drawn_outside_cancelled=0.0)


def test_batch_cancel_compensation_is_exact_no_drift(api, manager_headers):
    """PRD §3.6: "Cancelling moves `FILLING → CANCELLED` and compensates every
    intake: for each intake of the batch, the run's `gallons_remaining` is
    increased by that intake's `gallons_drawn`, so draws of a cancelled batch
    no longer count against their runs."

    Design: Difficulty/compensating_invariant/batch_cancel_restores_sap_conservation
    """
    ctx = setup_live_operation()
    run = collect_confirmed_run(ctx, 100.0, 2.0)
    batch = create_filling_batch(ctx, capacity=200)
    draw_from_run(ctx, batch["id"], run["id"], 40.0)

    validate_success(
        api.cancel_batch(batch["id"], make_sugarmaker_headers(ctx["boiler"]["id"])),
        200)

    batch_after = validate_success(api.get_batch(batch["id"], manager_headers), 200)
    assert batch_after["status"] == "CANCELLED"
    run_after = validate_success(api.get_sap_run(run["id"], manager_headers), 200)
    # Conservation restored exactly: 100.00 remaining + 0 live draws == 100.00.
    assert run_after["gallons_remaining"] == pytest.approx(100.0, abs=0.004)
    assert_sap_conservation(run_after, drawn_outside_cancelled=0.0)


def test_fk_reverse_reachability_filters(api, manager_headers):
    """PRD §4: "| GET | /sugarhouse/sap-runs | List sap runs (filters:
    `sugarbush_id`, `weather_window_id`, `collected_by`, `status`) |
    SugarhouseManager, FieldCrew, SugarMaker, CertInspector |"
    PRD §4: "| GET | /sugarhouse/batches/{id}/intakes | List intakes of a batch
    | SugarhouseManager, FieldCrew, SugarMaker, CertInspector |"
    PRD §4: "| GET | /sugarhouse/sap-runs/{id}/intakes | List intakes drawn
    from a sap run | SugarhouseManager, FieldCrew, SugarMaker, CertInspector |"

    Design: Corner/endpoints/fk_reverse_reachability_filters
    """
    ctx = setup_live_operation()
    run = collect_confirmed_run(ctx, 10.0, 2.0)
    batch = create_filling_batch(ctx, capacity=200)
    intake = draw_from_run(ctx, batch["id"], run["id"], 4.0)

    by_bush, _ = validate_paginated(
        api.list_sap_runs(manager_headers, params={"sugarbush_id": ctx["bush"]["id"]}))
    assert [r["id"] for r in by_bush] == [run["id"]]

    by_window, _ = validate_paginated(
        api.list_sap_runs(manager_headers,
                          params={"weather_window_id": ctx["window"]["id"]}))
    assert [r["id"] for r in by_window] == [run["id"]]

    batch_intakes, _ = validate_paginated(
        api.list_batch_intakes(batch["id"], manager_headers))
    assert [i["id"] for i in batch_intakes] == [intake["id"]]
    assert batch_intakes[0]["gallons_drawn"] == pytest.approx(4.0, abs=0.004)

    run_intakes, _ = validate_paginated(
        api.list_sap_run_intakes(run["id"], manager_headers))
    assert [i["id"] for i in run_intakes] == [intake["id"]]
    assert run_intakes[0]["gallons_drawn"] == pytest.approx(4.0, abs=0.004)
