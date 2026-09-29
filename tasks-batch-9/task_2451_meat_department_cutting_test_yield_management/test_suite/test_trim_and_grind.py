"""Trim lots, the grinder schedule, and the grind run's two exits.

Every test builds its own department, bench work and trim from scratch through
the public endpoints: the runner restarts the server against an empty database
with the logical clock at its initial instant before each one.
"""

import pytest

from test_helpers import (
    CUTTER,
    FIXTURE_DATE,
    MANAGER,
    NON_EXISTENT_UUID,
    abort_grind_run,
    add_cutting_test_line,
    add_grind_input,
    approve_cutting_test,
    approved_cutting_test,
    assert_grind_input,
    assert_grind_run,
    assert_trim_lot,
    assert_trim_lot_buckets_conserve,
    complete_grind_run,
    create_cutting_test,
    create_grind_run,
    create_ground_item,
    create_primal_purchase,
    create_retail_item,
    create_trim_lot_from_line,
    discard_trim_lot,
    get_success_data,
    grind_input_payload,
    grind_run_payload,
    propose_price,
    read_grind_input,
    read_grind_run,
    read_retail_item,
    read_trim_lot,
    rework_trim_lot,
    seeded_department,
    start_grind_run,
    submit_cutting_test,
    transition_payload,
    trim_lot_payload,
    trim_lots_for_blend,
    validate_error,
    validate_paginated,
)


# ---------------------------------------------------------------------------
# The state gate on an open run against the pounds gate on the lot
# ---------------------------------------------------------------------------

def test_over_weight_input_on_an_aborted_run_reports_the_run_state_gate(api):
    """Trim drawn into an aborted run breaks both the open-run rung 13 and the
    lot-pounds rung 36, and the department hears about the closed run.

    "A request that would fail three checks reports only the lowest-numbered
    one; a later, more dramatic-sounding failure never masks an earlier one."

    Design: Difficulty/priority_pair_validation_conflict/grind_run_state_gate_outranks_trim_insufficiency
    """
    ctx = approved_cutting_test(api)
    department_id = ctx["department"]["id"]
    lot = create_trim_lot_from_line(
        api, department_id, "TL-A78", 12.0, ctx["lines"][1]["id"]
    )

    run = create_grind_run(
        api,
        department_id,
        ctx["ground_item"]["id"],
        "2026-08-06T06:00:00Z",
        "2026-08-06T07:00:00Z",
        declared_coo="USA",
        target_lean_pct=78.0,
    )
    abort_grind_run(api, run["id"], reason="grinder taken out of service for repair")

    # 20.0 lb is more than the lot's 12.00 remaining pounds as well, so both the
    # closed-run rule (PRD §2.11 rung 13) and the pounds rule (rung 36) bite.
    response = api.create_grind_input(
        run["id"], grind_input_payload(lot["id"], 1, 20.0), CUTTER
    )
    validate_error(response, "ERR_GRIND_RUN_NOT_OPEN", 409)

    refused_lot = read_trim_lot(api, lot["id"])
    assert refused_lot["status"] == "AVAILABLE"
    assert refused_lot["allocated_lb"] == pytest.approx(0.0, abs=0.01)
    assert refused_lot["remaining_lb"] == pytest.approx(12.0, abs=0.01)
    assert_trim_lot(refused_lot)

    refused_run = read_grind_run(api, run["id"])
    assert refused_run["status"] == "ABORTED"
    assert refused_run["batch_weight_lb"] == pytest.approx(0.0, abs=0.01)

    inputs, meta = validate_paginated(
        api.list_grind_inputs(CUTTER, {"grind_run_id": run["id"]})
    )
    assert meta["total_count"] == 0
    assert inputs == []


def test_over_weight_input_on_a_scheduled_run_reports_the_trim_shortfall(api):
    """The same over-weight draw against a run that is still open surfaces the
    pounds rule instead, so the refusal tracks the ladder and not a preference.

    "The run must still be open, meaning its `status` is `SCHEDULED` or
    `IN_PROGRESS`, or the request is refused with `ERR_GRIND_RUN_NOT_OPEN`; the
    lot must be `AVAILABLE` or `PARTIALLY_COMMITTED`, or refused with
    `ERR_TRIM_LOT_NOT_AVAILABLE`; the lot and the run must belong to the same
    department, or refused with `ERR_DEPARTMENT_MISMATCH`; and the pounds drawn
    must not exceed the lot's `remaining_lb`, or refused with
    `ERR_TRIM_INSUFFICIENT`."

    Design: Difficulty/priority_pair_validation_conflict/grind_run_state_gate_outranks_trim_insufficiency
    """
    ctx = approved_cutting_test(api)
    department_id = ctx["department"]["id"]
    lot = create_trim_lot_from_line(
        api, department_id, "TL-A78", 12.0, ctx["lines"][1]["id"]
    )

    run = create_grind_run(
        api,
        department_id,
        ctx["ground_item"]["id"],
        "2026-08-06T08:00:00Z",
        "2026-08-06T09:00:00Z",
        declared_coo="USA",
        target_lean_pct=78.0,
    )
    assert run["status"] == "SCHEDULED"

    response = api.create_grind_input(
        run["id"], grind_input_payload(lot["id"], 1, 20.0), CUTTER
    )
    validate_error(response, "ERR_TRIM_INSUFFICIENT", 422)

    untouched_lot = read_trim_lot(api, lot["id"])
    assert untouched_lot["status"] == "AVAILABLE"
    assert untouched_lot["allocated_lb"] == pytest.approx(0.0, abs=0.01)
    assert untouched_lot["remaining_lb"] == pytest.approx(12.0, abs=0.01)
    assert_trim_lot_buckets_conserve(untouched_lot)

    # A draw inside the remaining pounds on the same open run is accepted, which
    # shows only the pounds rule had been standing in the way.
    accepted = get_success_data(
        api.create_grind_input(
            run["id"], grind_input_payload(lot["id"], 1, 12.0), CUTTER
        ),
        201,
    )
    assert accepted["weight_lb"] == pytest.approx(12.0, abs=0.01)
    committed_lot = read_trim_lot(api, lot["id"])
    assert committed_lot["status"] == "FULLY_COMMITTED"
    assert committed_lot["allocated_lb"] == pytest.approx(12.0, abs=0.01)
    assert committed_lot["remaining_lb"] == pytest.approx(0.0, abs=0.01)


