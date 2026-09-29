"""Logical clock and the pavement inventory (PRD 2.4, 3.1)."""
from flask import Blueprint

import calc
import clock
import db
import response
import validators as v
from errors import ApiError
from middleware import ALL_ROLES, endpoint

bp = Blueprint("segments", __name__)


# ------------------------------------------------------------ logical clock

@bp.post("/_clock/set_current_utc")
@endpoint(*ALL_ROLES)
def set_current_utc():
    data = v.body()
    instant = v.field_datetime(data, "current_utc")
    clock.set_now(instant)
    return response.object_response({"current_utc": clock.iso(clock.now())})


# --------------------------------------------------------- network segments

def _find_segment(segment_id):
    segment = db.segments.get(segment_id)
    if segment is None:
        raise ApiError("ERR_SEGMENT_NOT_FOUND")
    return segment


@bp.post("/segments")
@endpoint("PavementEngineer")
def create_segment():
    data = v.body()
    street_name = v.field_string(data, "street_name", 1, 120)
    from_node = v.field_string(data, "from_node", 1, 80)
    to_node = v.field_string(data, "to_node", 1, 80)
    geo_zone = v.field_string(data, "geo_zone", 1, 40)
    functional_class = v.field_enum(data, "functional_class", calc.FUNCTIONAL_CLASSES)
    surface_type = v.field_enum(data, "surface_type", calc.SURFACE_TYPES)
    length_ft = v.field_number(data, "length_ft", minimum=0, exclusive_minimum=True)
    width_ft = v.field_number(data, "width_ft", minimum=8)
    baseline = v.field_number(data, "baseline_condition_index", minimum=0,
                              maximum=100)
    last_treatment_date = v.field_datetime(data, "last_treatment_date",
                                           required=False)

    pre, knee = calc.DECAY[functional_class]
    segment = {
        "id": db.new_id(),
        "street_name": street_name,
        "from_node": from_node,
        "to_node": to_node,
        "geo_zone": geo_zone,
        "functional_class": functional_class,
        "surface_type": surface_type,
        "length_ft": length_ft,
        "width_ft": width_ft,
        "area_sy": calc.segment_area_sy(length_ft, width_ft),
        "baseline_condition_index": calc.num(baseline, 1),
        "last_treatment_type": "NONE",
        "last_treatment_date": last_treatment_date,
        "decay_coefficient": float(calc.D(pre)),
        "decay_knee_coefficient": float(calc.D(knee)),
        "condition_index": None,
        "condition_index_source": "MODEL_PROJECTED",
        "condition_band": None,
        "moratorium_until": None,
        "active_project_count": 0,
        "open_service_request_count": 0,
    }
    segment.update(db.audit())
    index = calc.model_projected_condition_index(segment, clock.now())
    segment["condition_index"] = index
    segment["condition_band"] = calc.condition_band(index)
    db.segments[segment["id"]] = segment
    return response.object_response(segment, 201)


@bp.get("/segments/<segment_id>")
@endpoint(*ALL_ROLES)
def read_segment(segment_id):
    return response.object_response(_find_segment(segment_id))


@bp.get("/segments")
@endpoint(*ALL_ROLES)
def list_segments():
    rows = v.filter_rows(db.ordered(db.segments.values()), {
        "geo_zone": "geo_zone",
        "functional_class": "functional_class",
        "condition_band": "condition_band",
    })
    page, meta = v.paginate(rows)
    return response.array_response(page, pagination=meta)
