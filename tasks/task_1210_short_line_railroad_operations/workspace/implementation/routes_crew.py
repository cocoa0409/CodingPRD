"""CrewMembers (HOS governance), CrewCalls, SwitchJobs (PRD 3.7, 3.4)."""

import math

from flask import Blueprint, request

from auth import authenticate, require_role, require_owner
from db import store
from envelope import success_object, success_list
from errors import (ApiError, ERR_INVALID_REQUEST, ERR_STALE_VERSION,
                    ERR_CALL_TARGET_REQUIRED, ERR_MEMBER_NOT_AVAILABLE,
                    ERR_HOS_DAILY_LIMIT, ERR_HOS_MONTHLY_LIMIT,
                    ERR_HOS_REST_REQUIRED, ERR_CALL_WINDOW_OVERLAP,
                    not_found, invalid_state)
from util import (json_body, req_str, opt_str, req_int, opt_int, req_dt,
                  req_enum, paginate)
from domain import (new_record, touch, crew_member_view, crew_call_view,
                    switch_job_view, CRAFTS, CALL_RESPONSES,
                    HOS_DAILY_LIMIT_MINUTES, HOS_MONTHLY_LIMIT_MINUTES,
                    HOS_REQUIRED_REST_MINUTES)

bp = Blueprint("crew", __name__)

CREW_CALL_READ_ROLES = ["CrewCaller", "Conductor", "Dispatcher", "SystemAdmin"]


# ---------------------------------------------------------------------------
# Crew members
# ---------------------------------------------------------------------------

@bp.post("/rail/crew-members")
def create_crew_member():
    uid, role = authenticate()
    body = json_body(required=True)
    name = req_str(body, "name")
    craft = req_enum(body, "craft", CRAFTS)
    require_role(role, ["SystemAdmin"])
    rec = new_record({
        "name": name,
        "craft": craft,
        "status": "AVAILABLE",
        "on_duty_minutes_rolling_24h": 0,
        "on_duty_minutes_month": 0,
        "rest_minutes_completed": None,
        "rest_start_at": None,
    })
    store.crew_members[rec["id"]] = rec
    return success_object(crew_member_view(rec), status=201)


@bp.get("/rail/crew-members")
def list_crew_members():
    uid, role = authenticate()
    records = list(store.crew_members.values())
    f_status = request.args.get("status")
    f_craft = request.args.get("craft")
    if f_status is not None:
        records = [m for m in records if m["status"] == f_status]
    if f_craft is not None:
        records = [m for m in records if m["craft"] == f_craft]
    limit, offset, total, page = paginate(records)
    return success_list([crew_member_view(m) for m in page], limit, offset, total)


def _get_member(mid):
    rec = store.crew_members.get(mid)
    if rec is None:
        raise not_found("crew member not found")
    return rec


@bp.get("/rail/crew-members/<mid>")
def get_crew_member(mid):
    uid, role = authenticate()
    return success_object(crew_member_view(_get_member(mid)))


@bp.post("/rail/crew-members/<mid>/adjust-hos")
def adjust_hos(mid):
    uid, role = authenticate()
    body = json_body(required=True)
    # Syntactic band: the OCC guard field is always required.
    expected = req_int(body, "expected_crew_member_version")
    rolling = opt_int(body, "rolling_24h_minutes")
    month = opt_int(body, "month_minutes")
    rest = opt_int(body, "minutes_of_rest_completed")
    for v, f in ((rolling, "rolling_24h_minutes"), (month, "month_minutes"),
                 (rest, "minutes_of_rest_completed")):
        if v is not None and v < 0:
            raise ApiError(400, ERR_INVALID_REQUEST, "%s must be >= 0" % f)
    require_role(role, ["SystemAdmin", "CrewCaller"])
    member = _get_member(mid)
    # OCC guard (PRD 2.8).
    if expected != member["version"]:
        raise ApiError(412, ERR_STALE_VERSION,
                       "expected_crew_member_version does not match the current version")
    if rolling is not None:
        member["on_duty_minutes_rolling_24h"] = rolling
    if month is not None:
        member["on_duty_minutes_month"] = month
    if rest is not None:
        member["rest_minutes_completed"] = rest
    touch(member)
    return success_object(crew_member_view(member))


# ---------------------------------------------------------------------------
# Crew calls
# ---------------------------------------------------------------------------

