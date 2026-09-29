"""Exceptional-event demonstrations and the hour exclusions under them."""
from datetime import timedelta

from flask import Blueprint

import clock
import constants as C
import response
import validate as V
from auth import ALL_ROLES, actor, require
from db import new_record, sorted_by_created, store, touch
from errors import ApiError
from routes.batches import applied_invalidations, check_hour_range, ranges_intersect
from routes.common import (ensure_from_state, ensure_not_terminal, get_batch,
                           get_demonstration, get_pollutant, get_site)
from services import cascade
from services import compute as K
from services import serialize as S

bp = Blueprint("demos", __name__)

BUFFER = timedelta(hours=C.EVENT_BUFFER_HOURS)


@bp.post("/exceptional-event-demonstrations")
@require("ProgramManager")
def open_demonstration():
    data = V.body()
    site_id = V.req_id(data, "site_id")
    pollutant_id = V.req_id(data, "pollutant_id")
    event_type = V.req_enum(data, "event_type", C.EVENT_TYPES)
    event_start_date = V.req_datetime(data, "event_start_date")
    event_end_date = V.req_datetime(data, "event_end_date")
    narrative = V.req_string(data, "narrative", min_len=1, max_len=4000)
    clear_causal = V.req_bool(data, "clear_causal_relationship")
    if event_end_date < event_start_date:
        V.bad("Field 'event_end_date' must be at or after 'event_start_date'.")
    get_site(site_id)
    get_pollutant(pollutant_id)
    # A one-day buffer on each side so two claims cannot be filed nose-to-tail.
    for other in store.demonstrations.values():
        if other["site_id"] != site_id or other["event_type"] != event_type:
            continue
        if other["status"] not in C.DEMONSTRATION_BLOCKING_STATUSES:
            continue
        if (event_start_date - BUFFER <= other["event_end_date"]
                and other["event_start_date"] - BUFFER <= event_end_date):
            raise ApiError("ERR_EVENT_WINDOW_CONFLICT",
                           "The claimed window conflicts with a live demonstration for the "
                           "same site and event type.")
    rec = new_record()
    rec.update({
        "site_id": site_id,
        "pollutant_id": pollutant_id,
        "event_type": event_type,
        "event_start_date": event_start_date,
        "event_end_date": event_end_date,
        "narrative": narrative,
        "clear_causal_relationship": bool(clear_causal),
        "status": "DRAFT",
        "info_request_count": 0,
        "determined_by_user_id": None,
        "determined_at": None,
        "excluded_hour_total": 0,
    })
    store.demonstrations[rec["id"]] = rec
    return response.object_response(S.demonstration(rec), 201)


