"""Index determinations (OCC-protected)."""
from flask import Blueprint

from db import store, base_entity, touch, serialize
from errors import (
    ApiError, ERR_PROFILE_NOT_FOUND, ERR_AIRCRAFT_NOT_FOUND,
    ERR_VALIDATION_FAILED, ERR_STALE_PROFILE_VERSION,
    ERR_AIRCRAFT_NOT_QUALIFYING, ERR_NOT_LARGEST_QUALIFYING_AIRCRAFT,
    ERR_INDEX_BELOW_REQUIRED,
)
from middleware import require, json_body, need_str, need_enum, ALL_ROLES
from response import success
from services import calc

bp = Blueprint("determinations", __name__)


@bp.post("/arff/index-determinations")
def create_determination():
    require(["AirportManager"])
    if store.profile is None:
        raise ApiError(ERR_PROFILE_NOT_FOUND, 404, "Airport profile not yet created")
    data = json_body()
    raw_aid = data.get("largest_aircraft_id")
    if isinstance(raw_aid, str) and raw_aid not in store.aircraft:
        raise ApiError(ERR_AIRCRAFT_NOT_FOUND, 404, "Aircraft id does not exist")
    aid = need_str(data, "largest_aircraft_id")
    new_cert = need_enum(data, "new_certificated_index", calc.INDEXES)
    ev = data.get("expected_profile_version")
    if isinstance(ev, bool) or not isinstance(ev, int):
        raise ApiError(ERR_VALIDATION_FAILED, 400,
                       "'expected_profile_version' is required and must be an integer")
    p = store.profile
    if ev != p["version"]:
        raise ApiError(ERR_STALE_PROFILE_VERSION, 412,
                       "expected_profile_version does not match current profile version")
    aircraft = store.aircraft[aid]
    if not aircraft["qualifies_for_index"]:
        raise ApiError(ERR_AIRCRAFT_NOT_QUALIFYING, 422,
                       "Named aircraft does not qualify for index determination")
    best = calc.largest_qualifying_aircraft()
    if best is None or best["id"] != aid:
        raise ApiError(ERR_NOT_LARGEST_QUALIFYING_AIRCRAFT, 422,
                       "Named aircraft is not the longest qualifying aircraft")
    required = calc.compute_required_index_by_aircraft()
    if calc.INDEX_RANK[new_cert] < calc.INDEX_RANK[required]:
        raise ApiError(ERR_INDEX_BELOW_REQUIRED, 422,
                       "new_certificated_index is below the computed required index")
    prev_active = next((d for d in store.determinations.values()
                        if d["status"] == "ACTIVE"), None)
    det = base_entity()
    det.update({
        "largest_aircraft_id": aid,
        "new_certificated_index": new_cert,
        "required_index": required,
        "vehicle_requirement_met":
            calc.INDEX_RANK[p["supported_index_by_equipment"]] >= calc.INDEX_RANK[required],
        "staffing_requirement_met":
            calc.INDEX_RANK[p["supported_index_by_staffing"]] >= calc.INDEX_RANK[required],
        "supersedes_determination_id": prev_active["id"] if prev_active else None,
        "status": "ACTIVE",
    })
    store.determinations[det["id"]] = det
    if prev_active is not None:
        prev_active["status"] = "SUPERSEDED"
        touch(prev_active)
    prev_cert = p["certificated_index"]
    p["certificated_index"] = new_cert
    calc.recompute_profile(bump="always", prev_cert=prev_cert)
    return success(serialize(det), "object", 201)
