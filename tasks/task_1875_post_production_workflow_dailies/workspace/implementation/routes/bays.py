"""EditBay routes (PRD §3.4)."""

from flask import Blueprint

import db
from errors import (
    ApiError,
    ERR_NOT_FOUND,
    ERR_INVALID_REQUEST,
    ERR_BAY_OCCUPIED,
)
from helpers import (
    new_entity,
    touch,
    get_json_body,
    require_fields,
    check_string,
    check_enum,
    check_int,
    get_pagination,
    get_filter,
    paginate,
)
from middleware import require_roles
from response import success_object, success_list
from routes.projects import get_project_or_404
from services.transitions import guard_transition
from clock import clock as logical_clock

bp = Blueprint("bays", __name__)

BAY_TYPES = ("OFFLINE", "ONLINE", "COLOR", "SOUND", "QC")
BAY_TERMINAL = ("DECOMMISSIONED",)
LIST_ROLES = ("PostSupervisor", "ConformEditor", "Artist")


def serialize(bay):
    return dict(bay)


def get_bay_or_404(project, bay_id):
    bay = db.edit_bays.get(bay_id)
    if bay is None or bay["project_id"] != project["id"]:
        raise ApiError(ERR_NOT_FOUND, f"EditBay {bay_id} does not exist", 404)
    return bay


def _has_blocking_bookings(bay_id, today_only_forward):
    """Bookings in RESERVED or CHECKED_IN blocking maintenance/decommission.

    For maintenance: bookings on or after today's logical date block.
    For decommission from AVAILABLE: any RESERVED/CHECKED_IN booking blocks.
    """
    today = logical_clock.now().date().isoformat()
    for booking in db.bookings.values():
        if booking.get("bay_id") != bay_id:
            continue
        if booking["status"] not in ("RESERVED", "CHECKED_IN"):
            continue
        if today_only_forward and booking["session_date"] < today:
            continue
        return True
    return False


@bp.route("/post-production/projects/<project_id>/bays", methods=["POST"])
def create_bay(project_id):
    require_roles(("PostSupervisor",))
    project = get_project_or_404(project_id)
    body = get_json_body()
    require_fields(body, ("bay_name", "bay_type", "capacity_hours_per_day"))
    bay_name = check_string(body, "bay_name")
    bay_type = check_enum(body, "bay_type", BAY_TYPES)
    capacity = check_int(body, "capacity_hours_per_day", min_v=1, max_v=24)
    for existing in db.edit_bays.values():
        if existing["project_id"] == project_id and existing["bay_name"] == bay_name:
            raise ApiError(
                ERR_INVALID_REQUEST,
                f"bay_name '{bay_name}' already exists in this project",
                400,
            )
    bay = new_entity(
        {
            "project_id": project_id,
            "bay_name": bay_name,
            "bay_type": bay_type,
            "capacity_hours_per_day": capacity,
            "status": "AVAILABLE",
        }
    )
    db.edit_bays[bay["id"]] = bay
    return success_object(serialize(bay), 201)


@bp.route("/post-production/projects/<project_id>/bays", methods=["GET"])
def list_bays(project_id):
    require_roles(LIST_ROLES)
    get_project_or_404(project_id)
    limit, offset = get_pagination()
    items = [b for b in db.edit_bays.values() if b["project_id"] == project_id]
    status = get_filter("status")
    if status is not None:
        items = [b for b in items if b["status"] == status]
    bay_type = get_filter("bay_type")
    if bay_type is not None:
        items = [b for b in items if b["bay_type"] == bay_type]
    window, total = paginate(items, limit, offset)
    return success_list([serialize(b) for b in window], limit, offset, total)


@bp.route(
    "/post-production/projects/<project_id>/bays/<bay_id>/maintenance",
    methods=["POST"],
)
def bay_maintenance(project_id, bay_id):
    require_roles(("PostSupervisor",))
    project = get_project_or_404(project_id)
    bay = get_bay_or_404(project, bay_id)
    guard_transition(bay, "AVAILABLE", BAY_TERMINAL, "edit bay")
    if _has_blocking_bookings(bay_id, today_only_forward=True):
        raise ApiError(
            ERR_BAY_OCCUPIED,
            "EditBay has forward RESERVED or CHECKED_IN bookings blocking "
            "maintenance",
            409,
        )
    bay["status"] = "MAINTENANCE"
    touch(bay)
    return success_object(serialize(bay))


