"""Publication pipelines, pipeline runs and the dataset version ledger."""

from flask import Blueprint, request

import calc
import services
from calc import D
from common import bad_state, dept_scope, find
from core import (
    body,
    caller,
    db,
    err,
    new_row,
    now,
    ok,
    opt_enum,
    opt_str,
    page,
    req_datetime,
    req_enum,
    req_int,
    req_str,
    sort_rows,
    touch,
)

bp = Blueprint("pipelines", __name__)

PIPELINE_STATUSES = ("DRAFT", "ARMED", "SUSPENDED", "DECOMMISSIONED")
RUN_STATUSES = ("SCHEDULED", "RUNNING", "SUCCEEDED", "FAILED", "RETRY_QUEUED", "SKIPPED")
VERSION_STATUSES = ("LIVE", "SUPERSEDED", "RETRACTED")


def check_occ(dataset, expected):
    if expected != dataset["version"]:
        err(
            "ERR_STALE_DATASET_VERSION",
            "expected_dataset_version %s does not match the dataset's current version %s."
            % (expected, dataset["version"]),
        )


def minute_of_day(moment):
    return moment.hour * 60 + moment.minute


def check_window(pipeline, moment):
    minute = minute_of_day(moment)
    if minute < pipeline["window_start_minute"] or minute >= pipeline["window_end_minute"]:
        err(
            "ERR_RUN_OUTSIDE_WINDOW",
            "scheduled_for_utc falls outside the pipeline's publication window.",
        )


def enum_filter(name, allowed):
    value = request.args.get(name)
    if value is None:
        return None
    if value not in allowed:
        err("ERR_INVALID_REQUEST", "%s must be one of %s." % (name, ", ".join(allowed)))
    return value


# --------------------------------------------------------------------------
# Publication pipelines
# --------------------------------------------------------------------------
@bp.post("/publication-pipelines")
def create_pipeline():
    role, user_id = caller("DataCoordinator")
    data = body()
    dataset_id = req_str(data, "dataset_id")
    runner_id = req_str(data, "runner_id")
    cadence = req_enum(data, "cadence", calc.PIPELINE_CADENCES)
    window_start = req_int(data, "window_start_minute", 0, 1439)
    duration = req_int(data, "window_duration_minutes", 1, 480)
    alert_email = req_str(data, "alert_email")
    expected = req_int(data, "expected_dataset_version")
    dataset = find("datasets", dataset_id)
    find("runners", runner_id)
    dept_scope(user_id, dataset["department_id"])
    check_occ(dataset, expected)
    window_end = window_start + duration
    if window_end > 1440:
        err(
            "ERR_WINDOW_WRAPS_MIDNIGHT",
            "window_start_minute + window_duration_minutes may not exceed 1440.",
        )
    predecessor_id = None
    for existing in services.pipelines_of_dataset(dataset_id):
        if existing["status"] in ("DRAFT", "ARMED", "SUSPENDED"):
            services.decommission_pipeline(existing, "PIPELINE_DECOMMISSIONED")
            predecessor_id = existing["id"]
    row = new_row()
    row.update(
        {
            "dataset_id": dataset_id,
            "runner_id": runner_id,
            "superseded_pipeline_id": predecessor_id,
            "cadence": cadence,
            "window_start_minute": window_start,
            "window_duration_minutes": duration,
            "window_end_minute": window_end,
            "alert_email": alert_email,
            "escrow_required_units": calc.escrow_required_units(cadence),
            "escrowed_credit_units": calc.ZERO,
            "consecutive_failure_count": 0,
            "suspend_reason": None,
            "status": "DRAFT",
        }
    )
    db.pipelines[row["id"]] = row
    touch(dataset)
    return ok(services.pipeline_out(row), 201)