# ---------------------------------------------------------------------------
# One grinder, half-open windows, and the origin changeover buffer
# ---------------------------------------------------------------------------

def test_a_grinder_window_may_begin_at_the_instant_the_previous_one_ends(api):
    """Back-to-back grinder windows under one origin block are accepted while a
    window that straddles an occupied one is refused.

    "Grinder windows are **half-open** on the start instant and exclusive of the
    end instant, so a run ending at the exact instant another begins does not
    overlap it; any true overlap with another `SCHEDULED` or `IN_PROGRESS` run in
    the department is refused with `ERR_GRINDER_WINDOW_CONFLICT`."

    Design: Difficulty/resource_temporal_overlap/grinder_window_half_open_overlap_and_sanitation_gap
    """
    department = seeded_department(api)
    ground = create_ground_item(api, department["id"])

    first = create_grind_run(
        api,
        department["id"],
        ground["id"],
        "2026-08-06T06:00:00Z",
        "2026-08-06T07:00:00Z",
        declared_coo="USA",
        target_lean_pct=80.0,
    )
    assert first["status"] == "SCHEDULED"

    # Touching the exclusive end instant is not an overlap, and the origin block
    # has not changed, so no idle gap is owed either.
    touching = create_grind_run(
        api,
        department["id"],
        ground["id"],
        "2026-08-06T07:00:00Z",
        "2026-08-06T08:00:00Z",
        declared_coo="USA",
        target_lean_pct=80.0,
    )
    assert touching["status"] == "SCHEDULED"
    assert touching["coo_label"] == "PENDING"
    assert touching["batch_weight_lb"] == pytest.approx(0.0, abs=0.01)
    assert_grind_run(touching)

    straddling = api.create_grind_run(
        grind_run_payload(
            department["id"],
            ground["id"],
            "2026-08-06T06:30:00Z",
            "2026-08-06T07:30:00Z",
            declared_coo="USA",
            target_lean_pct=80.0,
        ),
        CUTTER,
    )
    validate_error(straddling, "ERR_GRINDER_WINDOW_CONFLICT", 409)

    rows, meta = validate_paginated(
        api.list_grind_runs(CUTTER, {"department_id": department["id"]})
    )
    assert meta["total_count"] == 2
    assert {row["id"] for row in rows} == {first["id"], touching["id"]}


def test_an_origin_changeover_accepts_a_gap_of_exactly_the_sanitation_buffer(api):
    """A different origin block cannot follow immediately on the grinder, but a
    gap of exactly the department's thirty sanitation minutes is enough.

    "Segregation adds a second temporal rule: when the nearest neighbouring
    `SCHEDULED` or `IN_PROGRESS` run in the department carries a different
    `declared_coo`, the idle gap between the two windows must be at least the
    department's `grind_sanitation_buffer_min` minutes, with a gap exactly equal
    to the buffer accepted; a shorter changeover gap is refused with
    `ERR_SANITATION_BUFFER_REQUIRED`."

    Design: Difficulty/resource_temporal_overlap/grinder_window_half_open_overlap_and_sanitation_gap
    """
    department = seeded_department(api)
    assert department["grind_sanitation_buffer_min"] == 30
    ground = create_ground_item(api, department["id"])

    domestic = create_grind_run(
        api,
        department["id"],
        ground["id"],
        "2026-08-06T06:00:00Z",
        "2026-08-06T07:00:00Z",
        declared_coo="USA",
        target_lean_pct=80.0,
    )

    # No overlap — the windows only touch — but the origin block changes and the
    # idle gap is zero minutes, short of the department's thirty.
    touching_changeover = api.create_grind_run(
        grind_run_payload(
            department["id"],
            ground["id"],
            "2026-08-06T07:00:00Z",
            "2026-08-06T08:00:00Z",
            declared_coo="CAN",
            target_lean_pct=80.0,
        ),
        CUTTER,
    )
    validate_error(touching_changeover, "ERR_SANITATION_BUFFER_REQUIRED", 409)

    # 07:00 to 07:30 is exactly the buffer, and a gap equal to it is accepted.
    cleaned_changeover = create_grind_run(
        api,
        department["id"],
        ground["id"],
        "2026-08-06T07:30:00Z",
        "2026-08-06T08:30:00Z",
        declared_coo="CAN",
        target_lean_pct=80.0,
    )
    assert cleaned_changeover["status"] == "SCHEDULED"
    assert cleaned_changeover["declared_coo"] == "CAN"
    assert cleaned_changeover["coo_label"] == "PENDING"

    rows, meta = validate_paginated(
        api.list_grind_runs(CUTTER, {"department_id": department["id"]})
    )
    assert meta["total_count"] == 2
    assert {row["id"] for row in rows} == {domestic["id"], cleaned_changeover["id"]}


