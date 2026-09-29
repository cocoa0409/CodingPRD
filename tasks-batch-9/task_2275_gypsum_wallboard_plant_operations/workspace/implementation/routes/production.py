"""Production runs: drafting, scheduling, running, completion, cancellation and
the independent quality dimension (PRD 3.5 - 3.7)."""

from decimal import Decimal

from flask import Blueprint

import calc
import validate as v
from db import base_entity, bump, db, ordered
from errors import fail
from middleware import ANY, acting_user_id, guard
from response import entity_response
from routes.common import (
    list_collection,
    require_ref,
    require_row,
    require_run,
)
from services.cascade import (
    cancel_loads,
    cancel_run,
    hold_run,
    hold_staged_loads,
    release_held_loads,
)
from services.plant import (
    debit_silo,
    recompute_available_msf,
    settle_plant,
)
from util import D, ZERO2, ZERO3, ZERO4, fmt_dt, rhu, whole_minutes

bp = Blueprint("production", __name__)

EDGE_DEFECT_CEILING_PPM = 1500
END_DEFECT_CEILING_PPM = 900
DISPOSITION_ACTIONS = ("RELEASE", "DOWNGRADE", "SCRAP")


def _spec_of(run):
    return db.product_specs[run["product_spec_id"]]


def _plant_of(run):
    return db.plants[run["plant_id"]]


def _line_of(run):
    return db.board_lines[run["line_id"]]


def _batch_of(run):
    return db.calciner_batches[run["calciner_batch_id"]]


def _board_tests_of(run_id):
    return [t for t in ordered(db.board_tests) if t["run_id"] == run_id]


# ------------------------------------------------------------------- drafting
@bp.post("/plant-ops/production-runs")
@guard(("ProductionScheduler",))
def draft_run():
    body = v.body_of()
    plant_id = v.text(body, "plant_id", min_len=1)
    line_id = v.text(body, "line_id", min_len=1)
    product_spec_id = v.text(body, "product_spec_id", min_len=1)
    calciner_batch_id = v.text(body, "calciner_batch_id", min_len=1)
    start_raw, start = v.instant(body, "window_start")
    end_raw, end = v.instant(body, "window_end")
    requested_planned_msf = v.num(body, "requested_planned_msf", gt=0, scale=3)
    line_speed_fpm = v.integer(body, "line_speed_fpm", ge=100, le=1200)
    paper_tension_lb = v.num(body, "paper_tension_lb", gt=0)
    kiln_dwell_minutes = v.integer(body, "kiln_dwell_minutes", ge=10, le=120)
    kiln_exit_moisture_target_pct = v.num(
        body, "kiln_exit_moisture_target_pct", ge="0.05", le="2.00"
    )

    plant = require_ref(db.plants, plant_id, "plant")
    line = require_ref(db.board_lines, line_id, "board line")
    spec = require_ref(db.product_specs, product_spec_id, "product spec")
    batch = require_ref(db.calciner_batches, calciner_batch_id, "calciner batch")

    for child, label in ((line, "board line"), (spec, "product spec"), (batch, "calciner batch")):
        if child["plant_id"] != plant["id"]:
            fail("ERR_PLANT_SCOPE_MISMATCH", "the %s belongs to a different plant" % label)

    if end <= start:
        fail("ERR_INVALID_WINDOW", "window_end must be strictly after window_start")

    ceiling = min(int(line["max_speed_fpm"]), int(spec["line_speed_max_fpm"]))
    if line_speed_fpm > ceiling:
        fail(
            "ERR_LINE_SPEED_EXCEEDS_SPEC",
            "line_speed_fpm %s exceeds the permitted ceiling %s" % (line_speed_fpm, ceiling),
        )

    tension_ok, required_tension = calc.paper_tension_ok(
        spec, line_speed_fpm, paper_tension_lb
    )
    if not tension_ok:
        fail(
            "ERR_PAPER_TENSION_OUT_OF_RANGE",
            "paper_tension_lb must lie within [%s, %s]"
            % (required_tension, spec["paper_tension_max_lb"]),
        )

    projected = calc.projected_exit_moisture(spec, kiln_dwell_minutes)
    if not calc.kiln_profile_feasible(projected, kiln_exit_moisture_target_pct):
        fail(
            "ERR_KILN_PROFILE_INFEASIBLE",
            "projected exit moisture %s breaches the target tolerance" % projected,
        )

    run = base_entity()
    run.update(
        {
            "plant_id": plant["id"],
            "line_id": line["id"],
            "product_spec_id": spec["id"],
            "calciner_batch_id": batch["id"],
            "prior_run_id": None,
            "window_start": start_raw,
            "window_end": end_raw,
            "_window_start": start,
            "_window_end": end,
            "requested_planned_msf": requested_planned_msf,
            "line_speed_fpm": line_speed_fpm,
            "paper_tension_lb": paper_tension_lb,
            "kiln_dwell_minutes": kiln_dwell_minutes,
            "kiln_exit_moisture_target_pct": kiln_exit_moisture_target_pct,
            "required_paper_tension_lb": required_tension,
            "projected_exit_moisture_pct": projected,
            "changeover_minutes": None,
            "gap_minutes": None,
            "in_window_changeover_minutes": None,
            "available_minutes": None,
            "capacity_msf": None,
            "effective_planned_msf": ZERO3,
            "stucco_reserved_tons": ZERO3,
            "kiln_energy_mmbtu": None,
            "kiln_energy_cost_usd": None,
            "actual_msf": ZERO3,
            "scrap_msf": ZERO3,
            "edge_defect_ppm": None,
            "end_defect_ppm": None,
            "stucco_consumed_tons": ZERO3,
            "net_good_msf": ZERO3,
            "scrapped_msf": ZERO3,
            "available_msf": ZERO3,
            "specimen_count": 0,
            "failing_specimen_count": 0,
            "fail_rate": ZERO4,
            "retest_count": 0,
            "last_failing_test_recorded_by_user_id": None,
            "held_reason": None,
            "saleable_grade": "UNGRADED",
            "cancel_reason": None,
            "status": "DRAFT",
            "quality_state": "UNTESTED",
        }
    )
    db.production_runs[run["id"]] = run
    return entity_response(run, 201)


