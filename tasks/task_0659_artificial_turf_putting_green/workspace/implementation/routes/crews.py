"""Crews (PRD 3.8). Created by Scheduler or OpsAdmin. Also exposes the
crew->install-jobs reverse list (PRD §4)."""

from flask import Blueprint, request

from common import (
    get_json_body,
    paginate,
    public,
    require_bool,
    require_fields,
    require_number_gt,
    require_string,
    stamp_new,
)
from db import db
from lookups import get_crew_or_404
from middleware import get_auth, require_role
from response import success

bp = Blueprint("crews", __name__)


@bp.route("/crews", methods=["POST"])
def create_crew():
    _uid, role = get_auth()
    require_role(role, {"OpsAdmin", "Scheduler"})
    body = get_json_body()
    require_fields(body, ["name", "daily_capacity_sqft"])
    name = require_string(body, "name")
    daily_capacity = require_number_gt(body, "daily_capacity_sqft", 0)
    certified_putting = require_bool(body, "certified_putting", False)
    certified_playground = require_bool(body, "certified_playground", False)
    active = require_bool(body, "active", True)

    rec = {
        "name": name,
        "daily_capacity_sqft": daily_capacity,
        "certified_putting": certified_putting,
        "certified_playground": certified_playground,
        "active": active,
    }
    stamp_new(rec)
    db.crews[rec["id"]] = rec
    return success(public(rec), status=201)


@bp.route("/crews/<crew_id>", methods=["GET"])
def get_crew(crew_id):
    _uid, role = get_auth()
    require_role(role, {"OpsAdmin", "Scheduler"})
    rec = get_crew_or_404(crew_id)
    return success(public(rec), status=200)


@bp.route("/crews/<crew_id>/install-jobs", methods=["GET"])
def list_crew_jobs(crew_id):
    _uid, role = get_auth()
    require_role(role, {"OpsAdmin", "Scheduler"})
    get_crew_or_404(crew_id)
    status_filter = request.args.get("status")
    items = [j for j in db.install_jobs.values() if j["crew_id"] == crew_id]
    if status_filter is not None:
        items = [j for j in items if j["status"] == status_filter]
    data, pagination = paginate(items, public)
    return success(data, status=200, pagination=pagination)
