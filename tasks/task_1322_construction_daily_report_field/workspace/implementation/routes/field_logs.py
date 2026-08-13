"""CrewEntry, EquipmentEntry, WeatherObservation, DelayEvent."""
from decimal import Decimal
from flask import Blueprint, request

from auth import ctx, need
from calc import bump_report, touch, crew_bands, calc_lost_hours
from db import store
from envelope import success
from errors import ApiError, bad
from route_helpers import stamp, list_response, day_window
from serializers import (
    ser_crew_entry,
    ser_equipment_entry,
    ser_weather,
    ser_delay_event,
)
from routes.daily_reports import get_report, require_editable
from routes.setup_resources import get_work_area
from validate import (
    body,
    req_str,
    opt_str,
    req_int,
    req_num,
    opt_num,
    req_enum,
    req_dt,
)

bp = Blueprint("field_logs", __name__)

ENTRY_STATUSES = ("ACTIVE", "VOIDED")
CONDITIONS = ("CLEAR", "CLOUDY", "RAIN", "SNOW", "WIND", "EXTREME_HEAT", "EXTREME_COLD")
WORK_IMPACTS = ("NONE", "PARTIAL", "STOPPAGE")
DELAY_CAUSES = ("WEATHER", "OWNER", "MATERIAL", "LABOR", "EQUIPMENT", "OTHER")
DELAY_CLASSIFICATIONS = (
    "EXCUSABLE_COMPENSABLE",
    "EXCUSABLE_NON_COMPENSABLE",
    "NON_EXCUSABLE",
    "CONCURRENT",
)
DELAY_STATUSES = ("RECORDED", "CLASSIFIED", "DISPUTED", "FINAL")


def get_crew(eid):
    e = store.crew_entries.get(eid)
    if e is None:
        raise ApiError("ERR_NOT_FOUND", 404, "CrewEntry not found")
    return e


def get_equipment(eid):
    e = store.equipment_entries.get(eid)
    if e is None:
        raise ApiError("ERR_NOT_FOUND", 404, "EquipmentEntry not found")
    return e


def get_weather(wid):
    w = store.weather_observations.get(wid)
    if w is None:
        raise ApiError("ERR_NOT_FOUND", 404, "WeatherObservation not found")
    return w


def get_delay(did):
    d = store.delay_events.get(did)
    if d is None:
        raise ApiError("ERR_DELAY_EVENT_NOT_FOUND", 404, "DelayEvent not found")
    return d


def _check_area_open(area):
    if area["status"] != "OPEN":
        raise ApiError("ERR_WORK_AREA_CLOSED", 409, "WorkArea is CLOSED")


# ---------------------------------------------------------------------------
# crew entries
# ---------------------------------------------------------------------------

@bp.post("/crew-entries")
def create_crew_entry():
    _, role = ctx()
    need(role, ["Superintendent"])
    b = body()
    report_id = req_str(b, "report_id")
    work_area_id = req_str(b, "work_area_id")
    subcontractor = req_str(b, "subcontractor")
    trade = req_str(b, "trade")
    worker_count = req_int(b, "worker_count", mn=1)
    hpw = req_num(b, "hours_per_worker", mn=Decimal(0), mx=Decimal(24))
    work_performed = req_str(b, "work_performed")
    report = get_report(report_id)
    area = get_work_area(work_area_id)
    require_editable(report)
    _check_area_open(area)
    reg, ot, dt = crew_bands(worker_count, hpw)
    rec = stamp(
        {
            "report_id": report_id,
            "work_area_id": work_area_id,
            "subcontractor": subcontractor,
            "trade": trade,
            "worker_count": worker_count,
            "hours_per_worker": hpw,
            "work_performed": work_performed,
            "regular_hours": reg,
            "ot_hours": ot,
            "dt_hours": dt,
            "status": "ACTIVE",
        }
    )
    store.crew_entries[rec["id"]] = rec
    bump_report(report)
    return success(ser_crew_entry(rec), 201)


@bp.get("/crew-entries/<eid>")
def get_one_crew(eid):
    ctx()
    return success(ser_crew_entry(get_crew(eid)), 200)


@bp.get("/crew-entries")
def list_crew():
    ctx()
    report_id = request.args.get("report_id")
    work_area_id = request.args.get("work_area_id")
    status = request.args.get("status")
    if status is not None and status not in ENTRY_STATUSES:
        bad("Invalid status filter")
    rows = list(store.crew_entries.values())
    if report_id is not None:
        rows = [r for r in rows if r["report_id"] == report_id]
    if work_area_id is not None:
        rows = [r for r in rows if r["work_area_id"] == work_area_id]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    return list_response(rows, ser_crew_entry)


@bp.post("/crew-entries/<eid>/void")
def void_crew(eid):
    _, role = ctx()
    need(role, ["Superintendent"])
    e = get_crew(eid)
    if e["status"] != "ACTIVE":
        raise ApiError(
            "ERR_ENTRY_INVALID_TRANSITION", 409, "Entry is not ACTIVE"
        )
    report = get_report(e["report_id"])
    require_editable(report)
    e["status"] = "VOIDED"
    touch(e)
    bump_report(report)
    return success(ser_crew_entry(e), 200)


