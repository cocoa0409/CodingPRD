"""Service crews (PRD 3.5)."""

import db
import serializers
from constants import SERVICE_CATEGORIES
from middleware import endpoint
from routes.common import one
from validate import req_enum, req_hhmm, req_int, req_str
from errors import ApiError


@endpoint("POST", "/campus/service-crews", roles=["ServiceCoordinator"], code=201)
def create_crew(ctx):
    body = ctx.body
    name = req_str(body, "name")
    category = req_enum(body, "category", SERVICE_CATEGORIES)
    concurrent_capacity = req_int(body, "concurrent_capacity")
    if concurrent_capacity < 1:
        raise ApiError("ERR_INVALID_REQUEST", "concurrent_capacity must be at least 1.")
    shift_start_raw, shift_start_minutes = req_hhmm(body, "shift_start")
    shift_end_raw, shift_end_minutes = req_hhmm(body, "shift_end")
    if shift_end_minutes <= shift_start_minutes:
        raise ApiError("ERR_INVALID_REQUEST", "shift_end must be later than shift_start.")
    row = db.new_row(
        db.service_crews,
        name=name,
        category=category,
        concurrent_capacity=concurrent_capacity,
        shift_start=shift_start_raw,
        shift_end=shift_end_raw,
        _shift_start_minutes=shift_start_minutes,
        _shift_end_minutes=shift_end_minutes,
    )
    return one(serializers.service_crew(row), status=201)