# ---------------------------------------------------------------------------
# Aborting the grinder gives every committed pound back
# ---------------------------------------------------------------------------

def test_aborting_a_started_run_returns_every_committed_pound_and_no_cost_effects(api):
    """An abort hands each lot back exactly the pounds it had committed and
    leaves the ground item's cost, label and price untouched.

    "Aborting instead — a `MeatManager` action available as either `IN_PROGRESS →
    ABORTED` or `SCHEDULED → ABORTED` and requiring an `abort_reason` of 1 to 280
    characters — moves every input lot's run pounds out of `allocated_lb` back
    into `remaining_lb`, leaves each input's `consumed` flag at `false`, and
    applies **none** of the cost, price, label or fill effects of the completion
    branch."

    Design: Difficulty/compensating_invariant/grind_run_abort_restores_trim_pounds_with_zero_drift
    """
    ctx = trim_lots_for_blend(api, lot_a_lb=12.0, lot_b_lb=6.5)
    department_id = ctx["department"]["id"]
    ground = propose_price(api, ctx["ground_item"]["id"], ctx["purchase"]["id"])
    assert ground["price_status"] == "PROPOSED"

    run = create_grind_run(
        api,
        department_id,
        ground["id"],
        "2026-08-06T06:00:00Z",
        "2026-08-06T07:00:00Z",
        declared_coo="MULTIPLE",
        target_lean_pct=84.0,
    )

    input_a = add_grind_input(api, run["id"], ctx["lot_a"]["id"], 1, 8.0)
    partly = read_trim_lot(api, ctx["lot_a"]["id"])
    assert partly["status"] == "PARTIALLY_COMMITTED"
    assert partly["allocated_lb"] == pytest.approx(8.0, abs=0.01)
    assert partly["remaining_lb"] == pytest.approx(4.0, abs=0.01)
    assert_trim_lot_buckets_conserve(partly)

    input_b = add_grind_input(api, run["id"], ctx["lot_b"]["id"], 2, 6.5)
    fully = read_trim_lot(api, ctx["lot_b"]["id"])
    assert fully["status"] == "FULLY_COMMITTED"
    assert fully["allocated_lb"] == pytest.approx(6.5, abs=0.01)
    assert fully["remaining_lb"] == pytest.approx(0.0, abs=0.01)
    assert_trim_lot_buckets_conserve(fully)

    started = start_grind_run(api, run["id"])
    assert started["status"] == "IN_PROGRESS"
    assert started["batch_weight_lb"] == pytest.approx(14.5, abs=0.01)
    # (8.0 x 78.0 + 6.5 x 90.0) / 14.5 = 83.379310... to two places.
    assert started["blended_lean_pct"] == pytest.approx(83.38, abs=0.01)
    # (8.0 x 369.8378 + 6.5 x 378.9333) / 14.5 to four places.
    assert started["blend_cost_per_lb_cents"] == pytest.approx(373.9151, abs=0.0001)
    assert started["coo_label"] == "MULTIPLE"

    aborted = abort_grind_run(
        api, run["id"], reason="auger seal failed mid-batch, product pulled to rework hold"
    )
    assert aborted["status"] == "ABORTED"
    assert aborted["abort_reason"] == "auger seal failed mid-batch, product pulled to rework hold"
    assert aborted.get("completed_at") in (None, "")

    restored_a = read_trim_lot(api, ctx["lot_a"]["id"])
    assert restored_a["status"] == "AVAILABLE"
    assert restored_a["allocated_lb"] == pytest.approx(0.0, abs=0.01)
    assert restored_a["remaining_lb"] == pytest.approx(12.0, abs=0.01)
    assert restored_a["consumed_lb"] == pytest.approx(0.0, abs=0.01)
    assert restored_a["discarded_lb"] == pytest.approx(0.0, abs=0.01)
    assert_trim_lot_buckets_conserve(restored_a)

    restored_b = read_trim_lot(api, ctx["lot_b"]["id"])
    assert restored_b["status"] == "AVAILABLE"
    assert restored_b["allocated_lb"] == pytest.approx(0.0, abs=0.01)
    assert restored_b["remaining_lb"] == pytest.approx(6.5, abs=0.01)
    assert restored_b["consumed_lb"] == pytest.approx(0.0, abs=0.01)
    assert restored_b["discarded_lb"] == pytest.approx(0.0, abs=0.01)
    assert_trim_lot_buckets_conserve(restored_b)

    assert read_grind_input(api, input_a["id"])["consumed"] is False
    assert read_grind_input(api, input_b["id"])["consumed"] is False

    # None of the completion branch's effects on the ground item may leak in.
    unchanged_item = read_retail_item(api, ground["id"])
    assert unchanged_item["yield_adjusted_cost_per_lb_cents"] == pytest.approx(0.0, abs=0.0001)
    assert unchanged_item["country_of_origin_label"] == "PENDING"
    assert unchanged_item["price_status"] == "PROPOSED"


