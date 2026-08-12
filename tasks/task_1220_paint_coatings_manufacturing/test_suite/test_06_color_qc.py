"""Color quality control: verdict segregation, terminal verdicts, the delta-e
threshold, the rework cap, retain samples, and pinned thresholds."""

import test_helpers as fx
from test_helpers import (
    ApiErrorId,
    QC_INSPECTOR_10,
    QC_INSPECTOR_9,
    validate_error,
    validate_success,
)


def test_colormatch_double_approve_returns_invalid_state(api):
    """PRD §3.6: "Both `APPROVED` and `REJECTED` are terminal verdicts for
    the measurement record itself."
    PRD §3.6: "An approved match records `decided_by_user_id` and
    `decided_at`, mints a `retain_sample_id`, and computes `retain_until` as
    the decision date plus the retention period for the batch's product
    category"

    Design: Corner/state_machines/colormatch_double_approve_returns_invalid_state
    """
    fx.set_clock("2026-05-01T00:00:00Z")
    _tb1, _c1, f1, m1 = fx.setup_plant()
    b1 = fx.plan_batch(f1["id"], m1["id"], planned_gallons=3)
    fx.start_batch(b1["id"])
    fx.dispersion_pass(b1["id"], 18)
    fx.submit_qc(b1["id"], 3)
    cm1 = fx.enter_measurement(b1["id"], 0.42)

    approved = fx.approve_match(cm1["id"])
    assert approved["status"] == "APPROVED"
    assert approved.get("retain_sample_id"), "approval mints a retain sample id"
    assert fx.read_batch(b1["id"])["status"] == "QC_APPROVED"

    second = api.approve_color_match(cm1["id"], fx.QC_INSPECTOR_2)
    validate_error(second, ApiErrorId.ERR_INVALID_STATE.value, 409)

    settled = fx.read_color_match(cm1["id"])
    assert settled["status"] == "APPROVED"
    assert settled["decided_by_user_id"] == "qc-1", (
        "the failed second approve must not overwrite the first decision"
    )


def test_segregation_colormatch_same_user_cannot_approve(api):
    """PRD §3.6: "And the approver must not be the operator who entered the
    measurement: an `X-User-ID` equal to the record's `measured_by_user_id`
    violates segregation of duties and is rejected with
    `ERR_SEGREGATION_OF_DUTY`."
    PRD §3.6: "An approved match records `decided_by_user_id` and
    `decided_at`, mints a `retain_sample_id`, and computes `retain_until` as
    the decision date plus the retention period for the batch's product
    category — 24 calendar months for `FLAT` and `NONFLAT`, 18 for `PRIMER`,
    36 for `INDUSTRIAL_MAINTENANCE`, and 12 for `TRAFFIC_MARKING`."

    Design: Corner/rbac/segregation_colormatch_same_user_cannot_approve
    """
    fx.set_clock("2026-05-01T00:00:00Z")
    _tb1, _c1, f1, m1 = fx.setup_plant()
    b1 = fx.plan_batch(f1["id"], m1["id"], planned_gallons=3)
    fx.start_batch(b1["id"])
    fx.dispersion_pass(b1["id"], 18)
    fx.submit_qc(b1["id"], 3)

    # Measurement entered by qc-9 acting in the QCInspector capacity.
    cm1 = fx.enter_measurement(b1["id"], 0.42, measured_by=QC_INSPECTOR_9)
    assert fx.read_color_match(cm1["id"])["measured_by_user_id"] == "qc-9"

    same_user = api.approve_color_match(cm1["id"], QC_INSPECTOR_9)
    validate_error(same_user, ApiErrorId.ERR_SEGREGATION_OF_DUTY.value, 422)

    # A different inspector approves the same match.
    approved = fx.approve_match(cm1["id"], headers=QC_INSPECTOR_10)
    assert approved["status"] == "APPROVED"
    assert approved["decided_by_user_id"] == "qc-10"
    # NONFLAT retention: decided 2026-05-01 + 24 calendar months.
    assert approved["retain_until"].startswith("2028-05-01"), (
        f"retain_until must be decision date + 24 months, got {approved['retain_until']}"
    )


