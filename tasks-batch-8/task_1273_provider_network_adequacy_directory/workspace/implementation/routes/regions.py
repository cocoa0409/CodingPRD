"""ServiceRegion endpoints."""

from flask import Blueprint

import db
import errors
import helpers
from middleware import require_roles, ALL_ROLES
from response import success_object, success_list

bp = Blueprint("regions", __name__)


@bp.route("/network/regions", methods=["POST"])
@require_roles("NetworkManager")
def create_region(user_id, role):
    body = helpers.get_body()
    county_fips = helpers.req_str(body, "county_fips")
    name = helpers.req_str(body, "name")
    geo_class = helpers.req_enum(body, "geo_class", helpers.GEO_CLASSES)
    enrolled = helpers.req_int(body, "enrolled_member_count")
    if enrolled < 0:
        raise errors.err_invalid("enrolled_member_count must be >= 0")
    for r in db.regions.values():
        if r["county_fips"] == county_fips:
            raise errors.err_region_duplicate()
    rec = {
        "county_fips": county_fips, "name": name, "geo_class": geo_class,
        "enrolled_member_count": enrolled,
    }
    helpers.stamp_new(rec)
    db.regions[rec["id"]] = rec
    return success_object(helpers.ser_region(rec), 201)


@bp.route("/network/regions", methods=["GET"])
@require_roles(*ALL_ROLES)
def list_regions(user_id, role):
    limit, offset = helpers.get_pagination()
    geo_class = helpers.query_enum("geo_class", helpers.GEO_CLASSES)
    items = list(db.regions.values())
    if geo_class is not None:
        items = [r for r in items if r["geo_class"] == geo_class]
    page, total = helpers.paginate(items, limit, offset)
    return success_list([helpers.ser_region(r) for r in page], limit, offset, total)


@bp.route("/network/regions/<rid>", methods=["GET"])
@require_roles(*ALL_ROLES)
def get_region(user_id, role, rid):
    rec = db.regions.get(rid)
    if rec is None:
        raise errors.err_region_not_found()
    return success_object(helpers.ser_region(rec))
