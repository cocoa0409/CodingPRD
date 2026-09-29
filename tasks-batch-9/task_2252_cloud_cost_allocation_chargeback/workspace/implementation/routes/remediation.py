"""Idle detection, remediation tasks and the window sweep (PRD 3.8)."""
from flask import Blueprint, request

from db import add_hours, db, fmt_dt, now, touch
from errors import fail
from middleware import authorize
from routes.common import (
    lookup,
    require_resource_owner,
    serve,
    serve_list,
    serve_many,
)
from services import derived, flows
from services.calc import MAX_SNOOZES, REMEDIATION_WINDOW_HOURS, task_metrics
from validation import body, opt_str, req_enum, req_str

bp = Blueprint("remediation", __name__)

KINDS = ("RIGHTSIZE", "IDLE_TERMINATE")
READERS = ("FinOpsAnalyst", "FinOpsController", "PlatformAdmin", "ResourceOwner")
REMEDIABLE_STATES = ("FLAGGED_IDLE", "RIGHTSIZE_PENDING")
WINDOWED_STATES = ("OWNER_NOTIFIED", "OWNER_SNOOZED", "APPROVED")


def _scope_business_unit(data):
    value = opt_str(data, "business_unit_id")
    if value is None:
        value = request.args.get("business_unit_id") or None
    return value


def _resource_for(task):
    return db.cloud_resources.get(task["cloud_resource_id"])


def _require_remediable(resource):
    if resource is None or resource["lifecycle_state"] not in REMEDIABLE_STATES:
        fail(
            "ERR_RESOURCE_NOT_REMEDIABLE",
            "The underlying cloud resource is not flagged for remediation.",
        )


# --------------------------------------------------------------------------
# scans
# --------------------------------------------------------------------------
@bp.route("/finops/scans/idle-detection", methods=["POST"])
@authorize("FinOpsAnalyst")
def idle_detection():
    data = body()
    scope = _scope_business_unit(data)
    created = flows.idle_detection_scan(scope)
    return serve_many(created)


@bp.route("/finops/scans/remediation-window-sweep", methods=["POST"])
@authorize("FinOpsAnalyst")
def window_sweep():
    return serve_many(flows.remediation_sweep())


# --------------------------------------------------------------------------
# tasks
# --------------------------------------------------------------------------
@bp.route("/finops/remediation-tasks", methods=["POST"])
@authorize("FinOpsAnalyst")
def create_task():
    data = body()
    resource = lookup("cloud_resources", req_str(data, "cloud_resource_id"))
    kind = req_enum(data, "kind", KINDS)
    _require_remediable(resource)
    task = flows.new_task(resource, kind, task_metrics(resource, kind))
    return serve(task, 201)


@bp.route("/finops/remediation-tasks", methods=["GET"])
@authorize(*READERS)
def list_tasks():
    return serve_list(
        db.remediation_tasks.values(),
        {"cloud_resource_id": "cloud_resource_id", "kind": "kind", "status": "status"},
    )


@bp.route("/finops/remediation-tasks/<task_id>", methods=["GET"])
@authorize(*READERS)
def get_task(task_id):
    return serve(lookup("remediation_tasks", task_id))


@bp.route("/finops/remediation-tasks/<task_id>/notify-owner", methods=["POST"])
@authorize("FinOpsAnalyst")
def notify_owner(task_id):
    task = lookup("remediation_tasks", task_id)
    if task["status"] not in ("PROPOSED", "OWNER_SNOOZED"):
        fail(
            "ERR_REMEDIATION_STATE_INVALID",
            "Only a PROPOSED or OWNER_SNOOZED task may notify the owner.",
        )
    resource = _resource_for(task)
    _require_remediable(resource)

    clock = now()
    if task["status"] == "PROPOSED":
        window_start = clock
        window_end = add_hours(clock, REMEDIATION_WINDOW_HOURS)
        for other in derived.resource_tasks(task["cloud_resource_id"]):
            if other["id"] == task["id"] or other["status"] not in WINDOWED_STATES:
                continue
            other_start = other.get("_window_start_dt")
            other_end = other.get("_window_end_dt")
            if other_start is None or other_end is None:
                continue
            if window_start <= other_end and other_start <= window_end:
                fail(
                    "ERR_REMEDIATION_WINDOW_OVERLAP",
                    "The new remediation window shares an instant with task %s." % other["id"],
                )
        task["remediation_window_starts_at"] = fmt_dt(window_start)
        task["remediation_window_ends_at"] = fmt_dt(window_end)
        task["_window_start_dt"] = window_start
        task["_window_end_dt"] = window_end
    else:
        window_end = task.get("_window_end_dt")
        if window_end is None or clock > window_end:
            fail("ERR_REMEDIATION_WINDOW_EXPIRED", "The remediation window has expired.")

    task["status"] = "OWNER_NOTIFIED"
    touch(task)
    return serve(task)


@bp.route("/finops/remediation-tasks/<task_id>/snooze", methods=["POST"])
@authorize("ResourceOwner")
def snooze_task(task_id):
    task = lookup("remediation_tasks", task_id)
    resource = _resource_for(task)
    if resource is not None:
        require_resource_owner(resource)
    if task["status"] != "OWNER_NOTIFIED":
        fail(
            "ERR_REMEDIATION_STATE_INVALID",
            "Only an OWNER_NOTIFIED task may be snoozed.",
        )
    window_end = task.get("_window_end_dt")
    if window_end is None or now() > window_end:
        fail("ERR_REMEDIATION_WINDOW_EXPIRED", "The remediation window has expired.")
    if task["snooze_count"] >= MAX_SNOOZES:
        fail("ERR_SNOOZE_LIMIT", "The task has already been snoozed twice.")

    new_end = add_hours(window_end, REMEDIATION_WINDOW_HOURS)
    task["status"] = "OWNER_SNOOZED"
    task["remediation_window_ends_at"] = fmt_dt(new_end)
    task["_window_end_dt"] = new_end
    task["snooze_count"] = task["snooze_count"] + 1
    touch(task)
    return serve(task)


@bp.route("/finops/remediation-tasks/<task_id>/approve", methods=["POST"])
@authorize("ResourceOwner")
def approve_task(task_id):
    task = lookup("remediation_tasks", task_id)
    resource = _resource_for(task)
    if resource is not None:
        require_resource_owner(resource)
    if task["status"] not in ("OWNER_NOTIFIED", "OWNER_SNOOZED"):
        fail(
            "ERR_REMEDIATION_STATE_INVALID",
            "Only a notified or snoozed task may be approved.",
        )
    _require_remediable(resource)
    window_end = task.get("_window_end_dt")
    if window_end is None or now() > window_end:
        fail("ERR_REMEDIATION_WINDOW_EXPIRED", "The remediation window has expired.")

    task["status"] = "APPROVED"
    touch(task)
    return serve(task)


@bp.route("/finops/remediation-tasks/<task_id>/cancel", methods=["POST"])
@authorize("ResourceOwner", "FinOpsAnalyst")
def cancel(task_id):
    task = lookup("remediation_tasks", task_id)
    resource = _resource_for(task)
    if resource is not None:
        require_resource_owner(resource)
    data = body()
    req_str(data, "reason")
    if task["status"] not in ("PROPOSED", "OWNER_NOTIFIED", "OWNER_SNOOZED"):
        fail(
            "ERR_REMEDIATION_STATE_INVALID",
            "Only a non-terminal task may be cancelled.",
        )
    flows.cancel_task(task)
    return serve(task)