@bp.route(
    "/post-production/projects/<project_id>/bays/<bay_id>/release",
    methods=["POST"],
)
def bay_release(project_id, bay_id):
    require_roles(("PostSupervisor",))
    project = get_project_or_404(project_id)
    bay = get_bay_or_404(project, bay_id)
    guard_transition(bay, "MAINTENANCE", BAY_TERMINAL, "edit bay")
    bay["status"] = "AVAILABLE"
    touch(bay)
    return success_object(serialize(bay))


@bp.route(
    "/post-production/projects/<project_id>/bays/<bay_id>/decommission",
    methods=["POST"],
)
def bay_decommission(project_id, bay_id):
    require_roles(("PostSupervisor",))
    project = get_project_or_404(project_id)
    bay = get_bay_or_404(project, bay_id)
    guard_transition(bay, ("AVAILABLE", "MAINTENANCE"), BAY_TERMINAL, "edit bay")
    if bay["status"] == "AVAILABLE":
        if _has_blocking_bookings(bay_id, today_only_forward=False):
            raise ApiError(
                ERR_BAY_OCCUPIED,
                "EditBay has RESERVED or CHECKED_IN bookings blocking "
                "decommission",
                409,
            )
    bay["status"] = "DECOMMISSIONED"
    touch(bay)
    # Side effect: all future RESERVED bookings for this bay -> CANCELLED.
    today = logical_clock.now().date().isoformat()
    for booking in db.bookings.values():
        if (
            booking.get("bay_id") == bay_id
            and booking["status"] == "RESERVED"
            and booking["session_date"] > today
        ):
            booking["status"] = "CANCELLED"
            touch(booking)
    return success_object(serialize(bay))


# ---------------------------------------------------------------------------
# Utilization computed read + flat aliases
# ---------------------------------------------------------------------------


def compute_bay_utilization(bay, session_date):
    booked = 0
    for booking in db.bookings.values():
        if booking.get("bay_id") != bay["id"]:
            continue
        if booking["session_date"] != session_date:
            continue
        if booking["status"] in ("RESERVED", "CHECKED_IN", "COMPLETED"):
            booked += booking["booked_hours"]
    capacity = bay["capacity_hours_per_day"]
    utilization_pct = (100 * booked) // capacity
    return {
        "session_date": session_date,
        "booked_hours": booked,
        "capacity_hours_per_day": capacity,
        "utilization_pct": utilization_pct,
    }


@bp.route(
    "/post-production/projects/<project_id>/bays/<bay_id>/utilization",
    methods=["GET"],
)
def bay_utilization(project_id, bay_id):
    require_roles(("PostSupervisor", "ConformEditor"))
    project = get_project_or_404(project_id)
    bay = get_bay_or_404(project, bay_id)
    session_date = get_filter("session_date")
    if session_date is None:
        session_date = logical_clock.now().date().isoformat()
    result = compute_bay_utilization(bay, session_date)
    return success_object(result)


@bp.route("/post-production/bays/<bay_id>", methods=["GET"])
def get_bay_flat(bay_id):
    require_roles(LIST_ROLES)
    bay = db.edit_bays.get(bay_id)
    if bay is None:
        raise ApiError(ERR_NOT_FOUND, f"EditBay {bay_id} does not exist", 404)
    return success_object(serialize(bay))


@bp.route("/post-production/bays/<bay_id>/bookings", methods=["GET"])
def list_bay_bookings(bay_id):
    require_roles(LIST_ROLES)
    bay = db.edit_bays.get(bay_id)
    if bay is None:
        raise ApiError(ERR_NOT_FOUND, f"EditBay {bay_id} does not exist", 404)
    from routes.bookings import serialize as serialize_booking

    limit, offset = get_pagination()
    items = [b for b in db.bookings.values() if b.get("bay_id") == bay_id]
    session_date = get_filter("session_date")
    if session_date is not None:
        items = [b for b in items if b["session_date"] == session_date]
    status = get_filter("status")
    if status is not None:
        items = [b for b in items if b["status"] == status]
    window, total = paginate(items, limit, offset)
    return success_list([serialize_booking(b) for b in window], limit, offset, total)
