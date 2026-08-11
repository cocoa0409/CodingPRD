"""ProgressUpdate / ProgressEntry endpoints (PRD §3.4)."""

from flask import Blueprint

from db import store
from errors import (
    ApiError,
    ERR_INVALID_STATE,
    ERR_INVALID_REQUEST,
    ERR_INVALID_PROGRESS,
    ERR_ACTIVITY_NOT_IN_VERSION,
    ERR_SCHEDULE_NOT_ACCEPTED,
)
from middleware import (
    require_roles, json_body, req_field, as_str, as_int, as_number,
    as_datetime, paginate, sorted_items, touch, serialize, ANY_ROLE,
)
from response import ok_object, ok_list
from util import new_id, clock_iso, parse_dt
from routes.common import (
    get_version, get_progress_update, activities_of,
)
from services.cpm import run_cpm_and_persist
from services.lda import compute_exposure

bp = Blueprint("progress", __name__)


def _entries_of(puid):
    return [e for e in store.progress_entries.values()
            if e["progress_update_id"] == puid]


@bp.route(
    "/construction-projects/<pid>/schedule-versions/<vid>/progress-updates",
    methods=["POST"], strict_slashes=False)
def create_progress_update(pid, vid):
    require_roles("ContractorScheduler")
    project, version = get_version(pid, vid)
    data = json_body()
    rpe = as_datetime(req_field(data, "reporting_period_end"),
                      "reporting_period_end")
    submitter = as_str(req_field(data, "submitted_by_contractor_user_id"),
                       "submitted_by_contractor_user_id")
    if version["kind"] != "UPDATE":
        raise ApiError(ERR_INVALID_REQUEST, 400,
                       "Progress updates may only be filed against an "
                       "UPDATE schedule version")
    now = clock_iso()
    pu = {
        "id": new_id(),
        "schedule_version_id": version["id"],
        "reporting_period_end": rpe,
        "submitted_by_contractor_user_id": submitter,
        "status": "DRAFT",
        "created_at": now,
        "updated_at": now,
        "version": 1,
        "_seq": store.next_seq(),
    }
    store.progress_updates[pu["id"]] = pu
    return ok_object(serialize(pu), 201)


@bp.route(
    "/construction-projects/<pid>/schedule-versions/<vid>/progress-updates",
    methods=["GET"], strict_slashes=False)
def list_progress_updates(pid, vid):
    require_roles(*ANY_ROLE)
    project, version = get_version(pid, vid)
    items = sorted_items(_ for _ in store.progress_updates.values()
                         if _["schedule_version_id"] == version["id"])
    page, pg = paginate(items)
    return ok_list([serialize(pu) for pu in page], pg)


@bp.route(
    "/construction-projects/<pid>/schedule-versions/<vid>/progress-updates/<puid>",
    methods=["GET"], strict_slashes=False)
def get_one_progress_update(pid, vid, puid):
    require_roles(*ANY_ROLE)
    _, _, pu = get_progress_update(pid, vid, puid)
    return ok_object(serialize(pu))


@bp.route(
    "/construction-projects/<pid>/schedule-versions/<vid>/progress-updates/<puid>/entries",
    methods=["POST"], strict_slashes=False)
def create_progress_entry(pid, vid, puid):
    require_roles("ContractorScheduler")
    project, version, pu = get_progress_update(pid, vid, puid)
    data = json_body()
    activity_id = as_str(req_field(data, "activity_id"), "activity_id")
    percent = as_number(req_field(data, "percent_complete"),
                        "percent_complete")
    remaining = as_int(req_field(data, "remaining_duration_days"),
                       "remaining_duration_days")
    actual_start = data.get("actual_start")
    actual_finish = data.get("actual_finish")
    if actual_start is not None:
        actual_start = as_datetime(actual_start, "actual_start")
    if actual_finish is not None:
        actual_finish = as_datetime(actual_finish, "actual_finish")
    if percent < 0 or percent > 100:
        raise ApiError(ERR_INVALID_REQUEST, 400,
                       "percent_complete must be within 0..100")
    if remaining < 0:
        raise ApiError(ERR_INVALID_REQUEST, 400,
                       "remaining_duration_days must be >= 0")
    if pu["status"] != "DRAFT":
        raise ApiError(ERR_INVALID_STATE, 409,
                       "Entries may only be added to a DRAFT progress update")
    act = store.activities.get(activity_id)
    if act is None or act["schedule_version_id"] != version["id"]:
        raise ApiError(ERR_ACTIVITY_NOT_IN_VERSION, 422,
                       "Activity does not belong to the ProgressUpdate's "
                       "schedule version")
    _check_progress_invariants(percent, remaining, actual_start, actual_finish)
    entry = {
        "id": new_id(),
        "progress_update_id": pu["id"],
        "activity_id": activity_id,
        "percent_complete": percent,
        "remaining_duration_days": remaining,
        "actual_start": actual_start,
        "actual_finish": actual_finish,
        "created_at": clock_iso(),
        "_seq": store.next_seq(),
    }
    store.progress_entries[entry["id"]] = entry
    return ok_object(serialize(entry), 201)


