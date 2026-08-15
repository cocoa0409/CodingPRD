"""SafetyConfiguration endpoints."""

from flask import Blueprint

import errors
import validate as V
from db import DB, new_id, wall_created_at
from middleware import require_role, get_auth
from response import success_object, success_list
from services import calc
from services.show import (
    serialize_safety_config, touch, recompute_posture, downgrade_show_to_planning,
)

bp = Blueprint("safety", __name__)


def _get_config(config_id):
    c = DB.safety_configs.get(config_id)
    if c is None:
        raise errors.not_found("ERR_SAFETY_CONFIG_NOT_FOUND", "safety configuration not found")
    return c


@bp.route("/api/safety-configurations", methods=["POST"])
def create_safety_config():
    body = V.get_body()
    V.reject_system_fields(body)
    V.req_fields(body, ["show_event_id", "geofence_radius_m",
                        "altitude_hard_ceiling_ft", "lost_link_action",
                        "geofence_breach_action", "battery_rtl_threshold_pct",
                        "expected_show_event_version"])
    uid, _ = require_role("ProductionPlanner")
    show_id = body["show_event_id"]
    if not isinstance(show_id, str):
        raise errors.validation("show_event_id must be a string")
    radius = V.req_number(body, "geofence_radius_m")
    ceiling = V.req_number(body, "altitude_hard_ceiling_ft")
    lost_link = V.req_enum(body, "lost_link_action",
                           {"HOVER_THEN_LAND", "RETURN_TO_HOME", "IMMEDIATE_LAND"})
    breach = V.req_enum(body, "geofence_breach_action",
                        {"RETURN_TO_HOME", "IMMEDIATE_LAND"})
    rtl = V.req_int(body, "battery_rtl_threshold_pct")
    if radius <= 0:
        raise errors.validation("geofence_radius_m must be > 0")
    if ceiling <= 0:
        raise errors.validation("altitude_hard_ceiling_ft must be > 0")
    if not (10 <= rtl <= 80):
        raise errors.validation("battery_rtl_threshold_pct must be within [10, 80]")

    show = DB.show_events.get(show_id)
    if show is None:
        raise errors.not_found("ERR_SHOW_NOT_FOUND", "show not found")

    expected = V.req_int(body, "expected_show_event_version")
    if expected != show["version"]:
        raise errors.stale_version()

    # supersede current non-SUPERSEDED config for the show
    for cid in DB.insertion_order["safety_configs"]:
        other = DB.safety_configs[cid]
        if other["show_event_id"] == show["id"] and other["status"] in ("DRAFT", "APPROVED"):
            other["status"] = "SUPERSEDED"
            touch(other)
            if show.get("pinned_safety_config_id") == other["id"]:
                downgrade_show_to_planning(show)

    cid = new_id()
    ts = wall_created_at()
    config = {
        "id": cid, "show_event_id": show_id,
        "geofence_radius_m": radius,
        "altitude_hard_ceiling_ft": ceiling,
        "lost_link_action": lost_link,
        "geofence_breach_action": breach,
        "battery_rtl_threshold_pct": rtl,
        "status": "DRAFT",
        "created_by_user_id": uid,
        "approved_by_user_id": None,
        "created_at": ts, "updated_at": ts, "version": 1,
    }
    DB.safety_configs[cid] = config
    DB.insertion_order["safety_configs"].append(cid)
    touch(show)
    return success_object(serialize_safety_config(config), 201)


@bp.route("/api/safety-configurations/<configId>", methods=["GET"])
def get_config(configId):
    get_auth()
    return success_object(serialize_safety_config(_get_config(configId)))


@bp.route("/api/safety-configurations", methods=["GET"])
def list_configs():
    get_auth()
    limit, offset = V.pagination_params()
    from flask import request
    show_id = V.opt_string(request.args, "show_event_id")
    status = V.opt_string(request.args, "status")
    items = [DB.safety_configs[i] for i in DB.insertion_order["safety_configs"]]
    if show_id is not None:
        items = [c for c in items if c["show_event_id"] == show_id]
    if status is not None:
        items = [c for c in items if c["status"] == status]
    total = len(items)
    page = items[offset:offset + limit]
    return success_list([serialize_safety_config(c) for c in page], limit, offset, total)


@bp.route("/api/safety-configurations/<configId>/approve", methods=["POST"])
def approve_config(configId):
    body = V.get_body()
    V.reject_system_fields(body)
    uid, _ = require_role("SafetyOfficer")
    config = _get_config(configId)
    show = DB.show_events.get(config["show_event_id"])
    if show is None:
        raise errors.not_found("ERR_SHOW_NOT_FOUND", "show not found")

    if config["status"] != "DRAFT":
        raise errors.conflict("ERR_INVALID_STATE", "configuration must be DRAFT to approve")

    design = DB.designs.get(show.get("pinned_design_id") or "")
    if design is None or design["status"] != "LOCKED":
        raise errors.conflict("ERR_DESIGN_NOT_LOCKED", "show must hold a pinned LOCKED design")

    if uid == config["created_by_user_id"]:
        raise errors.sod("approver must differ from creator")

    # safety gates
    site = DB.sites.get(show["site_id"])
    if site is None:
        raise errors.not_found("ERR_SITE_NOT_FOUND", "site not found")
    required = calc.crowd_required_radius(design["max_altitude_ft"], design["drone_count"])
    if config["geofence_radius_m"] < required:
        raise errors.conflict("ERR_GEOFENCE_BELOW_REQUIRED", "geofence radius below required crowd distance")
    if config["altitude_hard_ceiling_ft"] < design["max_altitude_ft"]:
        raise errors.conflict("ERR_CEILING_BELOW_DESIGN", "hard ceiling below design max altitude")
    if config["altitude_hard_ceiling_ft"] > site["site_max_altitude_ft"]:
        raise errors.conflict("ERR_ALTITUDE_CEILING_EXCEEDS_SITE", "hard ceiling exceeds site max altitude")

    # supersede any other APPROVED config for this show
    for cid in DB.insertion_order["safety_configs"]:
        other = DB.safety_configs[cid]
        if other["id"] != config["id"] and other["show_event_id"] == show["id"] and other["status"] == "APPROVED":
            other["status"] = "SUPERSEDED"
            touch(other)

    config["status"] = "APPROVED"
    config["approved_by_user_id"] = uid
    touch(config)

    show["pinned_safety_config_id"] = config["id"]
    recompute_posture(show)
    touch(show)
    return success_object(serialize_safety_config(config))
