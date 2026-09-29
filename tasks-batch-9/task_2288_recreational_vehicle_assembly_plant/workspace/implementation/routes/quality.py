"""Quality: booth scheduling and the grading fork that drives the build machine."""
import constants as C
import db
import validation as V
from db import store
from errors import ApiError, bad_request
from flask import Blueprint, g
from middleware import authorize
from routes.common import insert, list_out, must_find, object_out
from services import calc, cascade, derive

bp = Blueprint("quality", __name__)

BOOTH_TYPES_REQUIRED = ("WATER_TEST", "FUNCTIONAL")


@bp.post("/quality-inspections")
@authorize("QualityInspector")
def create_inspection():
    body = V.body_dict()
    build_id = V.field_string(body, "unit_build_id", required=True, min_len=1)
    inspection_type = V.field_enum(body, "inspection_type", C.INSPECTION_TYPES, required=True)
    booth_id = V.field_string(body, "test_booth_id", min_len=1)
    window_start = V.field_datetime(body, "window_start")
    window_end = V.field_datetime(body, "window_end")

    # structural combination rules (band 3 of the ladder)
    if inspection_type in BOOTH_TYPES_REQUIRED:
        if booth_id is None:
            raise bad_request(
                "Field 'test_booth_id' is required for a {} inspection.".format(inspection_type)
            )
        if window_start is None:
            raise bad_request(
                "Field 'window_start' is required for a {} inspection.".format(inspection_type)
            )
        if window_end is None:
            raise bad_request(
                "Field 'window_end' is required for a {} inspection.".format(inspection_type)
            )
        if window_end <= window_start:
            raise bad_request("Field 'window_end' must be strictly after 'window_start'.")
        minutes = (window_end - window_start).total_seconds() / 60.0
        if minutes < C.MIN_TEST_MINUTES or minutes > C.MAX_TEST_MINUTES:
            raise bad_request(
                "The booth window must last between {} and {} minutes.".format(
                    C.MIN_TEST_MINUTES, C.MAX_TEST_MINUTES
                )
            )
    else:
        if booth_id is not None:
            raise bad_request("Field 'test_booth_id' must be omitted for a PDI inspection.")
        if window_start is not None:
            raise bad_request("Field 'window_start' must be omitted for a PDI inspection.")
        if window_end is not None:
            raise bad_request("Field 'window_end' must be omitted for a PDI inspection.")

    must_find("unit_builds", build_id)
    booth = None
    if booth_id is not None:
        booth = must_find("test_booths", booth_id)
        if booth["booth_type"] != inspection_type:
            raise bad_request(
                "Booth type '{}' does not match inspection type '{}'.".format(
                    booth["booth_type"], inspection_type
                )
            )
        if booth["status"] != "OPEN":
            raise ApiError("ERR_BOOTH_NOT_OPEN", "Test booth '{}' is DOWN.".format(booth["booth_code"]))
        if derive.booth_conflict_count(booth, window_start, window_end) + 1 > int(booth["bay_count"]):
            raise ApiError(
                "ERR_BOOTH_WINDOW_CONFLICT",
                "All {} bays of booth '{}' are occupied in this window.".format(
                    booth["bay_count"], booth["booth_code"]
                ),
            )

    row = db.new_row(
        {
            "unit_build_id": build_id,
            "test_booth_id": booth_id,
            "inspection_type": inspection_type,
            "window_start": window_start,
            "window_end": window_end,
            "inspector_user_id": g.user_id,
            "completed_by_user_id": None,
            "defect_points": 0,
            "leak_detected": False,
            "result": None,
            "status": "SCHEDULED",
        }
    )
    insert("quality_inspections", row)
    return object_out("quality_inspections", row, 201)


@bp.get("/quality-inspections/<row_id>")
@authorize("PlantAdmin", "QualityInspector", "LineSupervisor")
def get_inspection(row_id):
    return object_out("quality_inspections", must_find("quality_inspections", row_id))


@bp.get("/quality-inspections")
@authorize("PlantAdmin", "QualityInspector", "LineSupervisor")
def list_inspections():
    build_id = V.query_string("unit_build_id")
    booth_id = V.query_string("test_booth_id")
    inspection_type = V.query_enum("inspection_type", C.INSPECTION_TYPES)
    status = V.query_enum("status", ["SCHEDULED", "COMPLETED"])
    result = V.query_enum("result", C.INSPECTION_GRADES)
    rows = list(store.quality_inspections.values())
    if build_id is not None:
        rows = [r for r in rows if r["unit_build_id"] == build_id]
    if booth_id is not None:
        rows = [r for r in rows if r.get("test_booth_id") == booth_id]
    if inspection_type is not None:
        rows = [r for r in rows if r["inspection_type"] == inspection_type]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    if result is not None:
        rows = [r for r in rows if r.get("result") == result]
    return list_out("quality_inspections", rows)


STATION_FOR_TYPE = {
    "WATER_TEST": ("WATER_TEST",),
    "PDI": ("PDI",),
    "FUNCTIONAL": ("WATER_TEST", "PDI"),
}


@bp.post("/quality-inspections/<row_id>/complete")
@authorize("QualityInspector")
def complete_inspection(row_id):
    body = V.body_dict()
    defect_points = V.field_int(body, "defect_points", required=True, minimum=0)
    leak_detected = V.field_bool(body, "leak_detected", required=True)
    row = must_find("quality_inspections", row_id)

    if row["status"] != "SCHEDULED":
        raise ApiError(
            "ERR_INVALID_STATE",
            "Inspection status is {}; only a SCHEDULED inspection can be completed.".format(
                row["status"]
            ),
        )
    build = store.unit_builds.get(row["unit_build_id"])
    inspection_type = row["inspection_type"]
    if build is None or build["current_station"] not in STATION_FOR_TYPE[inspection_type]:
        raise ApiError(
            "ERR_INSPECTION_STATION_MISMATCH",
            "The build is not standing at the station a {} inspection requires.".format(
                inspection_type
            ),
        )

    if inspection_type == "PDI":
        latest = derive.latest_completed_water_test(build["id"])
        if latest is not None and latest.get("completed_by_user_id") == g.user_id:
            raise ApiError(
                "ERR_SEGREGATION_OF_DUTIES",
                "The user who completed the water test may not complete the PDI.",
            )

    result = calc.inspection_grade(inspection_type, defect_points, leak_detected)
    row["defect_points"] = defect_points
    row["leak_detected"] = leak_detected
    row["result"] = result
    row["completed_by_user_id"] = g.user_id
    row["status"] = "COMPLETED"
    db.touch(row)

    build["defect_points_total"] = int(build["defect_points_total"]) + defect_points
    if inspection_type == "WATER_TEST":
        if result == "FAIL":
            build["rework_count"] = int(build["rework_count"]) + 1
            build["water_test_passed"] = False
            if build["rework_count"] > C.MAX_REWORK:
                cascade.scrap_build(build)
            else:
                build["current_station"] = "ROUGH_IN"
        else:
            build["water_test_passed"] = True
    elif inspection_type == "PDI":
        if result == "FAIL":
            build["rework_count"] = int(build["rework_count"]) + 1
            build["pdi_passed"] = False
            if build["rework_count"] > C.MAX_REWORK:
                cascade.scrap_build(build)
            else:
                build["current_station"] = "FINISH"
        else:
            build["pdi_passed"] = True
    db.touch(build)
    return object_out("quality_inspections", row)
