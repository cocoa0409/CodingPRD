"""DelayEvent endpoints (PRD §3.5)."""

from datetime import timedelta

from flask import Blueprint, request

from db import store
from errors import (
    ApiError,
    ERR_INVALID_STATE,
    ERR_NOTICE_DATA_INVALID,
    ERR_SCHEDULE_NOT_ACCEPTED,
    ERR_ACTIVITY_NOT_IN_VERSION,
)
from middleware import (
    require_roles, json_body, req_field, as_str, as_datetime, as_enum,
    as_str_list, paginate, sorted_items, touch, serialize, ANY_ROLE,
)
from response import ok_object, ok_list
from util import new_id, clock_iso, clock_now, parse_dt
from routes.common import get_project, get_delay_event, delay_events_of
from services.tia import run_tia, run_apportionment, clear_tia_fields

bp = Blueprint("delay_events", __name__)

CAUSATIONS = {"OWNER_CAUSED", "CONTRACTOR_CAUSED", "THIRD_PARTY",
              "FORCE_MAJEURE"}


def _opt_query(name):
    v = request.args.get(name)
    return v if v not in (None, "") else None


@bp.route("/construction-projects/<pid>/delay-events", methods=["POST"],
          strict_slashes=False)
def create_delay_event(pid):
    require_roles("ContractorScheduler")
    project = get_project(pid)
    data = json_body()
    title = as_str(req_field(data, "title"), "title")
    causation = as_enum(req_field(data, "causation"), "causation", CAUSATIONS)
    start = as_datetime(req_field(data, "event_start_date"),
                        "event_start_date")
    end = data.get("event_end_date")
    if end is not None:
        end = as_datetime(end, "event_end_date")
    frag_ids = data.get("fragnet_activity_ids")
    if frag_ids is None:
        frag_ids = []
    frag_ids = as_str_list(frag_ids, "fragnet_activity_ids")
    frag_version = data.get("fragnet_inserted_into_version_id")
    if frag_version is not None:
        frag_version = as_str(frag_version, "fragnet_inserted_into_version_id")
    if end is not None and parse_dt(end, "event_end_date") < parse_dt(
            start, "event_start_date"):
        raise ApiError(ERR_NOTICE_DATA_INVALID, 422,
                       "event_end_date must not precede event_start_date")
    now = clock_iso()
    event = {
        "id": new_id(),
        "project_id": project["id"],
        "title": title,
        "causation": causation,
        "event_start_date": start,
        "event_end_date": end,
        "notice_submitted_at": None,
        "notice_within_window": None,
        "fragnet_activity_ids": frag_ids,
        "fragnet_inserted_into_version_id": frag_version,
        "tia_prolongation_days_prospective": None,
        "tia_prolongation_days_retrospective": None,
        "apportioned_compensable_days": None,
        "apportioned_excusable_non_compensable_days": None,
        "apportioned_non_excusable_days": None,
        "status": "DRAFT",
        "created_at": now,
        "updated_at": now,
        "version": 1,
        "_seq": store.next_seq(),
    }
    store.delay_events[event["id"]] = event
    return ok_object(serialize(event), 201)


@bp.route("/construction-projects/<pid>/delay-events", methods=["GET"],
          strict_slashes=False)
def list_delay_events(pid):
    require_roles(*ANY_ROLE)
    project = get_project(pid)
    items = delay_events_of(project["id"])
    status = _opt_query("status")
    causation = _opt_query("causation")
    if status is not None:
        items = [d for d in items if d["status"] == status]
    if causation is not None:
        items = [d for d in items if d["causation"] == causation]
    items = sorted_items(items)
    page, pg = paginate(items)
    return ok_list([serialize(d) for d in page], pg)


@bp.route("/construction-projects/<pid>/delay-events/<did>", methods=["GET"],
          strict_slashes=False)
def get_one_delay_event(pid, did):
    require_roles(*ANY_ROLE)
    _, event = get_delay_event(pid, did)
    return ok_object(serialize(event))


@bp.route("/construction-projects/<pid>/delay-events/<did>/notice",
          methods=["POST"], strict_slashes=False)