# ---------------------------------------------------------------------------
# equipment entries
# ---------------------------------------------------------------------------

@bp.post("/equipment-entries")
def create_equipment_entry():
    _, role = ctx()
    need(role, ["Superintendent"])
    b = body()
    report_id = req_str(b, "report_id")
    work_area_id = req_str(b, "work_area_id")
    equipment_type = req_str(b, "equipment_type")
    unit_count = req_int(b, "unit_count", mn=1)
    hours_used = req_num(b, "hours_used", mn=Decimal(0))
    hours_idle = req_num(b, "hours_idle", mn=Decimal(0))
    report = get_report(report_id)
    area = get_work_area(work_area_id)
    require_editable(report)
    # priority 8.3: capacity
    if hours_used + hours_idle > Decimal(24) * Decimal(unit_count):
        raise ApiError(
            "ERR_EQUIPMENT_CAPACITY_EXCEEDED",
            422,
            "hours_used + hours_idle exceeds 24 * unit_count",
        )
    _check_area_open(area)
    rec = stamp(
        {
            "report_id": report_id,
            "work_area_id": work_area_id,
            "equipment_type": equipment_type,
            "unit_count": unit_count,
            "hours_used": hours_used,
            "hours_idle": hours_idle,
            "status": "ACTIVE",
        }
    )
    store.equipment_entries[rec["id"]] = rec
    bump_report(report)
    return success(ser_equipment_entry(rec), 201)


@bp.get("/equipment-entries/<eid>")
def get_one_equipment(eid):
    ctx()
    return success(ser_equipment_entry(get_equipment(eid)), 200)


@bp.get("/equipment-entries")
def list_equipment():
    ctx()
    report_id = request.args.get("report_id")
    work_area_id = request.args.get("work_area_id")
    status = request.args.get("status")
    if status is not None and status not in ENTRY_STATUSES:
        bad("Invalid status filter")
    rows = list(store.equipment_entries.values())
    if report_id is not None:
        rows = [r for r in rows if r["report_id"] == report_id]
    if work_area_id is not None:
        rows = [r for r in rows if r["work_area_id"] == work_area_id]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    return list_response(rows, ser_equipment_entry)


@bp.post("/equipment-entries/<eid>/void")
def void_equipment(eid):
    _, role = ctx()
    need(role, ["Superintendent"])
    e = get_equipment(eid)
    if e["status"] != "ACTIVE":
        raise ApiError("ERR_ENTRY_INVALID_TRANSITION", 409, "Entry is not ACTIVE")
    report = get_report(e["report_id"])
    require_editable(report)
    e["status"] = "VOIDED"
    touch(e)
    bump_report(report)
    return success(ser_equipment_entry(e), 200)


# ---------------------------------------------------------------------------
# weather observations (immutable; no updated_at/version)
# ---------------------------------------------------------------------------

@bp.post("/weather-observations")
def create_weather():
    _, role = ctx()
    need(role, ["Superintendent"])
    b = body()
    report_id = req_str(b, "report_id")
    observed_at = req_dt(b, "observed_at")
    condition = req_enum(b, "condition", CONDITIONS)
    work_impact = req_enum(b, "work_impact", WORK_IMPACTS)
    temperature_f = opt_num(b, "temperature_f")
    precipitation_in = opt_num(b, "precipitation_in", mn=Decimal(0))
    wind_mph = opt_num(b, "wind_mph", mn=Decimal(0))
    report = get_report(report_id)
    require_editable(report)
    # priority 9.1: observed_at within report_date calendar day [00:00Z, +24h)
    day_start, day_end = day_window(report["report_date"])
    if not (day_start <= observed_at < day_end):
        raise ApiError(
            "ERR_WEATHER_OUTSIDE_REPORT_DATE",
            422,
            "observed_at outside report_date calendar day",
        )
    rec = stamp(
        {
            "report_id": report_id,
            "observed_at": observed_at,
            "condition": condition,
            "temperature_f": temperature_f,
            "precipitation_in": precipitation_in,
            "wind_mph": wind_mph,
            "work_impact": work_impact,
        },
        common=False,
    )
    store.weather_observations[rec["id"]] = rec
    bump_report(report)
    return success(ser_weather(rec), 201)


@bp.get("/weather-observations/<wid>")
def get_one_weather(wid):
    ctx()
    return success(ser_weather(get_weather(wid)), 200)


@bp.get("/weather-observations")
def list_weather():
    ctx()
    report_id = request.args.get("report_id")
    rows = list(store.weather_observations.values())
    if report_id is not None:
        rows = [r for r in rows if r["report_id"] == report_id]
    return list_response(rows, ser_weather)


# ---------------------------------------------------------------------------
# delay events
# ---------------------------------------------------------------------------

