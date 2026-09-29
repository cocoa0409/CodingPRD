"""The promotional and event calendar (PRD 3.5)."""
from datetime import timedelta

from flask import Blueprint

import derive as dv
import envelope as env
import guards as gd
import store as db
import validation as va
from auth import require
from errors import ApiError

bp = Blueprint("promo", __name__)

SCOPES = ("PROGRAM", "CLUSTER", "STORE")
PROMO_STATES = ("DRAFT", "SCHEDULED", "ACTIVE", "ENDED", "CANCELLED")
PROMO_BUFFER = timedelta(days=1)


def _same_target(a, b):
    if a["scope"] != b["scope"]:
        return False
    if a["scope"] == "STORE":
        return a["store_id"] == b["store_id"]
    if a["scope"] == "CLUSTER":
        return a["cluster_code"] == b["cluster_code"]
    return True


def _classes_overlap(a, b):
    return a["item_class"] is None or b["item_class"] is None or a["item_class"] == b["item_class"]


def _windows_intersect(a, b):
    a_start = a["start_date"] - PROMO_BUFFER
    a_end = a["end_date"] + PROMO_BUFFER
    b_start = b["start_date"] - PROMO_BUFFER
    b_end = b["end_date"] + PROMO_BUFFER
    return a_start <= b_end and b_start <= a_end


def conflict_check(candidate):
    for other in db.promo_events.values():
        if other["id"] == candidate.get("id"):
            continue
        if other["program_id"] != candidate["program_id"]:
            continue
        if other["status"] not in ("SCHEDULED", "ACTIVE"):
            continue
        if (
            _same_target(candidate, other)
            and _classes_overlap(candidate, other)
            and _windows_intersect(candidate, other)
        ):
            raise ApiError("ERR_PROMO_WINDOW_CONFLICT")


@bp.post("/allocation/promo-events")
@require("PlanningAdmin")
def create_promo_event():
    data = va.body()
    program_id = va.get_str(data, "program_id")
    event_code = va.get_str(data, "event_code")
    scope = va.get_enum(data, "scope", SCOPES)
    cluster_code = va.get_str(data, "cluster_code", required=False)
    store_id = va.get_str(data, "store_id", required=False)
    item_class = va.get_enum(data, "item_class", gd.ITEM_CLASSES, required=False)
    start_date = va.get_dt(data, "start_date")
    end_date = va.get_dt(data, "end_date")
    lift_bp = va.get_int(data, "lift_factor_bp", minimum=10000)
    if end_date < start_date:
        va.bad("end_date must not precede start_date.")
    if scope == "CLUSTER" and (cluster_code is None or store_id is not None):
        va.bad("A CLUSTER-scope event needs cluster_code and no store_id.")
    if scope == "STORE" and (store_id is None or cluster_code is not None):
        va.bad("A STORE-scope event needs store_id and no cluster_code.")
    if scope == "PROGRAM" and (store_id is not None or cluster_code is not None):
        va.bad("A PROGRAM-scope event carries neither cluster_code nor store_id.")
    program = gd.get_program(program_id)
    store = gd.get_store(store_id) if store_id else None
    if store is not None and store["program_id"] != program["id"]:
        raise ApiError("ERR_CROSS_PROGRAM_REFERENCE")
    for existing in db.promo_events.values():
        if existing["program_id"] == program["id"] and existing["event_code"] == event_code:
            raise ApiError("ERR_DUPLICATE_EVENT_CODE")
    record = db.base_record()
    record.update(
        {
            "program_id": program["id"],
            "event_code": event_code,
            "scope": scope,
            "cluster_code": cluster_code,
            "store_id": store["id"] if store else None,
            "item_class": item_class,
            "start_date": start_date,
            "end_date": end_date,
            "lift_factor_bp": lift_bp,
            "status": "DRAFT",
        }
    )
    conflict_check(record)
    db.promo_events[record["id"]] = record
    return env.created(dv.promo_out(record))


@bp.get("/allocation/promo-events/<event_id>")
@require("PlanningAdmin", "Allocator", "AllocationManager")
def read_promo_event(event_id):
    return env.ok(dv.promo_out(gd.get_promo(event_id)))


@bp.get("/allocation/promo-events")
@require("PlanningAdmin", "Allocator", "AllocationManager")
def list_promo_events():
    program_id = va.q_str("program_id")
    store_id = va.q_str("store_id")
    scope = va.q_enum("scope", SCOPES)
    status = va.q_enum("status", PROMO_STATES)
    records = dv.by_created(list(db.promo_events.values()))
    if program_id:
        records = [r for r in records if r["program_id"] == program_id]
    if store_id:
        records = [r for r in records if r["store_id"] == store_id]
    if scope:
        records = [r for r in records if r["scope"] == scope]
    if status:
        records = [r for r in records if r["status"] == status]
    chunk, meta = va.page(records)
    return env.ok_array([dv.promo_out(r) for r in chunk], meta)


def _transition(event_id, allowed_from, target):
    event = gd.get_promo(event_id)
    if event["status"] not in allowed_from:
        gd.bad_state()
    if target == "SCHEDULED":
        conflict_check(event)
    event["status"] = target
    db.touch(event)
    return env.ok(dv.promo_out(event))


@bp.post("/allocation/promo-events/<event_id>/schedule")
@require("PlanningAdmin")
def schedule_promo_event(event_id):
    return _transition(event_id, ("DRAFT",), "SCHEDULED")


@bp.post("/allocation/promo-events/<event_id>/activate")
@require("PlanningAdmin")
def activate_promo_event(event_id):
    return _transition(event_id, ("SCHEDULED",), "ACTIVE")


@bp.post("/allocation/promo-events/<event_id>/end")
@require("PlanningAdmin")
def end_promo_event(event_id):
    return _transition(event_id, ("ACTIVE",), "ENDED")


@bp.post("/allocation/promo-events/<event_id>/cancel")
@require("PlanningAdmin")
def cancel_promo_event(event_id):
    return _transition(event_id, ("DRAFT", "SCHEDULED", "ACTIVE"), "CANCELLED")
