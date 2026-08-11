"""ScheduleVersion endpoints (PRD §3.2, §3.3)."""

from datetime import timedelta

from flask import Blueprint

from db import store
from errors import (
    ApiError,
    ERR_INVALID_STATE,
    ERR_EMPTY_SCHEDULE,
    ERR_BASELINE_ALREADY_ACCEPTED,
    ERR_BASELINE_NOT_ACCEPTED,
    ERR_STALE_VERSION,
    ERR_INVALID_REQUEST,
)
from middleware import (
    require_roles, json_body, req_field, as_str, as_datetime, as_enum,
    as_int, paginate, sorted_items, touch, serialize, ANY_ROLE,
)
from response import ok_object, ok_list
from util import new_id, clock_iso, parse_dt, fmt_dt
from routes.common import (
    get_project, get_version, activities_of, latest_accepted_baseline,
)
from services.cpm import run_cpm_and_persist, clear_computed_activity_fields
from services.tia import run_tia

bp = Blueprint("schedule_versions", __name__)

KINDS = {"BASELINE", "UPDATE"}


@bp.route("/construction-projects/<pid>/schedule-versions", methods=["POST"],
          strict_slashes=False)
def create_version(pid):
    require_roles("ContractorScheduler")
    project = get_project(pid)
    data = json_body()
    kind = as_enum(req_field(data, "kind"), "kind", KINDS)
    data_date = as_datetime(req_field(data, "data_date"), "data_date")
    supersedes = data.get("supersedes_version_id")
    if supersedes is not None:
        supersedes = as_str(supersedes, "supersedes_version_id")
        if kind == "BASELINE":
            raise ApiError(ERR_INVALID_REQUEST, 400,
                           "A BASELINE version never carries "
                           "supersedes_version_id")
        sv = store.schedule_versions.get(supersedes)
        if sv is None or sv["project_id"] != project["id"] \
                or sv["kind"] != "UPDATE":
            raise ApiError(ERR_INVALID_REQUEST, 400,
                           "supersedes_version_id must reference a prior "
                           "UPDATE version of this project")
    # Per-kind monotonically increasing counter starting at 1.
    revision = 1 + sum(
        1 for v in store.schedule_versions.values()
        if v["project_id"] == project["id"] and v["kind"] == kind)
    now = clock_iso()
    version = {
        "id": new_id(),
        "project_id": project["id"],
        "kind": kind,
        "data_date": data_date,
        "revision_number": revision,
        "supersedes_version_id": supersedes,
        "projected_finish_date": None,
        "critical_path_activity_count": None,
        "total_activities": 0,
        "status": "DRAFT",
        "created_at": now,
        "updated_at": now,
        "version": 1,
        "_seq": store.next_seq(),
        "_accepted_seq": None,
    }
    store.schedule_versions[version["id"]] = version
    return ok_object(serialize(version), 201)


@bp.route("/construction-projects/<pid>/schedule-versions", methods=["GET"],
          strict_slashes=False)
def list_versions(pid):
    require_roles(*ANY_ROLE)
    project = get_project(pid)
    items = [v for v in store.schedule_versions.values()
             if v["project_id"] == project["id"]]
    kind = _opt_query("kind")
    status = _opt_query("status")
    if kind is not None:
        items = [v for v in items if v["kind"] == kind]
    if status is not None:
        items = [v for v in items if v["status"] == status]
    items = sorted_items(items)
    page, pg = paginate(items)
    return ok_list([serialize(v) for v in page], pg)


def _opt_query(name):
    from flask import request
    v = request.args.get(name)
    return v if v not in (None, "") else None


@bp.route("/construction-projects/<pid>/schedule-versions/<vid>",
          methods=["GET"], strict_slashes=False)
def get_one_version(pid, vid):
    require_roles(*ANY_ROLE)
    _, version = get_version(pid, vid)
    return ok_object(serialize(version))


@bp.route("/construction-projects/<pid>/schedule-versions/<vid>/submit",
          methods=["POST"], strict_slashes=False)