@bp.get("/publication-pipelines")
def list_pipelines():
    caller("DataCoordinator", "PortalAdmin")
    dataset_id = request.args.get("dataset_id")
    runner_id = request.args.get("runner_id")
    superseded = request.args.get("superseded_pipeline_id")
    status = enum_filter("status", PIPELINE_STATUSES)
    cadence = enum_filter("cadence", calc.PIPELINE_CADENCES)
    rows = list(db.pipelines.values())
    if dataset_id is not None:
        rows = [r for r in rows if r["dataset_id"] == dataset_id]
    if runner_id is not None:
        rows = [r for r in rows if r["runner_id"] == runner_id]
    if superseded is not None:
        rows = [r for r in rows if r["superseded_pipeline_id"] == superseded]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    if cadence is not None:
        rows = [r for r in rows if r["cadence"] == cadence]
    return page(rows, services.pipeline_out)


@bp.get("/publication-pipelines/<pipeline_id>")
def get_pipeline(pipeline_id):
    caller("DataCoordinator", "PortalAdmin")
    return ok(services.pipeline_out(find("pipelines", pipeline_id)))


@bp.post("/publication-pipelines/<pipeline_id>/arm")
def arm_pipeline(pipeline_id):
    role, user_id = caller("DataCoordinator")
    pipeline = find("pipelines", pipeline_id)
    dataset = db.datasets.get(pipeline["dataset_id"])
    department = services.dept_of_dataset(dataset)
    runner = db.runners.get(pipeline["runner_id"])
    dept_scope(user_id, dataset["department_id"] if dataset else None)
    if pipeline["status"] != "DRAFT":
        bad_state("Only a DRAFT pipeline may be armed.")
    if dataset is None or dataset["publication_status"] != "PUBLISHED":
        err("ERR_DATASET_NOT_PUBLISHED", "The dataset must be PUBLISHED to arm its pipeline.")
    services.check_runner_exclusivity(pipeline)
    services.check_department_capacity(pipeline)
    if runner is None or runner["status"] != "ACTIVE":
        err("ERR_RUNNER_NOT_ACTIVE", "The ingest runner is not ACTIVE.")
    if department is not None and department["compliance_posture"] == "SUSPENDED":
        err("ERR_DEPARTMENT_SUSPENDED", "The owning department's posture is SUSPENDED.")
    required = D(pipeline["escrow_required_units"])
    if department is None or D(department["credit_balance_units"]) < required:
        err(
            "ERR_INSUFFICIENT_CREDITS",
            "The department's credit balance is below the required escrow.",
        )
    pipeline["status"] = "ARMED"
    pipeline["escrowed_credit_units"] = required
    touch(pipeline)
    department["credit_balance_units"] = calc.q2(D(department["credit_balance_units"]) - required)
    department["credits_escrowed_units"] = calc.q2(
        D(department["credits_escrowed_units"]) + required
    )
    touch(department)
    runner["armed_window_count"] = runner["armed_window_count"] + 1
    touch(runner)
    return ok(services.pipeline_out(pipeline))


@bp.post("/publication-pipelines/<pipeline_id>/suspend")
def suspend(pipeline_id):
    role, user_id = caller("DataCoordinator", "PortalAdmin")
    pipeline = find("pipelines", pipeline_id)
    data = body()
    reason = opt_enum(data, "suspend_reason", calc.SUSPEND_REASONS, "ADMIN_REQUEST")
    if pipeline["status"] != "ARMED":
        bad_state("Only an ARMED pipeline may be suspended.")
    services.suspend_pipeline(pipeline, reason)
    return ok(services.pipeline_out(pipeline))


@bp.post("/publication-pipelines/<pipeline_id>/resume")
def resume(pipeline_id):
    role, user_id = caller("DataCoordinator")
    pipeline = find("pipelines", pipeline_id)
    dataset = db.datasets.get(pipeline["dataset_id"])
    runner = db.runners.get(pipeline["runner_id"])
    dept_scope(user_id, dataset["department_id"] if dataset else None)
    if pipeline["status"] != "SUSPENDED":
        bad_state("Only a SUSPENDED pipeline may be resumed.")
    if dataset is None or dataset["publication_status"] != "PUBLISHED":
        err("ERR_DATASET_NOT_PUBLISHED", "The dataset must be PUBLISHED to resume its pipeline.")
    services.check_runner_exclusivity(pipeline)
    services.check_department_capacity(pipeline)
    if runner is None or runner["status"] != "ACTIVE":
        err("ERR_RUNNER_NOT_ACTIVE", "The ingest runner is not ACTIVE.")
    pipeline["status"] = "ARMED"
    pipeline["consecutive_failure_count"] = 0
    pipeline["suspend_reason"] = None
    touch(pipeline)
    runner["armed_window_count"] = runner["armed_window_count"] + 1
    touch(runner)
    services.recompute_currency(dataset)
    services.recompute_department_of(dataset)
    return ok(services.pipeline_out(pipeline))