def test_delta_e_threshold_equality_boundary(api):
    """PRD §3.6: "The measured distance must be at or below the pinned
    threshold — `measured_delta_e` greater than `threshold_delta_e` is
    rejected with `ERR_DELTA_E_EXCEEDED`."
    PRD §3.6: "When the batch's `rework_count` is still below the cap of 2,
    rejection moves the batch from `QC_PENDING` to `REWORK` and increments
    `rework_count` by one"

    Design: Corner/calculations/delta_e_threshold_equality_boundary
    """
    fx.set_clock("2026-05-01T00:00:00Z")
    _tb1, _c1, f1, m1 = fx.setup_plant()

    # Batch A measured exactly at the formula's 0.8 target.
    ba = fx.plan_batch(f1["id"], m1["id"], planned_gallons=3)
    fx.start_batch(ba["id"])
    fx.dispersion_pass(ba["id"], 18)
    fx.submit_qc(ba["id"], 3)
    cma = fx.enter_measurement(ba["id"], 0.8)

    # Batch B one hundredth over, on a disjoint mill window.
    bb = fx.plan_batch(f1["id"], m1["id"], planned_gallons=3,
                       window=("2026-06-11T08:00:00Z", "2026-06-11T12:00:00Z"))
    fx.start_batch(bb["id"])
    fx.dispersion_pass(bb["id"], 18)
    fx.submit_qc(bb["id"], 3)
    cmb = fx.enter_measurement(bb["id"], 0.81)

    approved = fx.approve_match(cma["id"])
    assert approved["status"] == "APPROVED", "0.8 <= 0.8: equality passes"
    assert fx.read_batch(ba["id"])["status"] == "QC_APPROVED"

    exceeded = api.approve_color_match(cmb["id"], fx.QC_INSPECTOR)
    validate_error(exceeded, ApiErrorId.ERR_DELTA_E_EXCEEDED.value, 422)

    # The over-threshold match can still be rejected, driving rework.
    rejected = fx.reject_match(cmb["id"])
    assert rejected["status"] == "REJECTED"
    bb_after = fx.read_batch(bb["id"])
    assert bb_after["status"] == "REWORK"
    assert bb_after["rework_count"] == 1


def test_rework_cap_condemns_batch_on_third_rejection(api):
    """PRD §3.6: "when the count has already reached 2, the third rejection
    condemns the batch outright, moving it from `QC_PENDING` to
    `DISPOSAL_PENDING`."
    PRD §3.9: "when nothing was expected, exactly nothing must be certified
    destroyed"
    PRD §3.7: "A condemned batch waits in `DISPOSAL_PENDING` until a disposal
    request referencing it completes (§3.9), at which point the batch becomes
    `DISPOSED` — terminal — and its mill reservation is finally released."

    Design: Corner/state_machines/rework_cap_condemns_batch_on_third_rejection
    """
    fx.set_clock("2026-05-01T00:00:00Z")
    _tb1, _c1, f1, m1 = fx.setup_plant()
    b1 = fx.plan_batch(f1["id"], m1["id"], planned_gallons=3)

    # Two full reject/rework cycles (rework_count climbs to the cap of 2).
    fx.start_batch(b1["id"])
    for i, reading in enumerate((1.5, 1.4)):
        fx.dispersion_pass(b1["id"], 18)
        fx.submit_qc(b1["id"], 3)
        cm = fx.enter_measurement(b1["id"], reading)
        fx.reject_match(cm["id"])
        state = fx.read_batch(b1["id"])
        assert state["status"] == "REWORK"
        assert state["rework_count"] == i + 1
        # Each full cycle ends with the rework action (REWORK -> MILLING,
        # §3.6) so the next dispersion check runs from a MILLING batch.
        validate_success(api.rework_batch(b1["id"], fx.PRODUCTION_OPERATOR))

    # Third rejection at the cap: condemned, no further rework.
    fx.dispersion_pass(b1["id"], 18)
    fx.submit_qc(b1["id"], 3)
    cm3 = fx.enter_measurement(b1["id"], 1.3)
    fx.reject_match(cm3["id"])
    condemned = fx.read_batch(b1["id"])
    assert condemned["status"] == "DISPOSAL_PENDING"
    assert condemned["rework_count"] == 2

    # A batch-only disposal request completes with the zero-expected gate.
    dr1 = fx.create_disposal_request(reason="BATCH_REJECT", container_ids=[],
                                     batch_ids=[b1["id"]])
    assert dr1["hazmat_class"] == "NON_HAZARDOUS"
    assert dr1["expected_destroyed_kg"] == 0
    completed = validate_success(
        api.complete_disposal_request(dr1["id"], {"actual_destroyed_kg": 0},
                                      fx.PLANT_MANAGER)
    )
    assert completed["status"] == "DISPOSED"
    assert fx.read_batch(b1["id"])["status"] == "DISPOSED"
    assert fx.read_mill(m1["id"])["reserved_minutes"] == 0, (
        "disposal releases the mill reservation"
    )