def notice_delay_event(pid, did):
    require_roles("ContractorScheduler")
    project, event = get_delay_event(pid, did)
    json_body()
    if event["status"] != "DRAFT":
        raise ApiError(ERR_INVALID_STATE, 409, "DelayEvent is not in DRAFT")
    if event.get("event_end_date") and parse_dt(
            event["event_end_date"], "event_end_date") < parse_dt(
            event["event_start_date"], "event_start_date"):
        raise ApiError(ERR_NOTICE_DATA_INVALID, 422,
                       "event_end_date must not precede event_start_date")
    now = clock_now()
    start = parse_dt(event["event_start_date"], "event_start_date")
    window_end = start + timedelta(days=int(project["notice_window_days"]))
    event["notice_submitted_at"] = clock_iso()
    # In-window: lodged no earlier than event start and no later than
    # event start + notice_window_days. Late notice never fails the step.
    event["notice_within_window"] = (start <= now <= window_end)
    event["status"] = "NOTICED"
    touch(event)
    return ok_object(serialize(event))


@bp.route("/construction-projects/<pid>/delay-events/<did>/tia/submit",
          methods=["POST"], strict_slashes=False)
def submit_tia(pid, did):
    require_roles("ContractorScheduler")
    project, event = get_delay_event(pid, did)
    json_body()
    if event["status"] != "NOTICED":
        raise ApiError(ERR_INVALID_STATE, 409, "DelayEvent is not in NOTICED")
    fv_id = event.get("fragnet_inserted_into_version_id")
    version = store.schedule_versions.get(fv_id) if fv_id else None
    if version is None or version["project_id"] != project["id"] \
            or version["kind"] != "UPDATE" or version["status"] != "ACCEPTED":
        raise ApiError(ERR_SCHEDULE_NOT_ACCEPTED, 409,
                       "fragnet_inserted_into_version_id must name an "
                       "ACCEPTED UPDATE schedule")
    frag = event.get("fragnet_activity_ids") or []
    if not frag:
        raise ApiError(ERR_ACTIVITY_NOT_IN_VERSION, 422,
                       "fragnet_activity_ids must be non-empty")
    for aid in frag:
        act = store.activities.get(aid)
        if act is None or act["schedule_version_id"] != version["id"]:
            raise ApiError(ERR_ACTIVITY_NOT_IN_VERSION, 422,
                           "Every fragnet activity must belong to "
                           "fragnet_inserted_into_version_id")
    run_tia(event)
    run_apportionment(event)
    event["status"] = "TIA_SUBMITTED"
    touch(event)
    return ok_object(serialize(event))


@bp.route("/construction-projects/<pid>/delay-events/<did>/tia/accept",
          methods=["POST"], strict_slashes=False)
def accept_tia(pid, did):
    require_roles("ClaimsConsultant")
    project, event = get_delay_event(pid, did)
    json_body()
    if event["status"] != "TIA_SUBMITTED":
        raise ApiError(ERR_INVALID_STATE, 409,
                       "DelayEvent is not in TIA_SUBMITTED")
    event["status"] = "TIA_ACCEPTED"
    touch(event)
    return ok_object(serialize(event))


@bp.route("/construction-projects/<pid>/delay-events/<did>/tia/reject",
          methods=["POST"], strict_slashes=False)
def reject_tia(pid, did):
    require_roles("ClaimsConsultant")
    project, event = get_delay_event(pid, did)
    json_body()
    if event["status"] != "TIA_SUBMITTED":
        raise ApiError(ERR_INVALID_STATE, 409,
                       "DelayEvent is not in TIA_SUBMITTED")
    event["status"] = "TIA_REJECTED"
    touch(event)
    return ok_object(serialize(event))


@bp.route("/construction-projects/<pid>/delay-events/<did>/resubmit",
          methods=["POST"], strict_slashes=False)
def resubmit_tia(pid, did):
    require_roles("ContractorScheduler")
    project, event = get_delay_event(pid, did)
    json_body()
    if event["status"] != "TIA_REJECTED":
        raise ApiError(ERR_INVALID_STATE, 409,
                       "DelayEvent is not in TIA_REJECTED")
    clear_tia_fields(event)
    event["status"] = "NOTICED"
    touch(event)
    return ok_object(serialize(event))
