"""Academic blocks (PRD 3.3): recurring weekly placement demand."""

from datetime import timedelta

import db
import serializers
from constants import DAYS_OF_WEEK, DAY_TO_WEEKDAY, FEATURES
from errors import ApiError
from middleware import endpoint
from routes.common import list_response, one
from services.placement import priority_score
from validate import (
    get_block,
    get_term,
    opt_enum_array,
    req_hhmm,
    req_int,
    req_str,
    req_str_array,
)


@endpoint("POST", "/campus/academic-blocks", roles=["Scheduler"], code=201)
def create_block(ctx):
    body = ctx.body
    term_id = req_str(body, "term_id")
    term = get_term(term_id)  # body FK existence (rung 3)
    course_code = req_str(body, "course_code")
    instructor_name = req_str(body, "instructor_name")
    enrollment = req_int(body, "enrollment")
    days_of_week = req_str_array(body, "days_of_week", DAYS_OF_WEEK)
    start_raw, start_minutes = req_hhmm(body, "start_time")
    end_raw, end_minutes = req_hhmm(body, "end_time")
    required_features = opt_enum_array(body, "required_features", FEATURES)
    if not days_of_week:
        raise ApiError("ERR_BLOCK_WINDOW_OUT_OF_TERM", "days_of_week must not be empty.")
    if start_minutes >= end_minutes:
        raise ApiError("ERR_BLOCK_WINDOW_OUT_OF_TERM", "start_time must be earlier than end_time.")
    # The recurrence must produce at least one instance inside the term dates.
    wanted = {DAY_TO_WEEKDAY[d] for d in days_of_week}
    has_instance = False
    day = term["_term_start"]
    while day <= term["_term_end"]:
        if day.weekday() in wanted:
            has_instance = True
            break
        day += timedelta(days=1)
    if not has_instance:
        raise ApiError(
            "ERR_BLOCK_WINDOW_OUT_OF_TERM",
            "The recurrence produces no instance inside the term dates.",
        )
    # Blocks are accepted only while the term is DRAFT or SCHEDULING.
    if term["status"] not in ("DRAFT", "SCHEDULING"):
        raise ApiError(
            "ERR_INVALID_STATE",
            "Academic blocks are accepted only while the term is DRAFT or SCHEDULING.",
        )

    row = db.new_row(
        db.academic_blocks,
        term_id=term["id"],
        course_code=course_code,
        instructor_name=instructor_name,
        enrollment=enrollment,
        required_features=required_features,
        days_of_week=days_of_week,
        start_time=start_raw,
        end_time=end_raw,
        priority_score=0,
        status="UNPLACED",
        assigned_room_id=None,
        scheduling_run_id=None,
        _start_time_minutes=start_minutes,
        _end_time_minutes=end_minutes,
    )
    row["priority_score"] = priority_score(row)
    return one(serializers.academic_block(row), status=201)


@endpoint("GET", "/campus/academic-blocks/{id}", roles=["Scheduler"], code=200)
def get_block_detail(ctx):
    return one(serializers.academic_block(get_block(ctx.id)))


@endpoint("GET", "/campus/academic-blocks", roles=["Scheduler"], code=200)
def list_blocks(ctx):
    rows = db.all_of(db.academic_blocks)
    return list_response(
        rows,
        ctx.args,
        serializers.academic_block,
        mapping={
            "term_id": lambda r: r.get("term_id"),
            "assigned_room_id": lambda r: r.get("assigned_room_id"),
            "scheduling_run_id": lambda r: r.get("scheduling_run_id"),
            "status": lambda r: r.get("status"),
        },
    )


@endpoint("POST", "/campus/academic-blocks/{id}/unplace", roles=["Scheduler"], code=200)
def unplace_block(ctx):
    block = get_block(ctx.id)
    if block["status"] != "PLACED":
        raise ApiError("ERR_INVALID_STATE", "Only a placed block can be unplaced.")
    # Previously bumped events are NOT retroactively restored.
    db.set_fields(block, status="UNPLACED", assigned_room_id=None, scheduling_run_id=None)
    return one(serializers.academic_block(block))