def test_aborting_one_of_two_runs_restores_only_that_run_s_pounds(api):
    """One lot committed to two grinder windows comes back down to partly
    committed when a single run is abandoned, and the other run keeps its trim.

    "Restoring pounds runs the same path backwards: an abort takes a lot
    `FULLY_COMMITTED → PARTIALLY_COMMITTED` when the restored pounds still leave
    it partly committed, and `PARTIALLY_COMMITTED → AVAILABLE` when restoring
    returns `allocated_lb` to 0, at which point `remaining_lb` is exactly
    `received_lb` minus `consumed_lb` minus `discarded_lb`."

    Design: Difficulty/compensating_invariant/grind_run_abort_restores_trim_pounds_with_zero_drift
    """
    ctx = approved_cutting_test(api)
    department_id = ctx["department"]["id"]
    lot = create_trim_lot_from_line(
        api, department_id, "TL-A78", 12.0, ctx["lines"][1]["id"]
    )

    morning = create_grind_run(
        api,
        department_id,
        ctx["ground_item"]["id"],
        "2026-08-06T06:00:00Z",
        "2026-08-06T07:00:00Z",
        declared_coo="USA",
        target_lean_pct=78.0,
    )
    afternoon = create_grind_run(
        api,
        department_id,
        ctx["ground_item"]["id"],
        "2026-08-06T08:00:00Z",
        "2026-08-06T09:00:00Z",
        declared_coo="USA",
        target_lean_pct=78.0,
    )

    add_grind_input(api, morning["id"], lot["id"], 1, 4.0)
    after_first = read_trim_lot(api, lot["id"])
    assert after_first["status"] == "PARTIALLY_COMMITTED"
    assert after_first["allocated_lb"] == pytest.approx(4.0, abs=0.01)
    assert after_first["remaining_lb"] == pytest.approx(8.0, abs=0.01)
    assert_trim_lot_buckets_conserve(after_first)

    add_grind_input(api, afternoon["id"], lot["id"], 1, 8.0)
    after_second = read_trim_lot(api, lot["id"])
    assert after_second["status"] == "FULLY_COMMITTED"
    assert after_second["allocated_lb"] == pytest.approx(12.0, abs=0.01)
    assert after_second["remaining_lb"] == pytest.approx(0.0, abs=0.01)
    assert_trim_lot_buckets_conserve(after_second)

    abort_grind_run(api, afternoon["id"], reason="second grinder window released to sanitation")

    partly_back = read_trim_lot(api, lot["id"])
    assert partly_back["status"] == "PARTIALLY_COMMITTED"
    assert partly_back["allocated_lb"] == pytest.approx(4.0, abs=0.01)
    assert partly_back["remaining_lb"] == pytest.approx(8.0, abs=0.01)
    assert partly_back["consumed_lb"] == pytest.approx(0.0, abs=0.01)
    assert partly_back["discarded_lb"] == pytest.approx(0.0, abs=0.01)
    assert_trim_lot_buckets_conserve(partly_back)

    # The surviving window keeps exactly the pounds it drew.
    survivor = read_grind_run(api, morning["id"])
    assert survivor["status"] == "SCHEDULED"
    assert survivor["batch_weight_lb"] == pytest.approx(4.0, abs=0.01)
    assert read_grind_run(api, afternoon["id"])["batch_weight_lb"] == pytest.approx(8.0, abs=0.01)


# ---------------------------------------------------------------------------
# The two completion gates and the terminal abort
# ---------------------------------------------------------------------------

def test_completing_a_run_whose_derived_origin_label_contradicts_its_declaration_is_refused(api):
    """A run declared under Canadian trim that actually ground American trim
    cannot be finished, and its committed pounds stay committed.

    "A grind run declares the segregation block it runs under in `declared_coo`,
    which may be `USA`, `CAN`, `MEX`, `AUS` or `MULTIPLE`, and the label actually
    derived from the run's trim inputs (`coo_label`) must agree with that
    declaration before the run may complete."

    Design: Corner/state_machines/grind_run_complete_with_coo_label_mismatch_is_rejected
    """
    ctx = approved_cutting_test(api)
    department_id = ctx["department"]["id"]
    ground = propose_price(api, ctx["ground_item"]["id"], ctx["purchase"]["id"])
    lot = create_trim_lot_from_line(
        api, department_id, "TL-A78", 12.0, ctx["lines"][1]["id"]
    )
    assert lot["country_of_origin"] == "USA"

    run = create_grind_run(
        api,
        department_id,
        ground["id"],
        "2026-08-06T06:00:00Z",
        "2026-08-06T07:00:00Z",
        declared_coo="CAN",
        target_lean_pct=78.0,
    )
    add_grind_input(api, run["id"], lot["id"], 1, 12.0)
    running = start_grind_run(api, run["id"])
    assert running["status"] == "IN_PROGRESS"
    assert running["declared_coo"] == "CAN"
    assert running["coo_label"] == "USA"
    # The lean gate would have passed, so only the label rule can refuse this.
    assert running["blended_lean_pct"] == pytest.approx(78.0, abs=0.01)

    response = api.transition_grind_run(run["id"], transition_payload("COMPLETE"), CUTTER)
    validate_error(response, "ERR_COO_LABEL_MISMATCH", 422)

    refused = read_grind_run(api, run["id"])
    assert refused["status"] == "IN_PROGRESS"
    assert refused.get("completed_at") in (None, "")

    held_lot = read_trim_lot(api, lot["id"])
    assert held_lot["status"] == "FULLY_COMMITTED"
    assert held_lot["allocated_lb"] == pytest.approx(12.0, abs=0.01)
    assert held_lot["consumed_lb"] == pytest.approx(0.0, abs=0.01)
    assert_trim_lot_buckets_conserve(held_lot)

    unstamped_item = read_retail_item(api, ground["id"])
    assert unstamped_item["country_of_origin_label"] == "PENDING"
    assert unstamped_item["yield_adjusted_cost_per_lb_cents"] == pytest.approx(0.0, abs=0.0001)