def test_reject_cascade_blocks_order_and_rework_reverses(api):
    """PRD §3.6: "Rejection shares the same state, cycle, and segregation
    preconditions and drives the rework loop. When the batch's `rework_count`
    is still below the cap of 2, rejection moves the batch from `QC_PENDING`
    to `REWORK` and increments `rework_count` by one; when the count has
    already reached 2, the third rejection condemns the batch outright,
    moving it from `QC_PENDING` to `DISPOSAL_PENDING`. Either way, an order
    in `IN_PRODUCTION` behind the batch moves to `BLOCKED`."
    PRD §3.6: "Sending a rejected batch back down the line is the operator's
    rework action: the mill must be `ACTIVE` (`ERR_MILL_NOT_AVAILABLE`), the
    batch moves from `REWORK` back to `MILLING` — where dispersion checks,
    further adjustments, and a fresh QC submission all run again — and a
    `BLOCKED` order behind it returns to `IN_PRODUCTION`."

    Design: Difficulty/transitive_cascade/color_match_reject_cascade_depth2
    """
    fx.set_clock("2026-05-01T00:00:00Z")
    env = fx.setup_plant_with_order(line_gallons=3)
    b1 = fx.plan_batch(env["f1"]["id"], env["m1"]["id"], planned_gallons=3,
                       order_id=env["o1"]["id"])
    validate_success(
        api.schedule_order(env["o1"]["id"], {"batch_id": b1["id"]},
                           fx.PRODUCTION_OPERATOR)
    )
    fx.start_batch(b1["id"])
    assert fx.read_order(env["o1"]["id"])["status"] == "IN_PRODUCTION"
    fx.dispersion_pass(b1["id"], 18)
    fx.submit_qc(b1["id"], 3)
    cm1 = fx.enter_measurement(b1["id"], 1.5)

    # Link 1: the verdict moves the batch; link 2: the batch blocks its
    # in-production order.
    rejected = fx.reject_match(cm1["id"])
    assert rejected["status"] == "REJECTED"
    batch = fx.read_batch(b1["id"])
    assert batch["status"] == "REWORK"
    assert batch["rework_count"] == 1
    assert fx.read_order(env["o1"]["id"])["status"] == "BLOCKED"

    # The rework action unwinds link 2.
    reentered = validate_success(api.rework_batch(b1["id"], fx.PRODUCTION_OPERATOR))
    assert reentered["status"] == "MILLING"
    assert fx.read_order(env["o1"]["id"])["status"] == "IN_PRODUCTION"


def test_reject_cascade_leaves_stock_batch_orderless(api):
    """PRD §3.6: "Either way, an order in `IN_PRODUCTION` behind the batch
    moves to `BLOCKED`."
    PRD §3.4: "a batch without an order is a stock batch."

    Design: Difficulty/transitive_cascade/color_match_reject_cascade_depth2
    """
    fx.set_clock("2026-05-01T00:00:00Z")
    _tb1, _c1, f1, m1 = fx.setup_plant()
    b1 = fx.plan_batch(f1["id"], m1["id"], planned_gallons=3)
    assert b1.get("order_id") is None
    fx.start_batch(b1["id"])
    fx.dispersion_pass(b1["id"], 18)
    fx.submit_qc(b1["id"], 3)
    cm1 = fx.enter_measurement(b1["id"], 1.5)

    fx.reject_match(cm1["id"])
    batch = fx.read_batch(b1["id"])
    assert batch["status"] == "REWORK"
    assert batch["rework_count"] == 1
    assert batch.get("order_id") is None

    reentered = validate_success(api.rework_batch(b1["id"], fx.PRODUCTION_OPERATOR))
    assert reentered["status"] == "MILLING"


