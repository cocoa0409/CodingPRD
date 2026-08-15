"""ShowDesign endpoints."""

from flask import Blueprint

import errors
import validate as V
from db import DB, new_id, wall_created_at
from middleware import require_role, get_auth
from response import success_object, success_list
from services.show import (
    serialize_design, touch, recompute_posture, latest_simulation_for_design,
    downgrade_show_to_planning,
)

bp = Blueprint("designs", __name__)


def _get_design(design_id):
    d = DB.designs.get(design_id)
    if d is None:
        raise errors.not_found("ERR_DESIGN_NOT_FOUND", "design not found")
    return d


@bp.route("/api/show-designs", methods=["POST"])
def create_design():
    body = V.get_body()
    V.reject_system_fields(body)
    V.req_fields(body, ["show_event_id", "drone_count", "max_altitude_ft",
                        "duration_sec", "min_separation_m"])
    require_role("ProductionPlanner")
    show_id = body["show_event_id"]
    if not isinstance(show_id, str):
        raise errors.validation("show_event_id must be a string")
    drone_count = V.req_int(body, "drone_count")
    max_alt = V.req_number(body, "max_altitude_ft")
    duration = V.req_int(body, "duration_sec")
    min_sep = V.req_number(body, "min_separation_m")
    if drone_count < 1:
        raise errors.validation("drone_count must be >= 1")
    if max_alt <= 0:
        raise errors.validation("max_altitude_ft must be > 0")
    if duration < 60:
        raise errors.validation("duration_sec must be >= 60")
    if min_sep <= 0:
        raise errors.validation("min_separation_m must be > 0")

    show = DB.show_events.get(show_id)
    if show is None:
        raise errors.not_found("ERR_SHOW_NOT_FOUND", "show not found")

    existing = [did for did in DB.insertion_order["designs"]
                if DB.designs[did]["show_event_id"] == show_id]
    version_no = len(existing) + 1

    did = new_id()
    ts = wall_created_at()
    design = {
        "id": did, "show_event_id": show_id, "design_version_no": version_no,
        "drone_count": drone_count, "max_altitude_ft": max_alt,
        "duration_sec": duration, "min_separation_m": min_sep,
        "status": "DRAFT",
        "created_at": ts, "updated_at": ts, "version": 1,
    }
    DB.designs[did] = design
    DB.insertion_order["designs"].append(did)
    return success_object(serialize_design(design), 201)


@bp.route("/api/show-designs/<designId>", methods=["GET"])
def get_design(designId):
    get_auth()
    return success_object(serialize_design(_get_design(designId)))


@bp.route("/api/show-designs", methods=["GET"])
def list_designs():
    get_auth()
    limit, offset = V.pagination_params()
    from flask import request
    show_id = V.opt_string(request.args, "show_event_id")
    status = V.opt_string(request.args, "status")
    items = [DB.designs[i] for i in DB.insertion_order["designs"]]
    if show_id is not None:
        items = [d for d in items if d["show_event_id"] == show_id]
    if status is not None:
        items = [d for d in items if d["status"] == status]
    total = len(items)
    page = items[offset:offset + limit]
    return success_list([serialize_design(d) for d in page], limit, offset, total)


@bp.route("/api/show-designs/<designId>/revise", methods=["POST"])
def revise_design(designId):
    body = V.get_body()
    V.reject_system_fields(body)
    require_role("ProductionPlanner")
    design = _get_design(designId)
    if design["status"] != "SIMULATED":
        raise errors.conflict("ERR_INVALID_STATE", "design must be SIMULATED to revise")
    design["status"] = "DRAFT"
    touch(design)
    return success_object(serialize_design(design))


@bp.route("/api/show-designs/<designId>/lock", methods=["POST"])
def lock_design(designId):
    body = V.get_body()
    V.reject_system_fields(body)
    V.req_fields(body, ["expected_show_event_version"])
    require_role("ProductionPlanner")
    design = _get_design(designId)
    show = DB.show_events.get(design["show_event_id"])
    if show is None:
        raise errors.not_found("ERR_SHOW_NOT_FOUND", "show not found")

    expected = V.req_int(body, "expected_show_event_version")
    if expected != show["version"]:
        raise errors.stale_version()

    if design["status"] != "SIMULATED":
        raise errors.conflict("ERR_INVALID_STATE", "design must be SIMULATED to lock")

    if show["lifecycle_status"] not in ("PLANNING", "DESIGN_LOCKED", "AUTHORIZED", "READY"):
        raise errors.conflict("ERR_INVALID_STATE", "show state does not permit design lock")

    sim = latest_simulation_for_design(design["id"])
    if sim is None or sim["verdict"] != "PASS":
        raise errors.conflict("ERR_SIMULATION_NOT_PASSING", "latest simulation verdict is not PASS")

    # supersede any other LOCKED design for this show
    for did in DB.insertion_order["designs"]:
        other = DB.designs[did]
        if other["id"] != design["id"] and other["show_event_id"] == show["id"] and other["status"] == "LOCKED":
            other["status"] = "SUPERSEDED"
            touch(other)

    design["status"] = "LOCKED"
    touch(design)

    show["pinned_design_id"] = design["id"]
    if show["lifecycle_status"] in ("PLANNING", "AUTHORIZED", "READY"):
        show["lifecycle_status"] = "DESIGN_LOCKED"
    recompute_posture(show)
    touch(show)
    return success_object(serialize_design(design))
