"""SchoolSite endpoints."""

from flask import Blueprint, request

import db
from middleware import require_roles, ALL_ROLES
from response import success_object, success_list
from services.common import (
    get_json_body,
    require_fields,
    require_string,
    require_int,
    get_or_404,
    new_id,
    now_iso,
    pagination_params,
    paginate,
    sort_created,
    serialize_site,
    serialize_student,
    serialize_placement,
)

bp = Blueprint("sites", __name__)


@bp.route("/gifted/school-sites", methods=["POST"])
def create_site():
    require_roles("GiftedCoordinator")
    body = get_json_body()
    require_fields(
        body,
        ["name", "code", "pull_out_capacity", "cluster_capacity", "acceleration_capacity"],
    )
    name = require_string(body, "name")
    code = require_string(body, "code")
    pull_out = require_int(body, "pull_out_capacity", lo=0)
    cluster = require_int(body, "cluster_capacity", lo=0)
    acceleration = require_int(body, "acceleration_capacity", lo=0)

    ts = now_iso()
    site = {
        "id": new_id(),
        "name": name,
        "code": code,
        "pull_out_capacity": pull_out,
        "cluster_capacity": cluster,
        "acceleration_capacity": acceleration,
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
    }
    db.school_sites[site["id"]] = site
    return success_object(serialize_site(site), 201)


@bp.route("/gifted/school-sites/<sid>", methods=["GET"])
def get_site(sid):
    require_roles(*ALL_ROLES)
    site = get_or_404(db.school_sites, sid, "school site")
    return success_object(serialize_site(site), 200)


@bp.route("/gifted/school-sites/<sid>/students", methods=["GET"])
def list_site_students(sid):
    require_roles(*ALL_ROLES)
    get_or_404(db.school_sites, sid, "school site")
    dg = request.args.get("demographic_group")
    gs = request.args.get("gifted_status")
    items = [s for s in db.students.values() if s["school_site_id"] == sid]
    if dg:
        items = [s for s in items if s["demographic_group"] == dg]
    if gs:
        items = [s for s in items if s["gifted_status"] == gs]
    items = sort_created(items)
    limit, offset = pagination_params()
    page, total = paginate(items, limit, offset)
    return success_list([serialize_student(s) for s in page], total, limit, offset)


@bp.route("/gifted/school-sites/<sid>/placements", methods=["GET"])
def list_site_placements(sid):
    require_roles(*ALL_ROLES)
    get_or_404(db.school_sites, sid, "school site")
    sm = request.args.get("service_model")
    st = request.args.get("status")
    items = [p for p in db.service_placements.values() if p["site_id"] == sid]
    if sm:
        items = [p for p in items if p["service_model"] == sm]
    if st:
        items = [p for p in items if p["status"] == st]
    items = sort_created(items)
    limit, offset = pagination_params()
    page, total = paginate(items, limit, offset)
    return success_list([serialize_placement(p) for p in page], total, limit, offset)