def _check_progress_invariants(percent, remaining, actual_start, actual_finish):
    """The four ProgressEntry invariants -> ERR_INVALID_PROGRESS (422)."""
    if percent > 0 and actual_start is None:
        raise ApiError(ERR_INVALID_PROGRESS, 422,
                       "actual_start is required once percent_complete > 0")
    if (percent == 100) != (remaining == 0):
        raise ApiError(ERR_INVALID_PROGRESS, 422,
                       "percent_complete == 100 if and only if "
                       "remaining_duration_days == 0")
    if percent == 100 and actual_finish is None:
        raise ApiError(ERR_INVALID_PROGRESS, 422,
                       "actual_finish is required when percent_complete "
                       "reaches 100")
    if percent != 100 and actual_finish is not None:
        raise ApiError(ERR_INVALID_PROGRESS, 422,
                       "actual_finish may only be set when percent_complete "
                       "reaches 100")
    if actual_start is not None and actual_finish is not None:
        if parse_dt(actual_finish, "actual_finish") < parse_dt(
                actual_start, "actual_start"):
            raise ApiError(ERR_INVALID_PROGRESS, 422,
                           "actual_finish must be >= actual_start")


@bp.route(
    "/construction-projects/<pid>/schedule-versions/<vid>/progress-updates/<puid>/entries",
    methods=["GET"], strict_slashes=False)
def list_progress_entries(pid, vid, puid):
    require_roles(*ANY_ROLE)
    _, _, pu = get_progress_update(pid, vid, puid)
    items = sorted_items(_entries_of(pu["id"]))
    page, pg = paginate(items)
    return ok_list([serialize(e) for e in page], pg)


@bp.route(
    "/construction-projects/<pid>/schedule-versions/<vid>/progress-updates/<puid>/submit",
    methods=["POST"], strict_slashes=False)
def submit_progress_update(pid, vid, puid):
    require_roles("ContractorScheduler")
    project, version, pu = get_progress_update(pid, vid, puid)
    json_body()
    if pu["status"] != "DRAFT":
        raise ApiError(ERR_INVALID_STATE, 409,
                       "ProgressUpdate is not in DRAFT")
    if version["kind"] != "UPDATE" or version["status"] != "ACCEPTED":
        raise ApiError(ERR_SCHEDULE_NOT_ACCEPTED, 409,
                       "Parent ScheduleVersion must be an ACCEPTED UPDATE")
    member_ids = {a["id"] for a in activities_of(version["id"])}
    for e in _entries_of(pu["id"]):
        if e["activity_id"] not in member_ids:
            raise ApiError(ERR_ACTIVITY_NOT_IN_VERSION, 422,
                           "Every ProgressEntry must reference an Activity "
                           "in the parent version")
    pu["status"] = "SUBMITTED"
    touch(pu)
    return ok_object(serialize(pu))


@bp.route(
    "/construction-projects/<pid>/schedule-versions/<vid>/progress-updates/<puid>/approve",
    methods=["POST"], strict_slashes=False)
def approve_progress_update(pid, vid, puid):
    require_roles("ProjectControlsEngineer")
    project, version, pu = get_progress_update(pid, vid, puid)
    json_body()
    if pu["status"] != "SUBMITTED":
        raise ApiError(ERR_INVALID_STATE, 409,
                       "ProgressUpdate is not in SUBMITTED")
    # Fold reported reality into the schedule.
    for e in sorted_items(_entries_of(pu["id"])):
        act = store.activities.get(e["activity_id"])
        if act is None:
            continue
        act["percent_complete"] = e["percent_complete"]
        act["remaining_duration_days"] = e["remaining_duration_days"]
        # actual_start stamps the first time progress reports above zero.
        if act.get("actual_start") is None and e.get("actual_start"):
            act["actual_start"] = e["actual_start"]
        if e.get("actual_finish") is not None:
            act["actual_finish"] = e["actual_finish"]
        touch(act)
    run_cpm_and_persist(version)
    pu["status"] = "APPROVED"
    touch(pu)
    # LD exposure cascade: projected finish beyond current completion spawns
    # a PROPOSED LiquidatedDamagesAssessment over the overrun window.
    pf = parse_dt(version["projected_finish_date"], "projected_finish_date")
    ccd = parse_dt(project["current_completion_date"],
                   "current_completion_date")
    if pf > ccd:
        now = clock_iso()
        lda = {
            "id": new_id(),
            "project_id": project["id"],
            "assessment_period_start": project["current_completion_date"],
            "assessment_period_end": version["projected_finish_date"],
            "culpable_days": 0,
            "gross_ld_cents": 0,
            "assessed_ld_cents": None,
            "prior_assessed_total_cents": None,
            "status": "PROPOSED",
            "created_at": now,
            "updated_at": now,
            "version": 1,
            "_seq": store.next_seq(),
        }
        culpable, gross = compute_exposure(project, ccd, pf)
        lda["culpable_days"] = culpable
        lda["gross_ld_cents"] = gross
        store.ld_assessments[lda["id"]] = lda
    return ok_object(serialize(pu))


@bp.route(
    "/construction-projects/<pid>/schedule-versions/<vid>/progress-updates/<puid>/reject",
    methods=["POST"], strict_slashes=False)
def reject_progress_update(pid, vid, puid):
    require_roles("ProjectControlsEngineer")
    project, version, pu = get_progress_update(pid, vid, puid)
    json_body()
    if pu["status"] != "SUBMITTED":
        raise ApiError(ERR_INVALID_STATE, 409,
                       "ProgressUpdate is not in SUBMITTED")
    pu["status"] = "REJECTED"
    touch(pu)
    return ok_object(serialize(pu))


@bp.route(
    "/construction-projects/<pid>/schedule-versions/<vid>/progress-updates/<puid>/revise",
    methods=["POST"], strict_slashes=False)
def revise_progress_update(pid, vid, puid):
    require_roles("ContractorScheduler")
    project, version, pu = get_progress_update(pid, vid, puid)
    json_body()
    if pu["status"] != "REJECTED":
        raise ApiError(ERR_INVALID_STATE, 409,
                       "ProgressUpdate is not in REJECTED")
    pu["status"] = "DRAFT"
    touch(pu)
    return ok_object(serialize(pu))
