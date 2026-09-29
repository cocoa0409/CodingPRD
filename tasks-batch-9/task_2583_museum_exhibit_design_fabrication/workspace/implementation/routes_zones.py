"""GalleryZone endpoints (PRD §3.4)."""

from flask import Blueprint

import helpers
import serializers
from auth import ALL_ROLES, ROLE_MUSEUM_OPERATIONS, ROLE_PROJECT_MANAGER, endpoint
from envelope import list_response, object_response, pagination, query_filter
from store import db, new_row
from validate import body_object, v_bool, v_int, v_num, v_str

bp = Blueprint("zones", __name__)


@bp.route("/exhibit-projects/<pid>/gallery-zones", methods=["POST"])
@endpoint(roles=[ROLE_MUSEUM_OPERATIONS, ROLE_PROJECT_MANAGER])
def create_zone(pid):
    project = helpers.get_project(pid)
    body = body_object()
    zone_code = v_str(body, "zone_code", 1, 40)
    route_order = v_int(body, "visitor_route_order", minimum=1)
    max_noise = v_num(body, "max_noise_dba", gt=0)
    capacity = v_int(body, "case_slot_capacity", minimum=1, maximum=20)
    is_public = v_bool(body, "is_public_operating", required=False, default=True)
    closure_allowed = v_bool(body, "closure_allowed", required=False, default=False)
    dust_buffer = v_int(body, "dust_settling_buffer_minutes", minimum=0, maximum=480,
                        required=False, default=120)

    # Step 8: both codes are scoped-unique within the commission, compared exactly.
    helpers.require_unique(db.zones, project["id"], "zone_code", zone_code)
    helpers.require_unique(db.zones, project["id"], "visitor_route_order", route_order)
    # Step 10: zones may be registered only in the three planning phases.
    helpers.require_phase(project, ("INTERPRETIVE", "SCHEMATIC", "DESIGN_DEV"))

    zone = new_row("zones", {
        "project_id": project["id"],
        "zone_code": zone_code,
        "is_public_operating": is_public,
        "visitor_route_order": route_order,
        "max_noise_dba": max_noise,
        "case_slot_capacity": capacity,
        "closure_allowed": closure_allowed,
        "dust_settling_buffer_minutes": dust_buffer,
        # reserved_case_slots starts at 0 and available_case_slots at capacity,
        # so the slot identity of §2.7 holds from creation.
        "occupancy_state": "OPERATING",
    })
    db.zones[zone["id"]] = zone
    return object_response(serializers.zone_json(zone), 201)


@bp.route("/exhibit-projects/<pid>/gallery-zones", methods=["GET"])
@endpoint(roles=ALL_ROLES)
def list_zones(pid):
    project = helpers.get_project(pid)
    limit, offset = pagination()
    occupancy = query_filter("occupancy_state")
    rows = helpers.rows_of_project(db.zones, project["id"])
    if occupancy is not None:
        rows = [r for r in rows if r["occupancy_state"] == occupancy]
    return list_response(rows, serializers.zone_json, limit, offset)


@bp.route("/gallery-zones/<zone_id>", methods=["GET"])
@endpoint(roles=ALL_ROLES)
def get_zone(zone_id):
    zone = helpers.get_zone(zone_id)
    return object_response(serializers.zone_json(zone))


@bp.route("/gallery-zones/<zone_id>/artifact-cases", methods=["GET"])
@endpoint(roles=ALL_ROLES)
def list_zone_cases(zone_id):
    zone = helpers.get_zone(zone_id)
    limit, offset = pagination()
    status = query_filter("status")
    rows = helpers.cases_of_zone(zone["id"])
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    return list_response(rows, serializers.case_json, limit, offset)


@bp.route("/gallery-zones/<zone_id>/install-windows", methods=["GET"])
@endpoint(roles=ALL_ROLES)
def list_zone_windows(zone_id):
    zone = helpers.get_zone(zone_id)
    limit, offset = pagination()
    status = query_filter("status")
    rows = helpers.windows_of_zone(zone["id"])
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    return list_response(rows, serializers.window_json, limit, offset)
