"""Durability test rigs and runs (PRD 3.2)."""

from flask import Blueprint

import calc
from auth import get_revision, get_rig, get_run, require
from constants import DUTY_CLASSES, RUN_STATUSES
from envelope import created, ok, ok_list
from errors import ApiError
from store import mutate, new_entity, store
from validation import (
    field_datetime,
    field_enum,
    field_enum_array,
    field_id,
    field_int,
    field_str,
    get_body,
    invalid,
    paginate,
    paging,
    query_enum,
    query_str,
)

bp = Blueprint("testing", __name__)


# ---------------------------------------------------------------------------
# rigs
# ---------------------------------------------------------------------------
@bp.post("/test-rigs")
@require("ProductEngineer", "ServiceOpsAdmin")
def create_test_rig():
    body = get_body()
    name = field_str(body, "name", min_len=1, max_len=80)
    parallel_station_count = field_int(
        body, "parallel_station_count", minimum=1, maximum=8
    )
    supported_duty_classes = field_enum_array(
        body, "supported_duty_classes", DUTY_CLASSES, non_empty=True
    )

    for row in store.test_rigs.values():
        if row["name"] == name:
            raise ApiError(
                "ERR_DUPLICATE_REVISION_CODE", "A test rig name must be unique."
            )

    rig = new_entity(
        {
            "name": name,
            "parallel_station_count": parallel_station_count,
            "supported_duty_classes": supported_duty_classes,
            "occupied_station_count": 0,
        }
    )
    store.test_rigs[rig["id"]] = rig
    return created(rig)


@bp.get("/test-rigs/<rig_id>")
@require("ProductEngineer", "ComplianceOfficer", "ServiceOpsAdmin")
def read_test_rig(rig_id):
    return ok(get_rig(rig_id))


# ---------------------------------------------------------------------------
# runs
# ---------------------------------------------------------------------------
@bp.post("/test-runs")
@require("ProductEngineer")
def create_test_run():
    body = get_body()
    model_revision_id = field_id(body, "model_revision_id")
    test_rig_id = field_id(body, "test_rig_id")
    window_start, start_dt = field_datetime(body, "window_start")
    window_end, end_dt = field_datetime(body, "window_end")
    target_cycles = field_int(body, "target_cycles", minimum=1000)

    # rung 8 — window sanity
    if end_dt <= start_dt:
        raise ApiError(
            "ERR_INVALID_TIME_WINDOW",
            "window_end must be strictly after window_start.",
        )

    # rung 9 — body reference existence
    revision = get_revision(model_revision_id)
    rig = get_rig(test_rig_id)

    # rung 11 — declared transition
    if revision["status"] != "IN_TESTING":
        raise ApiError(
            "ERR_INVALID_STATE_TRANSITION",
            "The revision must be IN_TESTING to book a durability run.",
        )

    # rung 26 — rig duty class
    model = calc.model_of_revision(revision)
    if model["duty_class"] not in rig["supported_duty_classes"]:
        raise ApiError(
            "ERR_RIG_DUTY_CLASS_UNSUPPORTED",
            "The rig does not support the revision's duty class.",
        )

    # rung 33 — rig station capacity, CLOSED/inclusive geometry
    overlapping = 0
    for run in store.test_runs.values():
        if run["test_rig_id"] != rig["id"]:
            continue
        if run["status"] not in ("RESERVED", "RUNNING"):
            continue
        existing_start = calc.dt(run["window_start"])
        existing_end = calc.dt(run["window_end"])
        if start_dt <= existing_end and existing_start <= end_dt:
            overlapping += 1
    if overlapping >= rig["parallel_station_count"]:
        raise ApiError(
            "ERR_RIG_CAPACITY_EXCEEDED",
            "The rig has no free station across the requested window.",
        )

    run = new_entity(
        {
            "model_revision_id": revision["id"],
            "test_rig_id": rig["id"],
            "window_start": window_start,
            "window_end": window_end,
            "target_cycles": target_cycles,
            "status": "RESERVED",
            "outcome": "PENDING",
            "achieved_cycles": 0,
            "failure_cycle_count": None,
            "superseded_by_rework": False,
        }
    )
    store.test_runs[run["id"]] = run
    calc.recompute_rig(rig)
    return created(run)