def test_completing_a_run_whose_blended_lean_misses_target_by_more_than_tolerance_is_refused(api):
    """A run aiming at 85 lean that ground only 78 lean trim is seven points out
    against a two-point tolerance and cannot be finished.

    "Completing it — the `IN_PROGRESS → COMPLETED` move, again a `MeatCutter`
    action — requires that the absolute difference between `blended_lean_pct` and
    `target_lean_pct` not exceed `lean_tolerance_pct`, or the completion is
    refused with `ERR_LEAN_OUT_OF_TOLERANCE`, and that `coo_label` equal
    `declared_coo` exactly, or refused with `ERR_COO_LABEL_MISMATCH`."

    Design: Corner/state_machines/grind_run_complete_outside_lean_tolerance_is_rejected
    """
    ctx = approved_cutting_test(api)
    department_id = ctx["department"]["id"]
    ground = propose_price(api, ctx["ground_item"]["id"], ctx["purchase"]["id"])
    lot = create_trim_lot_from_line(
        api, department_id, "TL-A78", 12.0, ctx["lines"][1]["id"]
    )

    run = create_grind_run(
        api,
        department_id,
        ground["id"],
        "2026-08-06T06:00:00Z",
        "2026-08-06T07:00:00Z",
        declared_coo="USA",
        target_lean_pct=85.0,
    )
    assert run["lean_tolerance_pct"] == pytest.approx(2.0, abs=0.1)
    add_grind_input(api, run["id"], lot["id"], 1, 12.0)
    running = start_grind_run(api, run["id"])
    assert running["blended_lean_pct"] == pytest.approx(78.0, abs=0.01)
    # The label gate is satisfied, isolating the lean rule.
    assert running["coo_label"] == running["declared_coo"] == "USA"

    response = api.transition_grind_run(run["id"], transition_payload("COMPLETE"), CUTTER)
    validate_error(response, "ERR_LEAN_OUT_OF_TOLERANCE", 422)

    refused = read_grind_run(api, run["id"])
    assert refused["status"] == "IN_PROGRESS"
    assert refused["coo_label"] == "USA"

    held_lot = read_trim_lot(api, lot["id"])
    assert held_lot["consumed_lb"] == pytest.approx(0.0, abs=0.01)
    assert held_lot["allocated_lb"] == pytest.approx(12.0, abs=0.01)
    assert held_lot["status"] == "FULLY_COMMITTED"


def test_no_transition_leaves_an_aborted_grind_run(api):
    """Once the grinder run has been abandoned neither a start nor a second
    abandonment moves it, and its stored reason survives untouched.

    "`COMPLETED` and `ABORTED` are both terminal, so a consumed input never
    reverts."

    Design: Corner/state_machines/grind_run_start_after_abort_is_terminal_lockdown
    """
    department = seeded_department(api)
    ground = create_ground_item(api, department["id"])
    run = create_grind_run(
        api,
        department["id"],
        ground["id"],
        "2026-08-06T06:00:00Z",
        "2026-08-06T07:00:00Z",
        declared_coo="USA",
        target_lean_pct=80.0,
    )
    aborted = abort_grind_run(api, run["id"], reason="grinder pulled for scheduled maintenance")
    assert aborted["status"] == "ABORTED"

    start_again = api.transition_grind_run(run["id"], transition_payload("START"), CUTTER)
    validate_error(start_again, "ERR_INVALID_STATE_TRANSITION", 409)

    abort_again = api.transition_grind_run(
        run["id"], transition_payload("ABORT", abort_reason="second attempt"), MANAGER
    )
    validate_error(abort_again, "ERR_INVALID_STATE_TRANSITION", 409)

    locked = read_grind_run(api, run["id"])
    assert locked["status"] == "ABORTED"
    assert locked["abort_reason"] == "grinder pulled for scheduled maintenance"
    assert locked.get("started_by_user_id") in (None, "")
    assert locked["batch_weight_lb"] == pytest.approx(0.0, abs=0.01)


# ---------------------------------------------------------------------------
# The blend the grinder actually produced
# ---------------------------------------------------------------------------

