"""Vehicle entries: staging bays, check-in and technical inspection (PRD 3.3)."""
from datetime import timedelta

from db import clock_dt, clock_raw, db, new_bare_row, new_row, touch
from errors import fail
from middleware import (
    ROLE_COMPETITOR_TEAM,
    ROLE_SAFETY_OFFICIAL,
    ROLE_SERIES_PROMOTER,
    ROLE_SPONSOR_REP,
    auth,
    enum_filter,
    pagination,
    string_filter,
)
from response import list_response, object_response
from services import calc, derive, flow, serialize
import validate

LOGISTICS_STATES = ("ENTERED", "STAGED", "WITHDRAWN")
INSPECTION_RESULTS = ("PASSED", "CONDITIONAL", "FAILED")
DEFECT_SEVERITIES = ("NONE", "MINOR", "MAJOR", "CRITICAL")
TECH_BRANCH = {
    "PASSED": "TECH_CLEARED",
    "CONDITIONAL": "TECH_CONDITIONAL",
    "FAILED": "TECH_HELD",
}


def _rescore(entry, stop):
    """Recompute the entry's score under POST_STAGING from its inspection history."""
    inspections = derive.inspections_of_entry(entry["id"])
    last = inspections[-1] if inspections else None
    failed = len([i for i in inspections if i["result"] == "FAILED"])
    entry["readiness_variant"] = "POST_STAGING"
    entry["readiness_score"] = calc.readiness_score(entry, stop, "POST_STAGING", last, failed)


