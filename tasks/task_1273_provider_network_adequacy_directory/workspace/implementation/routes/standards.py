"""NetworkStandard endpoints (PUT is OCC-guarded via expected_standard_version)."""

from flask import Blueprint

import db
import errors
import helpers
from middleware import require_roles, ALL_ROLES
from response import success_object, success_list

bp = Blueprint("standards", __name__)


@bp.route("/network/standards", methods=["POST"])
@require_roles("NetworkManager")
def create_standard(user_id, role):
    body = helpers.get_body()
    specialty = helpers.req_enum(body, "specialty", helpers.SPECIALTIES)
    geo_class = helpers.req_enum(body, "geo_class", helpers.GEO_CLASSES)
    max_mpp = helpers.req_int(body, "max_members_per_provider")
    max_tm = helpers.req_int(body, "max_travel_minutes")
    max_mi = helpers.req_int(body, "max_travel_miles")
    max_wr = helpers.req_int(body, "max_wait_days_routine")
    max_wu = helpers.req_int(body, "max_wait_days_urgent")
    for s in db.standards.values():
        if s["specialty"] == specialty and s["geo_class"] == geo_class:
            raise errors.err_standard_duplicate()
    rec = {
        "specialty": specialty, "geo_class": geo_class,
        "max_members_per_provider": max_mpp, "max_travel_minutes": max_tm,
        "max_travel_miles": max_mi, "max_wait_days_routine": max_wr,
        "max_wait_days_urgent": max_wu,
    }
    helpers.stamp_new(rec)
    db.standards[rec["id"]] = rec
    return success_object(helpers.ser_standard(rec), 201)


@bp.route("/network/standards", methods=["GET"])
@require_roles(*ALL_ROLES)
def list_standards(user_id, role):
    limit, offset = helpers.get_pagination()
    specialty = helpers.query_enum("specialty", helpers.SPECIALTIES)
    geo_class = helpers.query_enum("geo_class", helpers.GEO_CLASSES)
    items = list(db.standards.values())
    if specialty is not None:
        items = [s for s in items if s["specialty"] == specialty]
    if geo_class is not None:
        items = [s for s in items if s["geo_class"] == geo_class]
    page, total = helpers.paginate(items, limit, offset)
    return success_list([helpers.ser_standard(s) for s in page], limit, offset, total)


@bp.route("/network/standards/<sid>", methods=["GET"])
@require_roles(*ALL_ROLES)
def get_standard(user_id, role, sid):
    rec = db.standards.get(sid)
    if rec is None:
        raise errors.err_standard_not_found()
    return success_object(helpers.ser_standard(rec))


@bp.route("/network/standards/<sid>", methods=["PUT"])
@require_roles("NetworkManager")
def update_standard(user_id, role, sid):
    rec = db.standards.get(sid)
    if rec is None:
        raise errors.err_standard_not_found()
    body = helpers.get_body()
    # OCC check runs before any business logic
    expected = helpers.req_int(body, "expected_standard_version")
    if expected != rec["version"]:
        raise errors.err_stale_standard()
    for field in ("max_members_per_provider", "max_travel_minutes", "max_travel_miles",
                  "max_wait_days_routine", "max_wait_days_urgent"):
        val = helpers.opt_int(body, field)
        if val is not None:
            rec[field] = val
    helpers.touch(rec)
    return success_object(helpers.ser_standard(rec))