def _whole_hours_from(quarter_start, instant):
    return int((instant - quarter_start).total_seconds() // 3600)


@bp.post("/exceptional-event-demonstrations/<demo_id>/exclusions")
@require("ProgramManager")
def nominate_exclusion(demo_id):
    data = V.body()
    data_batch_id = V.req_id(data, "data_batch_id")
    start = V.req_int(data, "start_hour_index")
    end = V.req_int(data, "end_hour_index")
    demo = get_demonstration(demo_id)
    batch = get_batch(data_batch_id)
    if batch["validation_status"] == "INVALIDATED":
        raise ApiError("ERR_INVALID_STATE",
                       "The quarter has been written off wholesale; its hour ledger is closed.")
    check_hour_range(batch, start, end, "ERR_INVALIDATION_RANGE_OUT_OF_BOUNDS")
    for other in applied_invalidations(batch["id"]):
        if ranges_intersect(start, end, other["start_hour_index"], other["end_hour_index"]):
            raise ApiError("ERR_EXCLUSION_OVERLAPS_INVALIDATION",
                           "An hour cannot be both invalid and event-excluded.")
    # the event window projected onto the quarter's own hour axis
    quarter_start = K.quarter_start(batch["year"], batch["quarter"])
    window_start = _whole_hours_from(quarter_start, demo["event_start_date"])
    window_end = _whole_hours_from(quarter_start, demo["event_end_date"] + BUFFER)
    span = K.quarter_hour_span(batch["year"], batch["quarter"])
    if (start < window_start or end > window_end
            or window_start < 0 or window_end > span):
        raise ApiError("ERR_EVENT_WINDOW_OUTSIDE_BATCH_PERIOD",
                       "The exclusion range lies outside the event window projected onto "
                       "this quarter.")
    rec = new_record()
    rec.update({
        "demonstration_id": demo_id,
        "data_batch_id": data_batch_id,
        "start_hour_index": start,
        "end_hour_index": end,
        "hours_affected": end - start,
        "status": "PROPOSED",
        "effective_at": None,
    })
    store.exclusions[rec["id"]] = rec
    # Nothing else moves: proposed hours are a claim, not yet a deduction.
    return response.object_response(S.exclusion(rec), 201)


@bp.post("/exceptional-event-demonstrations/<demo_id>/submit")
@require("ProgramManager")
def submit_demonstration(demo_id):
    data = V.body()
    V.opt_string(data, "submission_note")
    demo = get_demonstration(demo_id)
    ensure_not_terminal(demo["status"], C.DEMONSTRATION_TERMINAL, "demonstration")
    ensure_from_state(demo["status"], ("DRAFT", "INFO_REQUESTED"), "demonstration")
    proposed = [e for e in K.exclusions_of_demonstration(demo_id) if e["status"] == "PROPOSED"]
    if not proposed:
        raise ApiError("ERR_INVALID_STATE",
                       "At least one PROPOSED exclusion must exist under the demonstration.")
    # clear_causal_relationship is settled at first submission and is not
    # re-tested on an INFO_REQUESTED resubmission.
    if demo["status"] == "DRAFT" and not demo["clear_causal_relationship"]:
        raise ApiError("ERR_INVALID_STATE",
                       "clear_causal_relationship must be true to submit the demonstration.")
    demo["status"] = "SUBMITTED"
    touch(demo)
    return response.object_response(S.demonstration(demo))


@bp.post("/exceptional-event-demonstrations/<demo_id>/request-info")
@require("EpaRegionalReviewer")
def request_info(demo_id):
    data = V.body()
    V.req_string(data, "info_request_note", min_len=1)
    demo = get_demonstration(demo_id)
    ensure_not_terminal(demo["status"], C.DEMONSTRATION_TERMINAL, "demonstration")
    ensure_from_state(demo["status"], ("SUBMITTED",), "demonstration")
    demo["status"] = "INFO_REQUESTED"
    demo["info_request_count"] += 1
    touch(demo)
    return response.object_response(S.demonstration(demo))


@bp.post("/exceptional-event-demonstrations/<demo_id>/determination")
@require("EpaRegionalReviewer")
def record_determination(demo_id):
    data = V.body()
    determination = V.req_enum(data, "determination", C.DETERMINATIONS)
    V.opt_string(data, "determination_note")
    demo = get_demonstration(demo_id)
    ensure_not_terminal(demo["status"], C.DEMONSTRATION_TERMINAL, "demonstration")
    ensure_from_state(demo["status"], ("SUBMITTED",), "demonstration")
    demo["status"] = "CONCURRED" if determination == "CONCUR" else "NON_CONCURRED"
    demo["determined_by_user_id"] = actor()
    demo["determined_at"] = clock.now()
    touch(demo)
    if determination == "CONCUR":
        cascade.concurrence_cascade(demo)
    else:
        cascade.non_concurrence_cascade(demo)
    return response.object_response(S.demonstration(demo))


@bp.get("/exceptional-event-demonstrations/<demo_id>")
@require(*ALL_ROLES)
def read_demonstration(demo_id):
    return response.object_response(S.demonstration(get_demonstration(demo_id)))


@bp.get("/exceptional-event-demonstrations")
@require(*ALL_ROLES)
def list_demonstrations():
    limit, offset = V.pagination()
    site_id = V.q_string("site_id")
    pollutant_id = V.q_string("pollutant_id")
    event_type = V.q_enum("event_type", C.EVENT_TYPES)
    status = V.q_enum("status", C.DEMONSTRATION_STATUSES)
    rows = list(store.demonstrations.values())
    if site_id is not None:
        rows = [d for d in rows if d["site_id"] == site_id]
    if pollutant_id is not None:
        rows = [d for d in rows if d["pollutant_id"] == pollutant_id]
    if event_type is not None:
        rows = [d for d in rows if d["event_type"] == event_type]
    if status is not None:
        rows = [d for d in rows if d["status"] == status]
    rows = sorted_by_created(rows)
    page, meta = response.paginate(rows, limit, offset)
    return response.array_response([S.demonstration(d) for d in page], pagination=meta)


@bp.get("/exceptional-event-demonstrations/<demo_id>/exclusions")
@require(*ALL_ROLES)
def list_demonstration_exclusions(demo_id):
    limit, offset = V.pagination()
    status = V.q_enum("status", C.EXCLUSION_STATUSES)
    data_batch_id = V.q_string("data_batch_id")
    get_demonstration(demo_id)
    rows = K.exclusions_of_demonstration(demo_id)
    if status is not None:
        rows = [e for e in rows if e["status"] == status]
    if data_batch_id is not None:
        rows = [e for e in rows if e["data_batch_id"] == data_batch_id]
    rows.sort(key=lambda e: (e["data_batch_id"], e["start_hour_index"], e["_seq"]))
    page, meta = response.paginate(rows, limit, offset)
    return response.array_response([S.exclusion(e) for e in page], pagination=meta)