def register(app):
    @app.route("/vehicle-entries", methods=["POST"])
    def create_entry():
        user_id, role = auth(ROLE_SERIES_PROMOTER, ROLE_COMPETITOR_TEAM)
        payload = validate.body()
        competitor_id = validate.field_id(payload, "competitor_id")
        stop_id = validate.field_id(payload, "tour_stop_id")
        vehicle_number = validate.field_string(payload, "vehicle_number")
        weight = validate.field_int(payload, "vehicle_weight_lbs", minimum=1)
        haul = validate.field_int(payload, "haul_distance_miles", minimum=0)
        arrival_raw, _arrival = validate.field_datetime(payload, "scheduled_arrival_utc")

        competitor = derive.get_competitor(competitor_id)
        stop = derive.get_stop(stop_id)

        if role == ROLE_COMPETITOR_TEAM and user_id != competitor["id"]:
            fail("ERR_OWNERSHIP_MISMATCH")

        flow.ensure_stop_writable(stop)
        flow.ensure_not_frozen(stop)

        for other in derive.entries_of_stop(stop["id"]):
            if (
                other["competitor_id"] == competitor["id"]
                and other["vehicle_number"] == vehicle_number
                and other["logistics_state"] != "WITHDRAWN"
            ):
                fail("ERR_DUPLICATE_VEHICLE_ENTRY")

        venue = derive.venue_of_stop(stop)
        occupied = set()
        for other in derive.entries_of_stop(stop["id"]):
            if other["logistics_state"] in ("ENTERED", "STAGED") and other[
                "staging_bay_index"
            ] is not None:
                occupied.add(other["staging_bay_index"])
        bay = calc.select_staging_bay(venue, occupied, weight)
        if bay is None:
            fail("ERR_NO_STAGING_BAY_AVAILABLE")

        row = new_row(
            competitor_id=competitor["id"],
            tour_stop_id=stop["id"],
            vehicle_number=vehicle_number,
            vehicle_weight_lbs=weight,
            haul_distance_miles=haul,
            scheduled_arrival_utc=arrival_raw,
            actual_arrival_utc=None,
            staging_bay_index=bay,
            logistics_state="ENTERED",
            tech_status="TECH_PENDING",
            readiness_score=0,
            readiness_variant="PRE_STAGING",
        )
        row["readiness_score"] = calc.readiness_score(row, stop, "PRE_STAGING")
        db.entries[row["id"]] = row

        touch(competitor)  # entry_count rose
        flow.refresh_plan_requirements(stop)
        flow.apply_posture(stop)
        return object_response(serialize.entry(row), 201)

    @app.route("/vehicle-entries", methods=["GET"])
    def list_entries():
        auth(
            ROLE_SERIES_PROMOTER,
            ROLE_COMPETITOR_TEAM,
            ROLE_SAFETY_OFFICIAL,
            ROLE_SPONSOR_REP,
        )
        limit, offset = pagination()
        stop_id = string_filter("tour_stop_id")
        competitor_id = string_filter("competitor_id")
        state = enum_filter("logistics_state", LOGISTICS_STATES)
        rows = derive.all_entries()
        if stop_id is not None:
            rows = [r for r in rows if r["tour_stop_id"] == stop_id]
        if competitor_id is not None:
            rows = [r for r in rows if r["competitor_id"] == competitor_id]
        if state is not None:
            rows = [r for r in rows if r["logistics_state"] == state]
        return list_response([serialize.entry(r) for r in rows], limit, offset)

    @app.route("/vehicle-entries/<entry_id>", methods=["GET"])
    def read_entry(entry_id):
        auth(
            ROLE_SERIES_PROMOTER,
            ROLE_COMPETITOR_TEAM,
            ROLE_SAFETY_OFFICIAL,
            ROLE_SPONSOR_REP,
        )
        return object_response(serialize.entry(derive.get_entry(entry_id)))

    @app.route("/vehicle-entries/<entry_id>/check-in", methods=["POST"])
    def check_in(entry_id):
        user_id, role = auth(ROLE_SERIES_PROMOTER, ROLE_COMPETITOR_TEAM)
        payload = validate.body()
        validate.field_string(payload, "arrival_note", required=False)
        entry = derive.get_entry(entry_id)
        if role == ROLE_COMPETITOR_TEAM and user_id != entry["competitor_id"]:
            fail("ERR_OWNERSHIP_MISMATCH")

        stop = db.stops[entry["tour_stop_id"]]
        flow.ensure_stop_writable(stop)
        if entry["logistics_state"] != "ENTERED":
            fail("ERR_INVALID_STATE_TRANSITION")
        flow.ensure_not_frozen(stop)
        if stop["safety_state"] != "SAFETY_CERTIFIED":
            fail("ERR_SAFETY_NOT_CERTIFIED")

        show_start = calc.dt(stop["show_start_utc"])
        now = clock_dt()
        if show_start is None:
            fail("ERR_STAGING_WINDOW_CLOSED")
        window_open = show_start - timedelta(hours=calc.STAGING_WINDOW_OPEN_HOURS)
        window_close = show_start - timedelta(hours=calc.STAGING_WINDOW_CLOSE_HOURS)
        if now < window_open or now > window_close:
            fail("ERR_STAGING_WINDOW_CLOSED")

        entry["logistics_state"] = "STAGED"
        entry["actual_arrival_utc"] = clock_raw()
        _rescore(entry, stop)
        touch(entry)
        flow.refresh_plan_requirements(stop)
        flow.apply_posture(stop)
        return object_response(serialize.entry(entry))

    @app.route("/vehicle-entries/<entry_id>/tech-inspections", methods=["POST"])
    def file_inspection(entry_id):
        user_id, _role = auth(ROLE_SAFETY_OFFICIAL)
        payload = validate.body()
        result = validate.field_enum(payload, "result", INSPECTION_RESULTS)
        severity = validate.field_enum(payload, "defect_severity", DEFECT_SEVERITIES)
        notes = validate.field_string(payload, "notes", required=False)

        entry = derive.get_entry(entry_id)
        stop = db.stops[entry["tour_stop_id"]]
        flow.ensure_stop_writable(stop)
        if entry["logistics_state"] != "STAGED":
            fail("ERR_INVALID_STATE_TRANSITION")
        attempts = derive.entry_tech_attempt_count(entry)
        if attempts >= calc.MAX_TECH_ATTEMPTS:
            fail("ERR_TECH_ATTEMPTS_EXHAUSTED")

        row = new_bare_row(
            vehicle_entry_id=entry["id"],
            attempt_no=attempts + 1,
            result=result,
            defect_severity=severity,
            notes=notes,
            inspected_by_user_id=user_id,
        )
        db.inspections[row["id"]] = row

        entry["tech_status"] = TECH_BRANCH[result]
        _rescore(entry, stop)
        touch(entry)
        flow.apply_posture(stop)
        return object_response(serialize.inspection(row), 201)

    @app.route("/vehicle-entries/<entry_id>/tech-inspections", methods=["GET"])
    def list_inspections(entry_id):
        auth(ROLE_SERIES_PROMOTER, ROLE_SAFETY_OFFICIAL, ROLE_COMPETITOR_TEAM)
        limit, offset = pagination()
        entry = derive.get_entry(entry_id)
        rows = derive.inspections_of_entry(entry["id"])
        return list_response([serialize.inspection(r) for r in rows], limit, offset)

    @app.route("/tech-inspections/<inspection_id>", methods=["GET"])
    def read_inspection(inspection_id):
        auth(ROLE_SERIES_PROMOTER, ROLE_SAFETY_OFFICIAL, ROLE_COMPETITOR_TEAM)
        return object_response(serialize.inspection(derive.get_inspection(inspection_id)))

    @app.route("/vehicle-entries/<entry_id>/featured-segments", methods=["GET"])
    def list_featured_segments(entry_id):
        auth(ROLE_SERIES_PROMOTER, ROLE_COMPETITOR_TEAM, ROLE_SPONSOR_REP)
        limit, offset = pagination()
        entry = derive.get_entry(entry_id)
        rows = sorted(
            derive.segments_featuring_entry(entry["id"]),
            key=lambda s: s["run_order_position"],
        )
        return list_response([serialize.segment(r) for r in rows], limit, offset)
