"""Civil grading areas, earthwork occupancy, stormwater events and acceptance."""

from datetime import timedelta

from flask import Blueprint

import calc
import clock
import envelope
import store
import validate
from clock import dec
from errors import fail, invalid
from routes.common import filter_eq, paginate, unique_check
from validate import ALL_ROLES, authorize, b, body, dt, e, i, n, s

bp = Blueprint("civil", __name__)

ACTIVITY_TYPES = ("CLEARING", "GRADING", "DRAINAGE", "ACCESS_ROAD")
EVENT_TYPES = ("RAIN_EVENT", "BMP_INSPECTION", "PERMIT_SUSPENSION", "PERMIT_REINSTATEMENT")
WORKABLE = ("PLANNED", "CLEARED", "GRADED")


@bp.post("/solar/projects/<project_id>/grading-areas")
def create_grading_area(project_id):
    authorize("CivilSuperintendent")
    data = body(
        s("area_code"),
        s("permit_number"),
        n("disturbed_acreage_limit", gt=0),
        i("bmp_inspection_interval_days", ge=1),
        i("access_road_meters", required=False, default=0, ge=0),
    )
    project = store.require_project(project_id)
    unique_check(store.grading_areas, "project_id", project_id, "area_code", data["area_code"])
    row = store.base()
    row.update(
        {
            "project_id": project_id,
            "area_code": data["area_code"],
            "permit_number": data["permit_number"],
            "disturbed_acreage_limit": data["disturbed_acreage_limit"],
            "disturbed_acreage_current": 0,
            "access_road_meters": data["access_road_meters"],
            "bmp_inspection_interval_days": data["bmp_inspection_interval_days"],
            "bmp_last_inspected_at": clock.now(),
            "bmp_deficiency_open": False,
            "rain_blackout_until": None,
            "permit_status": "ACTIVE",
            "status": "PLANNED",
            "status_before_hold": None,
            "compaction_test_pct": None,
            "drainage_inspection_passed": None,
            "earthwork_windows": [],
        }
    )
    store.grading_areas[row["id"]] = row
    calc.sync_project(project, force=True)
    return envelope.created(row)


@bp.get("/solar/grading-areas/<area_id>")
def get_grading_area(area_id):
    authorize(*ALL_ROLES)
    return envelope.ok(store.require_grading_area(area_id))


@bp.get("/solar/projects/<project_id>/grading-areas")
def list_grading_areas(project_id):
    authorize(*ALL_ROLES)
    store.require_project(project_id)
    rows = store.children(store.grading_areas, "project_id", project_id)
    rows = filter_eq(rows, "status", validate.q("status"))
    return paginate(rows)


@bp.post("/solar/grading-areas/<area_id>/earthwork-logs")
def create_earthwork_log(area_id):
    authorize("CivilSuperintendent")
    data = body(
        e("activity_type", ACTIVITY_TYPES),
        dt("work_start_at"),
        dt("work_end_at"),
        n("acreage_disturbed_delta", ge=0),
        s("crew_ref", required=False),
    )
    validate.window_bounds(data["work_start_at"], data["work_end_at"])
    area = store.require_grading_area(area_id)
    activity = data["activity_type"]

    # priority 8 -- civil state
    if area["status"] not in WORKABLE:
        fail("ERR_GRADING_AREA_NOT_OPEN_FOR_WORK")
    if activity == "GRADING" and area["status"] not in ("CLEARED", "GRADED"):
        fail("ERR_GRADING_AREA_NOT_OPEN_FOR_WORK")

    # priority 11 -- permit / BMP deficiency
    if area["permit_status"] != "ACTIVE" or area["bmp_deficiency_open"]:
        fail("ERR_PERMIT_NOT_ACTIVE")

    # priority 12 -- post-rain blackout (boundary equality is workable)
    blackout = area["rain_blackout_until"]
    if blackout is not None and data["work_start_at"] < blackout:
        fail("ERR_RAIN_EVENT_BLACKOUT")

    # priority 13 -- BMP currency
    due = area["bmp_last_inspected_at"] + timedelta(days=area["bmp_inspection_interval_days"])
    if data["work_start_at"] > due:
        fail("ERR_BMP_INSPECTION_OVERDUE")

    # priority 14 -- exclusive crew occupancy
    if calc.earthwork_conflict(area, data["work_start_at"], data["work_end_at"]):
        fail("ERR_EARTHWORK_WINDOW_CONFLICT")

    # priority 17 -- permitted disturbance
    projected = clock.rhu(
        dec(area["disturbed_acreage_current"]) + dec(data["acreage_disturbed_delta"]), 2
    )
    if projected > dec(area["disturbed_acreage_limit"]):
        fail("ERR_DISTURBED_ACREAGE_EXCEEDED")

    area["earthwork_windows"].append(
        {
            "work_start_at": data["work_start_at"],
            "work_end_at": data["work_end_at"],
            "activity_type": activity,
            "acreage_disturbed_delta": data["acreage_disturbed_delta"],
        }
    )
    calc.recompute_area_acreage(area)
    if activity == "CLEARING" and area["status"] == "PLANNED":
        area["status"] = "CLEARED"
    elif activity == "GRADING" and area["status"] == "CLEARED":
        area["status"] = "GRADED"
    store.touch(area)
    project = store.projects.get(area["project_id"])
    if project is not None:
        calc.sync_project(project)
    return envelope.ok(area)