def test_version_pinning_color_match_threshold_snapshot(api):
    """PRD §3.6: "The record is born `PENDING` with two snapshots pinned at
    entry: `cycle_index`, the batch's `rework_count` at measurement time, and
    `threshold_delta_e`, the formula's `target_delta_e` at that same moment,
    so a later formula change cannot retroactively move the goalposts."
    PRD §3.1: "Every batch still in `PLANNED` against the deprecated
    predecessor moves to `ON_HOLD`"

    Design: Corner/cross_cutting_layers/version_pinning_color_match_threshold_snapshot
    """
    fx.set_clock("2026-05-01T00:00:00Z")
    _tb1, _c1, f1, m1 = fx.setup_plant()
    b1 = fx.plan_batch(f1["id"], m1["id"], planned_gallons=3)
    fx.start_batch(b1["id"])
    fx.dispersion_pass(b1["id"], 18)
    fx.submit_qc(b1["id"], 3)
    cm1 = fx.enter_measurement(b1["id"], 0.7)
    assert fx.read_color_match(cm1["id"])["threshold_delta_e"] == 0.8

    # The formula is deprecated after the measurement was taken.
    validate_success(api.deprecate_formula(f1["id"], fx.LAB_TECHNICIAN))

    # The in-flight batch is unaffected (only PLANNED batches go on hold),
    # and approval is still judged against the pinned 0.8.
    assert fx.read_batch(b1["id"])["status"] == "QC_PENDING"
    assert fx.read_color_match(cm1["id"])["threshold_delta_e"] == 0.8
    approved = fx.approve_match(cm1["id"])
    assert approved["status"] == "APPROVED", "0.7 <= pinned 0.8 still approves"
    assert fx.read_batch(b1["id"])["status"] == "QC_APPROVED"


def test_close_blocked_after_retain_purge_returns_error(api):
    """PRD §3.7: "Closure is refused with `ERR_INVALID_STATE` while any
    container of the batch remains `QUARANTINED`, and refused with
    `ERR_RETAIN_SAMPLE_MISSING` unless an `APPROVED` color match from the
    batch's final cycle exists whose retain sample is still live —
    `retain_purged_at` still null."
    PRD §3.8: "every `APPROVED` color match whose `retain_until` is strictly
    before the sweep date has its `retain_purged_at` stamped with the sweep
    date, retiring the retain sample."

    Design: Corner/state_machines/close_blocked_after_retain_purge_returns_error
    """
    fx.set_clock("2026-05-01T00:00:00Z")
    _tb1, _c1, f1, m1 = fx.setup_plant()
    b1 = fx.plan_batch(f1["id"], m1["id"], planned_gallons=1)
    batch, containers = fx.drive_batch_to_filled(
        b1["id"], actual_gallons=1, fills=[("GALLON", 4600)], waste_gallons=0
    )
    assert batch["status"] == "FILLED"

    # Approved at clock 2026-05-01 (approval happened before fills);
    # NONFLAT retention is 24 months -> retain_until 2028-05-01.
    matches, _ = fx.validate_paginated(
        api.list_color_matches(fx.PLANT_MANAGER, params={"batch_id": b1["id"]})
    )
    cm1 = matches[0]
    assert cm1["status"] == "APPROVED"
    assert cm1["retain_until"].startswith("2028-05-01")

    # Age past the retain window and sweep: the sample is retired.
    fx.set_clock("2028-06-11T00:00:00Z")
    sweep = fx.run_daily_sweep()
    assert isinstance(sweep["purged_retain_sample_ids"], list)
    purged = fx.read_color_match(cm1["id"])
    assert purged["retain_purged_at"] is not None
    assert purged["retain_purged_at"].startswith("2028-06-11")

    blocked = api.close_batch(b1["id"], fx.PRODUCTION_OPERATOR)
    validate_error(blocked, ApiErrorId.ERR_RETAIN_SAMPLE_MISSING.value, 422)
    assert fx.read_batch(b1["id"])["status"] == "FILLED"


def test_order_cancel_in_production_returns_invalid_state(api):
    """PRD §3.3: "An order in `IN_PRODUCTION` cannot be cancelled — product
    is being made — and the attempt is rejected with `ERR_INVALID_STATE`."
    PRD §3.3: "From then on the order's status mirrors its batch: the order
    moves from `SCHEDULED` to `IN_PRODUCTION` when the batch starts milling"

    Design: Corner/state_machines/order_cancel_in_production_returns_invalid_state
    """
    fx.set_clock("2026-05-01T00:00:00Z")
    env = fx.setup_plant_with_order(line_gallons=3)
    b1 = fx.plan_batch(env["f1"]["id"], env["m1"]["id"], planned_gallons=3,
                       order_id=env["o1"]["id"])
    validate_success(
        api.schedule_order(env["o1"]["id"], {"batch_id": b1["id"]},
                           fx.PRODUCTION_OPERATOR)
    )
    fx.start_batch(b1["id"])
    assert fx.read_order(env["o1"]["id"])["status"] == "IN_PRODUCTION"

    refused = api.cancel_order(env["o1"]["id"], fx.PLANT_MANAGER)
    validate_error(refused, ApiErrorId.ERR_INVALID_STATE.value, 409)
    assert fx.read_order(env["o1"]["id"])["status"] == "IN_PRODUCTION"