@bp.get("/test-runs")
@require("ProductEngineer", "ComplianceOfficer", "ServiceOpsAdmin")
def list_test_runs():
    limit, offset = paging()
    model_revision_id = query_str("model_revision_id")
    test_rig_id = query_str("test_rig_id")
    status = query_enum("status", RUN_STATUSES)

    rows = list(store.test_runs.values())
    if model_revision_id is not None:
        rows = [r for r in rows if r["model_revision_id"] == model_revision_id]
    if test_rig_id is not None:
        rows = [r for r in rows if r["test_rig_id"] == test_rig_id]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    page, total = paginate(rows, limit, offset)
    return ok_list(page, limit, offset, total)


@bp.get("/test-runs/<run_id>")
@require("ProductEngineer", "ComplianceOfficer", "ServiceOpsAdmin")
def read_test_run(run_id):
    return ok(get_run(run_id))


@bp.post("/test-runs/<run_id>/start")
@require("ProductEngineer")
def start_test_run(run_id):
    run = get_run(run_id)
    get_body()
    revision = store.model_revisions[run["model_revision_id"]]

    if run["status"] != "RESERVED":
        raise ApiError(
            "ERR_INVALID_STATE_TRANSITION", "Only a RESERVED run may be started."
        )
    if revision["status"] != "IN_TESTING":
        raise ApiError(
            "ERR_INVALID_STATE_TRANSITION",
            "The owning revision must still be IN_TESTING.",
        )

    with mutate(run):
        run["status"] = "RUNNING"
    calc.recompute_rig(store.test_rigs[run["test_rig_id"]])
    calc.recompute_revision_cycles(revision)
    return ok(run)


@bp.post("/test-runs/<run_id>/complete")
@require("ProductEngineer")
def complete_test_run(run_id):
    run = get_run(run_id)
    body = get_body()
    outcome = field_enum(body, "outcome", ("PASSED", "FAILED"))
    achieved_cycles = field_int(body, "achieved_cycles", required=False, minimum=1)
    failure_cycle_count = field_int(body, "failure_cycle_count", required=False, minimum=1)

    if outcome == "PASSED":
        if achieved_cycles is None:
            invalid("Field 'achieved_cycles' is required for a PASSED outcome.")
        if "failure_cycle_count" in body:
            invalid("Field 'failure_cycle_count' must be omitted for a PASSED outcome.")
    else:
        if failure_cycle_count is None:
            invalid("Field 'failure_cycle_count' is required for a FAILED outcome.")
        if failure_cycle_count > run["target_cycles"]:
            invalid("Field 'failure_cycle_count' must not exceed the run's target_cycles.")

    if run["status"] != "RUNNING":
        raise ApiError(
            "ERR_INVALID_STATE_TRANSITION", "Only a RUNNING run may be completed."
        )

    revision = store.model_revisions[run["model_revision_id"]]
    with mutate(run):
        run["status"] = "COMPLETED"
        run["outcome"] = outcome
        if outcome == "PASSED":
            run["achieved_cycles"] = achieved_cycles
            run["failure_cycle_count"] = None
        else:
            run["failure_cycle_count"] = failure_cycle_count

    calc.recompute_rig(store.test_rigs[run["test_rig_id"]])
    calc.recompute_revision_cycles(revision)

    if (
        outcome == "FAILED"
        and revision["verified_cycle_count"] < revision["min_required_cycles"]
        and revision["status"] == "IN_TESTING"
    ):
        with mutate(revision):
            revision["status"] = "TEST_FAILED"
        calc.recompute_model(calc.model_of_revision(revision))
    return ok(run)


@bp.post("/test-runs/<run_id>/abort")
@require("ProductEngineer")
def abort_test_run(run_id):
    run = get_run(run_id)
    body = get_body()
    field_str(body, "abort_reason", min_len=1)

    if run["status"] not in ("RESERVED", "RUNNING"):
        raise ApiError(
            "ERR_INVALID_STATE_TRANSITION",
            "Only a RESERVED or RUNNING run may be aborted.",
        )

    with mutate(run):
        run["status"] = "ABORTED"
    calc.recompute_rig(store.test_rigs[run["test_rig_id"]])
    calc.recompute_revision_cycles(store.model_revisions[run["model_revision_id"]])
    return ok(run)