def test_a_two_country_blend_labels_the_batch_multiple_and_stamps_the_ground_item(api):
    """Ten pounds of American chuck trim ground with ten pounds of Canadian
    round trim labels the batch as coming from more than one country.

    "`coo_label` is `PENDING` when the run has no inputs, the single shared value
    when every input lot carries the same `country_of_origin`, and `MULTIPLE`
    when two or more distinct countries are represented."

    Design: Corner/calculations/grind_blend_labels_a_two_country_batch_multiple
    """
    department = seeded_department(api)
    department_id = department["id"]
    chuck_item = create_retail_item(
        api,
        department_id,
        item_code="CHK01",
        subprimal_code="CHUCK_ROAST",
        product_class="WHOLE_MUSCLE",
    )
    round_item = create_retail_item(
        api,
        department_id,
        item_code="RND01",
        subprimal_code="ROUND_ROAST",
        product_class="WHOLE_MUSCLE",
    )
    ground_item = create_ground_item(api, department_id)

    # 30000 cents landed over 100 net pounds; the trim line takes 5000 of it.
    domestic_purchase = create_primal_purchase(
        api,
        department_id,
        primal_code="BEEF_CHUCK_ROLL",
        country_of_origin="USA",
        gross_weight_lb=100.0,
        invoice_cost_cents=30000,
        freight_cost_cents=0,
        vendor_allowance_cents=0,
        receiving_shrink_lb=0.0,
        received_at="2026-08-05T06:00:00Z",
    )
    # 18000 cents landed over 60 net pounds; the trim line takes 4500 of it.
    imported_purchase = create_primal_purchase(
        api,
        department_id,
        primal_code="BEEF_STRIP_LOIN",
        country_of_origin="CAN",
        vendor_name="Maple Beef",
        gross_weight_lb=60.0,
        invoice_cost_cents=18000,
        freight_cost_cents=0,
        vendor_allowance_cents=0,
        receiving_shrink_lb=0.0,
        received_at="2026-08-05T06:30:00Z",
    )
    ground_item = propose_price(api, ground_item["id"], domestic_purchase["id"])

    domestic_test = create_cutting_test(
        api,
        domestic_purchase["id"],
        domestic_purchase["net_weight_lb"],
        domestic_purchase["version"],
    )
    add_cutting_test_line(
        api,
        domestic_test["id"],
        1,
        "CHUCK_ROAST",
        "SALABLE_CUT",
        50.0,
        1000,
        retail_item_id=chuck_item["id"],
    )
    domestic_trim_line = add_cutting_test_line(
        api, domestic_test["id"], 2, "CHUCK_TRIM_80", "GRIND_TRIM", 25.0, 400, lean_pct=80.0
    )
    add_cutting_test_line(
        api, domestic_test["id"], 3, "CHUCK_FAT_BONE", "FAT_BONE_LOSS", 25.0, 0
    )
    submit_cutting_test(api, domestic_test["id"])
    approve_cutting_test(api, domestic_test["id"])

    imported_test = create_cutting_test(
        api,
        imported_purchase["id"],
        imported_purchase["net_weight_lb"],
        imported_purchase["version"],
    )
    add_cutting_test_line(
        api,
        imported_test["id"],
        1,
        "ROUND_ROAST",
        "SALABLE_CUT",
        30.0,
        900,
        retail_item_id=round_item["id"],
    )
    imported_trim_line = add_cutting_test_line(
        api, imported_test["id"], 2, "ROUND_TRIM_90", "GRIND_TRIM", 20.0, 450, lean_pct=90.0
    )
    add_cutting_test_line(
        api, imported_test["id"], 3, "ROUND_FAT_BONE", "FAT_BONE_LOSS", 10.0, 0
    )
    submit_cutting_test(api, imported_test["id"])
    approve_cutting_test(api, imported_test["id"])

    domestic_lot = create_trim_lot_from_line(
        api, department_id, "TL-USA", 10.0, domestic_trim_line["id"]
    )
    imported_lot = create_trim_lot_from_line(
        api, department_id, "TL-CAN", 10.0, imported_trim_line["id"]
    )
    assert domestic_lot["country_of_origin"] == "USA"
    assert domestic_lot["lean_pct"] == pytest.approx(80.0, abs=0.1)
    # 5000 cents over 25.0 pounds.
    assert domestic_lot["cost_per_lb_cents"] == pytest.approx(200.0, abs=0.0001)
    assert imported_lot["country_of_origin"] == "CAN"
    assert imported_lot["lean_pct"] == pytest.approx(90.0, abs=0.1)
    # 4500 cents over 20.0 pounds.
    assert imported_lot["cost_per_lb_cents"] == pytest.approx(225.0, abs=0.0001)

    run = create_grind_run(
        api,
        department_id,
        ground_item["id"],
        "2026-08-06T06:00:00Z",
        "2026-08-06T07:00:00Z",
        declared_coo="MULTIPLE",
        target_lean_pct=85.0,
    )
    first_input = add_grind_input(api, run["id"], domestic_lot["id"], 1, 10.0)
    second_input = add_grind_input(api, run["id"], imported_lot["id"], 2, 10.0)
    running = start_grind_run(api, run["id"])
    assert running["batch_weight_lb"] == pytest.approx(20.0, abs=0.01)
    # (10.0 x 80.0 + 10.0 x 90.0) / 20.0 and (10.0 x 200 + 10.0 x 225) / 20.0.
    assert running["blended_lean_pct"] == pytest.approx(85.0, abs=0.01)
    assert running["blend_cost_per_lb_cents"] == pytest.approx(212.5, abs=0.0001)
    assert running["coo_label"] == "MULTIPLE"

    completed = complete_grind_run(api, run["id"])
    assert completed["status"] == "COMPLETED"
    assert completed["completed_at"].startswith("2026-08-05T08:00:00")
    assert_grind_run(completed)

    stamped_item = read_retail_item(api, ground_item["id"])
    assert stamped_item["yield_adjusted_cost_per_lb_cents"] == pytest.approx(212.5, abs=0.0001)
    assert stamped_item["country_of_origin_label"] == "MULTIPLE"

    for lot_id in (domestic_lot["id"], imported_lot["id"]):
        consumed_lot = read_trim_lot(api, lot_id)
        assert consumed_lot["status"] == "CONSUMED"
        assert consumed_lot["consumed_lb"] == pytest.approx(10.0, abs=0.01)
        assert consumed_lot["allocated_lb"] == pytest.approx(0.0, abs=0.01)
        assert consumed_lot["remaining_lb"] == pytest.approx(0.0, abs=0.01)
        assert_trim_lot_buckets_conserve(consumed_lot)

    assert read_grind_input(api, first_input["id"])["consumed"] is True
    assert read_grind_input(api, second_input["id"])["consumed"] is True


