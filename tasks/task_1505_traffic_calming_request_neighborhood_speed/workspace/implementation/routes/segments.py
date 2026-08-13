"""Street segments (PRD §3.1)."""
from flask import Blueprint

from auth import require_roles, ALL_ROLES
from envelope import object_response
from helpers import get_segment
from store import store
from validate import parse_body, Struct

bp = Blueprint("segments", __name__)

FUNCTIONAL_CLASSES = ("LOCAL", "COLLECTOR", "ARTERIAL")


@bp.post("/api/segments")
@require_roles("CityAdmin")
def create_segment():
    data, perr = parse_body()
    s = Struct(data, perr)
    name = s.get_str("name")
    speed_limit = s.get_int("speed_limit_mph", min=15)
    households = s.get_int("household_count", min=1)
    fclass = s.get_enum("functional_class", FUNCTIONAL_CLASSES)
    emergency = s.get_bool("emergency_route", default=False)
    crashes = s.get_int("crash_count_3yr", required=False, min=0, default=0)
    peds = s.get_int("pedestrian_generator_count", required=False, min=0, default=0)
    s.raise_if_errors()
    seg = {
        "id": store.new_id(),
        "name": name,
        "speed_limit_mph": speed_limit,
        "household_count": households,
        "functional_class": fclass,
        "emergency_route": emergency,
        "crash_count_3yr": crashes,
        "pedestrian_generator_count": peds,
        "created_at": store.now,
        "updated_at": store.now,
        "version": 1,
        "_seq": store.next_seq(),
    }
    store.segments[seg["id"]] = seg
    return object_response(seg, 201)


@bp.get("/api/segments/<segmentId>")
@require_roles(*ALL_ROLES)
def get_one(segmentId):
    return object_response(get_segment(segmentId))