@bp.post("/delay-events")
def create_delay():
    _, role = ctx()
    need(role, ["Superintendent"])
    b = body()
    report_id = req_str(b, "report_id")
    work_area_id = req_str(b, "work_area_id")
    start_at = req_dt(b, "start_at")
    end_at = req_dt(b, "end_at")
    cause = req_enum(b, "cause", DELAY_CAUSES)
    report = get_report(report_id)
    area = get_work_area(work_area_id)
    require_editable(report)
    # priority 9.4: end strictly after start
    if end_at <= start_at:
        raise ApiError(
            "ERR_DELAY_WINDOW_INVALID", 422, "end_at must be strictly after start_at"
        )
    _check_area_open(area)
    rec = stamp(
        {
            "report_id": report_id,
            "work_area_id": work_area_id,
            "start_at": start_at,
            "end_at": end_at,
            "cause": cause,
            "classification": None,
            "lost_hours": None,
            "status": "RECORDED",
            "dispute_reason": None,
        }
    )
    store.delay_events[rec["id"]] = rec
    bump_report(report)
    return success(ser_delay_event(rec), 201)


@bp.get("/delay-events/<did>")
def get_one_delay(did):
    ctx()
    return success(ser_delay_event(get_delay(did)), 200)


@bp.get("/delay-events")
def list_delays():
    ctx()
    report_id = request.args.get("report_id")
    work_area_id = request.args.get("work_area_id")
    status = request.args.get("status")
    if status is not None and status not in DELAY_STATUSES:
        bad("Invalid status filter")
    rows = list(store.delay_events.values())
    if report_id is not None:
        rows = [r for r in rows if r["report_id"] == report_id]
    if work_area_id is not None:
        rows = [r for r in rows if r["work_area_id"] == work_area_id]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    return list_response(rows, ser_delay_event)


@bp.post("/delay-events/<did>/classify")
def classify_delay(did):
    _, role = ctx()
    need(role, ["ProjectManager"])
    ev = get_delay(did)
    b = body()
    classification = req_enum(b, "classification", DELAY_CLASSIFICATIONS)
    # priority 6: state
    if ev["status"] not in ("RECORDED", "DISPUTED"):
        raise ApiError(
            "ERR_DELAY_INVALID_TRANSITION",
            409,
            "DelayEvent must be RECORDED or DISPUTED to classify",
        )
    # priority 9.5: EXCUSABLE_COMPENSABLE overlap prohibition (half-open)
    if classification == "EXCUSABLE_COMPENSABLE":
        for other in store.delay_events.values():
            if other["id"] == ev["id"]:
                continue
            if other["work_area_id"] != ev["work_area_id"]:
                continue
            if (
                other["classification"] == "EXCUSABLE_COMPENSABLE"
                and other["status"] in ("CLASSIFIED", "FINAL")
                and ev["start_at"] < other["end_at"]
                and other["start_at"] < ev["end_at"]
            ):
                raise ApiError(
                    "ERR_DELAY_OVERLAP_COMPENSABLE",
                    409,
                    "Overlapping EXCUSABLE_COMPENSABLE delay on the same work area",
                )
    # priority 10.5: classify forbidden when report APPROVED/LOCKED
    report = get_report(ev["report_id"])
    if report["status"] in ("APPROVED", "LOCKED"):
        raise ApiError(
            "ERR_DELAY_LOCKED_REPORT",
            409,
            "Cannot classify a delay on an APPROVED or LOCKED report",
        )
    project = store.projects.get(report["project_id"])
    ev["classification"] = classification
    ev["lost_hours"] = calc_lost_hours(ev, report, project)
    ev["status"] = "CLASSIFIED"
    touch(ev)
    bump_report(report)
    return success(ser_delay_event(ev), 200)


@bp.post("/delay-events/<did>/dispute")
def dispute_delay(did):
    _, role = ctx()
    need(role, ["OwnerRep"])
    ev = get_delay(did)
    b = body()
    reason = req_str(b, "reason")
    if ev["status"] != "CLASSIFIED":
        raise ApiError(
            "ERR_DELAY_INVALID_TRANSITION", 409, "DelayEvent must be CLASSIFIED"
        )
    ev["status"] = "DISPUTED"
    ev["dispute_reason"] = reason
    touch(ev)
    bump_report(get_report(ev["report_id"]))
    return success(ser_delay_event(ev), 200)


@bp.post("/delay-events/<did>/finalize")
def finalize_delay(did):
    _, role = ctx()
    need(role, ["ProjectManager"])
    ev = get_delay(did)
    if ev["status"] != "CLASSIFIED":
        raise ApiError(
            "ERR_DELAY_INVALID_TRANSITION", 409, "DelayEvent must be CLASSIFIED"
        )
    report = get_report(ev["report_id"])
    if report["status"] not in ("SUBMITTED", "UNDER_REVIEW", "APPROVED"):
        raise ApiError(
            "ERR_DELAY_FINALIZE_REQUIRES_SUBMITTED_REPORT",
            409,
            "Report must be SUBMITTED, UNDER_REVIEW, or APPROVED",
        )
    ev["status"] = "FINAL"
    touch(ev)
    bump_report(report)
    return success(ser_delay_event(ev), 200)