# ---------------------------------------------------------------------------
# The trim-side gates: one re-work only, and no discarding committed trim
# ---------------------------------------------------------------------------

def test_trim_rework_and_discard_gates_are_enforced_on_one_lot_family(api):
    """Trim may be re-worked once and no further, committed trim may not be
    written off, and written-off trim may not be drawn into the grinder.

    "Because the department's re-grind limit is one generation, re-working a lot
    that is itself already a re-work is prohibited outright and is rejected with
    `ERR_PROHIBITED_REGRIND` (HTTP 422); consequently `rework_generation` never
    exceeds 1."

    Design: Corner/validations/trim_lot_rework_and_discard_gates_are_enforced
    """
    department = seeded_department(api)
    department_id = department["id"]
    chuck_item = create_retail_item(
        api,
        department_id,
        item_code="CHK01",
        subprimal_code="CHUCK_ROAST",
        product_class="WHOLE_MUSCLE",
    )
    ground_item = create_ground_item(api, department_id)
    purchase = create_primal_purchase(
        api,
        department_id,
        primal_code="BEEF_CHUCK_ROLL",
        country_of_origin="USA",
        gross_weight_lb=100.0,
        invoice_cost_cents=30000,
        freight_cost_cents=0,
        vendor_allowance_cents=0,
        receiving_shrink_lb=0.0,
        received_at="2026-08-05T06:00:00Z",
    )
    test = create_cutting_test(
        api, purchase["id"], purchase["net_weight_lb"], purchase["version"]
    )
    add_cutting_test_line(
        api, test["id"], 1, "CHUCK_ROAST", "SALABLE_CUT", 50.0, 1000,
        retail_item_id=chuck_item["id"],
    )
    trim_line = add_cutting_test_line(
        api, test["id"], 2, "CHUCK_TRIM_80", "GRIND_TRIM", 25.0, 400, lean_pct=80.0
    )
    add_cutting_test_line(api, test["id"], 3, "CHUCK_FAT_BONE", "FAT_BONE_LOSS", 25.0, 0)
    submit_cutting_test(api, test["id"])
    approve_cutting_test(api, test["id"])

    harvested = create_trim_lot_from_line(api, department_id, "TL-1", 10.0, trim_line["id"])
    assert harvested["rework_generation"] == 0
    reworked = rework_trim_lot(api, department_id, "TL-2", 5.0, harvested["id"])
    assert reworked["rework_generation"] == 1
    assert reworked["country_of_origin"] == "USA"
    assert reworked["lean_pct"] == pytest.approx(80.0, abs=0.1)
    assert reworked["cost_per_lb_cents"] == pytest.approx(200.0, abs=0.0001)
    # Re-worked trim is dated as ground product: pack date plus two days.
    assert reworked["sell_by_date"] == "2026-08-07"

    committed_lot = create_trim_lot_from_line(
        api, department_id, "TL-4", 10.0, trim_line["id"]
    )
    spoiled_lot = create_trim_lot_from_line(
        api, department_id, "TL-5", 5.0, trim_line["id"]
    )
    run = create_grind_run(
        api,
        department_id,
        ground_item["id"],
        "2026-08-06T06:00:00Z",
        "2026-08-06T07:00:00Z",
        declared_coo="USA",
        target_lean_pct=80.0,
    )
    add_grind_input(api, run["id"], committed_lot["id"], 1, 5.0)

    second_generation = api.create_trim_lot(
        trim_lot_payload(
            department_id,
            "TL-3",
            2.0,
            FIXTURE_DATE,
            source_trim_lot_id=reworked["id"],
        ),
        CUTTER,
    )
    validate_error(second_generation, "ERR_PROHIBITED_REGRIND", 422)

    lots, _meta = validate_paginated(
        api.list_trim_lots(CUTTER, {"department_id": department_id})
    )
    assert {lot["lot_code"] for lot in lots} == {"TL-1", "TL-2", "TL-4", "TL-5"}

    partly_committed = read_trim_lot(api, committed_lot["id"])
    assert partly_committed["status"] == "PARTIALLY_COMMITTED"
    assert partly_committed["allocated_lb"] == pytest.approx(5.0, abs=0.01)
    assert partly_committed["remaining_lb"] == pytest.approx(5.0, abs=0.01)

    discard_committed = api.transition_trim_lot(
        committed_lot["id"], transition_payload("DISCARD"), CUTTER
    )
    validate_error(discard_committed, "ERR_TRIM_LOT_COMMITTED", 422)
    still_committed = read_trim_lot(api, committed_lot["id"])
    assert still_committed["discarded_lb"] == pytest.approx(0.0, abs=0.01)
    assert still_committed["status"] == "PARTIALLY_COMMITTED"

    written_off = discard_trim_lot(api, spoiled_lot["id"])
    assert written_off["status"] == "DISCARDED"
    assert written_off["discarded_lb"] == pytest.approx(5.0, abs=0.01)
    assert written_off["remaining_lb"] == pytest.approx(0.0, abs=0.01)
    assert_trim_lot_buckets_conserve(written_off)

    # Written-off trim is no longer available, which is heard before the pounds
    # rule further down the ladder of PRD §2.11.
    drawn_after_discard = api.create_grind_input(
        run["id"], grind_input_payload(spoiled_lot["id"], 2, 1.0), CUTTER
    )
    validate_error(drawn_after_discard, "ERR_TRIM_LOT_NOT_AVAILABLE", 409)
    assert read_grind_run(api, run["id"])["batch_weight_lb"] == pytest.approx(5.0, abs=0.01)