@bp.get("/plant-ops/production-runs")
@guard(ANY)
def list_runs():
    return list_collection(
        db.production_runs,
        (
            "plant_id",
            "line_id",
            "product_spec_id",
            "calciner_batch_id",
            "prior_run_id",
            "status",
            "quality_state",
        ),
    )


@bp.get("/plant-ops/production-runs/<run_id>")
@guard(ANY)
def read_run(run_id):
    return entity_response(require_run(run_id))


# ----------------------------------------------------------------- scheduling
@bp.post("/plant-ops/production-runs/<run_id>/schedule")
@guard(("ProductionScheduler",))
def schedule_run(run_id):
    run = require_run(run_id)
    body = v.body_of()
    expected_plant_version = v.integer(body, "expected_plant_version", ge=0)

    plant = _plant_of(run)
    spec = _spec_of(run)
    batch = _batch_of(run)

    if expected_plant_version != int(plant["version"]):
        fail(
            "ERR_STALE_PLANT_VERSION",
            "expected_plant_version %s does not match the plant's current version %s"
            % (expected_plant_version, plant["version"]),
        )

    if run["status"] != "DRAFT":
        fail("ERR_INVALID_STATE", "only a DRAFT run may be scheduled")
    if batch["status"] not in ("CALCINING", "COMPLETED"):
        fail(
            "ERR_INVALID_STATE",
            "the calciner batch is %s; CALCINING or COMPLETED is required" % batch["status"],
        )

    if plant["production_posture"] == "FROZEN":
        fail("ERR_PLANT_POSTURE_FROZEN", "the plant's production posture is FROZEN")
    if plant["production_posture"] == "RESTRICTED" and spec["fire_rated"]:
        fail(
            "ERR_POSTURE_RESTRICTED_FIRE_RATED",
            "a fire-rated SKU may not be scheduled while the plant is RESTRICTED",
        )

    if spec["fire_rated"] and batch["stucco_quality_flag"] != "PASS":
        fail(
            "ERR_FIRE_RATED_STUCCO_NONCONFORMING",
            "a fire-rated SKU requires a batch whose stucco_quality_flag is PASS",
        )

    for outage in ordered(db.maintenance_outages):
        if outage["line_id"] != run["line_id"]:
            continue
        if outage["status"] not in ("APPROVED", "IN_PROGRESS"):
            continue
        if run["_window_start"] <= outage["_window_end"] and (
            outage["_window_start"] <= run["_window_end"]
        ):
            fail(
                "ERR_OUTAGE_WINDOW_CONFLICT",
                "the window intersects a maintenance outage on this line",
            )

    for other in ordered(db.production_runs):
        if other["id"] == run["id"] or other["line_id"] != run["line_id"]:
            continue
        if other["status"] not in ("SCHEDULED", "RUNNING"):
            continue
        if run["_window_start"] < other["_window_end"] and (
            other["_window_start"] < run["_window_end"]
        ):
            fail("ERR_LINE_WINDOW_CONFLICT", "the window overlaps another run on this line")

    # ---- calculations.run_line_capacity_and_reservation, steps 1..6
    prior = calc.select_prior_run(run, ordered(db.production_runs))
    prior_spec = _spec_of(prior) if prior is not None else None
    changeover = calc.changeover_minutes(run, spec, prior, prior_spec)

    if prior is None:
        gap = None
    else:
        gap = whole_minutes(prior["_window_end"], run["_window_start"])
        if gap < changeover:
            fail(
                "ERR_CHANGEOVER_BUFFER_VIOLATION",
                "gap of %s minutes is shorter than the %s minute changeover"
                % (gap, changeover),
            )

    in_window = calc.COLD_START_MINUTES if prior is None else 0
    available_minutes = whole_minutes(run["_window_start"], run["_window_end"]) - in_window
    per_minute = calc.msf_per_minute(spec, run["line_speed_fpm"])
    capacity_msf = rhu(D(available_minutes) * per_minute, 3)
    if capacity_msf <= ZERO3:
        fail(
            "ERR_WINDOW_TOO_SHORT_FOR_CHANGEOVER",
            "the window yields no production capacity once changeover is absorbed",
        )
    effective = min(D(run["requested_planned_msf"]), capacity_msf)
    reserved = calc.stucco_reservation(effective, spec)
    if reserved > D(plant["stucco_available_tons"]):
        fail(
            "ERR_STUCCO_INSUFFICIENT",
            "the reservation of %s tons exceeds the available %s tons"
            % (reserved, plant["stucco_available_tons"]),
        )

    run["prior_run_id"] = prior["id"] if prior is not None else None
    run["changeover_minutes"] = changeover
    run["gap_minutes"] = gap
    run["in_window_changeover_minutes"] = in_window
    run["available_minutes"] = available_minutes
    run["capacity_msf"] = capacity_msf
    run["effective_planned_msf"] = effective
    run["stucco_reserved_tons"] = reserved

    mmbtu, cost = calc.kiln_energy(spec, plant, run, effective)
    run["kiln_energy_mmbtu"] = mmbtu
    run["kiln_energy_cost_usd"] = cost

    run["status"] = "SCHEDULED"
    bump(run)
    settle_plant(plant)
    return entity_response(run)