@bp.post("/publication-pipelines/<pipeline_id>/decommission")
def decommission(pipeline_id):
    role, user_id = caller("DataCoordinator", "PortalAdmin")
    pipeline = find("pipelines", pipeline_id)
    dataset = db.datasets.get(pipeline["dataset_id"])
    if role == "DataCoordinator":
        dept_scope(user_id, dataset["department_id"] if dataset else None)
    if pipeline["status"] not in ("DRAFT", "ARMED", "SUSPENDED"):
        bad_state("A DECOMMISSIONED pipeline accepts no further transitions.")
    services.decommission_pipeline(pipeline, "PIPELINE_DECOMMISSIONED")
    return ok(services.pipeline_out(pipeline))


# --------------------------------------------------------------------------
# Pipeline runs
# --------------------------------------------------------------------------
@bp.post("/pipeline-runs")
def create_run():
    caller("DataCoordinator", "PortalAdmin")
    data = body()
    pipeline_id = req_str(data, "pipeline_id")
    scheduled_for = req_datetime(data, "scheduled_for_utc")
    pipeline = find("pipelines", pipeline_id)
    if scheduled_for < now():
        err("ERR_RUN_SCHEDULE_INVALID", "scheduled_for_utc may not be in the past.")
    check_window(pipeline, scheduled_for)
    row = new_row()
    row.update(
        {
            "pipeline_id": pipeline_id,
            "scheduled_for_utc": scheduled_for,
            "started_at": None,
            "finished_at": None,
            "rows_ingested": 0,
            "failure_code": None,
            "alert_dispatched": False,
            "consecutive_failure_index": pipeline["consecutive_failure_count"],
            "compute_credits": calc.ZERO,
            "alert_credits": calc.ZERO,
            "subtotal_credits": calc.ZERO,
            "reliability_discount_pct": calc.ZERO,
            "discount_credits": calc.ZERO,
            "total_charge_credits": calc.ZERO,
            "escrow_drawn_units": calc.ZERO,
            "balance_drawn_units": calc.ZERO,
            "skip_reason": None,
            "status": "SCHEDULED",
        }
    )
    db.runs[row["id"]] = row
    return ok(services.run_out(row), 201)


@bp.get("/pipeline-runs")
def list_runs():
    caller("DataCoordinator", "PortalAdmin")
    pipeline_id = request.args.get("pipeline_id")
    status = enum_filter("status", RUN_STATUSES)
    failure_code = enum_filter("failure_code", calc.FAILURE_CODES)
    rows = list(db.runs.values())
    if pipeline_id is not None:
        rows = [r for r in rows if r["pipeline_id"] == pipeline_id]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    if failure_code is not None:
        rows = [r for r in rows if r["failure_code"] == failure_code]
    return page(rows, services.run_out)


@bp.get("/pipeline-runs/<run_id>")
def get_run(run_id):
    caller("DataCoordinator", "PortalAdmin")
    return ok(services.run_out(find("runs", run_id)))


