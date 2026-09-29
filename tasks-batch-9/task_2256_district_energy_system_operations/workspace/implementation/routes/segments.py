"""PipeSegment endpoints and the leak-detection assessment (PRD 3.1, 3.8)."""

from flask import Blueprint

import calc
import enums
import services as svc
from db import base_record, now, store, touch
from errors import fail
from middleware import ALL_STAFF, endpoint, paginate
from validators import (get_enum, get_int, get_num, get_str, json_body, present,
                        query_enum, query_str)

bp = Blueprint("segments", __name__, url_prefix="/district-energy")


def _check_chain(loop_id, upstream):
    """The upstream chain must stay on the loop and terminate without a revisit."""
    seen = set()
    current = upstream
    while current is not None:
        if current["id"] in seen:
            fail("ERR_SEGMENT_CYCLE", "the upstream chain revisits segment '%s'"
                 % current["id"])
        if current["loop_id"] != loop_id:
            fail("ERR_SEGMENT_CYCLE",
                 "the upstream chain leaves loop '%s'" % loop_id)
        seen.add(current["id"])
        parent_id = current.get("upstream_segment_id")
        if parent_id is None:
            return
        current = store.segments.get(parent_id)
        if current is None:
            fail("ERR_SEGMENT_CYCLE", "the upstream chain does not terminate")


@endpoint(bp, "/pipe-segments", ["POST"], ["NetworkEngineer"], status=201)
def create_segment():
    body = json_body()
    loop_id = get_str(body, "loop_id")
    code = get_str(body, "code")
    length_m = get_num(body, "length_m", gt=0)
    diameter_mm = get_int(body, "diameter_mm", gt=0)
    install_year = get_int(body, "install_year")
    insulation_class = get_enum(body, "insulation_class", enums.INSULATION_CLASS)
    buried_depth_m = get_num(body, "buried_depth_m")
    upstream_segment_id = get_str(body, "upstream_segment_id", required=False,
                                  default=None)
    makeup_water_ratio = get_num(body, "makeup_water_ratio", required=False,
                                 default=0.0, ge=0)
    historical_leak_count = get_int(body, "historical_leak_count", required=False,
                                    default=0, ge=0)

    loop = svc.fk_get("loops", loop_id)
    upstream = None
    if upstream_segment_id is not None:
        upstream = svc.fk_get("segments", upstream_segment_id)

    svc.require_unique_code("segments", "code", code, loop_id=loop["id"])

    if upstream is not None:
        _check_chain(loop["id"], upstream)

    segment = base_record()
    segment.update({
        "loop_id": loop["id"],
        "upstream_segment_id": upstream_segment_id,
        "code": code,
        "length_m": length_m,
        "diameter_mm": diameter_mm,
        "install_year": install_year,
        "insulation_class": insulation_class,
        "makeup_water_ratio": makeup_water_ratio,
        "historical_leak_count": historical_leak_count,
        "buried_depth_m": buried_depth_m,
        "leak_risk_score": 0.0,
        "condition": "SOUND",
    })
    store.segments[segment["id"]] = segment
    return segment


@endpoint(bp, "/pipe-segments", ["GET"], ALL_STAFF)
def list_segments():
    filters = {}
    loop_id = query_str("loop_id")
    upstream_segment_id = query_str("upstream_segment_id")
    condition = query_enum("condition", enums.CONDITION)
    if loop_id is not None:
        filters["loop_id"] = loop_id
    if upstream_segment_id is not None:
        filters["upstream_segment_id"] = upstream_segment_id
    if condition is not None:
        filters["condition"] = condition
    return paginate(svc.where("segments", **filters))


@endpoint(bp, "/pipe-segments/<segment_id>", ["GET"], ALL_STAFF)
def get_segment(segment_id):
    return svc.path_get("segments", segment_id)


@endpoint(bp, "/pipe-segments/<segment_id>/condition-assessment", ["POST"],
          ["NetworkEngineer"])
def assess_segment(segment_id):
    body = json_body()
    makeup_water_ratio = get_num(body, "makeup_water_ratio", ge=0)
    historical_leak_count = get_int(body, "historical_leak_count", ge=0)
    insulation_class = get_enum(body, "insulation_class", enums.INSULATION_CLASS)
    if present(body, "survey_note"):
        get_str(body, "survey_note", min_len=0)

    segment = svc.path_get("segments", segment_id)

    segment["makeup_water_ratio"] = makeup_water_ratio
    segment["historical_leak_count"] = historical_leak_count
    segment["insulation_class"] = insulation_class

    score = calc.segment_leak_risk_score(segment, now().year)
    if segment["condition"] == "UNDER_REPAIR":
        # A segment under repair is not re-banded by a survey (PRD 3.8).
        segment["leak_risk_score"] = float(score)
        touch(segment)
        return segment

    svc.apply_band(segment, score, store.loops.get(segment["loop_id"]))
    return segment