# ------------------------------------------------------------------- lifecycle
@bp.post("/plant-ops/production-runs/<run_id>/start")
@guard(("ProductionScheduler",))
def start_run(run_id):
    run = require_run(run_id)
    v.body_of()

    plant = _plant_of(run)
    line = _line_of(run)
    batch = _batch_of(run)

    if run["status"] != "SCHEDULED":
        fail("ERR_INVALID_STATE", "only a SCHEDULED run may be started")
    if line["status"] != "AVAILABLE":
        fail("ERR_LINE_NOT_AVAILABLE", "the line is %s" % line["status"])
    if batch["status"] != "COMPLETED":
        fail(
            "ERR_INVALID_STATE",
            "the calciner batch is %s; COMPLETED is required to start" % batch["status"],
        )
    if batch["stucco_quality_flag"] == "FAIL":
        fail("ERR_INVALID_STATE", "the calciner batch's stucco is nonconforming")

    if plant["production_posture"] == "FROZEN":
        fail("ERR_PLANT_POSTURE_FROZEN", "the plant's production posture is FROZEN")

    if db.now() < run["_window_start"]:
        fail("ERR_RUN_WINDOW_NOT_STARTED", "the logical clock has not reached window_start")

    run["status"] = "RUNNING"
    bump(run)
    return entity_response(run)


