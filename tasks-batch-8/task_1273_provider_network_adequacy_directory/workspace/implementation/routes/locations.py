"""PracticeLocation endpoints (PATCH is OCC-guarded via expected_location_version)."""

from flask import Blueprint

import db
import errors
import helpers
from middleware import require_roles, ALL_ROLES
from response import success_object, success_list

bp = Blueprint("locations", __name__)


@bp.route("/network/locations", methods=["POST"])
@require_roles("NetworkManager")
def create_location(user_id, role):
    body = helpers.get_body()
    provider_id = helpers.req_str(body, "provider_id")
    region_id = helpers.req_str(body, "region_id")
    address_line = helpers.req_str(body, "address_line")
    avg_tm = helpers.req_int(body, "avg_travel_minutes")
    avg_mi = helpers.req_int(body, "avg_travel_miles")
    panel_status = helpers.opt_enum(body, "panel_status", helpers.PANEL_STATUSES, default="OPEN")
    # existence, left-to-right as referenced in the payload
    if provider_id not in db.providers:
        raise errors.err_provider_not_found()
    if region_id not in db.regions:
        raise errors.err_region_not_found()
    rec = {
        "provider_id": provider_id, "region_id": region_id,
        "address_line": address_line, "panel_status": panel_status,
        "avg_travel_minutes": avg_tm, "avg_travel_miles": avg_mi,
    }
    helpers.stamp_new(rec)
    db.locations[rec["id"]] = rec
    return success_object(helpers.ser_location(rec), 201)


@bp.route("/network/locations", methods=["GET"])
@require_roles(*ALL_ROLES)
def list_locations(user_id, role):
    limit, offset = helpers.get_pagination()
    provider_id = helpers.query_str("provider_id")
    region_id = helpers.query_str("region_id")
    panel_status = helpers.query_enum("panel_status", helpers.PANEL_STATUSES)
    items = list(db.locations.values())
    if provider_id is not None:
        items = [l for l in items if l["provider_id"] == provider_id]
    if region_id is not None:
        items = [l for l in items if l["region_id"] == region_id]
    if panel_status is not None:
        items = [l for l in items if l["panel_status"] == panel_status]
    page, total = helpers.paginate(items, limit, offset)
    return success_list([helpers.ser_location(l) for l in page], limit, offset, total)


@bp.route("/network/locations/<lid>", methods=["GET"])
@require_roles(*ALL_ROLES)
def get_location(user_id, role, lid):
    rec = db.locations.get(lid)
    if rec is None:
        raise errors.err_location_not_found()
    return success_object(helpers.ser_location(rec))


@bp.route("/network/locations/<lid>", methods=["PATCH"])
@require_roles("NetworkManager")
def patch_location(user_id, role, lid):
    rec = db.locations.get(lid)
    if rec is None:
        raise errors.err_location_not_found()
    body = helpers.get_body()
    # OCC check runs before any business logic
    expected = helpers.req_int(body, "expected_location_version")
    if expected != rec["version"]:
        raise errors.err_stale_location()
    panel = helpers.opt_enum(body, "panel_status", helpers.PANEL_STATUSES)
    if panel is not None:
        rec["panel_status"] = panel
    for field in ("avg_travel_minutes", "avg_travel_miles"):
        val = helpers.opt_int(body, field)
        if val is not None:
            rec[field] = val
    addr = helpers.opt_str(body, "address_line")
    if addr is not None:
        rec["address_line"] = addr
    helpers.touch(rec)
    return success_object(helpers.ser_location(rec))