# ---------------------------------------------------------------------------
# The grind input as the edge between a run and a lot
# ---------------------------------------------------------------------------

def test_a_grind_input_binds_run_to_lot_and_moves_pounds_on_both_sides(api):
    """Committing trim into a run needs a lot that exists, and the commitment
    shows up on the lot, on the run's blend and in listings from either side.

    "Committing pounds to a run moves them from `remaining_lb` into
    `allocated_lb`; completing that run moves them from `allocated_lb` into
    `consumed_lb`; aborting it moves them back out of `allocated_lb` into
    `remaining_lb`."

    Design: Corner/endpoints/grind_input_link_binds_a_run_to_a_lot_and_moves_both_sides
    """
    department = seeded_department(api)
    department_id = department["id"]
    chuck_item = create_retail_item(
        api,
        department_id,
        item_code="CHK01",
        subprimal_code="CHUCK_ROAST",
        product_class="WHOLE_MUSCLE",
    )
    ground_item = create_ground_item(api, department_id)
    purchase = create_primal_purchase(
        api,
        department_id,
        primal_code="BEEF_CHUCK_ROLL",
        country_of_origin="USA",
        gross_weight_lb=100.0,
        invoice_cost_cents=30000,
        freight_cost_cents=0,
        vendor_allowance_cents=0,
        receiving_shrink_lb=0.0,
        received_at="2026-08-05T06:00:00Z",
    )
    test = create_cutting_test(
        api, purchase["id"], purchase["net_weight_lb"], purchase["version"]
    )
    add_cutting_test_line(
        api, test["id"], 1, "CHUCK_ROAST", "SALABLE_CUT", 50.0, 1000,
        retail_item_id=chuck_item["id"],
    )
    trim_line = add_cutting_test_line(
        api, test["id"], 2, "CHUCK_TRIM_80", "GRIND_TRIM", 25.0, 400, lean_pct=80.0
    )
    add_cutting_test_line(api, test["id"], 3, "CHUCK_FAT_BONE", "FAT_BONE_LOSS", 25.0, 0)
    submit_cutting_test(api, test["id"])
    approve_cutting_test(api, test["id"])

    lot = create_trim_lot_from_line(api, department_id, "TL-1", 10.0, trim_line["id"])
    run = create_grind_run(
        api,
        department_id,
        ground_item["id"],
        "2026-08-06T06:00:00Z",
        "2026-08-06T07:00:00Z",
        declared_coo="USA",
        target_lean_pct=80.0,
    )

    unknown_lot = api.create_grind_input(
        run["id"], grind_input_payload(NON_EXISTENT_UUID, 1, 4.0), CUTTER
    )
    validate_error(unknown_lot, "ERR_TRIM_LOT_NOT_FOUND", 404)
    assert read_grind_run(api, run["id"])["batch_weight_lb"] == pytest.approx(0.0, abs=0.01)

    edge = get_success_data(
        api.create_grind_input(run["id"], grind_input_payload(lot["id"], 1, 4.0), CUTTER),
        201,
    )
    assert edge["grind_run_id"] == run["id"]
    assert edge["trim_lot_id"] == lot["id"]
    assert edge["input_seq"] == 1
    assert edge["weight_lb"] == pytest.approx(4.0, abs=0.01)
    assert edge["consumed"] is False
    assert_grind_input(edge)

    from_the_run, run_meta = validate_paginated(
        api.list_grind_inputs(CUTTER, {"grind_run_id": run["id"]})
    )
    assert run_meta["total_count"] == 1
    assert from_the_run[0]["id"] == edge["id"]

    from_the_lot, lot_meta = validate_paginated(
        api.list_grind_inputs(MANAGER, {"trim_lot_id": lot["id"], "consumed": "false"})
    )
    assert lot_meta["total_count"] == 1
    assert from_the_lot[0]["id"] == edge["id"]

    drawn_lot = read_trim_lot(api, lot["id"])
    assert drawn_lot["status"] == "PARTIALLY_COMMITTED"
    assert drawn_lot["allocated_lb"] == pytest.approx(4.0, abs=0.01)
    assert drawn_lot["remaining_lb"] == pytest.approx(6.0, abs=0.01)
    assert_trim_lot_buckets_conserve(drawn_lot)

    loaded_run = read_grind_run(api, run["id"])
    assert loaded_run["batch_weight_lb"] == pytest.approx(4.0, abs=0.01)
    assert loaded_run["blended_lean_pct"] == pytest.approx(80.0, abs=0.01)
    assert loaded_run["blend_cost_per_lb_cents"] == pytest.approx(200.0, abs=0.0001)
    assert loaded_run["coo_label"] == "USA"
    # Trim may be attached before the grinder ever turns.
    assert loaded_run["status"] == "SCHEDULED"