@bp.post("/plant-ops/production-runs/<run_id>/complete")
@guard(("ProductionScheduler",))
def complete_run(run_id):
    run = require_run(run_id)
    body = v.body_of()
    actual_msf = v.num(body, "actual_msf", ge=0, scale=3)
    scrap_msf = v.num(body, "scrap_msf", ge=0, scale=3)
    edge_defect_ppm = v.integer(body, "edge_defect_ppm", ge=0)
    end_defect_ppm = v.integer(body, "end_defect_ppm", ge=0)

    if scrap_msf > actual_msf:
        fail("ERR_INVALID_REQUEST", "scrap_msf may not exceed actual_msf")

    if run["status"] != "RUNNING":
        fail("ERR_INVALID_STATE", "only a RUNNING run may be completed")

    plant = _plant_of(run)
    spec = _spec_of(run)

    run["actual_msf"] = actual_msf
    run["scrap_msf"] = scrap_msf
    run["edge_defect_ppm"] = edge_defect_ppm
    run["end_defect_ppm"] = end_defect_ppm
    run["stucco_consumed_tons"] = rhu(
        actual_msf * D(spec["stucco_lb_per_msf"]) / Decimal(2000), 3
    )
    run["net_good_msf"] = rhu(actual_msf - scrap_msf, 3)
    run["status"] = "COMPLETED"
    recompute_available_msf(run)
    bump(run)

    debit_silo(plant, run["stucco_consumed_tons"])
    settle_plant(plant)

    held_reason = None
    if edge_defect_ppm > EDGE_DEFECT_CEILING_PPM:
        held_reason = "EDGE_DEFECT"
    elif end_defect_ppm > END_DEFECT_CEILING_PPM:
        held_reason = "END_DEFECT"
    if held_reason is not None:
        run["quality_state"] = "HELD"
        run["held_reason"] = held_reason
        run["saleable_grade"] = "UNGRADED"
        hold_staged_loads(run)
        settle_plant(plant)

    return entity_response(run)


@bp.post("/plant-ops/production-runs/<run_id>/cancel")
@guard(("ProductionScheduler", "PlantManager"))
def cancel_production_run(run_id):
    run = require_run(run_id)
    body = v.body_of()
    cancel_reason = v.text(body, "cancel_reason", required=False)

    if run["status"] not in ("DRAFT", "SCHEDULED"):
        fail("ERR_INVALID_STATE", "a run in %s may not be cancelled" % run["status"])

    cancel_run(run, _plant_of(run), cancel_reason)
    return entity_response(run)


# --------------------------------------------------------------- board tests
@bp.post("/plant-ops/production-runs/<run_id>/board-tests")
@guard(("QualityInspector",))
def create_board_test(run_id):
    run = require_run(run_id)
    body = v.body_of()
    specimen_seq = v.integer(body, "specimen_seq", ge=1)
    core_hardness_lbf = v.num(body, "core_hardness_lbf", ge=0)
    nail_pull_lbf = v.num(body, "nail_pull_lbf", ge=0)
    flexural_cross_lbf = v.num(body, "flexural_cross_lbf", ge=0)
    flexural_parallel_lbf = v.num(body, "flexural_parallel_lbf", ge=0)
    exit_moisture_pct = v.num(body, "exit_moisture_pct", ge="0.00", le="5.00")

    for existing in db.board_tests.values():
        if existing["run_id"] == run["id"] and existing["specimen_seq"] == specimen_seq:
            fail(
                "ERR_INVALID_REQUEST",
                "specimen_seq %s already exists on this run" % specimen_seq,
            )

    if run["status"] != "COMPLETED":
        fail("ERR_INVALID_STATE", "only a COMPLETED run may be sampled")
    if run["quality_state"] not in ("UNTESTED", "IN_TEST", "HELD"):
        fail(
            "ERR_INVALID_STATE",
            "a run whose quality_state is %s may not be sampled" % run["quality_state"],
        )

    spec = _spec_of(run)
    plant = _plant_of(run)
    result, failing = calc.specimen_result(
        spec,
        run,
        core_hardness_lbf,
        nail_pull_lbf,
        flexural_cross_lbf,
        exit_moisture_pct,
    )

    test = base_entity(versioned=False)
    test.update(
        {
            "run_id": run["id"],
            "specimen_seq": specimen_seq,
            "core_hardness_lbf": core_hardness_lbf,
            "nail_pull_lbf": nail_pull_lbf,
            "flexural_cross_lbf": flexural_cross_lbf,
            "flexural_parallel_lbf": flexural_parallel_lbf,
            "exit_moisture_pct": exit_moisture_pct,
            "result": result,
            "failing_attributes": failing,
            "recorded_by_user_id": acting_user_id(),
            "tested_at": fmt_dt(db.now()),
        }
    )
    db.board_tests[test["id"]] = test

    specimens = _board_tests_of(run["id"])
    run["specimen_count"] = len(specimens)
    run["failing_specimen_count"] = sum(1 for t in specimens if t["result"] == "FAIL")
    run["fail_rate"] = calc.fail_rate_of(
        run["failing_specimen_count"], run["specimen_count"]
    )
    if result == "FAIL":
        run["last_failing_test_recorded_by_user_id"] = acting_user_id()

    was_held = run["quality_state"] == "HELD"
    if was_held:
        run["retest_count"] = int(run["retest_count"]) + 1
    run["quality_state"] = "IN_TEST"
    bump(run)
    if was_held:
        settle_plant(plant)

    return entity_response(test, 201)