@bp.post("/solar/grading-areas/<area_id>/site-events")
def create_site_event(area_id):
    authorize("CivilSuperintendent")
    data = body(
        e("event_type", EVENT_TYPES),
        dt("occurred_at"),
        n("rainfall_inches", required=False, ge=0),
        b("deficiencies_found", required=False),
        s("note", required=False),
    )
    event = data["event_type"]
    if event == "RAIN_EVENT" and data["rainfall_inches"] is None:
        invalid("Field 'rainfall_inches' is required for a RAIN_EVENT")
    if event == "BMP_INSPECTION" and data["deficiencies_found"] is None:
        invalid("Field 'deficiencies_found' is required for a BMP_INSPECTION")

    area = store.require_grading_area(area_id)
    before = (
        area["status"],
        area["permit_status"],
        area["status_before_hold"],
        area["bmp_last_inspected_at"],
        area["bmp_deficiency_open"],
        area["rain_blackout_until"],
    )

    if event == "RAIN_EVENT":
        if dec(data["rainfall_inches"]) >= calc.RAIN_TRIGGER_INCHES:
            area["rain_blackout_until"] = data["occurred_at"] + timedelta(
                hours=calc.RAIN_BLACKOUT_HOURS
            )
    elif event == "BMP_INSPECTION":
        area["bmp_last_inspected_at"] = data["occurred_at"]
        area["bmp_deficiency_open"] = bool(data["deficiencies_found"])
    elif event == "PERMIT_SUSPENSION":
        if area["status"] not in WORKABLE or area["permit_status"] != "ACTIVE":
            fail("ERR_GRADING_AREA_NOT_OPEN_FOR_WORK")
        area["status_before_hold"] = area["status"]
        area["status"] = "HOLD"
        area["permit_status"] = "SUSPENDED"
    else:
        if (
            area["status"] != "HOLD"
            or area["permit_status"] != "SUSPENDED"
            or area["bmp_deficiency_open"]
        ):
            fail("ERR_GRADING_AREA_NOT_OPEN_FOR_WORK")
        area["status"] = area["status_before_hold"] or "PLANNED"
        area["status_before_hold"] = None
        area["permit_status"] = "ACTIVE"

    after = (
        area["status"],
        area["permit_status"],
        area["status_before_hold"],
        area["bmp_last_inspected_at"],
        area["bmp_deficiency_open"],
        area["rain_blackout_until"],
    )
    if before != after:
        store.touch(area)
    project = store.projects.get(area["project_id"])
    if project is not None:
        calc.sync_project(project)
    return envelope.ok(area)


@bp.post("/solar/grading-areas/<area_id>/acceptance")
def accept_grading_area(area_id):
    authorize("OwnerEngineer")
    data = body(n("compaction_test_pct"), b("drainage_inspection_passed"))
    if (
        dec(data["compaction_test_pct"]) < calc.MIN_COMPACTION_PCT
        or data["drainage_inspection_passed"] is not True
    ):
        invalid("Civil acceptance requires compaction >= 95.0 and a passed drainage inspection")
    area = store.require_grading_area(area_id)
    if area["status"] != "GRADED":
        fail("ERR_GRADING_AREA_NOT_OPEN_FOR_WORK")
    if area["permit_status"] != "ACTIVE" or area["bmp_deficiency_open"]:
        fail("ERR_PERMIT_NOT_ACTIVE")
    area["compaction_test_pct"] = data["compaction_test_pct"]
    area["drainage_inspection_passed"] = data["drainage_inspection_passed"]
    area["status"] = "ACCEPTED"
    store.touch(area)
    project = store.projects.get(area["project_id"])
    if project is not None:
        calc.sync_project(project, force=True)
    return envelope.ok(area)
