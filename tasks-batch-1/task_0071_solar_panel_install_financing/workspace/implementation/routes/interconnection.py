from flask import Blueprint, request
from db import db, new_id, now_iso
from errors import err
from response import ok
from middleware import authenticate
from services.common import get_body, require_fields, is_num, list_response

bp = Blueprint("interconnection", __name__)


def _common_create():
    ts = now_iso()
    return {"created_at": ts, "updated_at": ts, "version": 1}


def _get_app(aid):
    a = db.interconnection_applications.get(aid)
    if not a:
        raise err("ERR_NOT_FOUND", "Interconnection application not found.")
    return a


@bp.route("/solar/interconnection-applications", methods=["POST"])
def file_app():
    authenticate({"SolarInstaller"})
    body = get_body()
    require_fields(body, ["project_id", "utility_id", "requested_export_kw"])
    project = db.projects.get(body["project_id"])
    if not project:
        raise err("ERR_NOT_FOUND", "Project not found.")
    utility = db.utilities.get(body["utility_id"])
    if not utility:
        raise err("ERR_NOT_FOUND", "Utility not found.")
    rek = body["requested_export_kw"]
    if not is_num(rek) or rek < 0:
        raise err("ERR_INVALID_REQUEST", "requested_export_kw must be >= 0.")
    with db.lock:
        aid = new_id()
        rec = {
            "id": aid,
            "project_id": body["project_id"],
            "utility_id": body["utility_id"],
            "status": "FILED",
            "requested_export_kw": rek,
        }
        rec.update(_common_create())
        db.interconnection_applications[aid] = rec
    return ok(rec, 201)


@bp.route("/solar/interconnection-applications/<aid>", methods=["GET"])
def get_app(aid):
    authenticate({"SolarInstaller", "Utility", "PlatformAdmin"})
    return ok(_get_app(aid), 200)


@bp.route("/solar/interconnection-applications", methods=["GET"])
def list_apps():
    authenticate({"SolarInstaller", "Utility", "PlatformAdmin"})
    rows = list(db.interconnection_applications.values())
    proj = request.args.get("project_id")
    util = request.args.get("utility_id")
    if proj is not None:
        rows = [r for r in rows if r["project_id"] == proj]
    if util is not None:
        rows = [r for r in rows if r["utility_id"] == util]
    return list_response(rows)


def _check_owner_utility(app, user_id):
    if app["utility_id"] != user_id:
        raise err("ERR_NOT_RESOURCE_OWNER", "Acting utility is not the application's utility.")


@bp.route("/solar/interconnection-applications/<aid>/begin-review", methods=["POST"])
def begin_review(aid):
    user_id, role = authenticate({"Utility"})
    app = _get_app(aid)
    _check_owner_utility(app, user_id)
    if app["status"] != "FILED":
        raise err("ERR_INVALID_STATE", "Application not in FILED.")
    with db.lock:
        app["status"] = "UNDER_REVIEW"
        db.touch(app)
    return ok(app, 200)


@bp.route("/solar/interconnection-applications/<aid>/approve", methods=["POST"])
def approve(aid):
    user_id, role = authenticate({"Utility"})
    app = _get_app(aid)
    _check_owner_utility(app, user_id)
    if app["status"] != "UNDER_REVIEW":
        raise err("ERR_INVALID_STATE", "Application not in UNDER_REVIEW.")
    utility = db.utilities.get(app["utility_id"])
    if utility["feeder_headroom_kw"] < app["requested_export_kw"]:
        raise err("ERR_INSUFFICIENT_FEEDER_HEADROOM", "Insufficient feeder headroom.")
    with db.lock:
        utility["feeder_headroom_kw"] = utility["feeder_headroom_kw"] - app["requested_export_kw"]
        app["status"] = "APPROVED"
        db.touch(utility)
        db.touch(app)
    return ok(app, 200)


@bp.route("/solar/interconnection-applications/<aid>/reject", methods=["POST"])
def reject(aid):
    user_id, role = authenticate({"Utility"})
    app = _get_app(aid)
    _check_owner_utility(app, user_id)
    if app["status"] != "UNDER_REVIEW":
        raise err("ERR_INVALID_STATE", "Application not in UNDER_REVIEW.")
    with db.lock:
        app["status"] = "REJECTED"
        db.touch(app)
    return ok(app, 200)


@bp.route("/solar/interconnection-applications/<aid>/withdraw", methods=["POST"])
def withdraw(aid):
    user_id, role = authenticate({"Utility"})
    app = _get_app(aid)
    _check_owner_utility(app, user_id)
    if app["status"] != "APPROVED":
        raise err("ERR_INVALID_STATE", "Application not in APPROVED.")
    project = db.projects.get(app["project_id"])
    if project and project["status"] == "OPERATIONAL":
        raise err("ERR_INVALID_STATE", "Project already OPERATIONAL.")
    with db.lock:
        utility = db.utilities.get(app["utility_id"])
        utility["feeder_headroom_kw"] = utility["feeder_headroom_kw"] + app["requested_export_kw"]
        app["status"] = "REJECTED"
        db.touch(utility)
        db.touch(app)
    return ok(app, 200)


@bp.route("/solar/interconnection-applications/<aid>/grant-pto", methods=["POST"])
def grant_pto(aid):
    user_id, role = authenticate({"Utility"})
    app = _get_app(aid)
    _check_owner_utility(app, user_id)
    if app["status"] != "APPROVED":
        raise err("ERR_INVALID_STATE", "Application not in APPROVED.")
    project = db.projects.get(app["project_id"])
    if not project or project["status"] != "PTO_PENDING":
        raise err("ERR_INVALID_STATE", "Project not in PTO_PENDING.")
    with db.lock:
        app["status"] = "PTO_GRANTED"
        project["status"] = "OPERATIONAL"
        # mint warranty policy (immutable: only id + created_at common fields)
        wid = new_id()
        policy = {
            "id": wid,
            "created_at": now_iso(),
            "project_id": project["id"],
            "coverage_start": now_iso(),
            "production_guarantee_pct": 0.85,
            "coverage_years": 25,
        }
        db.warranty_policies[wid] = policy
        db.touch(app)
        db.touch(project)
    return ok(app, 200)