@bp.get("/plant-ops/production-runs/<run_id>/board-tests")
@guard(ANY)
def list_run_board_tests(run_id):
    run = require_run(run_id)
    return list_collection(db.board_tests, (), base=_board_tests_of(run["id"]))


@bp.get("/plant-ops/board-tests")
@guard(ANY)
def list_board_tests():
    return list_collection(db.board_tests, ("run_id", "result"))


@bp.get("/plant-ops/board-tests/<board_test_id>")
@guard(ANY)
def read_board_test(board_test_id):
    return entity_response(require_row(db.board_tests, board_test_id, "board test"))


# ------------------------------------------------------- quality evaluation
@bp.post("/plant-ops/production-runs/<run_id>/quality-evaluation")
@guard(("QualityInspector",))
def evaluate_run_quality(run_id):
    run = require_run(run_id)
    v.body_of()

    if run["quality_state"] == "UNTESTED":
        fail("ERR_NO_BOARD_TEST_SPECIMENS", "this run has no recorded specimens")
    if run["quality_state"] != "IN_TEST":
        fail(
            "ERR_INVALID_STATE",
            "a run whose quality_state is %s may not be evaluated" % run["quality_state"],
        )
    if int(run["specimen_count"]) < calc.MIN_SPECIMENS_FOR_RELEASE:
        fail(
            "ERR_INSUFFICIENT_SPECIMENS",
            "at least %s specimens are required" % calc.MIN_SPECIMENS_FOR_RELEASE,
        )

    spec = _spec_of(run)
    plant = _plant_of(run)
    outcome, rate = calc.run_quality_state(
        spec, int(run["specimen_count"]), int(run["failing_specimen_count"])
    )
    run["fail_rate"] = rate

    if outcome == "HELD":
        strength_failure = False
        for test in _board_tests_of(run["id"]):
            for attribute in test.get("failing_attributes") or ():
                if attribute in ("CORE_HARDNESS", "NAIL_PULL", "FLEXURAL_CROSS"):
                    strength_failure = True
        hold_run(run, plant, "BOARD_TEST_FAIL" if strength_failure else "MOISTURE_EXCEEDANCE")
        return entity_response(run)

    run["quality_state"] = outcome
    run["saleable_grade"] = "FIRST_QUALITY" if outcome == "RELEASED" else "SECONDS"
    run["held_reason"] = None
    recompute_available_msf(run)
    bump(run)
    release_held_loads(run)
    return entity_response(run)


@bp.post("/plant-ops/production-runs/<run_id>/quality-disposition")
@guard(("QualityManager",))
def disposition_run_quality(run_id):
    run = require_run(run_id)
    body = v.body_of()
    action = v.enum(body, "action", DISPOSITION_ACTIONS)
    v.text(body, "disposition_note", required=False)

    if run["quality_state"] != "HELD":
        fail("ERR_INVALID_STATE", "only a HELD run may be dispositioned")

    if (
        run["last_failing_test_recorded_by_user_id"] is not None
        and run["last_failing_test_recorded_by_user_id"] == acting_user_id()
    ):
        fail(
            "ERR_SEGREGATION_OF_DUTIES",
            "the inspector who recorded the failing specimen may not disposition this run",
        )

    if action == "RELEASE" and int(run["retest_count"]) < 1:
        fail("ERR_RETEST_REQUIRED", "a RELEASE disposition requires evidence of a re-test")

    plant = _plant_of(run)

    if action == "RELEASE":
        run["quality_state"] = "RELEASED"
        run["saleable_grade"] = "FIRST_QUALITY"
        run["held_reason"] = None
        bump(run)
        release_held_loads(run)
    elif action == "DOWNGRADE":
        run["quality_state"] = "DOWNGRADED"
        run["saleable_grade"] = "SECONDS"
        run["held_reason"] = None
        bump(run)
        release_held_loads(run)
    else:
        run["scrapped_msf"] = rhu(D(run["net_good_msf"]), 3)
        run["net_good_msf"] = ZERO3
        run["quality_state"] = "SCRAPPED"
        run["saleable_grade"] = "SCRAP"
        run["held_reason"] = None
        bump(run)
        cancel_loads(run, "RUN_SCRAPPED")
        run["available_msf"] = ZERO3

    settle_plant(plant)
    return entity_response(run)