@bp.post("/rail/crew-calls")
def create_crew_call():
    uid, role = authenticate()
    body = json_body(required=True)
    crew_member_id = req_str(body, "crew_member_id")
    movement_id = opt_str(body, "movement_id")
    switch_job_id = opt_str(body, "switch_job_id")
    start = req_dt(body, "scheduled_start_at")
    end = req_dt(body, "scheduled_end_at")
    if not (end > start):
        raise ApiError(400, ERR_INVALID_REQUEST,
                       "scheduled_end_at must be strictly later than scheduled_start_at")
    require_role(role, ["CrewCaller"])
    # Existence band, left to right.
    member = store.crew_members.get(crew_member_id)
    if member is None:
        raise not_found("crew member not found")
    if movement_id is not None and movement_id not in store.movements:
        raise not_found("train movement not found")
    if switch_job_id is not None and switch_job_id not in store.switch_jobs:
        raise not_found("switch job not found")
    # State band: the member must be AVAILABLE.
    if member["status"] != "AVAILABLE":
        raise ApiError(409, ERR_MEMBER_NOT_AVAILABLE,
                       "crew member status is not AVAILABLE")
    # Business safety band: HOS gates (strictly greater than zero remaining).
    daily_remaining = max(0, HOS_DAILY_LIMIT_MINUTES - member["on_duty_minutes_rolling_24h"])
    if daily_remaining <= 0:
        raise ApiError(422, ERR_HOS_DAILY_LIMIT, "no daily HOS capacity remaining")
    monthly_remaining = max(0, HOS_MONTHLY_LIMIT_MINUTES - member["on_duty_minutes_month"])
    if monthly_remaining <= 0:
        raise ApiError(422, ERR_HOS_MONTHLY_LIMIT, "no monthly HOS capacity remaining")
    rest = member["rest_minutes_completed"]
    if rest is not None and rest < HOS_REQUIRED_REST_MINUTES:
        raise ApiError(422, ERR_HOS_REST_REQUIRED,
                       "member has not completed the required rest")
    # Temporal band: half-open window must not overlap the member's live calls.
    for call in store.crew_calls.values():
        if call["crew_member_id"] != crew_member_id:
            continue
        if call["status"] not in ("CALLED", "ACCEPTED", "ON_DUTY"):
            continue
        if start < call["scheduled_end_at"] and call["scheduled_start_at"] < end:
            raise ApiError(409, ERR_CALL_WINDOW_OVERLAP,
                           "duty window overlaps an existing call")
    # Referential band: exactly one duty target.
    if (movement_id is None) == (switch_job_id is None):
        raise ApiError(400, ERR_CALL_TARGET_REQUIRED,
                       "exactly one of movement_id / switch_job_id is required")
    rec = new_record({
        "crew_member_id": crew_member_id,
        "movement_id": movement_id,
        "switch_job_id": switch_job_id,
        "scheduled_start_at": start,
        "scheduled_end_at": end,
        "status": "CALLED",
        "on_duty_at": None,
        "off_duty_at": None,
        "actual_on_duty_minutes": None,
    })
    store.crew_calls[rec["id"]] = rec
    return success_object(crew_call_view(rec), status=201)


@bp.get("/rail/crew-calls")
def list_crew_calls():
    uid, role = authenticate()
    require_role(role, CREW_CALL_READ_ROLES)
    records = list(store.crew_calls.values())
    for param, field in (("crew_member_id", "crew_member_id"),
                         ("movement_id", "movement_id"),
                         ("switch_job_id", "switch_job_id"),
                         ("status", "status")):
        v = request.args.get(param)
        if v is not None:
            records = [c for c in records if c[field] == v]
    limit, offset, total, page = paginate(records)
    return success_list([crew_call_view(c) for c in page], limit, offset, total)


def _get_call(cid):
    rec = store.crew_calls.get(cid)
    if rec is None:
        raise not_found("crew call not found")
    return rec


@bp.get("/rail/crew-calls/<cid>")
def get_crew_call(cid):
    uid, role = authenticate()
    require_role(role, CREW_CALL_READ_ROLES)
    return success_object(crew_call_view(_get_call(cid)))


@bp.post("/rail/crew-calls/<cid>/respond")
def respond_crew_call(cid):
    uid, role = authenticate()
    body = json_body(required=True)
    response = req_enum(body, "response", CALL_RESPONSES)
    require_role(role, ["Conductor"])
    call = _get_call(cid)
    require_owner(call["crew_member_id"], uid)
    if call["status"] != "CALLED":
        raise invalid_state("only a CALLED call can be answered")
    call["status"] = response  # ACCEPTED or DECLINED
    touch(call)
    return success_object(crew_call_view(call))


@bp.post("/rail/crew-calls/<cid>/report-on-duty")
def report_on_duty(cid):
    uid, role = authenticate()
    json_body()
    require_role(role, ["Conductor"])
    call = _get_call(cid)
    require_owner(call["crew_member_id"], uid)
    if call["status"] != "ACCEPTED":
        raise invalid_state("only an ACCEPTED call can report on duty")
    call["on_duty_at"] = store.now
    call["status"] = "ON_DUTY"
    member = store.crew_members.get(call["crew_member_id"])
    if member is not None:
        member["status"] = "ON_DUTY"
        member["rest_minutes_completed"] = None
        member["rest_start_at"] = None
        touch(member)
    touch(call)
    return success_object(crew_call_view(call))


