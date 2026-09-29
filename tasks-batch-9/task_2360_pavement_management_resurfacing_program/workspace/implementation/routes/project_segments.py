"""Project lines: bundling, removal and the resident-notice track
(PRD 3.5, 3.6)."""
from datetime import timedelta

from flask import Blueprint

import calc
import clock
import db
import response
import validators as v
from errors import ApiError
from middleware import ALL_ROLES, endpoint
from services import derive

bp = Blueprint("project_segments", __name__)

NOTICE_ACTIONS = ("SCHEDULE", "DELIVER", "RESCHEDULE")
DRIVEWAY_PLANS = ("MAINTAINED", "LIMITED_NIGHTLY", "BLOCKED_WITH_ALT")
NOTIFIABLE_WORK_STATES = ("PLANNED", "IN_PROGRESS", "REMEDIATION_REQUIRED")


def _find_line(line_id):
    line = db.project_segments.get(line_id)
    if line is None:
        raise ApiError("ERR_PROJECT_SEGMENT_NOT_FOUND")
    return line


@bp.post("/project-segments")
@endpoint("PavementEngineer")
def create_line():
    data = v.body()
    project_id = v.field_id(data, "project_id")
    segment_id = v.field_id(data, "segment_id")
    candidate_id = v.field_id(data, "candidate_id")
    window_start = v.field_datetime(data, "work_window_start")
    window_end = v.field_datetime(data, "work_window_end")
    expected_version = v.field_int(data, "expected_project_version")
    design_thickness = v.field_number(data, "design_thickness_in", minimum=0.5,
                                      maximum=12.0, required=False, default=2.0)
    v.window(window_start, window_end, "work window")

    # Body foreign keys resolve in the API's declared order (PRD 2.5).
    segment = db.segments.get(segment_id)
    if segment is None:
        raise ApiError("ERR_SEGMENT_NOT_FOUND")
    candidate = db.candidates.get(candidate_id)
    if candidate is None:
        raise ApiError("ERR_CANDIDATE_NOT_FOUND")
    project = db.projects.get(project_id)
    if project is None:
        raise ApiError("ERR_PROJECT_NOT_FOUND")

    if expected_version != project["version"]:
        raise ApiError("ERR_STALE_PROJECT_VERSION")
    if project["delivery_status"] not in ("DRAFT", "COORDINATING"):
        raise ApiError("ERR_PROJECT_SCOPE_LOCKED")

    if candidate["segment_id"] != segment_id:
        raise ApiError("ERR_CANDIDATE_SEGMENT_MISMATCH")
    scenario = db.scenarios.get(project["scenario_id"])
    funded = scenario is not None \
        and candidate["survey_id"] == scenario["survey_id"] \
        and any(a["scenario_id"] == scenario["id"]
                and a["allocation_status"] == "FUNDED"
                for a in derive.allocations_of_candidate(candidate["id"]))
    if not funded:
        raise ApiError("ERR_CANDIDATE_NOT_FUNDED")
    if segment["geo_zone"] != project["geo_zone"]:
        raise ApiError("ERR_SEGMENT_ZONE_MISMATCH")

    for line in derive.lines_of_project(project["id"]):
        if line["work_state"] != "REMOVED" and line["segment_id"] == segment_id:
            raise ApiError("ERR_DUPLICATE_PROJECT_SEGMENT")
    for line in db.project_segments.values():
        if line["work_state"] != "REMOVED" \
                and line["candidate_id"] == candidate_id:
            raise ApiError("ERR_CANDIDATE_ALREADY_PROGRAMMED")

    for line in derive.lines_of_segment(segment_id):
        if line["work_state"] == "REMOVED":
            continue
        # Half-open comparison: touching endpoints are allowed.
        if line["work_window_start"] < window_end \
                and window_start < line["work_window_end"]:
            raise ApiError("ERR_SEGMENT_WINDOW_CONFLICT")

    line = {
        "id": db.new_id(),
        "project_id": project["id"],
        "segment_id": segment["id"],
        "candidate_id": candidate["id"],
        "treatment_type": candidate["treatment_type"],
        "line_area_sy": segment["area_sy"],
        "line_cost_cents": 0,
        "design_thickness_in": calc.num(design_thickness, 2),
        "work_window_start": window_start,
        "work_window_end": window_end,
        "work_state": "PLANNED",
        "notice_state": "PENDING",
        "parking_restriction_start": None,
        "parking_restriction_end": None,
        "driveway_access_plan": None,
        "notice_delivered_at": None,
        "notice_round": 1,
        "pay_factor": None,
        "test_count": 0,
    }
    line["line_cost_cents"] = calc.construction_cost_cents(
        line["line_area_sy"], line["treatment_type"],
        segment["functional_class"], segment["width_ft"],
        candidate["selection_condition_index"],
    )
    line.update(db.audit())
    db.project_segments[line["id"]] = line

    derive.apply_updates(candidate, {"candidate_status": "CONSUMED"})
    derive.recompute_project_counters(project)
    derive.recompute_project_estimate(project)
    derive.recompute_segment_counters(segment)
    return response.object_response(line, 201)


