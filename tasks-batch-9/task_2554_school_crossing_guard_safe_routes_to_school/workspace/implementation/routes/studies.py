"""Warrant studies: counting, scoring, adoption and recounts (PRD 3.2, 3.3)."""
from flask import Blueprint

import calc
import domain
import validate as v
from auth import require
from db import base_entity, db, now, touch
from errors import bad_request, fail
from response import object_response
from timeutil import add_days, fmt_date, fmt_dt, parse_date

bp = Blueprint("studies", __name__)

PERIODS = ("AM_ARRIVAL", "MIDDAY", "PM_DISMISSAL")
COUNTING_STATUSES = ("DRAFT", "COUNTING")
REOPENABLE_STATUSES = ("ANALYZED", "CONDITIONAL", "NOT_WARRANTED")
COOL_OFF_DAYS = 30


@bp.post("/srts/warrant-studies")
def open_study():
    user_id, _role = require("TrafficEngineer")
    body = v.body()
    intersection_id = v.req_str(body, "intersection_id")
    window_start = v.req_date(body, "count_window_start")
    window_end = v.req_date(body, "count_window_end")
    if window_end <= window_start:
        bad_request("count_window_end must be strictly later than count_window_start.")
    expected_version = v.req_int(body, "expected_intersection_version")
    intersection = domain.get_intersection(intersection_id)

    if expected_version != intersection["version"]:
        fail("ERR_STALE_INTERSECTION_VERSION",
             "expected_intersection_version does not match the stored version.")

    for other in db.studies.values():
        if other["intersection_id"] != intersection["id"]:
            continue
        other_start = parse_date(other["count_window_start"])
        other_end = parse_date(other["count_window_end"])
        if (window_start < add_days(other_end, COOL_OFF_DAYS)
                and window_end > other_start):
            fail("ERR_COUNT_WINDOW_OVERLAP",
                 "The count window crowds an existing study on this intersection.")

    study = base_entity()
    study.update({
        "intersection_id": intersection["id"],
        "count_window_start": fmt_date(window_start),
        "count_window_end": fmt_date(window_end),
        "authored_by_user_id": user_id,
        "finalized_by_user_id": None,
        "status": "DRAFT",
        "scoring_variant": None,
        "count_sessions": [],
        "recount_round": 0,
        "included_child_count": None,
        "included_adequate_gaps": None,
        "included_vehicle_count": None,
        "pedestrian_crash_count_3yr": None,
        "severe_pedestrian_crash_count_3yr": None,
        "warrant_score": None,
        "determination": None,
        "reopen_reason": None,
    })
    db.studies[study["id"]] = study

    intersection["warrant_status"] = "UNDER_STUDY"
    intersection["latest_warrant_score"] = None
    touch(intersection)
    return object_response(study, 201)


@bp.get("/srts/warrant-studies/<study_id>")
def read_study(study_id):
    require("ProgramAdmin", "TrafficEngineer", "CrossingSupervisor")
    study = domain.get_study(study_id)
    return object_response(study)


@bp.post("/srts/warrant-studies/<study_id>/count-sessions")
def record_count_session(study_id):
    require("TrafficEngineer")
    body = v.body()
    session_date = v.req_date(body, "session_date")
    period = v.req_enum(body, "period", PERIODS)
    observed_minutes = v.req_int(body, "observed_minutes", minimum=1)
    child_count = v.req_int(body, "child_count", minimum=0)
    adult_count = v.req_int(body, "adult_count", minimum=0)
    vehicle_count = v.req_int(body, "vehicle_count", minimum=0)
    adequate_gaps = v.req_int(body, "adequate_gaps", minimum=0)
    study = domain.get_study(study_id)

    if study["status"] not in COUNTING_STATUSES:
        fail("ERR_STUDY_NOT_IN_COUNTING",
             "Count sessions may only be recorded while the study is DRAFT or COUNTING.")

    window_start = parse_date(study["count_window_start"])
    window_end = parse_date(study["count_window_end"])
    if session_date < window_start or session_date > window_end:
        fail("ERR_SESSION_DATE_OUTSIDE_WINDOW",
             "session_date must fall inside the study's closed count window.")

    study["count_sessions"].append({
        "session_date": fmt_date(session_date),
        "period": period,
        "observed_minutes": observed_minutes,
        "child_count": child_count,
        "adult_count": adult_count,
        "vehicle_count": vehicle_count,
        "adequate_gaps": adequate_gaps,
        "voided": False,
        "recorded_at": fmt_dt(now()),
    })
    study["status"] = "COUNTING"
    touch(study)
    return object_response(study)


