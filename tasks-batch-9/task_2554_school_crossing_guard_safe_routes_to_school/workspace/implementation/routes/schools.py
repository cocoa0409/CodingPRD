"""Schools, the seasonal calendar and the term travel tally (PRD 3.1, 3.9)."""
from flask import Blueprint

import calc
import domain
import validate as v
from auth import require
from db import base_entity, db, now, touch
from errors import bad_request
from response import list_response, object_response
from timeutil import fmt_date, fmt_dt

bp = Blueprint("schools", __name__)

READ_ROLES = ("ProgramAdmin", "TrafficEngineer", "CrossingSupervisor", "SchoolLiaison")
ROUTE_READ_ROLES = READ_ROLES + ("PublicReporter",)


@bp.post("/srts/schools")
def register_school():
    require("ProgramAdmin")
    body = v.body()
    name = v.req_str(body, "name")
    district_code = v.req_str(body, "district_code")
    enrollment_count = v.req_int(body, "enrollment_count", minimum=1)
    session_start = v.req_date(body, "session_start_date")
    session_end = v.req_date(body, "session_end_date")
    if session_end < session_start:
        bad_request("session_end_date must be on or after session_start_date.")
    am_start = v.req_hhmm(body, "am_window_start_utc")
    am_end = v.req_hhmm(body, "am_window_end_utc")
    pm_start = v.req_hhmm(body, "pm_window_start_utc")
    pm_end = v.req_hhmm(body, "pm_window_end_utc")
    baseline = v.req_num(body, "baseline_walk_bike_mode_share_pct",
                         minimum=0, maximum=100)
    offset_minutes = v.opt_int(body, "early_dismissal_pm_offset_minutes", default=-120)
    no_school_dates = v.opt_date_array(body, "no_school_dates")
    early_dismissal_dates = v.opt_date_array(body, "early_dismissal_dates")

    school = base_entity()
    school.update({
        "name": name,
        "district_code": district_code,
        "enrollment_count": enrollment_count,
        "session_start_date": fmt_date(session_start),
        "session_end_date": fmt_date(session_end),
        "am_window_start_utc": "%02d:%02d" % am_start,
        "am_window_end_utc": "%02d:%02d" % am_end,
        "pm_window_start_utc": "%02d:%02d" % pm_start,
        "pm_window_end_utc": "%02d:%02d" % pm_end,
        "early_dismissal_pm_offset_minutes": offset_minutes,
        "no_school_dates": no_school_dates,
        "early_dismissal_dates": early_dismissal_dates,
        "baseline_walk_bike_mode_share_pct": float(baseline),
        "mode_share_surveys": [],
        "walk_bike_mode_share_pct": None,
        "walk_bike_mode_share_weighted_pct": None,
        "mode_share_trend_pct": None,
        "latest_survey_term_code": None,
        "active_post_count": 0,
        "covered_post_count": 0,
        "uncovered_post_count": 0,
        "coverage_rate_pct": 100.00,
        "coverage_posture": "OPEN",
    })
    db.schools[school["id"]] = school
    return object_response(school, 201)


@bp.get("/srts/schools/<school_id>")
def read_school(school_id):
    require(*READ_ROLES)
    school = domain.get_school(school_id)
    return object_response(school)


@bp.get("/srts/schools/<school_id>/intersections")
def list_school_intersections(school_id):
    require(*READ_ROLES)
    limit, offset = v.pagination()
    school = domain.get_school(school_id)
    return list_response(domain.intersections_of_school(school), limit, offset)


@bp.get("/srts/schools/<school_id>/walking-routes")
def list_school_routes(school_id):
    require(*ROUTE_READ_ROLES)
    limit, offset = v.pagination()
    status = v.query_filter("status")
    school = domain.get_school(school_id)
    records = domain.routes_of_school(school)
    if status is not None:
        records = [r for r in records if r["status"] == status]
    return list_response(records, limit, offset)


@bp.post("/srts/schools/<school_id>/mode-share-surveys")
def append_mode_share_survey(school_id):
    require("SchoolLiaison", "ProgramAdmin")
    body = v.body()
    term_code = v.req_str(body, "term_code")
    survey_date = v.req_date(body, "survey_date")
    classrooms_reporting = v.req_int(body, "classrooms_reporting", minimum=0)
    enrollment_at_survey = v.req_int(body, "enrollment_at_survey", minimum=1)
    walk_count = v.req_int(body, "walk_count", minimum=0)
    bike_count = v.req_int(body, "bike_count", minimum=0)
    bus_count = v.req_int(body, "bus_count", minimum=0)
    car_count = v.req_int(body, "car_count", minimum=0)
    other_count = v.req_int(body, "other_count", minimum=0)
    if (walk_count + bike_count + bus_count + car_count + other_count) == 0:
        bad_request("The five travel-mode buckets must not all be zero.")
    school = domain.get_school(school_id)

    survey = {
        "term_code": term_code,
        "survey_date": fmt_date(survey_date),
        "classrooms_reporting": classrooms_reporting,
        "enrollment_at_survey": enrollment_at_survey,
        "walk_count": walk_count,
        "bike_count": bike_count,
        "bus_count": bus_count,
        "car_count": car_count,
        "other_count": other_count,
        "recorded_at": fmt_dt(now()),
    }
    school["mode_share_surveys"].append(survey)
    _recompute_mode_share(school)
    touch(school)
    return object_response(school)


def _recompute_mode_share(school):
    """The picture is built from exactly one survey -- the latest -- selected by
    survey_date DESC then recorded_at DESC (PRD 3.9)."""
    surveys = school["mode_share_surveys"]
    if not surveys:
        return
    latest = max(
        enumerate(surveys),
        key=lambda pair: (pair[1]["survey_date"], pair[1]["recorded_at"], pair[0]),
    )[1]
    raw = calc.mode_share_raw_pct(latest)
    weighted = calc.mode_share_weighted_pct(latest)
    baseline = calc.dec(school["baseline_walk_bike_mode_share_pct"])
    school["walk_bike_mode_share_pct"] = float(raw)
    school["walk_bike_mode_share_weighted_pct"] = float(weighted)
    school["mode_share_trend_pct"] = calc.f2(raw - baseline)
    school["latest_survey_term_code"] = latest["term_code"]
