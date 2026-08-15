"""UtilityDisconnect endpoints: scheduling with half-open window overlap
checks, and the dual-dimension report/verify/reject/confirm machine."""

from flask import Blueprint, g

from db import store, new_record, touch
from errors import (err, ERR_VALIDATION, ERR_INVALID_STATE, ERR_SOD_VIOLATION,
                    ERR_DISCONNECT_WINDOW_OVERLAP)
from middleware import require_roles, body
from response import success, list_response
from serializers import ser_utility_disconnect
from services import get_project, get_utility_disconnect, project_disconnects
from util import req_str, req_enum, req_datetime

bp = Blueprint("utilities", __name__)

UTILITY_TYPES = ("ELECTRIC", "GAS", "WATER", "SEWER", "TELECOM")
UD_READ_ROLES = ("ContractorAdmin", "SiteSupervisor", "UtilityCoordinator", "PermitCoordinator")
UD_ACTIONS = ("REPORT_DISCONNECTED", "VERIFY", "REJECT_VERIFICATION", "CONFIRM")


@bp.post("/demolition/projects/<pid>/utility-disconnects")
@require_roles("UtilityCoordinator")
def create_utility_disconnect(pid):
    b = body()
    utility_type = req_enum(b, "utility_type", UTILITY_TYPES)
    provider_name = req_str(b, "provider_name")
    start = req_datetime(b, "disconnect_window_start")
    end = req_datetime(b, "disconnect_window_end")
    if not (end > start):
        raise err(ERR_VALIDATION, "disconnect_window_end must be strictly after start")
    project = get_project(pid)

    # Half-open [start, end) overlap on same project + utility_type; adjacency allowed.
    for other in project_disconnects(project["id"]):
        if other["utility_type"] != utility_type:
            continue
        if start < other["disconnect_window_end"] and other["disconnect_window_start"] < end:
            raise err(ERR_DISCONNECT_WINDOW_OVERLAP,
                      "disconnect window overlaps an existing window for this utility type")

    rec = new_record()
    rec.update({
        "project_id": project["id"],
        "utility_type": utility_type,
        "provider_name": provider_name,
        "disconnect_window_start": start,
        "disconnect_window_end": end,
        "disconnect_status": "SCHEDULED",
        "verification_status": "UNVERIFIED",
        "reported_by_user_id": None,
        "verified_by_user_id": None,
        "confirmed_by_user_id": None,
    })
    store.utility_disconnects[rec["id"]] = rec
    return success(ser_utility_disconnect(rec), status=201)


@bp.get("/demolition/projects/<pid>/utility-disconnects")
@require_roles(*UD_READ_ROLES)
def list_utility_disconnects(pid):
    project = get_project(pid)
    return list_response(project_disconnects(project["id"]), ser_utility_disconnect)


@bp.post("/demolition/utility-disconnects/<uid>/transition")
@require_roles("UtilityCoordinator")
def utility_disconnect_transition(uid):
    b = body()
    action = b.get("action")
    if not isinstance(action, str) or action not in UD_ACTIONS:
        raise err(ERR_VALIDATION, "invalid action")
    ud = get_utility_disconnect(uid)

    if action == "REPORT_DISCONNECTED":
        if ud["disconnect_status"] != "SCHEDULED":
            raise err(ERR_INVALID_STATE, "REPORT_DISCONNECTED requires SCHEDULED")
        ud["disconnect_status"] = "REPORTED_DISCONNECTED"
        ud["reported_by_user_id"] = g.user_id
    elif action == "VERIFY":
        if ud["disconnect_status"] != "REPORTED_DISCONNECTED":
            raise err(ERR_INVALID_STATE, "VERIFY requires a reported disconnection")
        if ud["verification_status"] not in ("UNVERIFIED", "VERIFICATION_REJECTED"):
            raise err(ERR_INVALID_STATE, "VERIFY requires UNVERIFIED or VERIFICATION_REJECTED")
        ud["verification_status"] = "FIELD_VERIFIED"
        ud["verified_by_user_id"] = g.user_id
    elif action == "REJECT_VERIFICATION":
        if ud["verification_status"] != "FIELD_VERIFIED":
            raise err(ERR_INVALID_STATE, "REJECT_VERIFICATION requires FIELD_VERIFIED")
        ud["verification_status"] = "VERIFICATION_REJECTED"
    else:  # CONFIRM
        if ud["verification_status"] != "FIELD_VERIFIED":
            raise err(ERR_INVALID_STATE, "CONFIRM requires FIELD_VERIFIED")
        if g.user_id == ud["verified_by_user_id"]:
            raise err(ERR_SOD_VIOLATION, "confirmer must differ from verifier")
        ud["verification_status"] = "CONFIRMED"
        ud["confirmed_by_user_id"] = g.user_id

    touch(ud)
    return success(ser_utility_disconnect(ud))