@bp.post("/srts/warrant-studies/<study_id>/analyze")
def analyze_study(study_id):
    require("TrafficEngineer")
    study = domain.get_study(study_id)
    if study["status"] != "COUNTING":
        fail("ERR_STUDY_NOT_IN_COUNTING", "Only a COUNTING study can be analyzed.")

    included = [s for s in study["count_sessions"]
                if not s["voided"] and s["period"] in ("AM_ARRIVAL", "PM_DISMISSAL")]
    am = sum(1 for s in included if s["period"] == "AM_ARRIVAL")
    pm = sum(1 for s in included if s["period"] == "PM_DISMISSAL")
    if len(included) < 2 or am < 1 or pm < 1:
        fail("ERR_INSUFFICIENT_COUNT_COVERAGE",
             "Analysis needs at least one AM_ARRIVAL and one PM_DISMISSAL session.")

    intersection = domain.get_intersection(study["intersection_id"])
    variant = ("GAP_ADEQUACY" if intersection["control_type"] == "UNCONTROLLED"
               else "EXPOSURE_INDEX")

    child_count = sum(s["child_count"] for s in included)
    adequate_gaps = sum(s["adequate_gaps"] for s in included)
    vehicle_count = sum(s["vehicle_count"] for s in included)

    anchor = parse_date(study["count_window_end"])
    crashes = domain.pedestrian_crashes_in_window(intersection, anchor)
    pedestrian_crashes = len(crashes)
    severe_crashes = sum(1 for e in crashes
                         if e["severity"] in calc.SEVERE_SEVERITIES)

    score = calc.warrant_score(variant, intersection["speed_limit_mph"],
                               child_count, vehicle_count, adequate_gaps,
                               pedestrian_crashes, severe_crashes)

    study["scoring_variant"] = variant
    study["included_child_count"] = child_count
    study["included_adequate_gaps"] = adequate_gaps
    study["included_vehicle_count"] = vehicle_count
    study["pedestrian_crash_count_3yr"] = pedestrian_crashes
    study["severe_pedestrian_crash_count_3yr"] = severe_crashes
    study["warrant_score"] = float(score)
    study["determination"] = calc.warrant_determination(score, pedestrian_crashes)
    study["status"] = "ANALYZED"
    touch(study)
    return object_response(study)


@bp.post("/srts/warrant-studies/<study_id>/finalize")
def finalize_study(study_id):
    user_id, _role = require("TrafficEngineer")
    body = v.body()
    v.opt_str(body, "engineer_note")
    study = domain.get_study(study_id)

    if study["status"] != "ANALYZED":
        fail("ERR_STUDY_NOT_ANALYZED", "Only an ANALYZED study can be finalized.")
    if user_id == study["authored_by_user_id"]:
        fail("ERR_SEGREGATION_OF_DUTIES",
             "The engineer who opened the study may not finalize it.")

    determination = study["determination"]
    study["status"] = determination
    study["finalized_by_user_id"] = user_id
    touch(study)

    intersection = domain.get_intersection(study["intersection_id"])
    intersection["warrant_status"] = determination
    intersection["latest_warrant_score"] = _latest_finalized_score(intersection)
    touch(intersection)

    if determination == "CONDITIONAL":
        doomed = [p for p in domain.posts_of_intersection(intersection)
                  if p["status"] == "ACTIVE" and p["required_shift"] in ("PM", "BOTH")]
        domain.suspend_posts(doomed, "WARRANT_LAPSED")
    elif determination == "NOT_WARRANTED":
        doomed = [p for p in domain.posts_of_intersection(intersection)
                  if p["status"] == "ACTIVE"]
        domain.suspend_posts(doomed, "WARRANT_LAPSED")
    domain.recompute_school_coverage(domain.school_of_intersection(intersection))
    return object_response(study)


def _latest_finalized_score(intersection):
    """The score of the most recently created finalized study, so re-finalizing
    an older study never displaces a newer determination (PRD 3.3)."""
    finalized = [s for s in db.studies.values()
                 if s["intersection_id"] == intersection["id"]
                 and s["status"] in domain.FINALIZED_STUDY_STATUSES]
    if not finalized:
        return None
    newest = max(finalized, key=lambda s: (s["created_at"], s["_seq"]))
    return newest["warrant_score"]


@bp.post("/srts/warrant-studies/<study_id>/reopen-counting")
def reopen_counting(study_id):
    require("TrafficEngineer")
    body = v.body()
    reopen_reason = v.req_str(body, "reopen_reason")
    study = domain.get_study(study_id)

    if study["status"] not in REOPENABLE_STATUSES:
        fail("ERR_STUDY_NOT_REOPENABLE",
             "Only an ANALYZED, CONDITIONAL or NOT_WARRANTED study can be reopened.")

    for session in study["count_sessions"]:
        session["voided"] = True
    study["warrant_score"] = None
    study["scoring_variant"] = None
    study["determination"] = None
    study["included_child_count"] = None
    study["included_adequate_gaps"] = None
    study["included_vehicle_count"] = None
    study["pedestrian_crash_count_3yr"] = None
    study["severe_pedestrian_crash_count_3yr"] = None
    study["recount_round"] += 1
    study["reopen_reason"] = reopen_reason
    study["status"] = "COUNTING"
    touch(study)

    intersection = domain.get_intersection(study["intersection_id"])
    intersection["warrant_status"] = "UNDER_STUDY"
    intersection["latest_warrant_score"] = None
    touch(intersection)
    return object_response(study)