@bp.get("/project-segments/<line_id>")
@endpoint(*ALL_ROLES)
def read_line(line_id):
    return response.object_response(_find_line(line_id))


@bp.get("/project-segments")
@endpoint(*ALL_ROLES)
def list_lines():
    rows = v.filter_rows(db.ordered(db.project_segments.values()), {
        "project_id": "project_id",
        "segment_id": "segment_id",
        "candidate_id": "candidate_id",
        "work_state": "work_state",
        "notice_state": "notice_state",
    })
    page, meta = v.paginate(rows)
    return response.array_response(page, pagination=meta)


@bp.delete("/project-segments/<line_id>")
@endpoint("PavementEngineer")
def remove_line(line_id):
    line = _find_line(line_id)
    if line["work_state"] != "PLANNED":
        raise ApiError("ERR_PROJECT_SEGMENT_NOT_REMOVABLE")
    project = db.projects.get(line["project_id"])
    if project is None or project["delivery_status"] not in ("DRAFT", "COORDINATING"):
        raise ApiError("ERR_PROJECT_SCOPE_LOCKED")

    derive.apply_updates(line, {"work_state": "REMOVED"})
    candidate = db.candidates.get(line["candidate_id"])
    if candidate is not None:
        restored = "OVERRIDDEN" if candidate["override_reason"] else "RECOMMENDED"
        derive.apply_updates(candidate, {"candidate_status": restored})
    derive.recompute_project_counters(project)
    derive.recompute_project_estimate(project)
    segment = db.segments.get(line["segment_id"])
    if segment is not None:
        derive.recompute_segment_counters(segment)
    return response.object_response(line)


@bp.post("/project-segments/<line_id>/notice")
@endpoint("PavementEngineer")
def notice(line_id):
    data = v.body()
    action = v.field_enum(data, "action", NOTICE_ACTIONS)
    if action in ("SCHEDULE", "RESCHEDULE"):
        start = v.field_datetime(data, "parking_restriction_start")
        end = v.field_datetime(data, "parking_restriction_end")
        plan = v.field_enum(data, "driveway_access_plan", DRIVEWAY_PLANS)
        v.window(start, end, "parking restriction window")
    else:
        start = end = plan = None

    line = _find_line(line_id)

    if action == "SCHEDULE":
        if line["notice_state"] != "PENDING":
            raise ApiError("ERR_NOTICE_ALREADY_SCHEDULED")
        if line["work_state"] not in NOTIFIABLE_WORK_STATES:
            raise ApiError("ERR_LINE_NOT_NOTIFIABLE")
    elif action == "DELIVER":
        if line["notice_state"] != "SCHEDULED":
            raise ApiError("ERR_NOTICE_NOT_SCHEDULED")
    else:  # RESCHEDULE
        if line["notice_state"] != "DELIVERED":
            raise ApiError("ERR_NOTICE_NOT_DELIVERED")
        if line["work_state"] == "ACCEPTED":
            raise ApiError("ERR_LINE_NOT_NOTIFIABLE")

    if action == "DELIVER":
        derive.apply_updates(line, {
            "notice_state": "DELIVERED",
            "notice_delivered_at": clock.now(),
        })
        return response.object_response(line)

    now = clock.now()
    if start < now + timedelta(hours=calc.NOTICE_LEAD_HOURS):
        raise ApiError("ERR_NOTICE_LEAD_TIME_TOO_SHORT")

    buffer = timedelta(hours=calc.NOTICE_BUFFER_HOURS)
    buffered_start = start - buffer
    buffered_end = end + buffer
    for other in derive.lines_of_segment(line["segment_id"]):
        if other["id"] == line["id"] or other["work_state"] == "REMOVED":
            continue
        if other["notice_state"] not in ("SCHEDULED", "DELIVERED"):
            continue
        if other["parking_restriction_start"] is None \
                or other["parking_restriction_end"] is None:
            continue
        # Closed-interval comparison: touching counts as an overlap.
        if buffered_start <= other["parking_restriction_end"] \
                and buffered_end >= other["parking_restriction_start"]:
            raise ApiError("ERR_NOTICE_WINDOW_CONFLICT")

    updates = {
        "notice_state": "SCHEDULED",
        "parking_restriction_start": start,
        "parking_restriction_end": end,
        "driveway_access_plan": plan,
    }
    if action == "RESCHEDULE":
        updates["notice_delivered_at"] = None
        updates["notice_round"] = line["notice_round"] + 1
    derive.apply_updates(line, updates)
    return response.object_response(line)