def submit_version(pid, vid):
    require_roles("ContractorScheduler")
    project, version = get_version(pid, vid)
    json_body()
    if version["status"] != "DRAFT":
        raise ApiError(ERR_INVALID_STATE, 409,
                       "ScheduleVersion is not in DRAFT")
    if not activities_of(version["id"]):
        raise ApiError(ERR_EMPTY_SCHEDULE, 422,
                       "Schedule submit requires at least one Activity")
    # Raises ERR_CYCLE_DETECTED on cyclic network; persists ES/EF/LS/LF/TF,
    # is_critical, critical_path_activity_count, projected_finish_date.
    run_cpm_and_persist(version)
    version["status"] = "SUBMITTED"
    touch(version)
    return ok_object(serialize(version))


@bp.route("/construction-projects/<pid>/schedule-versions/<vid>/accept",
          methods=["POST"], strict_slashes=False)
def accept_version(pid, vid):
    require_roles("ProjectControlsEngineer")
    project, version = get_version(pid, vid)
    data = json_body()
    expected = as_int(req_field(data, "expected_project_version"),
                      "expected_project_version")
    if version["status"] != "SUBMITTED":
        raise ApiError(ERR_INVALID_STATE, 409,
                       "ScheduleVersion is not in SUBMITTED")
    if version["kind"] == "BASELINE":
        if latest_accepted_baseline(project["id"]) is not None:
            raise ApiError(ERR_BASELINE_ALREADY_ACCEPTED, 409,
                           "A different BASELINE is already ACCEPTED for "
                           "this project")
    else:
        if latest_accepted_baseline(project["id"]) is None:
            raise ApiError(ERR_BASELINE_NOT_ACCEPTED, 409,
                           "An UPDATE cannot be ACCEPTED unless an ACCEPTED "
                           "BASELINE exists")
    # OCC stale-version check is evaluated last (PRD §2.6, §2.9).
    if expected != project["version"]:
        raise ApiError(ERR_STALE_VERSION, 412,
                       "expected_project_version does not match the project's "
                       "current version")
    version["status"] = "ACCEPTED"
    version["_accepted_seq"] = store.next_seq()
    touch(version)
    if version["kind"] == "BASELINE" and project["status"] == "PRECONSTRUCTION":
        # Auto-fire the activation chain (PRD §3.1).
        project["status"] = "ACTIVE"
        project["current_completion_date"] = project["contract_completion_date"]
    if version["kind"] == "UPDATE":
        # Recompute current_completion_date against approved EOTs.
        total = 0
        for e in store.eot_requests.values():
            if e["project_id"] == project["id"] and e["status"] in (
                    "APPROVED", "PARTIALLY_APPROVED"):
                total += e.get("approved_days") or 0
        new_ccd = parse_dt(project["contract_completion_date"],
                           "contract_completion_date") + timedelta(days=total)
        project["current_completion_date"] = fmt_dt(new_ccd)
    # Acceptance advances the project version by exactly one.
    project["version"] += 1
    project["updated_at"] = clock_iso()
    # Bubble up: recompute TIA prolongation figures for delay events whose
    # fragnet was inserted into this version.
    for d in store.delay_events.values():
        if d.get("fragnet_inserted_into_version_id") == version["id"] \
                and d["status"] in ("TIA_SUBMITTED", "TIA_ACCEPTED"):
            run_tia(d)
    return ok_object(serialize(version))


@bp.route("/construction-projects/<pid>/schedule-versions/<vid>/reject",
          methods=["POST"], strict_slashes=False)
def reject_version(pid, vid):
    require_roles("ProjectControlsEngineer")
    project, version = get_version(pid, vid)
    json_body()
    if version["status"] != "SUBMITTED":
        raise ApiError(ERR_INVALID_STATE, 409,
                       "ScheduleVersion is not in SUBMITTED")
    version["status"] = "REJECTED"
    touch(version)
    clear_computed_activity_fields(version)
    return ok_object(serialize(version))


@bp.route("/construction-projects/<pid>/schedule-versions/<vid>/revise",
          methods=["POST"], strict_slashes=False)
def revise_version(pid, vid):
    require_roles("ContractorScheduler")
    project, version = get_version(pid, vid)
    json_body()
    if version["status"] != "REJECTED":
        raise ApiError(ERR_INVALID_STATE, 409,
                       "ScheduleVersion is not in REJECTED")
    version["status"] = "DRAFT"
    version["revision_number"] += 1
    touch(version)
    return ok_object(serialize(version))
