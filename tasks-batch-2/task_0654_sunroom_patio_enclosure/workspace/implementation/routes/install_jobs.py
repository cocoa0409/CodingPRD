"""InstallJob endpoints (PRD §3.6). Parallel progress + weather axes."""
from datetime import timedelta

from flask import Blueprint

import errors
import response
from db import db, parse_iso
from middleware import require_roles
from services import common, serialize, calculations

bp = Blueprint("install_jobs", __name__)

# Non-terminal install jobs (progress axis terminal is INSTALLED).
NON_TERMINAL_PROGRESS = {"SCHEDULED", "IN_PROGRESS"}


def _job_non_terminal(job):
    return job["progress_status"] in NON_TERMINAL_PROGRESS


def _overlaps_half_open(a_start, a_end, b_start, b_end):
    """Half-open overlap: [a_start,a_end) intersects [b_start,b_end), no buffer."""
    return a_start < b_end and b_start < a_end


@bp.route("/install-jobs", methods=["POST"])
def create_install_job():
    require_roles({"InstallManager"})
    body = common.get_json()

    project_id = common.require_field(body, "project_id", expected_types=["string"])
    crew_id = common.require_field(body, "crew_id", expected_types=["string"])
    scheduled_start_raw = common.require_field(
        body, "scheduled_start", expected_types=["string"])
    scheduled_end_raw = common.require_field(
        body, "scheduled_end", expected_types=["string"])
    forecast_wind_mph = common.require_field(
        body, "forecast_wind_mph", expected_types=["integer"],
        validator=lambda v: v >= 0)

    # parse timestamps (well-formedness, priority 21)
    try:
        scheduled_start = parse_iso(scheduled_start_raw)
        scheduled_end = parse_iso(scheduled_end_raw)
    except (ValueError, TypeError):
        raise errors.invalid_request("scheduled_start/scheduled_end must be ISO 8601.")

    # existence left-to-right: project then crew (priority 4)
    project = common.get_project(project_id)
    crew = common.get_crew(crew_id)

    # state (priority 5): project IN_MANUFACTURE and order READY
    if project["status"] != "IN_MANUFACTURE":
        raise errors.invalid_state("Project must be IN_MANUFACTURE to schedule install.")
    ready_order = any(
        mo["project_id"] == project_id and mo["status"] == "READY"
        for mo in db.manufacture_orders.values())
    if not ready_order:
        raise errors.invalid_state("The manufacture order must be READY.")

    # business rules in scaffold priority order:
    # 9 crew certification, 10 crew active, 11 window, 12 double-book, 13 site rest
    if project["structure_type"] == "FOUR_SEASON" and not crew["certified_four_season"]:
        raise errors.ApiError(
            errors.ERR_CREW_NOT_CERTIFIED, 422,
            "Crew is not certified for FOUR_SEASON.")
    if not crew["active"]:
        raise errors.ApiError(
            errors.ERR_CREW_INACTIVE, 422, "Assigned crew is inactive.")
    if not (scheduled_start < scheduled_end):
        raise errors.ApiError(
            errors.ERR_INVALID_WINDOW, 422,
            "scheduled_start must be strictly before scheduled_end.")

    # crew double-booking: half-open overlap, no buffer (priority 12)
    for job in db.install_jobs.values():
        if job["crew_id"] != crew_id:
            continue
        if not _job_non_terminal(job):
            continue
        if _overlaps_half_open(scheduled_start, scheduled_end,
                               job["scheduled_start"], job["scheduled_end"]):
            raise errors.ApiError(
                errors.ERR_CREW_DOUBLE_BOOKED, 409,
                "Crew already booked for an overlapping window.")

    # site-rest: same project, window expanded by 24h on both ends intersects
    # (buffered closed-interval) (priority 13)
    buffer = timedelta(hours=calculations.SITE_REST_BUFFER_HOURS)
    for job in db.install_jobs.values():
        if job["project_id"] != project_id:
            continue
        if not _job_non_terminal(job):
            continue
        exp_start = job["scheduled_start"] - buffer
        exp_end = job["scheduled_end"] + buffer
        # closed-interval intersection with the buffered existing window
        if scheduled_start <= exp_end and exp_start <= scheduled_end:
            raise errors.ApiError(
                errors.ERR_SITE_WINDOW_CONFLICT, 409,
                "Another install on this site is within the 24h rest buffer.")

    entity = {
        "project_id": project_id,
        "crew_id": crew_id,
        "scheduled_start": scheduled_start,
        "scheduled_end": scheduled_end,
        "forecast_wind_mph": forecast_wind_mph,
        "progress_status": "SCHEDULED",
        "weather_status": "CLEAR",
    }
    common.stamp_create(entity)
    db.install_jobs[entity["id"]] = entity

    project["status"] = "INSTALLING"
    common.touch(project)
    return response.success(serialize.install_job(entity), status=201)


@bp.route("/install-jobs/<jid>/start", methods=["POST"])
def start_install(jid):
    require_roles({"InstallManager"})
    common.get_json()
    job = common.get_install_job(jid)
    crew = db.install_crews[job["crew_id"]]

    # state (priority 5): progress SCHEDULED
    if job["progress_status"] != "SCHEDULED":
        raise errors.invalid_state("Install job must be SCHEDULED to start.")

    # weather safety (priority 8): WEATHER_HOLD or forecast > crew.max_wind_mph
    if job["weather_status"] == "WEATHER_HOLD" or job["forecast_wind_mph"] > crew["max_wind_mph"]:
        raise errors.ApiError(
            errors.ERR_WEATHER_UNSAFE, 409,
            "Cannot start install under unsafe weather conditions.")

    job["progress_status"] = "IN_PROGRESS"
    common.touch(job)
    return response.success(serialize.install_job(job), status=200)


@bp.route("/install-jobs/<jid>/weather", methods=["POST"])
def set_weather(jid):
    require_roles({"InstallManager"})
    body = common.get_json()
    weather_status = common.require_field(
        body, "weather_status", expected_types=["string"],
        validator=lambda v: v in ("CLEAR", "WEATHER_HOLD"))
    job = common.get_install_job(jid)

    # state (priority 5): the requested weather transition must be legal
    if weather_status == "WEATHER_HOLD":
        if not (job["weather_status"] == "CLEAR"
                and job["progress_status"] in ("SCHEDULED", "IN_PROGRESS")):
            raise errors.invalid_state(
                "A weather hold may only be raised from CLEAR while SCHEDULED or IN_PROGRESS.")
        job["weather_status"] = "WEATHER_HOLD"
    else:  # CLEAR
        if job["weather_status"] != "WEATHER_HOLD":
            raise errors.invalid_state(
                "Weather can only be cleared from WEATHER_HOLD.")
        job["weather_status"] = "CLEAR"
    common.touch(job)
    return response.success(serialize.install_job(job), status=200)


@bp.route("/install-jobs/<jid>/complete", methods=["POST"])
def complete_install(jid):
    require_roles({"InstallManager"})
    common.get_json()
    job = common.get_install_job(jid)

    # state (priority 5): progress IN_PROGRESS
    if job["progress_status"] != "IN_PROGRESS":
        raise errors.invalid_state("Install job must be IN_PROGRESS to complete.")

    # weather safety (priority 8): WEATHER_HOLD blocks completion
    if job["weather_status"] == "WEATHER_HOLD":
        raise errors.ApiError(
            errors.ERR_WEATHER_UNSAFE, 409,
            "Cannot complete install under a weather hold.")

    job["progress_status"] = "INSTALLED"
    common.touch(job)
    return response.success(serialize.install_job(job), status=200)