@bp.post("/pipeline-runs/<run_id>/start")
def start_run(run_id):
    caller("DataCoordinator", "PortalAdmin")
    run = find("runs", run_id)
    pipeline = db.pipelines.get(run["pipeline_id"])
    dataset = db.datasets.get(pipeline["dataset_id"]) if pipeline else None
    runner = db.runners.get(pipeline["runner_id"]) if pipeline else None
    first_start = run["status"] == "SCHEDULED"
    if run["status"] not in ("SCHEDULED", "RETRY_QUEUED"):
        bad_state("Only a SCHEDULED or RETRY_QUEUED run may be started.")
    if pipeline is None or pipeline["status"] != "ARMED":
        err("ERR_PIPELINE_NOT_ARMED", "The owning pipeline is not ARMED.")
    if first_start and (dataset is None or dataset["publication_status"] != "PUBLISHED"):
        err("ERR_DATASET_NOT_PUBLISHED", "The dataset must be PUBLISHED to start a run.")
    if (
        first_start
        and dataset is not None
        and dataset["embargo_until_utc"] is not None
        and now() < dataset["embargo_until_utc"]
    ):
        err("ERR_EMBARGO_ACTIVE", "The dataset's embargo has not yet expired.")
    if now() < run["scheduled_for_utc"]:
        err("ERR_RUN_SCHEDULE_INVALID", "The run may not start before scheduled_for_utc.")
    if runner is None or runner["status"] != "ACTIVE":
        err("ERR_RUNNER_NOT_ACTIVE", "The ingest runner is not ACTIVE.")
    run["status"] = "RUNNING"
    run["started_at"] = now()
    touch(run)
    return ok(services.run_out(run))


@bp.post("/pipeline-runs/<run_id>/report-success")
def report_success(run_id):
    caller("DataCoordinator", "PortalAdmin")
    run = find("runs", run_id)
    data = body()
    rows_ingested = req_int(data, "rows_ingested", 0)
    pipeline = db.pipelines.get(run["pipeline_id"])
    dataset = db.datasets.get(pipeline["dataset_id"]) if pipeline else None
    department = services.dept_of_dataset(dataset) if dataset else None
    if run["status"] != "RUNNING":
        bad_state("Only a RUNNING run may report success.")
    run["status"] = "SUCCEEDED"
    run["finished_at"] = now()
    run["rows_ingested"] = rows_ingested
    run["alert_dispatched"] = False
    services.settle(run, pipeline, department)
    touch(run)
    pipeline["consecutive_failure_count"] = 0
    touch(pipeline)
    if dataset is not None:
        services.mint_version(
            dataset, "SCHEDULED_REFRESH", rows_ingested, source_run_id=run["id"]
        )
        services.recompute_currency(dataset)
        services.recompute_department(department)
    return ok(services.run_out(run))


@bp.post("/pipeline-runs/<run_id>/report-failure")
def report_failure(run_id):
    caller("DataCoordinator", "PortalAdmin")
    run = find("runs", run_id)
    data = body()
    failure_code = req_enum(data, "failure_code", calc.FAILURE_CODES)
    pipeline = db.pipelines.get(run["pipeline_id"])
    dataset = db.datasets.get(pipeline["dataset_id"]) if pipeline else None
    department = services.dept_of_dataset(dataset) if dataset else None
    if run["status"] != "RUNNING":
        bad_state("Only a RUNNING run may report failure.")
    run["status"] = "FAILED"
    run["finished_at"] = now()
    run["failure_code"] = failure_code
    run["rows_ingested"] = 0
    run["alert_dispatched"] = True
    pipeline["consecutive_failure_count"] = pipeline["consecutive_failure_count"] + 1
    run["consecutive_failure_index"] = pipeline["consecutive_failure_count"]
    services.settle(run, pipeline, department)
    touch(run)
    touch(pipeline)
    if (
        pipeline["consecutive_failure_count"] >= calc.FAILURE_STREAK_LIMIT
        and pipeline["status"] == "ARMED"
    ):
        services.suspend_pipeline(pipeline, "FAILURE_STREAK")
    return ok(services.run_out(run))


@bp.post("/pipeline-runs/<run_id>/requeue")
def requeue_run(run_id):
    caller("DataCoordinator", "PortalAdmin")
    run = find("runs", run_id)
    data = body()
    scheduled_for = req_datetime(data, "scheduled_for_utc")
    pipeline = db.pipelines.get(run["pipeline_id"])
    if run["status"] != "FAILED":
        bad_state("Only a FAILED run may be requeued.")
    if pipeline is None or pipeline["status"] != "ARMED":
        err("ERR_PIPELINE_NOT_ARMED", "The owning pipeline is not ARMED.")
    if scheduled_for < now():
        err("ERR_RUN_SCHEDULE_INVALID", "scheduled_for_utc may not be in the past.")
    check_window(pipeline, scheduled_for)
    run["status"] = "RETRY_QUEUED"
    run["scheduled_for_utc"] = scheduled_for
    run["failure_code"] = None
    run["started_at"] = None
    run["finished_at"] = None
    run["alert_dispatched"] = False
    touch(run)
    return ok(services.run_out(run))