@bp.post("/rail/crew-calls/<cid>/relieve")
def relieve_crew_call(cid):
    uid, role = authenticate()
    json_body()
    require_role(role, ["CrewCaller"])
    call = _get_call(cid)
    if call["status"] != "ON_DUTY":
        raise invalid_state("only an ON_DUTY call can be relieved")
    call["off_duty_at"] = store.now
    actual = int(math.floor(
        (call["off_duty_at"] - call["on_duty_at"]).total_seconds() / 60.0))
    call["actual_on_duty_minutes"] = actual
    call["status"] = "RELIEVED"
    member = store.crew_members.get(call["crew_member_id"])
    if member is not None:
        member["status"] = "RESTING"
        member["on_duty_minutes_rolling_24h"] += actual
        member["on_duty_minutes_month"] += actual
        member["rest_minutes_completed"] = 0
        member["rest_start_at"] = store.now
        touch(member)
    touch(call)
    return success_object(crew_call_view(call))


# ---------------------------------------------------------------------------
# Switch jobs
# ---------------------------------------------------------------------------

@bp.post("/rail/switch-jobs")
def create_switch_job():
    uid, role = authenticate()
    body = json_body(required=True)
    car_order_id = opt_str(body, "car_order_id")
    scheduled_date = req_str(body, "scheduled_date")
    notes = opt_str(body, "notes")
    require_role(role, ["Dispatcher"])
    if car_order_id is not None and car_order_id not in store.car_orders:
        raise not_found("car order not found")
    rec = new_record({
        "car_order_id": car_order_id,
        "scheduled_date": scheduled_date,
        "notes": notes,
        "crew_call_id": None,
        "status": "PLANNED",
    })
    store.switch_jobs[rec["id"]] = rec
    return success_object(switch_job_view(rec), status=201)


@bp.get("/rail/switch-jobs")
def list_switch_jobs():
    uid, role = authenticate()
    records = list(store.switch_jobs.values())
    for param, field in (("car_order_id", "car_order_id"),
                         ("crew_call_id", "crew_call_id"),
                         ("status", "status")):
        v = request.args.get(param)
        if v is not None:
            records = [j for j in records if j[field] == v]
    limit, offset, total, page = paginate(records)
    return success_list([switch_job_view(j) for j in page], limit, offset, total)


def _get_job(jid):
    rec = store.switch_jobs.get(jid)
    if rec is None:
        raise not_found("switch job not found")
    return rec


@bp.get("/rail/switch-jobs/<jid>")
def get_switch_job(jid):
    uid, role = authenticate()
    return success_object(switch_job_view(_get_job(jid)))


@bp.post("/rail/switch-jobs/<jid>/assign")
def assign_switch_job(jid):
    uid, role = authenticate()
    body = json_body(required=True)
    crew_call_id = req_str(body, "crew_call_id")
    require_role(role, ["Dispatcher"])
    job = _get_job(jid)
    call = store.crew_calls.get(crew_call_id)
    if call is None:
        raise not_found("crew call not found")
    if job["status"] != "PLANNED":
        raise invalid_state("only a PLANNED job can be assigned")
    if (call["status"] not in ("ACCEPTED", "ON_DUTY")
            or call["switch_job_id"] != jid):
        raise invalid_state(
            "crew call must be ACCEPTED or ON_DUTY and target this switch job")
    job["crew_call_id"] = crew_call_id
    job["status"] = "ASSIGNED"
    touch(job)
    return success_object(switch_job_view(job))


@bp.post("/rail/switch-jobs/<jid>/complete")
def complete_switch_job(jid):
    uid, role = authenticate()
    json_body()
    require_role(role, ["Dispatcher"])
    job = _get_job(jid)
    if job["status"] not in ("PLANNED", "ASSIGNED"):
        raise invalid_state("only a PLANNED or ASSIGNED job can be completed")
    job["status"] = "COMPLETED"
    touch(job)
    return success_object(switch_job_view(job))


@bp.post("/rail/switch-jobs/<jid>/annul")
def annul_switch_job(jid):
    uid, role = authenticate()
    json_body()
    require_role(role, ["Dispatcher"])
    job = _get_job(jid)
    if job["status"] not in ("PLANNED", "ASSIGNED"):
        raise invalid_state("only a PLANNED or ASSIGNED job can be annulled")
    job["status"] = "ANNULLED"
    touch(job)
    return success_object(switch_job_view(job))
