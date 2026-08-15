"""Routes: startup sessions (scheduling, windows, completion cascade)."""

from datetime import timedelta

from flask import Blueprint, request

from calc import reevaluate_job_posture, startup_billable
from core import (
    bump,
    envelope_object,
    err_backup,
    err_double_booked,
    err_invalid_request,
    err_invalid_state,
    err_outside_window,
    err_remote,
    err_turnover,
    get_body,
    iso,
    now_dt,
    now_iso,
    opt_bool,
    opt_enum,
    paginate,
    parse_iso,
    req_str,
    require_roles,
    sorted_by_created,
    stamp_new,
)
from lookups import get_panel, get_startup, job_of_panel, sweep_no_show
from serializers import ser_startup_session
from store import db

bp = Blueprint("startup", __name__)

SUPPORT_MODES = ("ONSITE", "REMOTE")
PANEL_TURNOVER_HOURS = 24


@bp.route("/panel-shop/panels/<panel_id>/startup-sessions", methods=["POST"])
def create_startup_session(panel_id):
    require_roles("ProjectManager")
    get_panel(panel_id)
    body = get_body()
    start_raw = body.get("scheduled_start")
    end_raw = body.get("scheduled_end")
    engineer_id = body.get("engineer_id")
    start_dt = parse_iso(start_raw) if start_raw is not None else None
    end_dt = parse_iso(end_raw) if end_raw is not None else None
    support_mode = opt_enum(body, "support_mode", SUPPORT_MODES, "ONSITE")
    remote_access_granted = opt_bool(body, "remote_access_granted", False)
    if start_dt is not None and end_dt is not None:
        # priority 13: engineer double-booking (half-open windows; adjacency ok)
        for other in db.startup_sessions.values():
            if other["engineer_id"] == engineer_id and other["status"] in (
                "SCHEDULED",
                "IN_PROGRESS",
            ):
                if start_dt < other["_end_dt"] and other["_start_dt"] < end_dt:
                    raise err_double_booked("Engineer has an overlapping session.")
        # priority 14: same-panel turnover buffer (buffer-inflated intervals;
        # a gap of exactly 24h is permitted)
        for other in db.startup_sessions.values():
            if (
                other["panel_id"] == panel_id
                and other["status"] in ("SCHEDULED", "IN_PROGRESS")
            ):
                inflated_end = other["_end_dt"] + timedelta(hours=PANEL_TURNOVER_HOURS)
                if start_dt < inflated_end and other["_start_dt"] < end_dt:
                    raise err_turnover("Panel turnover buffer violated.")
    # priority 20: REMOTE requires remote_access_granted
    if support_mode == "REMOTE" and not remote_access_granted:
        raise err_remote("REMOTE support mode requires remote_access_granted.")
    # priority 22: shape
    if start_dt is None:
        raise err_invalid_request("Missing or invalid required field: scheduled_start")
    if end_dt is None:
        raise err_invalid_request("Missing or invalid required field: scheduled_end")
    if not isinstance(engineer_id, str) or not engineer_id:
        raise err_invalid_request("Missing or invalid required field: engineer_id")
    if not (end_dt > start_dt):
        raise err_invalid_request("scheduled_end must be strictly after scheduled_start.")
    s = stamp_new(
        {
            "panel_id": panel_id,
            "scheduled_start": iso(start_dt),
            "scheduled_end": iso(end_dt),
            "_start_dt": start_dt,
            "_end_dt": end_dt,
            "status": "SCHEDULED",
            "remote_access_granted": remote_access_granted,
            "support_mode": support_mode,
            "engineer_id": engineer_id,
            "labor_hours": 0,
            "billable_cents": None,
        }
    )
    db.startup_sessions[s["id"]] = s
    return envelope_object(ser_startup_session(s), 201)


@bp.route("/panel-shop/startup-sessions/<ss_id>", methods=["GET"])
def fetch_startup_session(ss_id):
    require_roles("ProjectManager", "QAManager", "FieldEngineer", "Customer")
    s = get_startup(ss_id)
    sweep_no_show(s)
    return envelope_object(ser_startup_session(s))


@bp.route("/panel-shop/panels/<panel_id>/startup-sessions", methods=["GET"])
def list_startup_sessions(panel_id):
    require_roles("ProjectManager", "QAManager", "FieldEngineer", "Customer")
    get_panel(panel_id)
    sweep_no_show()
    sessions = [s for s in db.startup_sessions.values() if s["panel_id"] == panel_id]
    if "status" in request.args:
        sessions = [s for s in sessions if s["status"] == request.args.get("status")]
    return paginate(sorted_by_created(sessions), ser_startup_session)


@bp.route("/panel-shop/startup-sessions/<ss_id>/start", methods=["POST"])
def start_startup_session(ss_id):
    require_roles("FieldEngineer")
    s = get_startup(ss_id)
    sweep_no_show(s)
    if s["status"] != "SCHEDULED":
        raise err_invalid_state("StartupSession is not SCHEDULED.")
    p = db.panels[s["panel_id"]]
    if p["status"] != "SHIPPED":
        raise err_invalid_state("Owning panel is not SHIPPED.")
    # priority 11: logical clock within [scheduled_start, scheduled_end]
    now = now_dt()
    if now < s["_start_dt"] or now > s["_end_dt"]:
        raise err_outside_window("Logical clock is outside the scheduled window.")
    # priority 20
    if s["support_mode"] == "REMOTE" and not s["remote_access_granted"]:
        raise err_remote("REMOTE support mode requires remote_access_granted.")
    s["status"] = "IN_PROGRESS"
    bump(s)
    return envelope_object(ser_startup_session(s))


@bp.route("/panel-shop/startup-sessions/<ss_id>/complete", methods=["POST"])
def complete_startup_session(ss_id):
    require_roles("FieldEngineer")
    s = get_startup(ss_id)
    if s["status"] != "IN_PROGRESS":
        raise err_invalid_state("StartupSession is not IN_PROGRESS.")
    body = get_body()
    labor_hours = body.get("labor_hours")
    if (
        labor_hours is None
        or not isinstance(labor_hours, (int, float))
        or isinstance(labor_hours, bool)
        or labor_hours <= 0
    ):
        raise err_invalid_request("labor_hours must be supplied and > 0 at completion.")
    p = db.panels[s["panel_id"]]
    # completion requires a RELEASED ProgramVersion with site_backup_taken
    if not any(
        v["panel_id"] == p["id"] and v["status"] == "RELEASED" and v["site_backup_taken"]
        for v in db.program_versions.values()
    ):
        raise err_backup("No RELEASED ProgramVersion with site_backup_taken == true.")
    s["labor_hours"] = labor_hours
    s["billable_cents"] = startup_billable(labor_hours, s["_start_dt"])
    s["status"] = "COMPLETED"
    bump(s)
    # commissioning cascade: owning panel SHIPPED -> COMMISSIONED
    if p["status"] == "SHIPPED":
        p["status"] = "COMMISSIONED"
        p["commissioned_at"] = now_iso()
        p["_commissioned_dt"] = now_dt()
        bump(p)
    reevaluate_job_posture(job_of_panel(p))
    return envelope_object(ser_startup_session(s))


@bp.route("/panel-shop/startup-sessions/<ss_id>/cancel", methods=["POST"])
def cancel_startup_session(ss_id):
    require_roles("ProjectManager")
    s = get_startup(ss_id)
    sweep_no_show(s)
    if s["status"] != "SCHEDULED":
        raise err_invalid_state("StartupSession is not SCHEDULED.")
    s["status"] = "CANCELLED"
    bump(s)
    return envelope_object(ser_startup_session(s))