# --------------------------------------------------------------------------
# Dataset versions
# --------------------------------------------------------------------------
@bp.post("/dataset-versions")
def create_version():
    role, user_id = caller("DataCoordinator")
    data = body()
    dataset_id = req_str(data, "dataset_id")
    change_type = req_enum(data, "change_type", calc.CHANGE_TYPES)
    row_count = req_int(data, "row_count", 0)
    notes = opt_str(data, "notes")
    correction_issue_id = opt_str(data, "correction_issue_id")
    expected = req_int(data, "expected_dataset_version")
    dataset = find("datasets", dataset_id)
    if correction_issue_id is not None:
        find("issues", correction_issue_id)
    dept_scope(user_id, dataset["department_id"])
    check_occ(dataset, expected)
    if dataset["publication_status"] not in calc.PUBLISHED_STATES:
        err(
            "ERR_DATASET_NOT_PUBLISHED",
            "Versions may only be published while the dataset is PUBLISHED or UNDER_REMEDIATION.",
        )
    version = services.mint_version(
        dataset, change_type, row_count, notes=notes, correction_issue_id=correction_issue_id
    )
    services.recompute_currency(dataset)
    services.recompute_department_of(dataset)
    return ok(services.version_out(version), 201)


@bp.get("/dataset-versions")
def list_versions():
    caller()
    dataset_id = request.args.get("dataset_id")
    source_run_id = request.args.get("source_run_id")
    correction_issue_id = request.args.get("correction_issue_id")
    supersedes = request.args.get("supersedes_version_id")
    status = enum_filter("status", VERSION_STATUSES)
    change_type = enum_filter("change_type", calc.CHANGE_TYPES)
    rows = list(db.versions.values())
    if dataset_id is not None:
        rows = [r for r in rows if r["dataset_id"] == dataset_id]
    if source_run_id is not None:
        rows = [r for r in rows if r["source_run_id"] == source_run_id]
    if correction_issue_id is not None:
        rows = [r for r in rows if r["correction_issue_id"] == correction_issue_id]
    if supersedes is not None:
        rows = [r for r in rows if r["supersedes_version_id"] == supersedes]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    if change_type is not None:
        rows = [r for r in rows if r["change_type"] == change_type]
    return page(rows, services.version_out)


@bp.get("/dataset-versions/<version_id>")
def get_version(version_id):
    caller()
    return ok(services.version_out(find("versions", version_id)))


@bp.post("/dataset-versions/<version_id>/retract")
def retract_version(version_id):
    caller("DataCoordinator", "PortalAdmin")
    version = find("versions", version_id)
    data = body()
    opt_str(data, "reason")
    dataset = db.datasets.get(version["dataset_id"])
    if version["status"] != "LIVE":
        err("ERR_VERSION_NOT_LIVE", "Only the LIVE version may be retracted.")
    predecessor = None
    if version["version_index"] >= 2:
        for candidate in sort_rows(services.versions_of_dataset(version["dataset_id"])):
            if candidate["version_index"] == version["version_index"] - 1:
                predecessor = candidate
                break
    if predecessor is None or predecessor["status"] != "SUPERSEDED":
        err("ERR_NO_PREDECESSOR_VERSION", "There is no SUPERSEDED predecessor to restore.")
    version["status"] = "RETRACTED"
    version["retracted_at"] = now()
    touch(version)
    predecessor["status"] = "LIVE"
    predecessor["superseded_at"] = None
    touch(predecessor)
    if dataset is not None:
        dataset["live_row_count"] = predecessor["row_count"]
        dataset["last_published_at"] = predecessor["published_at"]
        touch(dataset)
        services.recompute_currency(dataset)
    return ok(services.version_out(version))
